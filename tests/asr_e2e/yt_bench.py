from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
  from faster_whisper import WhisperModel
except ImportError as exc:
  raise SystemExit("faster-whisper が見つかりません。tests/asr_e2e/requirements-optional.txt をインストールしてください") from exc

try:
  from yt_dlp import YoutubeDL
except ImportError as exc:
  raise SystemExit("yt-dlp が見つかりません。tests/asr_e2e/requirements-optional.txt をインストールしてください") from exc

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from asr_metrics import compute_scores, passes_thresholds  # noqa: E402
from yt_utils import extract_video_id, fetch_transcript  # noqa: E402

OUT_ROOT = ROOT / "out"
DEFAULT_RESULTS_MD = ROOT / "TEST_RESULTS.md"
COLLECT = ROOT / "collect_results.py"
DEFAULT_THRESHOLDS = {"wer": 0.35, "cer": 0.25, "jwer": 0.35}


def write_text(path: Path, text: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(text.strip() + "\n", encoding="utf-8")


def write_json(path: Path, data: Dict[str, Any]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Transcriber:
  def __init__(self, model_name: str, device: str, compute_type: str, beam_size: int):
    self.model_name = model_name
    self.device = device
    self.compute_type = compute_type
    self.beam_size = beam_size
    self.model = WhisperModel(model_name, device=device, compute_type=compute_type)

  def run(self, audio_path: Path) -> Dict[str, Any]:
    start = time.perf_counter()
    segments, info = self.model.transcribe(
      str(audio_path),
      beam_size=self.beam_size,
      language="ja",
      vad_filter=True,
      task="transcribe",
    )
    lines: List[str] = []
    for seg in segments:
      text = (seg.text or "").strip()
      if text:
        lines.append(text)
    decode_seconds = time.perf_counter() - start
    return {
      "text": "\n".join(lines).strip(),
      "duration": info.duration,
      "language": info.language,
      "decode_seconds": decode_seconds,
    }


def load_urls(url: Optional[str], url_file: Optional[str]) -> List[str]:
  urls: List[str] = []
  if url:
    urls.append(url)
  if url_file:
    file_path = Path(url_file)
    if not file_path.exists():
      raise SystemExit(f"{file_path} が存在しません")
    for line in file_path.read_text(encoding="utf-8").splitlines():
      stripped = line.strip()
      if stripped and not stripped.startswith("#"):
        urls.append(stripped)
  env_url = os.environ.get("npm_config_url")
  if not urls and env_url:
    urls.append(env_url)
  if not urls:
    raise SystemExit("--url= または --url-file= で対象動画を指定してください")
  return urls


def ensure_cache_hit(cache_dir: Path, video_id: str) -> Optional[Path]:
  if not cache_dir.exists():
    return None
  for candidate in cache_dir.glob(f"{video_id}.*"):
    if candidate.is_file():
      return candidate
  return None


def download_audio(url: str, video_id: str, run_dir: Path, *, cache_dir: Optional[Path], log: Callable[[str], None]) -> Dict[str, Any]:
  run_dir.mkdir(parents=True, exist_ok=True)
  ffmpeg = os.environ.get("FFMPEG", "ffmpeg")
  info: Dict[str, Any]
  orig_path: Path

  cache_src: Optional[Path] = None
  if cache_dir is not None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_src = ensure_cache_hit(cache_dir, video_id)
    if cache_src:
      log(f"use cached audio: {cache_src}")
      with YoutubeDL({"quiet": True, "no_warnings": True, "extractor_args": {"youtube": {"player_client": ["android"]}}}) as ydl:
        info = ydl.extract_info(url, download=False)
      orig_path = run_dir / f"audio_orig{cache_src.suffix}"
      shutil.copy2(cache_src, orig_path)

  if cache_src is None:
    with tempfile.TemporaryDirectory() as tmpdir:
      tmp_path = Path(tmpdir)
      ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(tmp_path / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
      }
      with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        src_path = Path(ydl.prepare_filename(info))
        if not src_path.exists():
          raise RuntimeError("音声のダウンロードに失敗しました")
        orig_path = run_dir / f"audio_orig{src_path.suffix}"
        shutil.copy2(src_path, orig_path)
        if cache_dir is not None:
          cache_dest = cache_dir / src_path.name
          shutil.copy2(src_path, cache_dest)

  wav_path = run_dir / "audio_16k.wav"
  cmd = [
    ffmpeg,
    "-y",
    "-i",
    str(orig_path),
    "-ar",
    "16000",
    "-ac",
    "1",
    "-c:a",
    "pcm_s16le",
    str(wav_path),
  ]
  log(" ".join(cmd))
  proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
  if proc.returncode != 0:
    raise RuntimeError(f"ffmpeg 変換に失敗しました: {proc.stderr.strip()}")
  return {
    "info": info,
    "audio_orig": orig_path,
    "audio_wav": wav_path,
  }


def run_collect(run_dir: Path, thresholds: Dict[str, float], append_path: Optional[Path], *, table: bool = False, csv: bool = False) -> int:
  executable = os.environ.get("PYTHON_FOR_BENCH", sys.executable)
  cmd = [
    executable,
    str(COLLECT),
    "--run-dir",
    str(run_dir),
    "--threshold-wer",
    str(thresholds["wer"]),
    "--threshold-cer",
    str(thresholds["cer"]),
    "--threshold-jwer",
    str(thresholds["jwer"]),
  ]
  if append_path:
    cmd.extend(["--output", str(append_path), "--append"])
  if table:
    cmd.append("--table")
  if csv:
    cmd.append("--csv")
  proc = subprocess.run(cmd, check=False)
  return proc.returncode


def benchmark_single(index: int, url: str, *, make_transcriber: Callable[[], Transcriber], thresholds: Dict[str, float], cache_dir: Optional[Path]) -> Dict[str, Any]:
  video_id = extract_video_id(url)
  run_dir = OUT_ROOT / video_id
  log_lines: List[str] = []

  def log(message: str) -> None:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}"
    print(f"[bench:yt] [{video_id}] {line}")
    log_lines.append(line)

  try:
    transcript = fetch_transcript(video_id, url=url)
    if not transcript.get("text"):
      raise RuntimeError("字幕テキストを取得できませんでした")
    write_text(run_dir / "ref.txt", transcript["text"])
    log("wrote ref.txt")

    download_result = download_audio(url, video_id, run_dir, cache_dir=cache_dir, log=log)
    info = download_result["info"]
    log(f"downloaded audio: {download_result['audio_orig'].name}")

    ctx = make_transcriber()
    transcribed = ctx.run(download_result["audio_wav"])
    if not transcribed["text"]:
      raise RuntimeError("ASR結果が空でした")
    write_text(run_dir / "hyp.txt", transcribed["text"])
    log("wrote hyp.txt")

    scores_detail = compute_scores(transcript["text"], transcribed["text"])
    asr_meta = {
      "model": ctx.model_name,
      "device": ctx.device,
      "compute_type": ctx.compute_type,
      "beam_size": ctx.beam_size,
      "decode_seconds": round(transcribed["decode_seconds"], 3),
      "rtf": round(transcribed["decode_seconds"] / transcribed["duration"], 3) if transcribed["duration"] else None,
      "language": transcribed.get("language"),
    }

    caption_source = transcript.get("source")
    notes = ""
    if caption_source == "auto":
      notes = "YouTube auto captions"
    elif caption_source == "translated":
      notes = "translated captions"
    elif caption_source == "yt_dlp_auto":
      notes = "yt-dlp auto captions"

    score_payload = {
      "video_id": video_id,
      "url": url,
      "title": info.get("title"),
      "duration_sec": info.get("duration"),
      "language": transcript.get("language"),
      "transcript": {
        "language": transcript.get("language"),
        "is_generated": transcript.get("is_generated"),
        "was_translated": transcript.get("was_translated"),
        "source": caption_source,
      },
      "audio": {
        "original_path": download_result["audio_orig"].name,
        "converted_path": download_result["audio_wav"].name,
        "sample_rate": 16000,
        "channels": 1,
        "sample_format": "pcm_s16le",
      },
      "asr": asr_meta,
      "scores": {
        "wer": scores_detail.get("wer"),
        "cer": scores_detail.get("cer"),
        "jwer": scores_detail.get("jwer"),
        "ref_length_tokens": scores_detail.get("ref_length_tokens"),
        "hyp_length_tokens": scores_detail.get("hyp_length_tokens"),
        "ref_length_chars": scores_detail.get("ref_length_chars"),
        "hyp_length_chars": scores_detail.get("hyp_length_chars"),
      },
      "metadata": {
        "timestamp": datetime.datetime.now().isoformat(),
        "notes": notes,
        "source": "yt_bench",
        "caption_source": caption_source,
        "is_generated_subtitle": bool(transcript.get("is_generated")),
      },
    }

    threshold_pass = passes_thresholds(
      score_payload["scores"],
      wer=thresholds["wer"],
      cer=thresholds["cer"],
      jwer=thresholds["jwer"],
    )
    score_payload["metadata"]["threshold_pass"] = threshold_pass

    write_json(run_dir / "scores.json", score_payload)
    write_json(
      run_dir / "metrics.json",
      {
        "mode": "youtube_bench",
        "video_id": video_id,
        "duration_sec": info.get("duration"),
        "rtf": asr_meta["rtf"],
        "model": ctx.model_name,
        "device": ctx.device,
      },
    )
    write_text(run_dir / "bench.log", "\n".join(log_lines))

    return {
      "index": index,
      "url": url,
      "video_id": video_id,
      "run_dir": run_dir,
      "threshold_pass": threshold_pass,
      "error": None,
      "caption_source": caption_source,
    }
  except Exception as exc:  # noqa: BLE001
    write_text(run_dir / "bench.log", "\n".join(log_lines + [f"ERROR: {exc}"]))
    return {
      "index": index,
      "url": url,
      "video_id": video_id,
      "run_dir": run_dir,
      "threshold_pass": False,
      "error": exc,
      "caption_source": None,
    }


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="YouTube 音源を用いた ASR ベンチ")
  parser.add_argument("--url", help="単発で実行する YouTube URL または動画ID")
  parser.add_argument("--url-file", help="1行1URL で列挙したテキストファイル")
  parser.add_argument("--jobs", type=int, default=1, help="同時実行数（既定:1）")
  parser.add_argument("--beam-size", type=int, default=int(os.environ.get("FW_BEAM", "5")))
  parser.add_argument("--model", default=os.environ.get("FW_MODEL", "small"))
  parser.add_argument("--device", default=os.environ.get("FW_DEVICE", "cpu"))
  parser.add_argument("--compute-type", default=os.environ.get("FW_COMPUTE_TYPE", "int8"))
  parser.add_argument("--no-append", action="store_true", help="collect_results.py で TEST_RESULTS.md に追記しません")
  parser.add_argument("--append-results", help="collect_results.py の追記先パスを明示的に指定")
  parser.add_argument("--cache-dir", help="音声ファイルのキャッシュディレクトリ（再DLを防止）")
  parser.add_argument("--cache", dest="cache_dir", help="--cache-dir のエイリアス")
  parser.add_argument("--threshold-wer", type=float, default=DEFAULT_THRESHOLDS["wer"])
  parser.add_argument("--threshold-cer", type=float, default=DEFAULT_THRESHOLDS["cer"])
  parser.add_argument("--threshold-jwer", type=float, default=DEFAULT_THRESHOLDS["jwer"])
  parser.add_argument("--table", action="store_true", help="collect_results.py 実行時に Markdown テーブルを出力")
  parser.add_argument("--csv", action="store_true", help="collect_results.py 実行時に CSV を出力")
  return parser.parse_args()


def main() -> None:
  args = parse_args()
  urls = load_urls(args.url, args.url_file)
  thresholds = {"wer": args.threshold_wer, "cer": args.threshold_cer, "jwer": args.threshold_jwer}
  cache_dir = Path(args.cache_dir).resolve() if args.cache_dir else None
  jobs = max(1, args.jobs or 1)

  OUT_ROOT.mkdir(parents=True, exist_ok=True)

  def make_transcriber() -> Transcriber:
    return Transcriber(args.model, args.device, args.compute_type, args.beam_size)

  if jobs == 1:
    shared_ctx = make_transcriber()

    def single_factory() -> Transcriber:
      return shared_ctx

    ctx_factory = single_factory
  else:
    ctx_factory = make_transcriber

  results: List[Dict[str, Any]] = []

  if jobs == 1:
    for index, url in enumerate(urls):
      result = benchmark_single(index, url, make_transcriber=ctx_factory, thresholds=thresholds, cache_dir=cache_dir)
      results.append(result)
  else:
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
      future_to_index = {
        executor.submit(
          benchmark_single,
          index,
          url,
          make_transcriber=ctx_factory,
          thresholds=thresholds,
          cache_dir=cache_dir,
        ): index
        for index, url in enumerate(urls)
      }
      for future in concurrent.futures.as_completed(future_to_index):
        results.append(future.result())

  results.sort(key=lambda item: item["index"])

  append_path: Optional[Path]
  if args.no_append:
    append_path = None
  elif args.append_results:
    append_path = Path(args.append_results).resolve()
  else:
    append_path = DEFAULT_RESULTS_MD

  successes = 0
  for result in results:
    video_id = result["video_id"]
    if result["error"]:
      print(f"[bench:yt] ❌ {video_id} ({result['url']}): {result['error']}", file=sys.stderr)
      continue
    collect_exit = run_collect(
      result["run_dir"],
      thresholds,
      append_path,
      table=args.table,
      csv=args.csv,
    )
    if collect_exit == 0:
      successes += 1
      print(f"[bench:yt] ✅ {video_id} OK")
    else:
      print(f"[bench:yt] ❌ {video_id} collect_results exit={collect_exit}", file=sys.stderr)

  total = len(results)
  if successes == total:
    print(f"[bench:yt] ✅ {successes}/{total} success")
    raise SystemExit(0)
  print(f"[bench:yt] ❌ {successes}/{total} success", file=sys.stderr)
  raise SystemExit(1)


if __name__ == "__main__":
  main()
