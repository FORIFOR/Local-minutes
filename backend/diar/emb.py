import os
from typing import Optional

import numpy as np
import librosa


class SpeakerEmbedding:
    def __init__(self):
        self.session = None
        self.path: Optional[str] = None
        self._sb = None
        self._sb_device = "cpu"
        self._torch = None

        if not self._init_speechbrain():
            self._init_onnx()

    def _init_speechbrain(self) -> bool:
        engine = os.getenv("M4_DIAR_ENGINE", "").strip().lower()
        emb_source = os.getenv("M4_DIAR_EMB_SOURCE", "").strip()
        emb_dir = os.getenv("M4_DIAR_EMB_DIR", "").strip()
        wants_speechbrain = bool(emb_source or emb_dir) or engine in {"speechbrain", "ecapa"}
        if not wants_speechbrain:
            return False
        try:
            import torchaudio  # type: ignore
            if not hasattr(torchaudio, "list_audio_backends"):
                torchaudio.list_audio_backends = lambda: []  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            from speechbrain.inference import EncoderClassifier
            import torch
        except Exception:
            return False

        source = emb_source
        if emb_dir:
            os.makedirs(emb_dir, exist_ok=True)
            if not source and os.path.exists(os.path.join(emb_dir, "hyperparams.yaml")):
                source = emb_dir
        if not source:
            source = "speechbrain/spkrec-ecapa-voxceleb"

        device = os.getenv("M4_DIAR_DEVICE", "cpu").strip() or "cpu"
        run_opts = {"device": device}
        try:
            self._sb = EncoderClassifier.from_hparams(source=source, savedir=emb_dir or None, run_opts=run_opts)
            self._sb_device = device
            self._torch = torch
            return True
        except Exception:
            self._sb = None
            self._torch = None
            return False

    def _init_onnx(self) -> None:
        diar_dir = os.getenv("M4_DIAR_DIR", "")
        emb_path = os.getenv("M4_DIAR_EMB", "").strip()
        cand = [
            emb_path if emb_path else None,
            os.path.join(diar_dir, "embedding.onnx") if diar_dir else None,
            os.path.join(diar_dir, "nemo_en_titanet_small.onnx") if diar_dir else None,
        ]
        cand = [c for c in cand if c]
        self.path = next((c for c in cand if os.path.exists(c)), None)
        if self.path:
            try:
                import onnxruntime as ort  # type: ignore
                self.session = ort.InferenceSession(self.path, providers=["CPUExecutionProvider"])  # CPU固定
            except Exception:
                self.session = None

    def _embed_speechbrain(self, wav: np.ndarray) -> Optional[np.ndarray]:
        if self._sb is None or self._torch is None:
            return None
        torch = self._torch
        tensor = torch.from_numpy(wav.astype(np.float32)).unsqueeze(0)
        try:
            tensor = tensor.to(self._sb_device)
        except Exception:
            self._sb_device = "cpu"
            tensor = tensor.to(self._sb_device)
        try:
            with torch.no_grad():
                emb = self._sb.encode_batch(tensor)
        except Exception:
            return None
        if isinstance(emb, (list, tuple)):
            emb = emb[0]
        if hasattr(emb, "squeeze"):
            emb = emb.squeeze()
        if hasattr(emb, "detach"):
            emb = emb.detach()
        if hasattr(emb, "cpu"):
            emb = emb.cpu()
        if hasattr(emb, "numpy"):
            emb = emb.numpy()
        v = np.asarray(emb, dtype=np.float32)
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm
        return v

    def embed(self, wav: np.ndarray, sr: int = 16000) -> np.ndarray:
        if self._sb is not None:
            v = self._embed_speechbrain(wav)
            if v is not None:
                return v

        if self.session is not None:
            try:
                feat = librosa.feature.melspectrogram(y=wav, sr=sr, n_fft=400, hop_length=160, n_mels=80)
                feat = np.log(np.maximum(feat, 1e-6)).astype(np.float32)
                x = feat.T[np.newaxis, :, :]
                out = self.session.run(None, {self.session.get_inputs()[0].name: x})[0]
                v = out.squeeze()
                if v.ndim == 1:
                    return v.astype(np.float32)
                return v.mean(axis=0).astype(np.float32)
            except Exception:
                pass

        feat = librosa.feature.melspectrogram(y=wav, sr=sr, n_fft=400, hop_length=160, n_mels=64)
        logm = np.log(np.maximum(feat, 1e-6))
        v = np.concatenate([logm.mean(axis=1), logm.std(axis=1)], axis=0)
        v = v / (np.linalg.norm(v) + 1e-6)
        return v.astype(np.float32)
