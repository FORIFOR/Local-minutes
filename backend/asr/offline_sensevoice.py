import os
from dataclasses import dataclass
from typing import Callable
from sherpa_onnx import (
    offline_recognizer as om,
)


@dataclass
class OfflineASRConfig:
    tokens: str
    model: str
    provider: str = "cpu"
    language: str = "ja"
    use_itn: bool = True


class OfflineASR:
    def __init__(self, cfg: OfflineASRConfig, log: Callable[[str], None] = print):
        log(f"asr.init: tokens={cfg.tokens}")
        log(f"asr.init: model={cfg.model}")
        log(f"asr.init: provider={cfg.provider}")
        # sherpa-onnx の OfflineRecognizer クラスメソッドでSenseVoice構成を初期化
        self._rec = om.OfflineRecognizer.from_sense_voice(
            model=cfg.model,
            tokens=cfg.tokens,
            provider=cfg.provider,
            language=cfg.language,
            use_itn=cfg.use_itn,
        )
        log("asr.init: models ready: SenseVoice (offline) initialized")

    def decode_wav(self, wav_path: str) -> str:
        s = self._rec.create_stream()
        # wavファイルを直接受け取るAPI
        try:
            s.accept_wave_file(wav_path)
        except Exception:
            # 古いバージョンで accept_wave_file がない場合のフォールバック
            import soundfile as sf
            import numpy as np
            wav, sr = sf.read(wav_path)
            if wav.ndim > 1:
                wav = wav.mean(axis=1)
            if sr != 16000:
                import librosa
                wav = librosa.resample(np.asarray(wav, dtype="float32"), orig_sr=sr, target_sr=16000)
            s.accept_waveform(16000, wav.astype("float32"))
        self._rec.decode_stream(s)
        return (getattr(getattr(s, "result", object()), "text", "") or "").strip()


def from_env(log: Callable[[str], None] = print) -> OfflineASR:
    cfg = OfflineASRConfig(
        tokens=os.environ["M4_ASR_TOKENS"],
        model=os.environ["M4_ASR_MODEL"],
        provider=os.environ.get("M4_ASR_PROVIDER", "cpu"),
    )
    return OfflineASR(cfg, log=log)

