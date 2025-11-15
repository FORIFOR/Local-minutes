import os
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from faster_whisper import WhisperModel  # type: ignore


@dataclass
class StreamingPartial:
    text: str
    stable: str
    unstable: str
    latency_ms: float


def _lcp(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


class WhisperRealtimeASR:
    """Simple sliding-window whisper decoder to emulate streaming partials."""

    def __init__(self) -> None:
        self.sample_rate = 16000
        self.win_ms = int(os.getenv("STREAM_WIN_MS", "960"))
        self.hop_ms = int(os.getenv("STREAM_HOP_MS", "240"))
        self.window_samples = max(1, int(self.sample_rate * self.win_ms / 1000))
        self.hop_samples = max(1, int(self.sample_rate * self.hop_ms / 1000))
        self.buffer = np.zeros((0,), dtype=np.float32)
        self.prev_text = ""
        self.rms_gate = float(os.getenv("M4_NEAR_SILENT_RMS", "0.0012"))

        model_name = os.getenv("M4_WHISPER_MODEL", "large-v3")
        device = os.getenv("M4_WHISPER_DEVICE", "auto")
        compute = os.getenv("M4_WHISPER_COMPUTE", "int8")
        threads = int(os.getenv("M4_WHISPER_THREADS", "4"))
        beam = int(os.getenv("M4_WHISPER_BEAM", "5"))

        self.decode_kwargs = {
            "beam_size": beam,
            "language": "ja",
            "vad_filter": False,
            "temperature": 0.0,
            "condition_on_previous_text": True,
            "initial_prompt": self._load_prompt(),
        }

        self.model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute,
            cpu_threads=threads,
            num_workers=1,
        )

    def _load_prompt(self) -> Optional[str]:
        prompt_path = os.getenv("M4_INITIAL_PROMPT_FILE", "").strip()
        if prompt_path and os.path.exists(prompt_path):
            try:
                with open(prompt_path, "r", encoding="utf-8") as fp:
                    prompt = fp.read().strip()
                    return prompt or None
            except OSError:
                return None
        return None

    def _append_buffer(self, pcm: np.ndarray) -> None:
        if pcm.size == 0:
            return
        self.buffer = np.concatenate([self.buffer, pcm])
        # keep at most window + hop for context
        max_keep = self.window_samples + self.hop_samples
        if self.buffer.size > max_keep:
            self.buffer = self.buffer[-max_keep :]

    def accept_chunk(self, pcm_bytes: bytes) -> Optional[StreamingPartial]:
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size == 0:
            return None
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        if rms < self.rms_gate:
            return None
        self._append_buffer(pcm)
        if self.buffer.size < self.window_samples:
            return None

        ctx = self.buffer[-(self.window_samples + self.hop_samples) :]
        start_ts = time.perf_counter()
        segments, _ = self.model.transcribe(
            ctx,
            **self.decode_kwargs,
        )
        hyp = "".join(seg.text for seg in segments).strip()
        latency_ms = (time.perf_counter() - start_ts) * 1000.0
        if not hyp:
            return None

        prefix_len = _lcp(self.prev_text, hyp)
        stable = hyp[:prefix_len]
        unstable = hyp[prefix_len:]
        self.prev_text = hyp
        return StreamingPartial(
            text=hyp,
            stable=stable,
            unstable=unstable,
            latency_ms=latency_ms,
        )

    def try_finalize(self) -> Optional[Tuple[float, float, str]]:
        """For compatibility; final output is just the current hypothesis."""
        if not self.prev_text:
            return None
        # treat entire buffer duration as a single segment
        duration = self.buffer.size / self.sample_rate
        return (0.0, duration, self.prev_text)
