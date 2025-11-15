import os
import numpy as np
import onnxruntime as ort
import soundfile as sf
import librosa

SR = 16000

def _get_env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _get_env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


FRAME_HZ = _get_env_int("M4_DIAR_FRAME_HZ", 100)
SPEECH_THR = _get_env_float("M4_DIAR_SPEECH_THR", 0.55)
MERGE_GAP = _get_env_float("M4_DIAR_MERGE_MS", 350) / 1000.0


def _sess(path: str):
    return ort.InferenceSession(path, providers=["CPUExecutionProvider"])  # 完全オフライン


class SegModel:
    def __init__(self, path: str):
        self.sess = _sess(path)
        self.in_name = self.sess.get_inputs()[0].name
        self.out_name = self.sess.get_outputs()[0].name
        self.in_shape = self.sess.get_inputs()[0].shape

    def run(self, wav_f32: np.ndarray):
        # sherpa-onnx-pyannote-segmentation-3-0 は (N,1,T) 波形入力
        x = wav_f32.astype("float32").reshape(1, 1, -1)
        out = self.sess.run(None, {self.in_name: x})[0]  # (N,T,C) or (T,C)
        # 出力形状に柔軟対応: (N,T,C) or (T,C)
        if out.ndim == 3:
            scores = out[0]
        else:
            scores = out
        # 最頻クラスを speech とみなす（閾値ではなくラベルで抽出）
        c = int(np.argmax(scores.mean(axis=0)))
        pred = np.argmax(scores, axis=1)
        mask = (pred == c)
        # 連続区間抽出（フレームは FRAME_HZ）
        segs = []
        i, N = 0, len(mask)
        while i < N:
            if mask[i]:
                j = i
                while j < N and mask[j]:
                    j += 1
                segs.append((i / FRAME_HZ, j / FRAME_HZ))
                i = j
            else:
                i += 1
        # 近接統合
        merged = []
        for seg in segs:
            if not merged:
                merged.append(seg)
                continue
            ps, pe = merged[-1]
            if seg[0] - pe <= MERGE_GAP:
                merged[-1] = (ps, seg[1])
            else:
                merged.append(seg)
        return merged  # [(s,e)]


def _vad_segments(wav_f32: np.ndarray):
    """
    暫定フォールバック: 単純エナジーVAD（完全ローカル）。
    撤去計画: セグメンテーションONNXのI/O仕様確定後に削除し、ONNXのみで運用。
    """
    win = int(0.025 * SR)  # 25ms
    hop = int(0.010 * SR)  # 10ms
    n = len(wav_f32)
    if n < win:
        return []
    # フレーム毎エナジー
    energies = []
    idx = []
    i = 0
    while i + win <= n:
        seg = wav_f32[i:i+win]
        energies.append(float(np.mean(seg * seg)))
        idx.append(i)
        i += hop
    energies = np.asarray(energies)
    thr = float(np.median(energies) * 3.0)
    mask = energies >= thr
    # 抽出と時刻化
    segs = []
    i = 0
    T = len(mask)
    while i < T:
        if mask[i]:
            j = i
            while j < T and mask[j]:
                j += 1
            s = idx[i] / SR
            e = min(n, idx[j-1] + win) / SR
            segs.append((s, e))
            i = j
        else:
            i += 1
    # 近接統合
    merged = []
    for seg in segs:
        if not merged:
            merged.append(seg)
            continue
        ps, pe = merged[-1]
        if seg[0] - pe <= MERGE_GAP:
            merged[-1] = (ps, seg[1])
        else:
            merged.append(seg)
    return merged


class EmbModel:
    def __init__(self, path: str):
        self.sess = _sess(path)
        self.in_name = self.sess.get_inputs()[0].name
        self.out_name = self.sess.get_outputs()[0].name

    def _logmelspec80(self, wav):
        m = librosa.feature.melspectrogram(
            y=wav,
            sr=SR,
            n_fft=400,
            hop_length=160,
            win_length=400,
            n_mels=80,
            fmin=20,
            fmax=7600,
            center=True,
            power=2.0,
        )
        lm = np.log(np.maximum(1e-10, m)).T.astype("float32")
        lm = (lm - lm.mean(0, keepdims=True)) / (lm.std(0, keepdims=True) + 1e-5)
        return lm

    def embed(self, wav_chunk: np.ndarray):
        feats = self._logmelspec80(wav_chunk)
        # 期待shape: (B, 80, T')
        inp = feats.T.reshape(1, feats.shape[1], feats.shape[0])
        # 入力名検出（audio_signal, length）
        feeds = {}
        names = [i.name for i in self.sess.get_inputs()]
        if len(names) == 2 and 'length' in names and 'audio_signal' in names:
            feeds['audio_signal'] = inp.astype('float32')
            feeds['length'] = np.asarray([inp.shape[-1]], dtype=np.int64)
        else:
            feeds[self.in_name] = inp.astype('float32')
        outs = self.sess.get_outputs()
        out_data = self.sess.run(None, feeds)
        # 'embs' 出力があればそれを使う
        emb = None
        for i, o in enumerate(outs):
            if o.name == 'embs':
                emb = out_data[i]
                break
        if emb is None:
            emb = out_data[-1]
        emb = emb[0]
        emb = emb / (np.linalg.norm(emb) + 1e-8)
        return emb


def diarize(wav_path: str):
    seg_path = os.environ["M4_DIAR_SEG"]
    emb_path = os.environ["M4_DIAR_EMB"]
    seg = SegModel(seg_path)
    emb = EmbModel(emb_path)

    wav, sr = sf.read(wav_path)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    if sr != SR:
        wav = librosa.resample(wav.astype(np.float32), orig_sr=sr, target_sr=SR)

    # 1) 発話区間
    try:
        segments = seg.run(wav)
    except Exception:
        # フォールバック: VAD で代替（暫定・最小範囲）
        segments = _vad_segments(wav)

    # 2) 埋め込み
    spans, embs = [], []
    for (s, e) in segments:
        a, b = int(s * SR), int(e * SR)
        if b - a < int(0.2 * SR):  # 200ms未満はスキップ
            continue
        spans.append((s, e))
        embs.append(emb.embed(wav[a:b]))
    if not embs:
        return []

    # 3) クラスタリング（Agglomerative）
    kmin = _get_env_int("M4_DIAR_MIN_SPK", 2)
    kmax = _get_env_int("M4_DIAR_MAX_SPK", 4)
    linkage = os.getenv("M4_DIAR_LINKAGE", "average")
    distance = os.getenv("M4_DIAR_DISTANCE", "cosine")
    X = np.stack(embs)

    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    def estimate_k():
        best, best_k = -1.0, kmin
        for k in range(kmin, min(kmax, len(X)) + 1):
            labels = AgglomerativeClustering(n_clusters=k, linkage=linkage, metric=distance).fit_predict(X)
            s = -1.0
            if len(np.unique(labels)) > 1:
                s = silhouette_score(X, labels, metric=distance)
            if s > best:
                best, best_k = s, k
        return best_k

    K = estimate_k()
    labels = AgglomerativeClustering(n_clusters=K, linkage=linkage, metric=distance).fit_predict(X)

    diar = []
    for (s, e), lb in zip(spans, labels):
        diar.append({"start": s, "end": e, "spk": f"spk{lb}"})

    # 4) 同一話者の隣接区間の軽結合
    diar.sort(key=lambda x: (x["spk"], x["start"]))
    merged = []
    for d in diar:
        if not merged or d["spk"] != merged[-1]["spk"] or d["start"] - merged[-1]["end"] > MERGE_GAP:
            merged.append(d.copy())
        else:
            merged[-1]["end"] = d["end"]
    merged.sort(key=lambda x: x["start"])  # 時系列へ
    return merged
