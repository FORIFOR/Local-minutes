import os
import subprocess
from backend.store.files import artifact_path_for_event


def tts_summary(event_id: str, text: str) -> str:
    voice = os.getenv("M4_TTS_VOICE", "")
    out_wav = artifact_path_for_event(event_id, "summary_ja.wav")
    # piper -m voice.onnx -f out.wav
    cmd = ["piper", "-m", voice, "-f", out_wav]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
    p.stdin.write(text)
    p.stdin.close()
    p.wait()
    return out_wav

