from __future__ import annotations

import re
import unicodedata
from typing import List, Sequence, Tuple

from jiwer import cer as jiwer_cer
from jiwer import wer as jiwer_wer

try:
  from fugashi import Tagger

  _tagger: Tagger | None = Tagger()
except Exception:
  _tagger = None

BRACKET_PATTERNS: Tuple[re.Pattern[str], ...] = tuple(
  re.compile(p, flags=re.IGNORECASE) for p in [
    r"\[[^\]]*(?:♪|music|音楽|applause|laugh|拍手|笑)[^\]]*\]",
    r"\([^\)]*(?:♪|music|音楽|applause|laugh|拍手|笑)[^\)]*\)",
    r"（[^）]*(?:♪|music|音楽|applause|laugh|拍手|笑)[^）]*）",
  ]
)

PUNCTUATION = re.compile(r"[、。，．,\.｡；;:！？!?・…⋯〜～ー—―‐\-＝=／/\"'「」『』（）()［］\[\]{}〈〉《》【】•‥·`´＇’“”‘’＆&＠@＃#＊*＋+％%]")
MULTI_WHITE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
  """Normalize Japanese text for ASR scoring."""
  if not text:
    return ""
  normalized = unicodedata.normalize("NFKC", text)
  normalized = normalized.replace("\u3000", " ")
  for pattern in BRACKET_PATTERNS:
    normalized = pattern.sub(" ", normalized)
  normalized = normalized.replace("\r", " ").replace("\n", " ")
  normalized = PUNCTUATION.sub(" ", normalized)
  normalized = MULTI_WHITE.sub(" ", normalized)
  return normalized.strip()


def _tokenize_core(text: str) -> List[str]:
  if not text:
    return []
  compact = text.replace(" ", "")
  if not compact:
    return []
  if _tagger:
    return [m.surface for m in _tagger(compact) if m.surface.strip()]
  return list(compact)


def tokenize(text: str) -> List[str]:
  return _tokenize_core(normalize_text(text))


def levenshtein(ref: Sequence[str], hyp: Sequence[str]) -> int:
  m, n = len(ref), len(hyp)
  if m == 0:
    return n
  if n == 0:
    return m
  dp = list(range(n + 1))
  for i in range(1, m + 1):
    prev = dp[0]
    dp[0] = i
    ri = ref[i - 1]
    for j in range(1, n + 1):
      tmp = dp[j]
      cost = 0 if ri == hyp[j - 1] else 1
      dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
      prev = tmp
  return dp[n]


def compute_scores(ref: str, hyp: str) -> dict:
  norm_ref = normalize_text(ref)
  norm_hyp = normalize_text(hyp)
  tokens_ref = _tokenize_core(norm_ref)
  tokens_hyp = _tokenize_core(norm_hyp)

  result = {
    "ref_length_tokens": len(tokens_ref),
    "hyp_length_tokens": len(tokens_hyp),
    "ref_length_chars": len(norm_ref.replace(" ", "")),
    "hyp_length_chars": len(norm_hyp.replace(" ", "")),
    "wer": None,
    "cer": None,
    "jwer": None,
  }

  if tokens_ref:
    joined_ref = " ".join(tokens_ref)
    joined_hyp = " ".join(tokens_hyp)
    result["wer"] = jiwer_wer(joined_ref, joined_hyp)
    result["jwer"] = levenshtein(tokens_ref, tokens_hyp) / max(1, len(tokens_ref))
  if norm_ref:
    ref_chars = norm_ref.replace(" ", "")
    hyp_chars = norm_hyp.replace(" ", "")
    result["cer"] = jiwer_cer(ref_chars, hyp_chars)
  return result


def passes_thresholds(scores: dict, *, wer: float = 0.35, cer: float = 0.25, jwer: float = 0.35) -> bool:
  if scores.get("wer") is None or scores.get("cer") is None or scores.get("jwer") is None:
    return False
  return scores["wer"] <= wer and scores["cer"] <= cer and scores["jwer"] <= jwer
