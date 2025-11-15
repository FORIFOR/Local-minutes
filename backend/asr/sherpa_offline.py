import os
import time

import numpy as np
import sherpa_onnx


SR = 16000


def _f32(x: np.ndarray) -> np.ndarray:
    if x.dtype == np.float32:
        return x
    if x.dtype == np.int16:
        return (x.astype(np.float32) / 32768.0).clip(-1.0, 1.0)
    return x.astype(np.float32, copy=False)


class SherpaOfflineASR:
    """
    - 非ストリーミング Zipformer(Transducer) を RMS-VAD で短区切り → 即デコード
    - partial は送らず、確定テキストだけ返す
    - return: (start_ts, end_ts, text) or None
    """

    def __init__(self):
        model_dir = os.getenv("M4_SHERPA_MODEL_DIR", "")
        tokens = os.getenv("M4_ASR_TOKENS", os.path.join(model_dir, "tokens.txt"))
        encoder = os.getenv("M4_ASR_ENCODER", os.path.join(model_dir, "encoder-epoch-99-avg-1.onnx"))
        decoder = os.getenv("M4_ASR_DECODER", os.path.join(model_dir, "decoder-epoch-99-avg-1.onnx"))
        joiner = os.getenv("M4_ASR_JOINER", os.path.join(model_dir, "joiner-epoch-99-avg-1.onnx"))

        self.rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            tokens=tokens,
            encoder=encoder,
            decoder=decoder,
            joiner=joiner,
            num_threads=int(os.getenv("M4_SHERPA_THREADS", "4") or "4"),
            sample_rate=SR,
            decoding_method=os.getenv("M4_SHERPA_DECODING", "greedy_search"),
        )

        # RMS-VAD
        self.block = int(os.getenv("STREAM_BLOCK", "512"))
        self.start_th = float(os.getenv("M4_VAD_RMS_START", "0.005"))
        self.stop_th = float(os.getenv("M4_VAD_RMS_STOP", "0.003"))
        self.start_frames = int(os.getenv("M4_VAD_START_FRAMES", "5"))
        self.stop_frames = int(os.getenv("M4_VAD_STOP_FRAMES", "10"))

        self.min_turn_sec = float(os.getenv("MIN_TURN_SEC", "0.80"))
        self.reset_on_gap_ms = int(os.getenv("M4_DIAR_RESET_ON_GAP_MS", "800"))

        # state
        self._in_speech = False
        self._seg_buf = []
        self._start_cnt = 0
        self._stop_cnt = 0
        self._t0 = time.monotonic()
        self._stream_pos = 0  # samples
        self._last_final_end = None  # seconds

    def accept_chunk(self, pcm):
        if isinstance(pcm, (bytes, bytearray, memoryview)):
            arr = np.frombuffer(pcm, dtype=np.int16)
        elif isinstance(pcm, np.ndarray):
            arr = pcm
        else:
            arr = np.asarray(pcm)
        x = _f32(arr).reshape(-1)
        if x.size == 0:
            return None

        # RMS-VAD フレーム単位（block サンプルごと）
        i = 0
        ret = None
        while i < x.size:
            j = min(i + self.block, x.size)
            frame = x[i:j]
            self._seg_buf.append(frame)
            self._stream_pos += frame.size

            rms = float(np.sqrt(np.mean(frame ** 2))) if frame.size else 0.0
            if not self._in_speech:
                self._start_cnt = self._start_cnt + 1 if rms > self.start_th else 0
                if self._start_cnt >= self.start_frames:
                    self._in_speech = True
                    self._stop_cnt = 0
            else:
                self._stop_cnt = self._stop_cnt + 1 if rms < self.stop_th else 0
                if self._stop_cnt >= self.stop_frames:
                    ret = self._finalize_segment()
            i = j
        return ret

    def try_finalize(self):
        # 明示フラッシュ用
        if self._in_speech and self._seg_buf:
            return self._finalize_segment()
        return None

    def _finalize_segment(self):
        samples = np.concatenate(self._seg_buf) if self._seg_buf else np.empty((0,), np.float32)
        self._seg_buf.clear()
        self._in_speech = False
        self._start_cnt = 0
        self._stop_cnt = 0

        if samples.size == 0:
            return None

        dur = samples.size / SR
        if dur < self.min_turn_sec:
            return None

        # タイムスタンプ計算（ざっくり：セグメント長ベース）
        end_ts = self._stream_pos / SR
        start_ts = max(0.0, end_ts - dur)

        stream = self.rec.create_stream()
        stream.accept_waveform(SR, samples)
        self.rec.decode_stream(stream)
        text = (stream.result.text or "").strip()

        if not text:
            return None
        return (start_ts, end_ts, text)
