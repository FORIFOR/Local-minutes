import os
import numpy as np
from .emb import SpeakerEmbedding


class OnlineDiarizer:
    """
    完全オフラインの簡易リアルタイム話者分離
    - 埋め込み: ONNX(TitaNet等) or ローカル特徴
    - 分割: Silero VAD による区切り（WS側）を利用
    - クラスタリング: コサイン類似度しきい値ベース（将来: 凝集型へ拡張）

    暫定措置（最小範囲）:
      - sklearn等に依存せず、閾値ベースでリアルタイム更新
      - 撤去計画: セグメンテーションONNXと併用した凝集型クラスタリング実装へ差替
    """

    def __init__(self, threshold: float = 0.6):
        self.emb = SpeakerEmbedding()
        self.centroids = []  # list[np.ndarray]
        self.labels = []
        self.threshold = threshold
        # オプション設定
        self.min_spk = int(os.getenv("M4_DIAR_MIN_SPEAKERS", "1") or 1)
        self.max_spk = int(os.getenv("M4_DIAR_MAX_SPEAKERS", "8") or 8)
        # 履歴（将来の凝集型再割り当て用）
        self._hist_vecs: list[np.ndarray] = []
        self._hist_lbls: list[str] = []

    def assign_speaker(self, pcm16: bytes, t_range):
        wav = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        v = self.emb.embed(wav)
        if v is None or not np.isfinite(v).all():
            return "S1"

        if not self.centroids:
            self.centroids.append(v)
            self.labels.append("S1")
            self._hist_vecs.append(v)
            self._hist_lbls.append("S1")
            return "S1"

        sims = [float(np.dot(c, v) / (np.linalg.norm(c) * np.linalg.norm(v) + 1e-6)) for c in self.centroids]
        j = int(np.argmax(sims))
        if sims[j] >= self.threshold:
            # update centroid
            self.centroids[j] = 0.9 * self.centroids[j] + 0.1 * v
            lbl = self.labels[j]
            self._hist_vecs.append(v)
            self._hist_lbls.append(lbl)
            return lbl

        # new speaker (上限に達していなければ増やす)
        if len(self.centroids) < max(1, self.max_spk):
            k = len(self.centroids) + 1
            lbl = f"S{k}"
            self.centroids.append(v)
            self.labels.append(lbl)
            self._hist_vecs.append(v)
            self._hist_lbls.append(lbl)
            return lbl

        # 上限到達時は最も近い話者に割当
        lbl = self.labels[j]
        self.centroids[j] = 0.9 * self.centroids[j] + 0.1 * v
        self._hist_vecs.append(v)
        self._hist_lbls.append(lbl)
        return lbl
