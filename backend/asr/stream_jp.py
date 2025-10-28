import os
import glob
from typing import Optional, Tuple, List
import numpy as np
import sherpa_onnx
from loguru import logger

# 完全オフライン: Silero VAD（pip版: silero-vad）
import torch
from silero_vad import load_silero_vad, get_speech_timestamps


class RealtimeASR:
    """
    疑似リアルタイムASR（完全オフライン）
    - Silero VAD で音声区間を検出し、区切れ毎に sherpa-onnx OfflineRecognizer(SenseVoice) で確定認識
    - 既存WSのIF(accept_chunk/try_finalize)を踏襲
    """

    def __init__(self):
        self.sr = 16000
        self.window_size_s = 10  # 10秒ウィンドウ
        asr_kind = os.getenv("M4_ASR_KIND", "sense-voice-offline").strip().lower()
        asr_dir = os.getenv("M4_ASR_DIR", "")
        if not asr_dir:
            raise RuntimeError("env M4_ASR_DIR is empty. Please set a sherpa-onnx model directory.")

        def pick(patterns):
            for pat in patterns:
                m = glob.glob(os.path.join(asr_dir, "**", pat), recursive=True)
                if m:
                    return m[0]
            return None

        provider = os.getenv("M4_ASR_PROVIDER", "cpu").strip() or "cpu"
        language = os.getenv("M4_ASR_LANGUAGE", "ja").strip() or "ja"

        logger.bind(tag="asr.init").info(f"M4_ASR_KIND={asr_kind}")
        logger.bind(tag="asr.init").info(f"M4_ASR_DIR={asr_dir}")

        # Offline (SenseVoice) 構成のみをサポート
        if asr_kind not in ("sense-voice-offline", "sense_voice_offline", "sensevoice-offline"):
            logger.bind(tag="asr.init").warning(
                f"forcing offline SenseVoice, got kind={asr_kind}; use M4_ASR_KIND=sense-voice-offline"
            )

        tokens = os.getenv("M4_ASR_TOKENS") or pick(["tokens.txt"]) or os.path.join(asr_dir, "tokens.txt")
        model = os.getenv("M4_ASR_MODEL") or pick(["model.int8.onnx", "model.onnx"]) or os.path.join(asr_dir, "model.onnx")
        logger.bind(tag="asr.init").info(f"tokens={tokens}")
        logger.bind(tag="asr.init").info(f"model={model}")
        if not (os.path.isfile(tokens) and os.path.isfile(model)):
            raise RuntimeError("SenseVoice model files not found. Expect tokens.txt and model(.int8).onnx")

        # OfflineRecognizer (SenseVoice)
        self.recognizer = sherpa_onnx.offline_recognizer.OfflineRecognizer.from_sense_voice(
            model=model,
            tokens=tokens,
            num_threads=4,
            sample_rate=self.sr,
            feature_dim=80,
            decoding_method="greedy_search",
            provider=provider,
            language=language,
            use_itn=True,
        )

        # Silero VAD (pip版, 完全ローカル)
        logger.bind(tag="asr.init").info("Loading Silero VAD model...")
        self.vad = load_silero_vad(onnx=False)
        self.vad_min_sil_ms = int(os.getenv("M4_VAD_MIN_SIL_MS", "300"))
        self.vad_min_speech_ms = int(os.getenv("M4_VAD_MIN_SPEECH_MS", "200"))
        self.vad_pad_ms = int(os.getenv("M4_VAD_PAD_MS", "30"))
        logger.bind(tag="asr.init").info(f"VAD settings: min_sil={self.vad_min_sil_ms}ms, min_speech={self.vad_min_speech_ms}ms, pad={self.vad_pad_ms}ms")

        # バッファと出力キュー
        self._buf = np.zeros(0, dtype=np.float32)
        self._emitted: List[Tuple[int, int]] = []  # 既に確定済みの [start,end] サンプル区間
        self._queue: List[Tuple[float, float, str]] = []  # (start_s, end_s, text)
        self._last_partial_text: Optional[str] = None  # 前回のpartial結果

    def _decode_segment(self, seg: np.ndarray) -> str:
        # OfflineStream に直接波形を渡して認識
        s = self.recognizer.create_stream()
        s.accept_waveform(self.sr, seg.astype(np.float32))
        self.recognizer.decode_stream(s)
        # OfflineStream.result は property。text を参照
        try:
            text = s.result.text  # type: ignore[attr-defined]
        except Exception:
            # 念のためのフォールバック
            text = getattr(getattr(s, "result", object()), "text", "")
        return text or ""

    def accept_chunk(self, pcm16_1s: bytes) -> Optional[str]:
        # 生PCM(16k/mono/16bit)を正規化して追記
        arr = np.frombuffer(pcm16_1s, dtype=np.int16).astype(np.float32) / 32768.0
        if arr.size == 0:
            return None
        
        logger.bind(tag="asr.chunk").debug(f"Processing chunk: {len(pcm16_1s)} bytes -> {arr.size} samples")
        self._buf = np.concatenate([self._buf, arr])
        
        # 15秒を超えた場合のみ5秒分をトリム（頻度を下げる）
        max_samples = int(self.window_size_s * self.sr * 1.5)  # 15秒
        if self._buf.shape[0] > max_samples:
            # 5秒分を削除
            samples_to_remove = int(5 * self.sr)  
            logger.bind(tag="asr.chunk").debug(f"Trimming buffer: removing {samples_to_remove} samples")
            self._buf = self._buf[samples_to_remove:]
            
            # 既処理セグメントのインデックスを調整（重複検出機能を維持）
            old_emitted = len(self._emitted)
            self._emitted = [(s - samples_to_remove, e - samples_to_remove) 
                           for s, e in self._emitted 
                           if e - samples_to_remove > 0]
            logger.bind(tag="asr.chunk").debug(f"Adjusted emitted segments: {old_emitted} -> {len(self._emitted)}")
            
            # キューのみクリア（古い時間参照を防ぐ）
            old_queue_size = len(self._queue)
            self._queue.clear()
            logger.bind(tag="asr.chunk").debug(f"Cleared queue: {old_queue_size} -> 0 items")
        
        logger.bind(tag="asr.chunk").debug(f"Buffer size: {self._buf.shape[0]} samples ({self._buf.shape[0]/self.sr:.2f}s)")

        # VAD で全体から区間推定（簡易: 全バッファ再推定）
        a = torch.from_numpy(self._buf)
        logger.bind(tag="asr.vad").debug(f"Running VAD on buffer: {a.shape} samples")
        ts = get_speech_timestamps(
            a, self.vad,
            sampling_rate=self.sr,
            min_silence_duration_ms=self.vad_min_sil_ms,
            min_speech_duration_ms=self.vad_min_speech_ms,
            speech_pad_ms=self.vad_pad_ms,
            return_seconds=False,
        ) or []
        
        logger.bind(tag="asr.vad").debug(f"VAD detected {len(ts)} speech segments: {ts}")

        # 区間のうち、終端が十分過去(=現在時点で無音が続いた)のものだけ確定
        # よりアグレッシブな処理のためmarginを半分に
        margin = int(self.sr * (self.vad_min_sil_ms / 1000.0)) // 2
        tail = self._buf.shape[0]
        logger.bind(tag="asr.vad").debug(f"Processing segments: margin={margin}, tail={tail}")
        partial_text: Optional[str] = None
        for i, seg in enumerate(ts):
            s_i = int(seg['start'])
            e_i = int(seg['end'])
            logger.bind(tag="asr.segment").debug(f"Segment {i}: [{s_i}-{e_i}] ({(e_i-s_i)/self.sr:.2f}s)")
            # 1秒以上のセグメントは即座に処理（リアルタイム性重視）
            if (e_i - s_i) >= self.sr and e_i <= tail - margin//2:
                logger.bind(tag="asr.segment").debug(f"Segment {i} long enough, processing immediately")
            elif e_i > tail - margin:
                # 直近の区間（終端が近い）は保留（まだ話している可能性）
                logger.bind(tag="asr.segment").debug(f"Segment {i} too recent, skipping (e_i={e_i} > tail-margin={tail-margin})")
                continue
            # より厳密な重複チェック：時間重複とテキスト重複の両方をチェック
            def overlaps_with_existing(start, end, threshold=0.5):
                for s, e in self._emitted:
                    overlap = max(0, min(end, e) - max(start, s))
                    duration = end - start
                    if duration > 0 and overlap / duration > threshold:
                        return True
                return False
            
            if overlaps_with_existing(s_i, e_i):
                logger.bind(tag="asr.segment").debug(f"Segment {i} overlaps with existing segment, skipping")
                continue
            wav_seg = self._buf[s_i:e_i]
            logger.bind(tag="asr.segment").debug(f"Decoding segment {i}: {wav_seg.shape} samples")
            text = self._decode_segment(wav_seg).strip()
            logger.bind(tag="asr.segment").debug(f"Segment {i} decoded text: '{text}'")
            self._emitted.append((s_i, e_i))
            if text:
                start_s = s_i / self.sr
                end_s = e_i / self.sr
                # finalキューへ投入（try_finalizeで取得される）
                self._queue.append((start_s, end_s, text))
                logger.bind(tag="asr.segment").info(f"Segment {i} added to queue: '{text}' [{start_s:.2f}-{end_s:.2f}s]")
                # partialとして返すのは新しいテキストのみ
                if text != self._last_partial_text:
                    partial_text = text
                    self._last_partial_text = text
            else:
                # 空のテキストでも部分結果として処理中を知らせる
                if (e_i - s_i) >= self.sr // 2:  # 0.5秒以上のセグメント
                    partial_text = "..."
                    logger.bind(tag="asr.segment").debug(f"Segment {i} processing, returning placeholder")

        return partial_text

    def try_finalize(self) -> Optional[Tuple[float, float, str]]:
        if self._queue:
            return self._queue.pop(0)
        return None
