import os

from .sherpa_offline import SherpaOfflineASR
from .stream_jp import RealtimeASR as SensevoiceRealtimeASR
from .whisper_stream import WhisperRealtimeASR


def create_realtime_asr():
    kind = os.getenv("M4_ASR_KIND", "sensevoice").strip().lower()
    if kind in {"whisper-stream", "whisper_stream", "whisper"}:
        return WhisperRealtimeASR()
    if kind in {"sherpa-offline", "sherpa_offline", "reazonspeech"}:
        return SherpaOfflineASR()
    return SensevoiceRealtimeASR()
