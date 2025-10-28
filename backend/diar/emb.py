import os
import numpy as np
import librosa


class SpeakerEmbedding:
    def __init__(self):
        diar_dir = os.getenv("M4_DIAR_DIR", "")
        # 優先: 明示パス（M4_DIAR_EMB）
        emb_path = os.getenv("M4_DIAR_EMB", "").strip()
        cand = [
            emb_path if emb_path else None,
            os.path.join(diar_dir, "embedding.onnx") if diar_dir else None,
            os.path.join(diar_dir, "nemo_en_titanet_small.onnx") if diar_dir else None,
        ]
        cand = [c for c in cand if c]
        self.path = next((c for c in cand if os.path.exists(c)), None)
        self.session = None
        if self.path:
            # onnxruntime のインポートは必要時にのみ実行（sherpa_onnxとのORt重複回避）
            try:
                import onnxruntime as ort  # type: ignore
                self.session = ort.InferenceSession(self.path, providers=["CPUExecutionProvider"])  # CPU固定
            except Exception:
                self.session = None

    def embed(self, wav: np.ndarray, sr: int = 16000) -> np.ndarray:
        # 例外回避の暫定: ONNXが通ればそれを、通らなければ log-mel の平均+分散を連結
        # 使用箇所: ライブ話者割当のみ。
        # 撤去計画: 提供モデルの前処理仕様に合わせ、正規の入出力shapeへ完全対応する。
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
