# ASR 配管 & 実音源ベンチ手順

実音源（YouTube/会議録音など）を唯一の評価ソースとし、字幕→音声DL→16 kHz変換→faster-whisper採点→集計までを自動化したワークフローです。音声合成由来の資産はすべて撤去済みです。

## 0. 事前準備（初回のみ）

```bash
npm install
python3.11 -m pip install -r tests/asr_e2e/requirements.txt
python3.11 -m pip install -r tests/asr_e2e/requirements-optional.txt  # faster-whisper / yt-dlp / transcript API
ffmpeg -version  # mac: brew install ffmpeg / Ubuntu: sudo apt-get install -y ffmpeg
python3 tests/asr_e2e/yt_bench.py --help
```

`yt_bench.py --help` と `ffmpeg -version` が通ることを確認してください。

## 0.5. デイリーベンチ（10〜15分で完了）

```bash
python3 -m pip install -r tests/asr_e2e/requirements-optional.txt
which ffmpeg || brew install ffmpeg                 # Ubuntu: sudo apt-get install -y ffmpeg

# 手動字幕の動画を中心に 3〜5 本
npm run bench:yt -- \
  --url-file tests/asr_e2e/urls.txt \
  --jobs 2 \
  --cache-dir tests/asr_e2e/.ytcache \
  --append-results tests/asr_e2e/TEST_RESULTS.md

# 指標を Markdown テーブルで俯瞰
npm run results:table
```

評価目安（日本語コンテンツ）:
- `WER ≤ 0.20`: ◎ 実務OK
- `0.20 < WER ≤ 0.25`: ◯ 正規化/辞書調整推奨
- `WER > 0.25`: 要改善
- `RTF ≤ 1.0`: リアルタイム同等、`1.0–1.5`: 準リアルタイム、`>1.5`: 高速化検討

`scores.json.metadata.is_generated_subtitle=true` のケース（自動字幕）は +0.05 程度ゆるめに見るのがおすすめです。

## 1. 単発ベンチ（1本の動画を評価）

```bash
npm run bench:yt -- --url="https://www.youtube.com/watch?v=XXXX"
```

実行後、`tests/asr_e2e/out/XXXX/`（動画ID単位）に成果物がまとまります。

```
tests/asr_e2e/out/XXXX/
  ├─ audio_orig.m4a          # DLしたままの音声（拡張子は素材に依存）
  ├─ audio_16k.wav           # 16 kHz / mono / PCM16
  ├─ ref.txt                 # YouTube字幕（正解）
  ├─ hyp.txt                 # faster-whisper出力（仮説）
  ├─ scores.json             # WER / CER / jWER / RTF / メタ情報
  ├─ metrics.json            # ベンチ実行メタ（mode, duration, rtf など）
  ├─ bench.log               # 進行ログ（DL/変換/collect結果）
  └─ collect_results.py が TEST_RESULTS.md に追記（しきい値: WER≤35%, CER≤25%, jWER≤35%）
```

`scores.json` には RT F (decode_seconds / duration_sec) や transcript ソース、トークン長なども記録されます。

### オプション
- `--url-file=tests/asr_e2e/urls.txt` … 複数URLをまとめて処理（直列実行）
- `--cache-dir=tests/asr_e2e/.ytcache` … `audio_orig` をキャッシュして再DLを回避
- `--model / --device / --compute-type / --beam-size` … faster-whisper のパラメータ上書き
- `--no-append` … `TEST_RESULTS.md` への追記を抑止（ローカル検証のみ行いたい場合）

## 2. URLリストによる一括ベンチ

```bash
cat > tests/asr_e2e/urls.txt <<'EOF'
https://www.youtube.com/watch?v=AAAA
https://www.youtube.com/watch?v=BBBB
EOF

npm run bench:yt -- --url-file=tests/asr_e2e/urls.txt --cache-dir=tests/asr_e2e/.ytcache
```

全URL共通で `scores.json` が生成され、合否判断も URL ごとに行われます（失敗が1件でもあれば exit code 1）。

## 3. 結果の集約（Markdown テーブル生成）

```bash
npm run results:table > tests/asr_e2e/RESULTS.md
# 例）手動でファイルに貼り付ける
python3.11 tests/asr_e2e/collect_results.py tests/asr_e2e/out
```

見出し例：

```
| video_id | lang | dur(s) | WER | CER | jWER | RTF | model | beam | subtitle | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AAAA | ja | 312.4 | 0.138 | 0.072 | 0.115 | 0.37 | faster-whisper-small | 5 | manual |  |
| BBBB | ja | 185.1 | 0.201 | 0.104 | 0.169 | 0.28 | faster-whisper-small | 5 | YouTube auto captions |  |
```

`scores.json` の `metadata.notes` を埋めると列に反映されます（手動編集可）。

## 4. 正規化とスコアリング仕様

`collect_results.py` / `yt_bench.py` は共通の正規化ロジック（`asr_metrics.py`）を利用します。

適用順：
1. NFKC 正規化（全角/半角の統一、数字は半角へ）
2. `[♪]`, `(笑)`, `[音楽]`, `[Music]` などノイズ括弧の除去
3. 主要句読点・中黒・波ダッシュ等をスペースへ変換
4. 連続空白の正規化
5. fugashi（有効時）でトークン化。未導入時は1文字ごと

算出指標：
- `WER`: fugashi トークン列をスペース区切りで `jiwer.wer`
- `CER`: 正規化後文字列を `jiwer.cer`
- `jWER`: トークン列に対するレーベンシュタイン距離 / 参照トークン数
- `RTF`: faster-whisper decode 秒 / 音声長（sec）

全指標が計算できない場合は失敗扱い（`--skip-missing` で回避可）。

## 5. YouTube 字幕/音源まわりのハマりどころ

- 字幕が 404 の場合でも、自動字幕（yt-dlp / auto subs）にフォールバックします。完全に取得できない場合は `scores.json.metadata.threshold_pass=false` となります。
- DL が 403/410 の場合はブラウザクッキーを共有してください（例: `yt-dlp --cookies-from-browser chrome` をリストに反映）。
- `--cache-dir` を指定すると DL 済み音源を再利用できます。長尺動画の繰り返し評価に便利です。
- 音声のみ欲しい場合は `yt_audio.py` + `ffmpeg` を単独で利用可能です。

## 6. WebSocket ベンチ（本番配管経由での採点）

### 手順
1. 正解字幕（ref）  
   `npm run ref:yt -- --url="https://www.youtube.com/watch?v=AAAA"`
2. 音声DL → 16 kHz変換  
   `npm run yt:audio -- --url="..."` → `/tmp/yt.wav`  
   `npm run wav:fix16k`
3. 配信（例: stdin 経由で 20 ms/640 B フレーム化）  
   ```bash
   ffmpeg -i tests/asr_e2e/out/AAAA/audio_16k.wav -f s16le -acodec pcm_s16le - \
     | node tests/asr_e2e/ws_sender.js --stdin --rate=16000 --sample-width=2 --channels=1 --url="wss://<host>/ws/stream?event_id=..."
   ```
4. minutes 取得（仮説テキスト）  
   `M4_TOKEN=<token> npm run export:hyp -- --base="http://127.0.0.1:3002" --event="<EVENT_ID>"`
5. 採点  
   `npm run results -- --run-dir tests/asr_e2e/out`

`ws_sender.js` は `--wav`, `--stdin`, `--silence` をサポートし、`--rate/--chunk-ms` で任意のフレーム幅を指定できます。進捗ログに PPS（packets per second）が表示されます。

## 7. ログとパラメータ管理

- 主要パラメータ（model/device/compute_type/beam）は `scores.json.asr` に記録されます。再現のため変更時は都度コミット推奨。
- `bench.log` には yt-dlp/ffmpeg コマンド、collect の exit code が残ります。失敗時の一次調査に利用してください。
- `tests/asr_e2e/out/` と `tests/asr_e2e/.ytcache/` は `.gitignore` 済みです（`.gitkeep` のみ版管対象）。

## 8. 回帰検出（baseline JSON）

1. ベースラインを作成  
   `tests/asr_e2e/baseline.json` 例:
   ```json
   {
     "targets": {
       "dQw4w9WgXcQ": { "WER": 0.18, "CER": 0.09, "RTF": 0.85 },
       "abc123xyz":  { "WER": 0.22, "CER": 0.11, "RTF": 0.95 }
     },
     "tolerance": { "WER": 0.03, "RTF": 0.20 }
   }
   ```
   - `targets` に比較対象の動画IDとベースライン指標を記録
   - `tolerance` は許容差分（未指定は 0 とみなす）

2. 比較コマンド
   ```bash
   python3 tests/asr_e2e/collect_results.py --run-dir tests/asr_e2e/out \
     --compare tests/asr_e2e/baseline.json \
     --fail-on-regression
   ```
   - baseline + tolerance を超えると exit code 1（PR/CI で赤）
   - `--fail-on-regression` を外すと警告表示のみ

`collect_results.py` は `--table` / `--csv` で Markdown / CSV を出力できます。`metadata.caption_source` や `metadata.is_generated_subtitle` を使えば自動字幕を分離した集計が可能です。

## 9. CI への組み込み例

```yaml
name: ASR Bench
on:
  pull_request:
  workflow_dispatch:

jobs:
  bench:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: sudo apt-get update && sudo apt-get install -y ffmpeg
      - run: |
          python -m pip install -r tests/asr_e2e/requirements-optional.txt
          npm ci
      - run: |
          npm run bench:yt -- \
            --url-file tests/asr_e2e/urls_ci.txt \
            --jobs 2 --cache-dir tests/asr_e2e/.ytcache
          python3 tests/asr_e2e/collect_results.py --run-dir tests/asr_e2e/out \
            --compare tests/asr_e2e/baseline.json --fail-on-regression \
            --table >> tests/asr_e2e/TEST_RESULTS.md
      - uses: actions/upload-artifact@v4
        with:
          name: asr-bench-artifacts
          path: |
            tests/asr_e2e/out/**/scores.json
            tests/asr_e2e/out/**/bench.log
            tests/asr_e2e/TEST_RESULTS.md
```

短尺動画（20〜60 秒）を 1 本だけ流す設定でも退行検知は成立します。長尺・重めのケースは nightly / 定期ジョブに回すのが現実的です。

## 10. 指標の見える化とメタデータ

- `scores.json.scores`: `WER` / `CER` / `jWER` / トークン長など
- `scores.json.asr`: `model` / `beam_size` / `compute_type` / `rtf` / `decode_seconds`
- `scores.json.metadata`: `threshold_pass` / `caption_source` / `is_generated_subtitle` / `notes`

Notion や Google Sheets に貼り付ける場合は `collect_results.py --csv` を併用すると整形が容易です。

## 11. データ選定ガイドライン

- **話者バリエーション**: ①明瞭&静音、②早口、③雑音あり（会議/屋外）を最低 1 本ずつ
- **字幕品質**: 手動字幕（`is_generated_subtitle=false`）を必ず含める
- **長さ**: CI 用は 20–60 秒、本番ベンチは 2–5 分で差が出やすい
- **再現性**: `--cache-dir` を活かしてローカル再試行を高速化しつつ、CI では毎回クリーン実行

## その他

- `tests/asr_e2e/out/` 配下は `.gitignore` 済み（成果物はアーティファクトとして共有）
- `tests/asr_e2e/.ytcache/` を活用すると同じ動画を何度でも高速に再検証できます
- `tests/asr_e2e/assets/jp_ref_sample.txt` は字幕整形のフォーマット例です
- `scores.json.metadata.is_generated_subtitle` を使うと、自動字幕サンプルを統計から除外しやすくなります
