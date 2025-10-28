import os
import tempfile
import shutil
import asyncio
import pytest


@pytest.fixture(scope="session")
def fake_models_env():
    d = tempfile.mkdtemp(prefix="m4_models_")
    asr = os.path.join(d, "sherpa_jp"); os.makedirs(asr)
    diar = os.path.join(d, "diar"); os.makedirs(diar)
    llm = os.path.join(d, "llm"); os.makedirs(llm)
    ct2 = os.path.join(d, "ct2_m2m100_418m"); os.makedirs(ct2)
    tts = os.path.join(d, "tts/piper"); os.makedirs(tts)
    # 必要ファイルのダミー(存在のみ検証)
    for f in ["encoder.onnx","decoder.onnx","joiner.onnx","tokens.txt"]:
        open(os.path.join(asr,f),"w").close()
    for f in ["segmentation.onnx","embedding.onnx"]:
        open(os.path.join(diar,f),"w").close()
    open(os.path.join(llm, "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf"),"w").close()
    open(os.path.join(tts, "ja_JP-lessac-medium.onnx"),"w").close()
    # LLMバイナリは which 検査を回避できないため、ここでは /usr/bin/true を指定
    env = {
        "M4_MODELS_DIR": d,
        "M4_ASR_DIR": asr,
        "M4_DIAR_DIR": diar,
        "M4_LLM_BIN": "/usr/bin/true",
        "M4_LLM_MODEL": os.path.join(llm, "Meta-Llama-3-8B-Instruct.Q4_K_M.gguf"),
        "M4_CT2_DIR": ct2,
        "M4_TTS_VOICE": os.path.join(tts, "ja_JP-lessac-medium.onnx"),
        "LOG_DIR": "backend/data"
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    yield env
    for k,v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(d, ignore_errors=True)

