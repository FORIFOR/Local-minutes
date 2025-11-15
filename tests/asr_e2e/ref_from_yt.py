from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from yt_utils import extract_video_id, fetch_transcript  # noqa: E402

OUT_DIR = ROOT / "out"
REF_PATH = OUT_DIR / "ref.txt"


def resolve_url(cli_value: str | None) -> str:
  if cli_value:
    return cli_value
  env_url = os.environ.get("npm_config_url")
  if env_url:
    return env_url
  raise SystemExit("YouTubeのURLを --url=... で指定してください")


def main():
  parser = argparse.ArgumentParser(description="YouTube字幕を ref.txt に保存します")
  parser.add_argument("--url", help="YouTubeのURLまたは動画ID")
  args = parser.parse_args()

  url_or_id = resolve_url(args.url)
  video_id = extract_video_id(url_or_id)
  transcript = fetch_transcript(video_id, url=url_or_id)
  text = transcript.get("text", "")
  if not text:
    raise SystemExit("字幕テキストを取得できませんでした")

  OUT_DIR.mkdir(parents=True, exist_ok=True)
  REF_PATH.write_text(text.strip() + "\n", encoding="utf-8")
  print(f"[ref:yt] saved transcript ({video_id}) -> {REF_PATH}")


if __name__ == "__main__":
  main()
