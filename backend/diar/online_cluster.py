import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
from loguru import logger

from .emb import SpeakerEmbedding


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)


def l2_norm(x: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(x) + 1e-12
    return (x / norm).astype(np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12
    return float(np.dot(a, b) / denom)


def ahc_cosine(embs: np.ndarray, k: int, thr: float) -> np.ndarray:
    if embs.shape[0] == 0:
        return np.zeros(0, dtype=int)
    labels = np.arange(embs.shape[0])

    def dist(i: int, j: int) -> float:
        return 1.0 - cosine(embs[i], embs[j])

    while len(set(labels)) > k:
        best_pair: Optional[Tuple[int, int]] = None
        best_d = 1e9
        uniq = sorted(set(labels))
        for idx_i, li in enumerate(uniq):
            for lj in uniq[idx_i + 1 :]:
                i = np.where(labels == li)[0][0]
                j = np.where(labels == lj)[0][0]
                d = dist(i, j)
                if d < best_d:
                    best_d = d
                    best_pair = (li, lj)
        if best_pair is None or (best_d > thr and len(set(labels)) <= k):
            break
        a, b = best_pair
        labels[labels == b] = a
    uniq = {lab: idx for idx, lab in enumerate(sorted(set(labels)))}
    return np.array([uniq[lab] for lab in labels], dtype=int)


def silhouette_like(embs: np.ndarray, labels: np.ndarray) -> float:
    n = len(embs)
    if n < 2 or len(set(labels)) == 1:
        return -1.0
    score = 0.0
    count = 0
    for i in range(n):
        li = labels[i]
        same = embs[labels == li]
        if same.shape[0] <= 1:
            continue
        a = np.mean(np.linalg.norm(same - embs[i], axis=1))
        b = 1e9
        for lj in set(labels):
            if lj == li:
                continue
            other = embs[labels == lj]
            b = min(b, np.mean(np.linalg.norm(other - embs[i], axis=1)))
        score += (b - a) / max(a, b, 1e-12)
        count += 1
    return float(score / max(count, 1))


@dataclass
class DiarDecision:
    label: str
    best_sim: float
    second_sim: float
    last_sim: float
    margin: float
    reason: str
    cut: bool
    cut_backtrace_sec: float


class VarKClustering:
    """オンライン可変Kクラスタリング。起動直後はAHCでK推定し、その後は閾値＋短発話ルールで更新。"""

    def __init__(self):
        self.mode = os.getenv("M4_DIAR_MODE", "auto").strip().lower() or "auto"
        legacy_mode = os.getenv("M40_DIAR_MODE")
        if legacy_mode:
            self.mode = legacy_mode.strip().lower()
        self.k_max = int(os.getenv("M4_DIAR_K_MAX", "3") or "3")
        self.boot_sec = _env_float("M4_DIAR_BOOT_SEC", 35.0)
        self.freeze_sec = _env_float("M4_DIAR_FREEZE_SEC", 8.0)
        self.min_short = _env_float("M4_DIAR_MIN_SHORT_SEC", 0.45)
        self.min_switch = _env_float("M4_DIAR_MIN_SWITCH_SEC", 0.60)
        self.short_alt = _env_float("M4_DIAR_SHORT_ALT", 0.72)
        self.short_delta = _env_float("M4_DIAR_SHORT_DELTA", 0.08)
        self.sim_base = _env_float("M4_DIAR_SIM_BASE", 0.74)
        soft_env = os.getenv("M4_DIAR_SOFTWARE_MIN") or os.getenv("M4_DIAR_SOFT_MIN")
        self.soft_min = float(soft_env) if soft_env is not None else 0.62
        self.delta_switch = _env_float("M4_DIAR_DELTA_SWITCH", 0.03)
        self.margin_strong = _env_float("M4_DIAR_MARGIN_STRONG", 0.10)
        self.weak_margin = _env_float("M4_DIAR_WEAK_MARGIN", 0.05)
        self.opp_streak_n = int(os.getenv("M4_DIAR_OPP_STREAK_N", "2") or "2")
        self.opp_streak_sec = _env_float("M4_DIAR_OPP_STREAK_SEC", 1.0)
        self.sticky_sec = _env_float("M4_DIAR_STICKY_SEC", 3.0)
        self.ahc_thr = _env_float("M4_DIAR_AHC_DIST_THR", 0.82)
        self.new_min_sec = _env_float("M4_DIAR_NEW_SPK_MIN_SEC", 2.4)
        self.new_cooldown = _env_float("M4_DIAR_NEW_SPK_COOLDOWN_SEC", 6.0)
        self.new_max_sim = _env_float("M4_DIAR_NEW_SPK_MAX_SIM", 0.995)
        self.switch_delta = _env_float("M4_DIAR_SWITCH_DELTA", 0.0015)
        same_sim = os.getenv("M4_DIAR_SAME_SPK_SIM")
        if same_sim is not None:
            self.same_spk_sim = float(same_sim)
        else:
            # 後方互換: 旧来の new_max_sim をそのまま「同一話者しきい値」として使う
            self.same_spk_sim = self.new_max_sim
        self.same_spk_sim = max(-1.0, min(1.0, self.same_spk_sim))
        self.prune_sec = _env_float("M4_DIAR_PRUNE_SEC", 3.0)
        self.bt_sec = _env_float("M4_DIAR_REASSIGN_BACKTRACE_SEC", 4.0)
        self.log_decisions = os.getenv("M4_DIAR_LOG_DECISIONS", "off").strip().lower() not in {"0", "off", "false"}

        self.sr = int(os.getenv("M4_ASR_SR", "16000") or "16000")
        self.emb = SpeakerEmbedding()
        self.start_t = time.monotonic()
        self.last_new_t = self.start_t

        self.centroids: Dict[str, np.ndarray] = {}
        self.durations: Dict[str, float] = defaultdict(float)
        self.boot: deque[Tuple[float, float, np.ndarray]] = deque(maxlen=512)
        self.last_spk: Optional[str] = None
        self._streak = {"n": 0, "dur": 0.0}
        self.last_switch_ts = self.start_t

    # --- helpers ---------------------------------------------------------
    def _embed_wav(self, wav: np.ndarray) -> Optional[np.ndarray]:
        if wav.size == 0:
            return None
        try:
            vec = self.emb.embed(wav.astype(np.float32), sr=self.sr)
        except Exception as exc:
            logger.warning(f"speaker embed failed: {exc!r}")
            return None
        if vec is None or not np.isfinite(vec).all():
            return None
        return l2_norm(vec.astype(np.float32))

    def _bootstrap_if_needed(self) -> None:
        if self.mode != "auto":
            return
        elapsed = time.monotonic() - self.start_t
        if self.centroids or elapsed < self.boot_sec:
            return
        if len(self.boot) < 6:
            if self.boot:
                self.centroids["S1"] = l2_norm(self.boot[0][2])
                logger.info("[SPK] bootstrap -> K=1 (insufficient evidence)")
            self.boot.clear()
            return
        embs = np.stack([item[2] for item in self.boot], axis=0)
        best_score = -1.0
        best_labels = np.zeros(len(embs), dtype=int)
        best_k = 1
        for k in range(1, min(self.k_max, len(embs)) + 1):
            labels = ahc_cosine(embs, k, self.ahc_thr)
            score = silhouette_like(embs, labels)
            if score > best_score:
                best_score = score
                best_labels = labels
                best_k = len(set(labels))
        self.centroids.clear()
        for idx in range(best_k):
            members = embs[best_labels == idx]
            if members.size == 0:
                continue
            self.centroids[f"S{len(self.centroids)+1}"] = l2_norm(members.mean(axis=0))
        self.boot.clear()
        self.last_new_t = time.monotonic()
        logger.info(f"[SPK] bootstrap -> K={len(self.centroids) or 1} (score={best_score:.3f})")

    def _can_make_new(self) -> bool:
        if self.mode == "fixed2":
            return len(self.centroids) < 2
        if self.mode == "fixedk":
            return len(self.centroids) < self.k_max
        if self.mode == "auto":
            now = time.monotonic()
            if len(self.centroids) >= self.k_max:
                return False
            if (now - self.start_t) < self.freeze_sec:
                return False
            if (now - self.last_new_t) < self.new_cooldown:
                return False
            return True
        return False

    def _update_centroid(self, spk: str, vec: np.ndarray, conf: float) -> None:
        vec = l2_norm(vec)
        base = self.centroids.get(spk)
        if base is None:
            self.centroids[spk] = vec
            return
        conf_term = max(0.0, conf - self.soft_min)
        alpha = 0.06 * max(0.25, min(1.0, conf_term / max(1e-6, 1.0 - self.soft_min)))
        updated = l2_norm((1.0 - alpha) * base + alpha * vec)
        self.centroids[spk] = updated

    def _prune_short_clusters(self, keep: str) -> None:
        if self.mode != "auto":
            return
        for spk, dur in list(self.durations.items()):
            if spk == keep or dur >= self.prune_sec:
                continue
            if len(self.centroids) <= 1:
                continue
            candidates = [c for c in self.centroids.keys() if c != spk]
            if not candidates:
                continue
            tgt = max(candidates, key=lambda c: cosine(self.centroids[spk], self.centroids[c]))
            self.centroids[tgt] = l2_norm(self.centroids[tgt] + self.centroids[spk])
            del self.centroids[spk]
            del self.durations[spk]
            logger.info(f"[SPK] prune+merge {spk} -> {tgt}")

    # --- public ----------------------------------------------------------
    def assign(self, wav: np.ndarray, start_ts: Optional[float], end_ts: Optional[float]) -> str:
        if wav is None or wav.size == 0:
            return self.last_spk or "S1"
        wav = wav.astype(np.float32, copy=False)
        duration = None
        if start_ts is not None and end_ts is not None:
            duration = max(0.0, end_ts - start_ts)
        if duration is None or duration <= 0.0:
            duration = float(len(wav) / self.sr)
        start_fmt = "-" if start_ts is None else f"{start_ts:.2f}"
        end_fmt = "-" if end_ts is None else f"{end_ts:.2f}"
        tag_logger = logger.bind(tag="diar.assign")
        if self.log_decisions:
            tag_logger.debug(
                f"[SPK_INPUT] start={start_fmt}s end={end_fmt}s dur={duration:.2f}s clusters={len(self.centroids)}"
            )
        vec = self._embed_wav(wav)
        if vec is None:
            return self.last_spk or "S1"

        now = time.monotonic()
        if self.mode == "auto" and not self.centroids:
            self.boot.append((start_ts or 0.0, end_ts or 0.0, vec))
            if now - self.start_t >= self.boot_sec:
                self._bootstrap_if_needed()

        if not self.centroids:
            spk = "S1"
            self.centroids[spk] = vec
            self.durations[spk] += duration
            self.last_spk = spk
            self.last_switch_ts = now
            logger.info(f"[SPK] init cluster {spk} (dur={duration:.2f}s start={start_fmt}s end={end_fmt}s)")
            return spk

        sims = {spk: cosine(vec, c) for spk, c in self.centroids.items()}
        best = max(sims, key=sims.get)
        best_sim = sims[best]
        sorted_sims = sorted(sims.items(), key=lambda item: item[1], reverse=True)
        second = sorted_sims[1][1] if len(sorted_sims) > 1 else -1.0
        margin = best_sim - second
        last = self.last_spk
        last_sim = sims.get(last, -1.0) if last else -1.0
        if self.log_decisions:
            tag_logger.debug(
                f"[SPK_SCORE] start={start_fmt}s end={end_fmt}s dur={duration:.2f}s best={best} sim={best_sim:.3f} "
                f"second={second:.3f} margin={margin:.3f} last={last or '-'} last_sim={last_sim:.3f} "
                f"new_gate<{self.same_spk_sim:.4f}"
            )

        def log_choice(kind: str, label: str) -> None:
            tag_logger.info(
                f"[SPK_{kind}] label={label} start={start_fmt}s end={end_fmt}s dur={duration:.2f}s "
                f"best={best_sim:.3f} second={second:.3f} margin={margin:.3f} "
                f"last={last or '-'} last_sim={last_sim:.3f} clusters={len(self.centroids)}"
            )

        # 短発話はstick優先
        if duration < self.min_short:
            chosen = last or best
            if last and best != last:
                if best_sim >= self.short_alt and (best_sim - last_sim) >= self.short_delta:
                    chosen = best
            self._update_centroid(chosen, vec, best_sim)
            self.durations[chosen] += duration
            self.last_spk = chosen
            if chosen != last:
                self.last_switch_ts = now
            log_choice("SHORT", chosen)
            return chosen

        if duration < self.min_switch and last:
            if best_sim >= max(self.sim_base, self.short_alt) and (best_sim - last_sim) >= self.short_delta:
                chosen = best
            else:
                chosen = last
            self._update_centroid(chosen, vec, best_sim)
            self.durations[chosen] += duration
            self.last_spk = chosen
            if chosen != last:
                self.last_switch_ts = now
            log_choice("SWITCH_GUARD", chosen)
            return chosen

        chosen = best
        since_switch = now - self.last_switch_ts
        if last and best != last:
            switch_delta = self.switch_delta
            same_th = self.same_spk_sim
            if best_sim >= same_th and last_sim >= same_th:
                chosen = last
            elif (best_sim - last_sim) < switch_delta or margin < switch_delta:
                if since_switch < self.sticky_sec:
                    chosen = last
            elif since_switch < self.sticky_sec:
                chosen = last
        self._streak = {"n": 0, "dur": 0.0}

        dur_gate = duration >= self.new_min_sec
        cooldown_ok = (now - self.last_new_t) >= self.new_cooldown
        can_new = self._can_make_new() and dur_gate and cooldown_ok
        sim_gate = best_sim < self.same_spk_sim
        margin_gate = margin >= self.margin_strong
        if len(self.centroids) < 2:
            margin_gate = True  # 2人目は余白がなくても許容
        gate_logger = logger.bind(tag="diar.gate")
        new_gate = can_new and sim_gate and margin_gate
        gate_logger.debug(
            "[SPK_GATE] start=%s end=%s dur=%.2fs best=%.3f margin=%.3f "
            "sim_gate=%s margin_ok=%s dur_ok=%s cooldown_ok=%s can_new=%s same_th=%.3f",
            start_fmt,
            end_fmt,
            duration,
            best_sim,
            margin,
            sim_gate,
            margin_gate,
            dur_gate,
            cooldown_ok,
            can_new,
            self.same_spk_sim,
        )
        if new_gate:
            new_name = f"S{len(self.centroids) + 1}"
            self.centroids[new_name] = vec
            self.durations[new_name] = duration
            self.last_spk = new_name
            self.last_new_t = now
            self.last_switch_ts = now
            log_choice("NEW", new_name)
            return new_name

        self._update_centroid(chosen, vec, best_sim)
        self.durations[chosen] += duration
        self.last_spk = chosen
        if chosen != last:
            self.last_switch_ts = now
        self._prune_short_clusters(chosen)
        log_choice("MERGE", chosen)
        return chosen


class StreamingDiarizer:
    """
    軽量インライン話者トラッカー（ASR内の文中カット用）
    - シンプルなEMAクラスタ + 類似度監視で cut 判定
    - OnlineDiarizer(assign_speaker) とは独立に動作
    """

    def __init__(self, sample_rate: int):
        self.sr = sample_rate
        self.emb = SpeakerEmbedding()
        self.centroids: Dict[str, np.ndarray] = {}
        self.durations: Dict[str, float] = defaultdict(float)
        self.alpha = _env_float("M4_DIAR_STREAM_EMA", 0.12)
        self.max_spk = int(os.getenv("M4_DIAR_MAX_K", "3") or "3")
        self.margin_strong = _env_float("M4_DIAR_MARGIN_STRONG", 0.10)
        self.weak_margin = _env_float("M4_DIAR_WEAK_MARGIN", 0.05)
        self.long_switch_sec = _env_float("M4_DIAR_LONG_SWITCH_SEC", 1.8)
        self.weak_req_sec = _env_float("M4_DIAR_OPP_STREAK_SEC", 1.0)
        self.weak_req_n = int(os.getenv("M4_DIAR_OPP_STREAK_N", "2") or "2")
        self.min_switch_sec = _env_float("M4_DIAR_MIN_SWITCH_SEC", 0.6)
        self.cut_backtrace_sec = _env_float("M4_DIAR_INTRASPLIT_BACKTRACE_SEC", 0.45)
        self.cooldown_sec = _env_float("M4_DIAR_INTRASPLIT_COOLDOWN_SEC", 2.5)
        self.sim_new_threshold = _env_float("M4_DIAR_SIM_BASE", 0.74) - 0.08

        self.last_cut_ts = -1e9
        self.last_label: Optional[str] = None
        self.opp_streak_sec = 0.0
        self.weak_hit_sec = 0.0
        self.weak_hit_count = 0

    def _embed(self, wav: np.ndarray) -> Optional[np.ndarray]:
        if wav.size == 0:
            return None
        try:
            vec = self.emb.embed(wav.astype(np.float32), sr=self.sr)
        except Exception as exc:
            logger.debug(f"stream diar embed failed: {exc!r}")
            return None
        if vec is None or not np.isfinite(vec).all():
            return None
        return l2_norm(vec.astype(np.float32))

    def _update_centroid(self, label: str, vec: np.ndarray, conf: float) -> None:
        base = self.centroids.get(label)
        if base is None:
            self.centroids[label] = vec
            return
        alpha = max(0.05, min(0.5, self.alpha * max(0.2, conf)))
        self.centroids[label] = l2_norm((1.0 - alpha) * base + alpha * vec)

    def _ensure_label(self, vec: np.ndarray) -> str:
        if not self.centroids:
            self.centroids["S1"] = vec
            return "S1"
        sims = {lbl: cosine(vec, cen) for lbl, cen in self.centroids.items()}
        best = max(sims, key=sims.get)
        best_sim = sims[best]
        if best_sim < self.sim_new_threshold and len(self.centroids) < self.max_spk:
            new_label = f"S{len(self.centroids) + 1}"
            self.centroids[new_label] = vec
            logger.info(f"[SPK] streaming new speaker -> {new_label} (sim={best_sim:.2f})")
            return new_label
        return best

    def step(
        self,
        wav: np.ndarray,
        current_label: Optional[str],
        seg_dur_sec: float,
        hop_sec: float,
    ) -> Optional[DiarDecision]:
        vec = self._embed(wav)
        if vec is None:
            return None
        label = self._ensure_label(vec)
        sims = {lbl: cosine(vec, cen) for lbl, cen in self.centroids.items()}
        best_label = max(sims, key=sims.get)
        best_sim = sims[best_label]
        second_sim = max((v for k, v in sims.items() if k != best_label), default=-1.0)
        last_sim = sims.get(current_label or self.last_label or best_label, -1.0)
        margin = best_sim - second_sim
        if self.last_label is None:
            self.last_label = best_label

        self._update_centroid(best_label, vec, best_sim)

        target_label = current_label or self.last_label or best_label
        if target_label and best_label != target_label:
            self.opp_streak_sec += hop_sec
            if margin >= self.weak_margin:
                self.weak_hit_sec += hop_sec
                self.weak_hit_count += 1
        else:
            self.opp_streak_sec = max(0.0, self.opp_streak_sec - hop_sec)
            self.weak_hit_sec = max(0.0, self.weak_hit_sec - 0.5 * hop_sec)
            if self.weak_hit_count > 0:
                self.weak_hit_count -= 1

        now = time.monotonic()
        rule = ""
        cut = False
        if margin >= self.margin_strong and seg_dur_sec >= self.min_switch_sec:
            rule, cut = "margin-strong", True
        elif self.opp_streak_sec >= self.long_switch_sec and seg_dur_sec >= self.min_switch_sec:
            rule, cut = "long-dominance", True
        elif (
            self.weak_hit_count >= self.weak_req_n
            and self.weak_hit_sec >= self.weak_req_sec
            and seg_dur_sec >= self.min_switch_sec
        ):
            rule, cut = "weak-accum", True

        if cut and (now - self.last_cut_ts) < self.cooldown_sec:
            cut = False
            rule = ""

        if cut:
            self.last_cut_ts = now
            self.last_label = best_label
            self.opp_streak_sec = 0.0
            self.weak_hit_sec = 0.0
            self.weak_hit_count = 0
        else:
            self.last_label = current_label or best_label

        return DiarDecision(
            label=best_label,
            best_sim=best_sim,
            second_sim=second_sim,
            last_sim=last_sim,
            margin=margin,
            reason=rule,
            cut=cut,
            cut_backtrace_sec=self.cut_backtrace_sec if cut else 0.0,
        )

    def notify_segment_end(self, label: Optional[str]) -> None:
        if label:
            self.last_label = label
        self.opp_streak_sec = 0.0
        self.weak_hit_sec = 0.0
        self.weak_hit_count = 0


class OnlineDiarizer(VarKClustering):
    """
    既存IF互換のラッパー。assign_speaker(pcm16, (start,end)) を提供する。
    """

    def assign_speaker(
        self, audio: Union[bytes, bytearray, memoryview, np.ndarray], t_range: Optional[Tuple[float, float]]
    ) -> str:
        if isinstance(audio, (bytes, bytearray, memoryview)):
            buf = audio.tobytes() if isinstance(audio, memoryview) else bytes(audio)
            wav = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            wav = np.asarray(audio, dtype=np.float32)
        start = t_range[0] if t_range else None
        end = t_range[1] if t_range else None
        return self.assign(wav, start, end)
