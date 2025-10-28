import os
import sys
import tempfile
import soundfile as sf
import librosa
from backend.asr.offline_sensevoice import from_env as asr_from_env
from backend.diar.onnx_diar import diarize, SR


def cut_save(wav, s, e, sr=SR):
    a, b = int(s * sr), int(e * sr)
    y = wav[a:b]
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    sf.write(f.name, y, sr)
    return f.name


def main(wav_path):
    print(f"[test] input={wav_path}")
    asr = asr_from_env(log=print)

    wav, sr = sf.read(wav_path)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    if sr != SR:
        wav = librosa.resample(wav.astype("float32"), orig_sr=sr, target_sr=SR)

    diar = diarize(wav_path)
    if not diar:
        print("[warn] diarization returned empty; decoding whole file")
        tmp = cut_save(wav, 0, len(wav) / SR)
        txt = asr.decode_wav(tmp)
        print(f"ALL: {txt}")
        return

    print(f"[info] segments={len(diar)}")
    for i, d in enumerate(diar, 1):
        chunk = cut_save(wav, d["start"], d["end"])
        txt = asr.decode_wav(chunk)
        print(f"{i:02d} [{d['spk']}] {d['start']:.2f}-{d['end']:.2f}s: {txt}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/test_diar_asr.py /path/to/audio.wav")
        sys.exit(1)
    main(sys.argv[1])

