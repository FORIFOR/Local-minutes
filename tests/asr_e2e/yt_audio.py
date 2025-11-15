from __future__ import annotations

import argparse
import os
import sys
import subprocess
import tempfile
from pathlib import Path

try:
  from yt_dlp import YoutubeDL
except ImportError as exc:
  raise SystemExit("yt-dlp が見つかりません。tests/asr_e2e/requirements-optional.txt をインストールしてください") from exc

OUTPUT = Path("/tmp/yt.wav")


def resolve_url(cli_value: str | None) -> str:
  if cli_value:
    return cli_value
  env_url = os.environ.get("npm_config_url")
  if env_url:
    return env_url
  raise SystemExit("YouTubeのURLを --url=... で指定してください")


def download(url: str, dst: Path):
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
      src = Path(ydl.prepare_filename(info))
      if not src.exists():
        raise SystemExit("音声のダウンロードに失敗しました")

      ffmpeg = os.environ.get("FFMPEG", "ffmpeg")
      cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(src),
        "-c:a",
        "pcm_s16le",
        str(dst),
      ]
      print(f"[yt:audio] ffmpeg -> {dst}")
      proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
      if proc.returncode != 0:
        raise SystemExit(f"ffmpeg で WAV 変換に失敗しました: {proc.stderr}")
      return info


def main():
  parser = argparse.ArgumentParser(description="YouTube 音声を /tmp/yt.wav に保存します")
  parser.add_argument("--url", help="YouTubeのURLまたは動画ID")
  args = parser.parse_args()

  url = resolve_url(args.url)
  print(f"[yt:audio] downloading {url}")
  download(url, OUTPUT)
  print(f"[yt:audio] done -> {OUTPUT}")


if __name__ == "__main__":
  main()
