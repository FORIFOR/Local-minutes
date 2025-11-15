import os
import sys

try:
  from faster_whisper import WhisperModel
except ImportError as exc:
  print('faster-whisper がインストールされていません: pip install -r tests/asr_e2e/requirements-optional.txt', file=sys.stderr)
  raise

OUT = os.path.join('tests', 'asr_e2e', 'out')
WAV = os.path.join(OUT, 'recv.wav')
HYP = os.path.join(OUT, 'hyp.txt')

if not os.path.exists(WAV):
  print(f'{WAV} が存在しません。先に sink/source で録音してください。', file=sys.stderr)
  sys.exit(1)

model_name = os.environ.get('FW_MODEL', 'tiny')
device = os.environ.get('FW_DEVICE', 'cpu')
compute_type = os.environ.get('FW_COMPUTE_TYPE')

kwargs = {'device': device}
if compute_type:
  kwargs['compute_type'] = compute_type

model = WhisperModel(model_name, **kwargs)
segments, info = model.transcribe(WAV, language='ja', vad_filter=True)
text = ''.join(segment.text for segment in segments).strip()

os.makedirs(OUT, exist_ok=True)
with open(HYP, 'w', encoding='utf-8') as f:
  f.write(text)

print(f'WROTE {HYP} ({len(text)} chars) | model={model_name} device={device}')
