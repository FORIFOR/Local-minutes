import glob
import os
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np
import sherpa_onnx
from loguru import logger

try:
    import webrtcvad  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    webrtcvad = None

from backend.diar.online_cluster import DiarDecision, OnlineDiarizer, StreamingDiarizer


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)


def _pad_to_len(x: np.ndarray, sec: float, sr: int) -> np.ndarray:
    need = int(max(0.0, sec) * sr) - x.size
    if need <= 0:
        return x
    return np.pad(x, (0, need), mode="constant")


class RealtimeASR:
    """
    Sherpa-ONNX SenseVoice を使ったライブASR
    - webrtc+energy VAD（fallback）
    - セグメント管理APIで語頭/語尾を保護
    - intraseg 話者監視（StreamingDiarizer）で文中カット
    """

    def __init__(self):
        self.sr = int(os.getenv("M4_ASR_SR", "16000") or "16000")
        self.block = int(os.getenv("M4_ASR_BLOCK", "320") or "320")  # 20ms @16k
        self.frame_sec = self.block / self.sr

        self._load_asr_model()
        self._setup_vad()
        self._setup_segments()
        self._setup_intraseg()
        self._setup_live_diar_stream()

    # ------------------------------------------------------------------ #
    #  Initialization helpers
    # ------------------------------------------------------------------ #
    def _load_asr_model(self) -> None:
        asr_dir = os.getenv("M4_ASR_DIR", "")
        if not asr_dir:
            raise RuntimeError("env M4_ASR_DIR is empty")

        def pick(patterns: List[str]) -> Optional[str]:
            for pat in patterns:
                found = glob.glob(os.path.join(asr_dir, "**", pat), recursive=True)
                if found:
                    return found[0]
            return None

        def require_file(path: Optional[str], fallback_patterns: List[str]) -> str:
            cand = path or pick(fallback_patterns)
            if not cand:
                raise RuntimeError(f"missing ASR file for patterns={fallback_patterns}")
            if not os.path.isfile(cand):
                raise RuntimeError(f"ASR file not found: {cand}")
            return cand

        kind = os.getenv("M4_ASR_KIND", "sense-voice-offline").strip().lower()
        provider = os.getenv("M4_ASR_PROVIDER", "cpu").strip() or "cpu"
        language = os.getenv("M4_ASR_LANGUAGE", "ja").strip() or "ja"
        num_threads = int(os.getenv("M4_ASR_THREADS", "4") or "4")
        decode_method = os.getenv("M4_ASR_DECODING_METHOD", "greedy_search").strip() or "greedy_search"
        feature_dim = int(os.getenv("M4_ASR_FEATURE_DIM", "80") or "80")

        logger.bind(tag="asr.init").info(f"M4_ASR_DIR={asr_dir}")
        logger.bind(tag="asr.init").info(f"M4_ASR_KIND={kind}")

        if kind in {"sensevoice", "sense-voice-offline", "sense_voice_offline"}:
            tokens = require_file(os.getenv("M4_ASR_TOKENS"), ["tokens.txt"])
            model = require_file(os.getenv("M4_ASR_MODEL"), ["model.onnx", "model.int8.onnx"])
            logger.bind(tag="asr.init").info(f"Sherpa tokens={tokens}")
            logger.bind(tag="asr.init").info(f"Sherpa model={model}")
            self.recognizer = sherpa_onnx.offline_recognizer.OfflineRecognizer.from_sense_voice(
                model=model,
                tokens=tokens,
                num_threads=num_threads,
                sample_rate=self.sr,
                feature_dim=feature_dim,
                decoding_method=decode_method,
                provider=provider,
                language=language,
                use_itn=True,
            )
            return

        if "zipformer" in kind or kind == "transducer":
            tokens = require_file(os.getenv("M4_ASR_TOKENS"), ["tokens.txt"])
            encoder = require_file(os.getenv("M4_ASR_ENCODER"), ["encoder-*.onnx"])
            decoder = require_file(os.getenv("M4_ASR_DECODER"), ["decoder-*.onnx"])
            joiner = require_file(os.getenv("M4_ASR_JOINER"), ["joiner-*.onnx"])
            logger.bind(tag="asr.init").info(f"Sherpa encoder={encoder}")
            logger.bind(tag="asr.init").info(f"Sherpa decoder={decoder}")
            logger.bind(tag="asr.init").info(f"Sherpa joiner={joiner}")
            logger.bind(tag="asr.init").info(f"Sherpa tokens={tokens}")
            self.recognizer = sherpa_onnx.offline_recognizer.OfflineRecognizer.from_transducer(
                encoder=encoder,
                decoder=decoder,
                joiner=joiner,
                tokens=tokens,
                num_threads=num_threads,
                sample_rate=self.sr,
                feature_dim=feature_dim,
                decoding_method=decode_method,
                provider=provider,
            )
            return

        raise RuntimeError(f"Unsupported M4_ASR_KIND={kind}")

    def _setup_vad(self) -> None:
        self.vad_engine = os.getenv("M4_VAD_ENGINE", "webrtc").strip().lower() or "webrtc"
        self._webrtc_vad = None
        if self.vad_engine in {"off", "none", "disabled"}:
            self.vad_enabled = False
            self.hang_start_frames = 10**9
            self.hang_stop_frames = 10**9
            self.bridge_frames = 10**9
            logger.bind(tag="asr.vad").info("VAD disabled via env (M4_VAD_ENGINE=%s)", self.vad_engine)
            return
        self.vad_enabled = True
        if self.vad_engine == "webrtc" and webrtcvad is not None:
            try:
                level = int(os.getenv("M4_VAD_AGGRESSIVENESS", "2") or "2")
                self._webrtc_vad = webrtcvad.Vad(max(0, min(3, level)))
                logger.bind(tag="asr.vad").info(f"Using webrtcvad level={level}")
            except Exception as exc:  # pragma: no cover - fallback path
                logger.bind(tag="asr.vad").warning(f"webrtcvad init failed ({exc}); fallback to energy gate")
                self._webrtc_vad = None
                self.vad_engine = "energy"
        else:
            self.vad_engine = "energy"

        self.noise_rms = _env_float("M4_NEAR_SILENT_RMS", 0.002)
        self.th_start_mul = _env_float("VAD_TH_START_MUL", 5.0)
        self.th_stop_mul = _env_float("VAD_TH_STOP_MUL", 3.5)
        self.th_min = 0.0005
        self.th_max = 0.02
        self._update_energy_thresholds()
        self._noise_cal_values: List[float] = []
        self._noise_calibrated = False
        self.noise_cal_frames = max(1, int(round(_env_float("VAD_NOISE_CAL_SEC", 0.6) / self.frame_sec)))

        min_speech_ms = float(os.getenv("M4_VAD_MIN_SPEECH_MS", "160") or "160")
        hang_ms = float(os.getenv("M4_VAD_HANG_MS", "300") or "300")
        frame_ms = self.frame_sec * 1000.0
        self.hang_start_frames = max(1, int(round(min_speech_ms / frame_ms)))
        self.hang_stop_frames = max(self.hang_start_frames, int(round(hang_ms / frame_ms)))

        self.bridge_sec = float(os.getenv("M4_VAD_BRIDGING_MS", "0") or "0") / 1000.0
        self.bridge_frames = int(round(self.bridge_sec / self.frame_sec))

        logger.bind(tag="asr.vad").info(
            f"VAD engine={self.vad_engine} start_frames={self.hang_start_frames} "
            f"stop_frames={self.hang_stop_frames} bridge={self.bridge_sec:.3f}s"
        )

    def _setup_segments(self) -> None:
        self.min_turn_sec = _env_float("MIN_TURN_SEC", 0.8)
        self.min_asr_sec = _env_float("MIN_ASR_SEC", 1.0)
        self.max_turn_sec = _env_float("M4_MAX_TURN_SEC", 0.0)

        prepad_ms = float(os.getenv("VAD_PREROLL_MS", "240") or "240")
        self.prepad_frames = max(1, int(round((prepad_ms / 1000.0) / self.frame_sec)))
        tail_ms = float(os.getenv("VAD_TAIL_CARRY_SEC", "0.3") or "0.3") * 1000.0
        self.tail_keep_samples = int(round((tail_ms / 1000.0) * self.sr))

        self._pre_audio: Deque[np.ndarray] = deque(maxlen=self.prepad_frames)
        self._pre_audio_samples = 0
        self._segment_audio: List[np.ndarray] = []
        self._segment_start_sample: Optional[int] = None

        self._queue: List[Tuple[float, float, str, bytes]] = []
        self._last_partial_text: Optional[str] = None

        self._processed_samples = 0
        self._residual = np.zeros(0, dtype=np.float32)
        self.spk_split_min_sec = _env_float("M4_DIAR_SPLIT_MIN_SEC", 1.2)
        cover = _env_float("M4_DIAR_SPLIT_MIN_COVERAGE", 0.85)
        self.spk_split_min_cover = max(0.5, min(0.98, cover))
        self._in_speech = False
        self._start_cnt = 0
        self._stop_cnt = 0
        self._gap_cnt = 0

    def _setup_intraseg(self) -> None:
        self.intraseg_enabled = _env_bool("M4_DIAR_INTRASEG", False)
        self._spk_tracker: Optional[StreamingDiarizer] = None
        self.current_speaker: Optional[str] = None
        self._samples_since_embed = 0
        if self.intraseg_enabled:
            self._spk_tracker = StreamingDiarizer(self.sr)
            self.emb_win_sec = _env_float("M4_DIAR_EMB_WIN_S", 1.0)
            self.emb_hop_sec = _env_float("M4_DIAR_EMB_HOP_S", 0.25)
            self.emb_win_samples = int(self.emb_win_sec * self.sr)
            self.emb_hop_samples = max(self.block, int(self.emb_hop_sec * self.sr))
            logger.bind(tag="asr.diar").info(
                f"intraseg=on win={self.emb_win_sec:.2f}s hop={self.emb_hop_sec:.2f}s"
            )
        else:
            logger.bind(tag="asr.diar").info("intraseg=off (legacy diarization only)")

    def _setup_live_diar_stream(self) -> None:
        self.live_diar_enabled = _env_bool("M4_ENABLE_DIAR_LIVE", True)
        self._live_diarizer: Optional[OnlineDiarizer] = None
        self._diar_buffer = np.zeros(0, dtype=np.float32)
        self._diar_buffer_start_sample = 0
        self._diar_next_window_sample = 0
        self._diar_total_samples = 0
        self._diar_timeline: Deque[Tuple[float, float, str]] = deque()
        self._diar_recent_segments: Deque[Tuple[float, float, str]] = deque(maxlen=64)
        self._diar_last_label: Optional[str] = None
        self._diar_dominant_min_sec = _env_float("M4_DIAR_DOMINANT_MIN_SEC", 0.8)

        win_sec = _env_float("M4_DIAR_EMB_WIN_S", 1.0)
        self._diar_win_sec = max(0.2, win_sec)
        hop_override = os.getenv("M4_DIAR_LIVE_HOP_S")
        if hop_override:
            try:
                hop_val = float(hop_override)
            except ValueError:
                hop_val = 0.5
        else:
            hop_val = _env_float("M4_DIAR_EMB_HOP_S", 0.5)
        self._diar_hop_sec = max(0.1, hop_val)
        self._diar_win_samples = max(1, int(round(self._diar_win_sec * self.sr)))
        self._diar_hop_samples = max(1, int(round(self._diar_hop_sec * self.sr)))
        retention_sec = _env_float("M4_DIAR_TIMELINE_RETENTION", 240.0)
        self._diar_retention_samples = max(self._diar_win_samples, int(round(retention_sec * self.sr)))

        if not self.live_diar_enabled:
            logger.bind(tag="asr.diar").info("live diarization disabled via env (M4_ENABLE_DIAR_LIVE=off)")
            return
        try:
            self._live_diarizer = OnlineDiarizer()
            logger.bind(tag="asr.diar").info(
                f"live diarization enabled win={self._diar_win_sec:.2f}s hop={self._diar_hop_sec:.2f}s"
            )
        except Exception as exc:  # pragma: no cover - optional component
            self._live_diarizer = None
            self.live_diar_enabled = False
            logger.bind(tag="asr.diar").warning(f"live diarization unavailable: {exc}")

    # ------------------------------------------------------------------ #
    #  Live diarization helpers
    # ------------------------------------------------------------------ #
    def _feed_live_diar_chunk(self, chunk: np.ndarray) -> None:
        if self._live_diarizer is None or chunk.size == 0:
            return
        if self._diar_buffer.size == 0:
            self._diar_buffer = chunk.copy()
            self._diar_buffer_start_sample = self._diar_total_samples
        else:
            self._diar_buffer = np.concatenate([self._diar_buffer, chunk])
        self._diar_total_samples += chunk.size
        buffer_end_sample = self._diar_buffer_start_sample + self._diar_buffer.size
        while self._diar_next_window_sample + self._diar_win_samples <= buffer_end_sample:
            offset = self._diar_next_window_sample - self._diar_buffer_start_sample
            if offset < 0:
                self._diar_buffer_start_sample = self._diar_next_window_sample
                buffer_end_sample = self._diar_buffer_start_sample + self._diar_buffer.size
                offset = 0
                if self._diar_next_window_sample + self._diar_win_samples > buffer_end_sample:
                    break
            window = self._diar_buffer[offset : offset + self._diar_win_samples]
            if window.size < self._diar_win_samples:
                break
            start_s = self._diar_next_window_sample / self.sr
            end_s = (self._diar_next_window_sample + self._diar_win_samples) / self.sr
            speaker = self._live_diarizer.assign(window, start_s, end_s)
            self._diar_timeline.append((start_s, end_s, speaker))
            self._diar_last_label = speaker
            self._diar_next_window_sample += self._diar_hop_samples
        self._shrink_diar_buffer()
        self._shrink_diar_timeline()

    def _shrink_diar_buffer(self) -> None:
        if self._diar_buffer.size == 0:
            return
        keep_from = max(0, self._diar_next_window_sample - self._diar_win_samples)
        drop = keep_from - self._diar_buffer_start_sample
        if drop <= 0:
            return
        if drop >= self._diar_buffer.size:
            self._diar_buffer = np.zeros(0, dtype=np.float32)
            self._diar_buffer_start_sample = keep_from
        else:
            self._diar_buffer = self._diar_buffer[drop:]
            self._diar_buffer_start_sample += drop

    def _shrink_diar_timeline(self) -> None:
        if not self._diar_timeline:
            return
        min_time = (self._diar_next_window_sample - self._diar_retention_samples) / self.sr
        while self._diar_timeline and self._diar_timeline[0][1] < min_time:
            self._diar_timeline.popleft()

    def _dominant_block_speaker(self, seg_t0: float, seg_t1: float) -> Optional[str]:
        if not self._diar_timeline:
            return None
        best_label: Optional[str] = None
        best_len = 0.0
        current_label: Optional[str] = None
        current_len = 0.0
        for win_t0, win_t1, spk in self._diar_timeline:
            if win_t1 <= seg_t0:
                continue
            if win_t0 >= seg_t1:
                break
            overlap = min(seg_t1, win_t1) - max(seg_t0, win_t0)
            if overlap <= 0:
                continue
            if spk == current_label:
                current_len += overlap
            else:
                if current_label and current_len > best_len:
                    best_label, best_len = current_label, current_len
                current_label = spk
                current_len = overlap
        if current_label and current_len > best_len:
            best_label, best_len = current_label, current_len
        if best_label and best_len >= self._diar_dominant_min_sec:
            return best_label
        return None

    def _majority_speaker_from_timeline(self, seg_t0: float, seg_t1: float) -> Optional[str]:
        if not self._diar_timeline:
            return None
        totals: Dict[str, float] = {}
        for win_t0, win_t1, spk in self._diar_timeline:
            if win_t1 <= seg_t0:
                continue
            if win_t0 >= seg_t1:
                break
            overlap = min(seg_t1, win_t1) - max(seg_t0, win_t0)
            if overlap <= 0:
                continue
            totals[spk] = totals.get(spk, 0.0) + overlap
        if not totals:
            return None
        return max(totals.items(), key=lambda kv: kv[1])[0]

    def _cache_segment_speaker(self, start_s: float, end_s: float, label: str) -> None:
        self._diar_recent_segments.append((start_s, end_s, label))

    def _lookup_cached_speaker(self, start_s: float, end_s: float) -> Optional[str]:
        for seg_start, seg_end, label in reversed(self._diar_recent_segments):
            if abs(seg_start - start_s) < 0.02 and abs(seg_end - end_s) < 0.02:
                return label
        return None

    def majority_speaker(self, start_s: float, end_s: float) -> Optional[str]:
        cached = self._lookup_cached_speaker(start_s, end_s)
        if cached:
            return cached
        if self._live_diarizer:
            label = self._majority_speaker_from_timeline(start_s, end_s)
            if label:
                return label
            dominant = self._dominant_block_speaker(start_s, end_s)
            if dominant:
                return dominant
            return self._diar_last_label
        return self.current_speaker

    def _infer_segment_speaker(self, start_s: float, end_s: float) -> str:
        label = self.majority_speaker(start_s, end_s)
        if label:
            return label
        return self.current_speaker or "S1"

    def _segment_diar_windows(self, seg_t0: float, seg_t1: float) -> List[Tuple[float, float, str]]:
        if not self._diar_timeline:
            return []
        windows: List[Tuple[float, float, str]] = []
        for win_t0, win_t1, spk in self._diar_timeline:
            if win_t1 <= seg_t0:
                continue
            if win_t0 >= seg_t1:
                break
            beg = max(seg_t0, win_t0)
            end = min(seg_t1, win_t1)
            if end <= beg:
                continue
            windows.append((beg, end, spk))
        return windows

    def _speaker_spans_for_segment(self, seg_t0: float, seg_t1: float) -> List[Tuple[float, float, str]]:
        windows = self._segment_diar_windows(seg_t0, seg_t1)
        if not windows:
            return []
        labels = {lbl for _, _, lbl in windows}
        if len(labels) <= 1:
            return []
        windows.sort(key=lambda item: item[0])
        spans: List[Tuple[float, float, str]] = []
        cur_s, cur_e, cur_label = windows[0]
        for win_s, win_e, win_label in windows[1:]:
            if win_label == cur_label and win_s <= cur_e + 1e-3:
                cur_e = max(cur_e, win_e)
            else:
                spans.append((cur_s, cur_e, cur_label))
                cur_s, cur_e, cur_label = win_s, win_e, win_label
        spans.append((cur_s, cur_e, cur_label))
        clipped: List[Tuple[float, float, str]] = []
        for span_s, span_e, label in spans:
            start = max(seg_t0, span_s)
            end = min(seg_t1, span_e)
            if end - start <= 0:
                continue
            clipped.append((start, end, label))
        if len(clipped) <= 1:
            return []
        if any((end - start) < self.spk_split_min_sec for start, end, _ in clipped):
            return []
        coverage = sum(end - start for start, end, _ in clipped)
        total = max(seg_t1 - seg_t0, 1e-6)
        if coverage < total * self.spk_split_min_cover:
            return []
        if clipped and clipped[0][0] > seg_t0:
            first_start, first_end, first_label = clipped[0]
            clipped[0] = (seg_t0, first_end, first_label)
        if clipped and clipped[-1][1] < seg_t1:
            last_start, last_end, last_label = clipped[-1]
            clipped[-1] = (last_start, seg_t1, last_label)
        normalized: List[Tuple[float, float, str]] = []
        for start, end, label in clipped:
            if not normalized:
                normalized.append((start, end, label))
                continue
            prev_start, prev_end, prev_label = normalized[-1]
            if start > prev_end:
                normalized[-1] = (prev_start, start, prev_label)
            normalized.append((start, end, label))
        return normalized

    def _split_segment_audio(
        self, audio: np.ndarray, seg_t0: float, seg_t1: float
    ) -> List[Tuple[np.ndarray, float, float, str]]:
        spans = self._speaker_spans_for_segment(seg_t0, seg_t1)
        if not spans:
            return []
        result: List[Tuple[np.ndarray, float, float, str]] = []
        total_dur = seg_t1 - seg_t0
        for span_start, span_end, label in spans:
            rel_start = max(0.0, span_start - seg_t0)
            rel_end = min(total_dur, span_end - seg_t0)
            beg = int(round(rel_start * self.sr))
            end = int(round(rel_end * self.sr))
            if end <= beg or beg >= audio.size:
                continue
            end = min(end, audio.size)
            chunk = audio[beg:end]
            if chunk.size == 0:
                continue
            result.append((chunk.copy(), span_start, span_end, label))
        if len(result) <= 1:
            return []
        return result

    def _emit_segment_chunk(
        self,
        audio: np.ndarray,
        start_s: float,
        end_s: float,
        speaker_hint: Optional[str],
        reason_label: str,
        cut_backtrace_sec: float,
    ) -> bool:
        padded = _pad_to_len(audio, self.min_asr_sec, self.sr)
        text = self._decode_stream(padded).strip()
        if not text:
            return False
        speaker = speaker_hint or self._infer_segment_speaker(start_s, end_s)
        if speaker:
            self._cache_segment_speaker(start_s, end_s, speaker)
        pcm16 = np.clip(audio, -1.0, 1.0)
        pcm16 = (pcm16 * 32767.0).astype(np.int16)
        self._queue.append((start_s, end_s, text, pcm16.tobytes()))
        self._last_partial_text = text
        dur = audio.size / self.sr
        chars = len(text)
        preview = text.replace("\n", " ")
        max_preview = 160
        if len(preview) > max_preview:
            preview = preview[: max_preview - 3] + "..."
        logger.bind(tag="asr.segment").info(
            f"SEG_FINAL start={start_s:.2f}s end={end_s:.2f}s dur={dur:.2f}s reason={reason_label} "
            f"cut_backtrace={cut_backtrace_sec:.2f}s chars={chars} speaker={speaker or '-'} "
            f"intraseg={self.current_speaker or '-'} "
            f"text={preview}"
        )
        return True

    # ------------------------------------------------------------------ #
    #  VAD helpers
    # ------------------------------------------------------------------ #
    def _update_energy_thresholds(self) -> None:
        self.start_th = float(np.clip(self.noise_rms * self.th_start_mul, self.th_min, self.th_max))
        self.stop_th = float(np.clip(self.noise_rms * self.th_stop_mul, self.th_min, self.th_max))

    def _is_speech(self, frame_f32: np.ndarray, frame_bytes: bytes) -> bool:
        if self._webrtc_vad is not None:
            try:
                return self._webrtc_vad.is_speech(frame_bytes, self.sr)
            except Exception:  # pragma: no cover - fallback
                pass
        rms = float(np.sqrt(np.mean(frame_f32 * frame_f32) + 1e-12))
        if not self._in_speech and rms < self.stop_th * 0.9:
            self.noise_rms = 0.98 * self.noise_rms + 0.02 * rms
            self._update_energy_thresholds()
        return rms >= (self.start_th if not self._in_speech else self.stop_th)

    def _maybe_calibrate(self, frame_f32: np.ndarray) -> None:
        if self._noise_calibrated:
            return
        self._noise_cal_values.append(float(np.sqrt(np.mean(frame_f32 * frame_f32) + 1e-12)))
        if len(self._noise_cal_values) >= self.noise_cal_frames:
            med = float(np.median(self._noise_cal_values))
            p95 = float(np.percentile(self._noise_cal_values, 95))
            self.noise_rms = max(self.th_min, (med + p95) / 2.0)
            self._noise_calibrated = True
            self._update_energy_thresholds()
            if self.start_th <= self.stop_th:
                self.start_th = min(self.th_max, self.stop_th * 1.1)
                self.stop_th = max(self.th_min, self.start_th * 0.7)
            logger.bind(tag="asr.vad").info(
                f"VAD calibrated noise={self.noise_rms:.4f} start={self.start_th:.4f} stop={self.stop_th:.4f}"
            )

    # ------------------------------------------------------------------ #
    #  Segment helpers
    # ------------------------------------------------------------------ #
    def _current_segment_duration(self) -> float:
        if not self._segment_audio:
            return 0.0
        samples = sum(arr.size for arr in self._segment_audio)
        return samples / self.sr

    def _collect_recent_audio(self, sample_count: int) -> np.ndarray:
        if not self._segment_audio or sample_count <= 0:
            return np.zeros(0, dtype=np.float32)
        chunks: List[np.ndarray] = []
        remaining = sample_count
        for arr in reversed(self._segment_audio):
            if remaining <= 0:
                break
            if arr.size >= remaining:
                chunks.append(arr[-remaining:])
                break
            chunks.append(arr)
            remaining -= arr.size
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(list(reversed(chunks))).astype(np.float32)

    def _append_pre_audio(self, frame: np.ndarray) -> None:
        self._pre_audio.append(frame.copy())
        self._pre_audio_samples = min(
            self.prepad_frames * self.block, self._pre_audio_samples + frame.size
        )

    def _seed_segment_from_pre(self) -> None:
        pre_samples = sum(arr.size for arr in self._pre_audio)
        self._segment_audio = [arr.copy() for arr in self._pre_audio]
        self._segment_start_sample = max(0, self._processed_samples - pre_samples)
        self._pre_audio.clear()
        self._pre_audio_samples = 0
        self._samples_since_embed = 0

    def _append_segment_frame(self, frame: np.ndarray) -> None:
        self._segment_audio.append(frame.copy())
        if self.intraseg_enabled:
            self._samples_since_embed += frame.size

    def _log_decision(self, decision: DiarDecision) -> None:
        logger.bind(tag="asr.diar").debug(
            f"SEG_DECIDE rule={decision.reason or '-'} cut={decision.cut} label={decision.label} "
            f"best={decision.best_sim:.3f} second={decision.second_sim:.3f} "
            f"last={decision.last_sim:.3f} margin={decision.margin:.3f}"
        )

    def _finalize_segment(self, cut_backtrace_sec: float = 0.0, reason: str = "") -> None:
        if not self._segment_audio:
            return
        raw = np.concatenate(self._segment_audio).astype(np.float32)
        if raw.size == 0:
            self._segment_audio.clear()
            return

        cut_samples = int(round(cut_backtrace_sec * self.sr))
        remainder = np.zeros(0, dtype=np.float32)
        if 0 < cut_samples < raw.size:
            keep = raw.size - cut_samples
            remainder = raw[keep:]
            raw = raw[:keep]
        elif cut_samples >= raw.size:
            remainder = raw
            raw = np.zeros(0, dtype=np.float32)

        dur = raw.size / self.sr
        if dur < max(0.1, self.min_turn_sec * 0.5):
            tail_buf = np.concatenate([raw, remainder]) if remainder.size else raw
            self._reset_segment_state(tail_buf)
            return

        start_sample = self._segment_start_sample or max(0, self._processed_samples - raw.size)
        start_s = start_sample / self.sr
        seg_end = start_s + dur
        reason_label = reason or "normal"
        emitted = False
        chunks = self._split_segment_audio(raw, start_s, seg_end)
        if chunks:
            split_reason = f"{reason_label}-split"
            for chunk_audio, chunk_start, chunk_end, chunk_label in chunks:
                emitted = self._emit_segment_chunk(
                    chunk_audio, chunk_start, chunk_end, chunk_label, split_reason, cut_backtrace_sec
                ) or emitted
        else:
            emitted = self._emit_segment_chunk(raw, start_s, seg_end, None, reason_label, cut_backtrace_sec)
        if not emitted:
            self._reset_segment_state(remainder)
            return

        if self._spk_tracker and self.current_speaker:
            self._spk_tracker.notify_segment_end(self.current_speaker)

        tail = remainder
        if tail.size < self.tail_keep_samples and raw.size >= self.tail_keep_samples:
            tail = raw[-self.tail_keep_samples :]
        self._reset_segment_state(tail)

    def _reset_segment_state(self, tail: Optional[np.ndarray] = None) -> None:
        self._segment_audio = []
        self._segment_start_sample = None
        self._samples_since_embed = 0
        self._in_speech = False
        self._start_cnt = 0
        self._stop_cnt = 0
        self._gap_cnt = 0
        self.current_speaker = None
        self._pre_audio.clear()
        self._pre_audio_samples = 0
        if tail is not None and tail.size > 0:
            max_samples = self.prepad_frames * self.block
            if tail.size > max_samples:
                tail = tail[-max_samples:]
            for idx in range(0, tail.size, self.block):
                self._pre_audio.append(tail[idx : idx + self.block].copy())
            self._pre_audio_samples = min(tail.size, max_samples)

    def _decode_stream(self, pcm: np.ndarray) -> str:
        stream = self.recognizer.create_stream()
        stream.accept_waveform(self.sr, pcm.astype(np.float32))
        self.recognizer.decode_stream(stream)
        try:
            return stream.result.text  # type: ignore[attr-defined]
        except Exception:
            return getattr(getattr(stream, "result", object()), "text", "") or ""

    # ------------------------------------------------------------------ #
    #  Intraseg diarization
    # ------------------------------------------------------------------ #
    def _maybe_run_intraseg(self) -> None:
        if not self.intraseg_enabled or not self._spk_tracker:
            return
        seg_dur = self._current_segment_duration()
        if seg_dur < max(self.min_turn_sec * 0.5, self.emb_win_sec * 0.8):
            return
        if self._samples_since_embed < self.emb_hop_samples:
            return
        pcm = self._collect_recent_audio(self.emb_win_samples)
        if pcm.size < self.emb_win_samples:
            return
        self._samples_since_embed = 0
        decision = self._spk_tracker.step(
            pcm,
            current_label=self.current_speaker,
            seg_dur_sec=seg_dur,
            hop_sec=self.emb_hop_sec,
        )
        if decision is None:
            return
        self.current_speaker = decision.label
        self._log_decision(decision)
        if decision.cut:
            self._finalize_segment(decision.cut_backtrace_sec, reason=decision.reason or "spk-cut")
            self._spk_tracker.notify_segment_end(decision.label)
            self.current_speaker = decision.label

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #
    def accept_chunk(self, pcm16_bytes: bytes) -> Optional[str]:
        if not pcm16_bytes:
            return None
        arr = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        self._feed_live_diar_chunk(arr)
        if self._residual.size:
            arr = np.concatenate([self._residual, arr])
            self._residual = np.zeros(0, dtype=np.float32)
        if arr.size == 0:
            return None

        frames = arr.size // self.block
        remainder = arr[frames * self.block :]
        cursor = 0
        for i in range(frames):
            beg = i * self.block
            end = beg + self.block
            frame = arr[beg:end]
            frame_bytes = (frame * 32767.0).clip(-32768, 32767).astype(np.int16).tobytes()
            self._process_frame(frame, frame_bytes)
            cursor = end
        if remainder.size:
            self._residual = remainder.copy()
        return None

    def try_finalize(self) -> Optional[Tuple[float, float, str, bytes]]:
        if self._queue:
            return self._queue.pop(0)
        return None

    # ------------------------------------------------------------------ #
    #  Frame processor
    # ------------------------------------------------------------------ #
    def _process_frame(self, frame_f32: np.ndarray, frame_bytes: bytes) -> None:
        self._processed_samples += frame_f32.size

        if not self.vad_enabled:
            self._append_segment_frame(frame_f32)
            if self.max_turn_sec > 0 and self._current_segment_duration() >= self.max_turn_sec:
                self._finalize_segment(reason="max-turn")
            elif self.intraseg_enabled:
                self._maybe_run_intraseg()
            return

        self._maybe_calibrate(frame_f32)
        speech = self._is_speech(frame_f32, frame_bytes)

        if not self._in_speech:
            self._append_pre_audio(frame_f32)
            if speech:
                self._start_cnt += 1
                if self._start_cnt >= self.hang_start_frames:
                    self._in_speech = True
                    self._seed_segment_from_pre()
            else:
                self._start_cnt = 0
            return

        # in speech
        self._append_segment_frame(frame_f32)
        if speech:
            self._stop_cnt = 0
            self._gap_cnt = 0
        else:
            self._stop_cnt += 1
            self._gap_cnt += 1

        if self.max_turn_sec and self._current_segment_duration() >= self.max_turn_sec:
            self._finalize_segment(reason="max-turn")
            return

        if self._stop_cnt >= self.hang_stop_frames and self._gap_cnt > self.bridge_frames:
            self._finalize_segment(reason="vad-stop")
            return

        if self.intraseg_enabled:
            self._maybe_run_intraseg()
