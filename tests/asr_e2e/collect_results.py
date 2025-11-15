from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from asr_metrics import compute_scores, passes_thresholds

DEFAULT_OUT_ROOT = Path("tests/asr_e2e/out")
DEFAULT_RESULTS_MD = Path("tests/asr_e2e/TEST_RESULTS.md")


def read_text(path: Path) -> str:
  return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def load_json(path: Path) -> Dict[str, Any]:
  if not path.exists():
    return {}
  return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def format_pct(value: Optional[float]) -> str:
  if value is None:
    return "n/a"
  return f"{value * 100:.1f}%"


def ensure_scores(run_dir: Path) -> Dict[str, Any]:
  scores_path = run_dir / "scores.json"
  if scores_path.exists():
    bundle = load_json(scores_path)
    bundle.setdefault("scores_path", str(scores_path))
    return bundle

  ref = read_text(run_dir / "ref.txt")
  hyp = read_text(run_dir / "hyp.txt")
  if not ref or not hyp:
    bundle = {
      "video_id": run_dir.name,
      "title": "",
      "duration_sec": None,
      "language": None,
      "transcript": {},
      "audio": {},
      "asr": {},
      "scores": {"wer": None, "cer": None, "jwer": None},
      "metadata": {"generated": True, "notes": "", "source": "collect_results"},
      "scores_path": str(scores_path),
    }
    return bundle

  scores = compute_scores(ref, hyp)
  bundle = {
    "video_id": run_dir.name,
    "title": "",
    "duration_sec": None,
    "language": None,
    "transcript": {},
    "audio": {},
    "asr": {},
    "scores": scores,
    "metadata": {"generated": True, "notes": "", "source": "collect_results"},
    "scores_path": str(scores_path),
  }
  write_json(scores_path, bundle)
  return bundle


def load_run(run_dir: Path) -> Dict[str, Any]:
  run_dir = run_dir.resolve()
  ref = read_text(run_dir / "ref.txt")
  hyp = read_text(run_dir / "hyp.txt")
  metrics = load_json(run_dir / "metrics.json")
  bundle = ensure_scores(run_dir)
  scores = bundle.get("scores", {})
  return {
    "dir": run_dir,
    "video_id": bundle.get("video_id") or run_dir.name,
    "ref_missing": not bool(ref),
    "hyp_missing": not bool(hyp),
    "scores_bundle": bundle,
    "scores": scores,
    "metrics": metrics,
  }


def is_run_dir(path: Path) -> bool:
  return path.is_dir() and ((path / "scores.json").exists() or (path / "ref.txt").exists())


def gather_run_dirs(root: Path) -> List[Path]:
  root = root.resolve()
  runs: List[Path] = []
  if is_run_dir(root):
    runs.append(root)
    return runs
  if not root.exists():
    return []
  candidates = [p for p in root.iterdir() if p.is_dir() and is_run_dir(p)]
  candidates.sort(key=lambda p: p.stat().st_mtime)
  return candidates


def append_result_md(run: Dict[str, Any], *, thresholds: Dict[str, float], output_path: Path) -> None:
  scores = run["scores"]
  ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  bundle = run["scores_bundle"]
  metrics = run["metrics"]

  lines = [
    f"\n## Run @ {ts}",
    "",
    f"- run_dir: {run['dir']}",
    f"- video_id: {bundle.get('video_id', '')}",
  ]
  title = bundle.get("title")
  if title:
    lines.append(f"- title: {title}")
  duration = bundle.get("duration_sec")
  if duration is not None:
    lines.append(f"- duration_sec: {duration}")
  rtf = (bundle.get("asr") or {}).get("rtf")
  if rtf is not None:
    lines.append(f"- RTF: {rtf:.3f}")
  lines.extend([
    f"- WER: {format_pct(scores.get('wer'))}",
    f"- CER: {format_pct(scores.get('cer'))}",
    f"- jWER: {format_pct(scores.get('jwer'))}",
    f"- thresholds: wer≤{thresholds['wer']*100:.0f}%, cer≤{thresholds['cer']*100:.0f}%, jwer≤{thresholds['jwer']*100:.0f}%",
  ])
  if metrics:
    lines.append("\n**Transport metrics**\n")
    for key, value in metrics.items():
      lines.append(f"- {key}: {value}")

  output_path.parent.mkdir(parents=True, exist_ok=True)
  with output_path.open("a", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")


def rows_for_runs(runs: Iterable[Dict[str, Any]]) -> List[List[str]]:
  rows: List[List[str]] = []
  for run in runs:
    bundle = run["scores_bundle"]
    scores = run["scores"]
    asr = bundle.get("asr") or {}
    metadata = bundle.get("metadata") or {}
    rtf = asr.get("rtf")
    rows.append([
      str(bundle.get("video_id", run["dir"].name)),
      str(bundle.get("language") or ""),
      f"{bundle.get('duration_sec', '')}",
      f"{scores.get('wer'):.3f}" if scores.get("wer") is not None else "",
      f"{scores.get('cer'):.3f}" if scores.get("cer") is not None else "",
      f"{scores.get('jwer'):.3f}" if scores.get("jwer") is not None else "",
      f"{rtf:.2f}" if rtf is not None else "",
      str(asr.get("model") or ""),
      str(asr.get("beam_size") or ""),
      str(metadata.get("caption_source") or ""),
      str(metadata.get("notes") or ""),
    ])
  return rows


def table_from_runs(runs: Iterable[Dict[str, Any]]) -> str:
  header = ["video_id", "lang", "dur(s)", "WER", "CER", "jWER", "RTF", "model", "beam", "subtitle", "notes"]
  lines = [
    "| " + " | ".join(header) + " |",
    "| " + " | ".join(["---"] * len(header)) + " |",
  ]
  for row in rows_for_runs(runs):
    lines.append("| " + " | ".join(row) + " |")
  return "\n".join(lines)


def csv_from_runs(runs: Iterable[Dict[str, Any]]) -> str:
  header = ["video_id", "lang", "dur(s)", "WER", "CER", "jWER", "RTF", "model", "beam", "subtitle", "notes"]
  lines = [",".join(header)]
  for row in rows_for_runs(runs):
    escaped = [value.replace('"', '""') for value in row]
    lines.append(",".join(f'"{value}"' for value in escaped))
  return "\n".join(lines)


def metric_value(bundle: Dict[str, Any], metric: str) -> Optional[float]:
  upper = metric.upper()
  scores = bundle.get("scores") or {}
  asr = bundle.get("asr") or {}
  if upper in {"WER", "CER", "JWER"}:
    return scores.get(upper.lower())
  if upper == "RTF":
    return asr.get("rtf")
  return None


def compare_against_baseline(
  runs: List[Dict[str, Any]],
  baseline_path: Path,
  *,
  fail_on_regression: bool,
) -> Tuple[bool, List[str]]:
  if not baseline_path.exists():
    raise SystemExit(f"baseline ファイルが存在しません: {baseline_path}")
  baseline = load_json(baseline_path)
  targets = baseline.get("targets") or {}
  tolerance = baseline.get("tolerance") or {}
  by_video = {run["scores_bundle"].get("video_id", run["dir"].name): run for run in runs}

  regressions: List[str] = []
  for video_id, expected in targets.items():
    run = by_video.get(video_id)
    if not run:
      regressions.append(f"{video_id}: 結果が見つかりません")
      continue
    bundle = run["scores_bundle"]
    for metric_name, baseline_value in expected.items():
      actual = metric_value(bundle, metric_name)
      if actual is None:
        regressions.append(f"{video_id}: {metric_name} が計測されていません")
        continue
      tol = tolerance.get(metric_name) or 0.0
      if actual > baseline_value + tol:
        regressions.append(
          f"{video_id}: {metric_name} 回帰 (actual={actual:.3f}, baseline={baseline_value:.3f}, tol={tol:.3f})"
        )

  ok = not regressions or not fail_on_regression
  return ok, regressions


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="ASR 結果の集計・検証ツール")
  parser.add_argument("table_dir", nargs="?", help="scores.json が並ぶディレクトリを指定すると Markdown テーブルを出力")
  parser.add_argument("--run-dir", help="単一または複数ベンチ結果のディレクトリ（既定: tests/asr_e2e/out）")
  parser.add_argument("--append", action="store_true", help="TEST_RESULTS.md に結果を追記します")
  parser.add_argument("--output", default=str(DEFAULT_RESULTS_MD), help="--append 時の出力先ファイル")
  parser.add_argument("--threshold-wer", type=float, default=0.35)
  parser.add_argument("--threshold-cer", type=float, default=0.25)
  parser.add_argument("--threshold-jwer", type=float, default=0.35)
  parser.add_argument("--skip-missing", action="store_true", help="ref/hyp が不足している場合は失敗ではなくスキップ扱いにします")
  parser.add_argument("--table", action="store_true", help="Markdown テーブルを標準出力に表示します")
  parser.add_argument("--csv", action="store_true", help="CSV を標準出力に表示します")
  parser.add_argument("--compare", help="baseline.json を比較し回帰を検出します")
  parser.add_argument("--fail-on-regression", action="store_true", help="回帰検出時に exit code 1 を返します")
  return parser.parse_args()


def main() -> None:
  args = parse_args()
  thresholds = {"wer": args.threshold_wer, "cer": args.threshold_cer, "jwer": args.threshold_jwer}

  if args.table_dir:
    root = Path(args.table_dir)
    runs = [load_run(run_dir) for run_dir in gather_run_dirs(root)]
    if not runs:
      raise SystemExit(f"{root} に scores.json が見つかりません")
    print(table_from_runs(runs))
    if args.csv:
      print()
      print(csv_from_runs(runs))
    return

  run_root = Path(args.run_dir) if args.run_dir else DEFAULT_OUT_ROOT
  run_dirs = gather_run_dirs(run_root)
  if not run_dirs:
    raise SystemExit(f"{run_root} に成果物が見つかりません")

  runs = [load_run(run_dir) for run_dir in run_dirs]

  exit_code = 0
  append_path = Path(args.output)
  threshold_failures: List[str] = []

  for run in runs:
    video_id = run["video_id"]
    scores = run["scores"]
    missing = run["ref_missing"] or run["hyp_missing"]
    if missing:
      msg = f"{video_id}: ref/hyp が不足しているため判定できません"
      if args.skip_missing:
        print(f"[collect] ⚠️  {msg}")
        continue
      threshold_failures.append(msg)
      continue

    passed = passes_thresholds(scores, wer=thresholds["wer"], cer=thresholds["cer"], jwer=thresholds["jwer"])
    print(f"{video_id}: WER={format_pct(scores.get('wer'))} CER={format_pct(scores.get('cer'))} jWER={format_pct(scores.get('jwer'))}")
    if not passed:
      threshold_failures.append(f"{video_id}: しきい値未達")
    if args.append:
      append_result_md(run, thresholds=thresholds, output_path=append_path)

  if threshold_failures:
    exit_code = 1
    for failure in threshold_failures:
      print(f"[collect] ❌ {failure}", file=sys.stderr)

  if args.compare:
    ok, regressions = compare_against_baseline(runs, Path(args.compare), fail_on_regression=args.fail_on_regression)
    if regressions:
      for reg in regressions:
        print(f"[collect] 回帰: {reg}", file=sys.stderr)
    if not ok:
      exit_code = 1

  if args.table:
    print()
    print(table_from_runs(runs))
  if args.csv:
    print()
    print(csv_from_runs(runs))

  raise SystemExit(exit_code)


if __name__ == "__main__":
  main()
