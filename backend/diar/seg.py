import os
import numpy as np
import librosa


class SegmentationModel:
    def __init__(self):
        diar_dir = os.getenv("M4_DIAR_DIR", "")
        # 想定: ${diar_dir}/pyannote/segmentation-3.0.onnx など
        # 配布アーカイブに含まれる .onnx を探索
        cand = [
            os.path.join(diar_dir, "segmentation.onnx"),
            os.path.join(diar_dir, "pyannote", "segmentation-3.0.onnx"),
        ]
        self.path = next((c for c in cand if os.path.exists(c)), None)
        self.session = None
        if self.path:
            try:
                import onnxruntime as ort  # type: ignore
                # CoreMLは競合の温床になるため開発時はCPU固定
                self.session = ort.InferenceSession(self.path, providers=["CPUExecutionProvider"])  # CPU only
            except Exception:
                self.session = None

    def speech_prob(self, wav: np.ndarray, sr: int = 16000) -> float:
        # 最小限: 無音/有音の確率近似 (モデルがあれば前方推論、なければRMS)
        if self.session is not None:
            # 期待形状に変換: log-mel 特徴量を仮に供給(実モデルに整合しない可能性あり -> 例外時はRMSへ)
            try:
                feat = librosa.feature.melspectrogram(y=wav, sr=sr, n_fft=400, hop_length=160, n_mels=80)
                feat = np.log(np.maximum(feat, 1e-6)).astype(np.float32)
                x = feat.T[np.newaxis, :, :]
                out = self.session.run(None, {self.session.get_inputs()[0].name: x})[0]
                p = float(np.clip(out.mean(), 0.0, 1.0))
                return p
            except Exception:
                pass
        rms = float(np.sqrt(np.mean(wav * wav)))
        return float(np.clip(rms * 10.0, 0.0, 1.0))
