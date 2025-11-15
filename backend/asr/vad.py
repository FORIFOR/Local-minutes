"""Voice Activity Detection backends with environment-controlled selection.

This module provides lightweight adapters for several VAD implementations:

- WebRTC VAD (`webrtcvad`): 最も低レイテンシで高精度。pip install webrtcvad が必要。
- Silero VAD (`silero_vad` + torch): ノイズに強いが依存が大きい。
- Energy VAD: 依存ゼロのシンプルなRMSしきい値。フォールバック用途。

`create_vad_from_env` で `VAD_ENGINE` 環境変数を読み取り、自動的に最適な実装を返す。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from typing import Optional

import numpy as np
from loguru import logger


DEFAULT_SAMPLE_RATE = 16000
DEFAULT_FRAME_MS = 20


def _env_get(*keys: str, default: Optional[str] = None) -> Optional[str]:
    for key in keys:
        value = os.getenv(key)
        if value is not None and value.strip():
            return value
    return default


@dataclass
class BaseVAD:
    """共通インターフェース。"""

    name: str = "base"

    def is_speech(self, frame_f32: np.ndarray) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class EnergyVAD(BaseVAD):
    """単純なエナジー（RMS）しきい値ベース。依存が無く、フォールバック用。"""

    name = "energy"

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE, threshold: float = 0.006) -> None:
        self.sample_rate = sample_rate
        self.threshold = threshold

    def is_speech(self, frame_f32: np.ndarray) -> bool:
        if frame_f32.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(frame_f32, dtype=np.float64))))
        return rms >= self.threshold


class WebRtcVAD(BaseVAD):
    """`webrtcvad` ライブラリによる判定。"""

    name = "webrtc"

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE, mode: int = 2) -> None:
        try:
            import webrtcvad  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(f"webrtcvad unavailable: {exc}") from exc
        if mode < 0 or mode > 3:
            raise ValueError("webrtcvad mode must be 0..3")
        self.sample_rate = sample_rate
        self.vad = webrtcvad.Vad(mode)

    def is_speech(self, frame_f32: np.ndarray) -> bool:
        if frame_f32.size == 0:
            return False
        pcm16 = np.clip(frame_f32, -1.0, 1.0)
        pcm16 = (pcm16 * 32767.0).astype(np.int16, copy=False)
        return self.vad.is_speech(pcm16.tobytes(), self.sample_rate)


class SileroVAD(BaseVAD):
    """Silero VAD を薄くラップ。torch が必要。"""

    name = "silero"

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        threshold: float = 0.5,
        frame_ms: int = DEFAULT_FRAME_MS,
    ) -> None:
        try:
            import torch  # type: ignore
            from silero_vad import load_silero_vad  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(f"silero_vad unavailable: {exc}") from exc

        self.sample_rate = sample_rate
        self.threshold = threshold
        self.frame_samples = int(sample_rate * frame_ms / 1000)
        self.device = torch.device(os.getenv("SILERO_VAD_DEVICE", "cpu"))

        model = load_silero_vad(onnx=False)
        self.model = model.to(self.device)
        self.model.eval()
        self._torch = torch
        # Silero VAD は 512 サンプル（16kHz/32ms）単位が既定。足りない場合はパディング。
        self.required_samples = 512 if sample_rate == 16000 else 256

    def is_speech(self, frame_f32: np.ndarray) -> bool:
        torch = self._torch
        frame = np.clip(frame_f32, -1.0, 1.0).astype(np.float32, copy=False)
        tensor = torch.from_numpy(frame).to(self.device)
        if tensor.dim() == 1:
            tensor = tensor.unsqueeze(0)
        length = tensor.shape[-1]
        if length < self.required_samples:
            pad = self.required_samples - length
            tensor = torch.nn.functional.pad(tensor, (0, pad), value=0.0)
        elif length > self.required_samples:
            tensor = tensor[..., : self.required_samples]

        with torch.inference_mode():
            prob = float(self.model(tensor, self.sample_rate).item())

        return prob >= self.threshold


def _env_float(primary: str, default: float, *aliases: str) -> float:
    name = None
    try:
        name = primary
        raw = _env_get(primary, *aliases, default=None)
        if raw is None:
            return default
        return float(raw)
    except ValueError:
        logger.bind(tag="vad").warning("invalid float env", key=name, value=_env_get(primary, *aliases))
        return default


def _env_int(primary: str, default: int, *aliases: str) -> int:
    name = None
    try:
        name = primary
        raw = _env_get(primary, *aliases, default=None)
        if raw is None:
            return default
        return int(raw)
    except ValueError:
        logger.bind(tag="vad").warning("invalid int env", key=name, value=_env_get(primary, *aliases))
        return default


def create_vad_from_env(
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    frame_ms: int = DEFAULT_FRAME_MS,
) -> BaseVAD:
    engine = (_env_get("VAD_ENGINE", "M4_VAD_ENGINE", default="webrtc") or "webrtc").strip().lower()
    aggressiveness = _env_int("VAD_AGGRESSIVENESS", 2, "M4_VAD_AGGRESSIVENESS")
    energy_threshold = _env_float("VAD_ENERGY_THRESHOLD", 0.006, "M4_VAD_ENERGY_THRESHOLD")
    silero_threshold = _env_float("VAD_SILERO_THRESHOLD", 0.5, "M4_VAD_SILERO_THRESHOLD")

    try:
        if engine == "webrtc":
            vad = WebRtcVAD(sample_rate=sample_rate, mode=aggressiveness)
        elif engine == "silero":
            vad = SileroVAD(sample_rate=sample_rate, threshold=silero_threshold, frame_ms=frame_ms)
        else:
            vad = EnergyVAD(sample_rate=sample_rate, threshold=energy_threshold)
    except Exception as exc:
        logger.bind(tag="vad").warning(
            "VAD init fallback",
            requested=engine,
            error=repr(exc),
        )
        vad = EnergyVAD(sample_rate=sample_rate, threshold=energy_threshold)

    logger.bind(tag="vad").info(
        "VAD engine ready",
        engine=getattr(vad, "name", vad.__class__.__name__),
        sr=sample_rate,
        frame_ms=frame_ms,
    )
    return vad


__all__ = [
    "BaseVAD",
    "EnergyVAD",
    "WebRtcVAD",
    "SileroVAD",
    "create_vad_from_env",
]
