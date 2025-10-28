import os
import time
import subprocess
from loguru import logger
import shutil
import httpx
from backend.store import db


PROMPT_LIVE = "以下の逐次発話を20-30秒ごとに日本語の短い箇条書きで要約してください。簡潔に。\n\n"
PROMPT_FINAL = "以下は会議全文です。日本語で正確に重要論点を段落と箇条書きで要約し、アクション項目を明示してください。\n\n"


def _resolve_llm_bin() -> str:
    """llama バイナリ候補を解決する。環境変数優先、無ければ一般的な名称を探索。"""
    names = [os.getenv("M4_LLM_BIN", ""), "llama-cli", "llama"]
    tried = []
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        tried.append(name)
        p = shutil.which(name)
        if p:
            return p
    logger.bind(tag="llama.run").warning(f"LLMバイナリが見つかりません: tried={tried}")
    return ""


def _detect_ollama_base() -> str:
    """Ollama(OpenAI互換) ベースURLを決定する。env優先、なければ既定ポート。"""
    base = (os.getenv("M4_OLLAMA_BASE", "").strip() or "http://127.0.0.1:11434").rstrip('/')
    return base


def _run_ollama_openai(prompt: str, text: str) -> str:
    """Ollama(OpenAI互換 /v1/chat/completions)で要約を実行する。"""
    base = _detect_ollama_base()
    model = (os.getenv("M4_OLLAMA_MODEL", "").strip() or "qwen2.5:7b-instruct")
    url = f"{base}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "あなたは簡潔で正確な日本語要約を書くアシスタントです。"},
            {"role": "user", "content": prompt + text},
        ],
        "temperature": float(os.getenv("M4_OLLAMA_TEMPERATURE", "0.3")),
        "max_tokens": int(os.getenv("M4_OLLAMA_MAX_TOKENS", "800")),
        "stream": False,
    }
    try:
        to = float(os.getenv("M4_OLLAMA_TIMEOUT", os.getenv("M4_LMSTUDIO_TIMEOUT", "180")))
        with httpx.Client(timeout=httpx.Timeout(to)) as client:
            r = client.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            try:
                logger.bind(tag="llama.run").error(f"Ollama {r.status_code}: {r.text}")
            except Exception:
                pass
            return ""
        j = r.json()
        c = j.get("choices", [{}])[0].get("message", {}).get("content", "")
        return (c or "").strip()
    except Exception as e:
        logger.bind(tag="llama.run").exception(e)
        return ""


def _run_llama(prompt: str, text: str) -> str:
    llm_bin = _resolve_llm_bin()
    llm_model = os.getenv("M4_LLM_MODEL", "").strip()
    if not llm_bin:
        logger.bind(tag="llama.run").warning("LLM未設定: 実行可能な llama バイナリが見つかりません")
        return ""
    if not llm_model or not os.path.exists(llm_model):
        logger.bind(tag="llama.run").warning(f"LLM未設定: モデルが見つかりません path={llm_model!r}")
        return ""
    cmd = [llm_bin, "-m", llm_model, "-p", prompt + text, "-n", "512"]
    logger.bind(tag="llama.run").info("running: " + " ".join(cmd[:4]) + " ...")
    try:
        out = subprocess.check_output(cmd, text=True)
        return out.strip()
    except Exception as e:
        logger.bind(tag="llama.run").exception(e)
        return ""


def run_chat_once(prompt: str) -> str:
    """Ollama優先で1ターンの回答を返す（フォールバック: llama.cpp）。"""
    # Ollama(OpenAI互換)
    try:
        out = _run_ollama_openai("以下に的確に回答してください。\n\n", prompt)
        if out:
            return out
    except Exception:
        pass
    # fallback llama.cpp
    return _run_llama("以下に的確に回答してください。\n\n", prompt)


def _split_text_by_chars(text: str, max_chars: int) -> list[str]:
    out = []
    buf = []
    size = 0
    for line in text.splitlines():
        if size + len(line) + 1 > max_chars and buf:
            out.append("\n".join(buf))
            buf = [line]
            size = len(line) + 1
        else:
            buf.append(line)
            size += len(line) + 1
    if buf:
        out.append("\n".join(buf))
    return out


def finalize_summary_for_event(event_id: str) -> None:
    import asyncio
    async def _go():
        segs = await db.list_segments(event_id)
        full = "\n".join([s["text_ja"] for s in segs])
        # 長文は分割→要点統合→最終要約の段階要約にする
        max_chars = int(os.getenv("M4_SUMMARY_CHUNK_CHARS", "4000"))
        chunks = _split_text_by_chars(full, max_chars) if len(full) > max_chars else [full]

        # プロバイダ選択: Ollama優先。失敗時は llama.cpp にフォールバック。
        def _summarize_chunk(txt: str) -> str:
            prompt = "以下の発話の要点を日本語の箇条書きで3-6項目に簡潔にまとめてください。\n\n"
            out = _run_ollama_openai(prompt, txt)
            return out if out else _run_llama(prompt, txt)

        if len(chunks) > 1:
            bullets_list = []
            for i, ch in enumerate(chunks):
                logger.bind(tag="llama.run").info(f"chunk summarize {i+1}/{len(chunks)} size={len(ch)}")
                b = _summarize_chunk(ch)
                if b:
                    bullets_list.append(b)
            merged = "\n".join(bullets_list)
            md = _run_ollama_openai(PROMPT_FINAL, merged) or _run_llama(PROMPT_FINAL, merged)
        else:
            md = _run_ollama_openai(PROMPT_FINAL, full) or _run_llama(PROMPT_FINAL, full)
        import aiosqlite
        from backend.store import db as _db
        async with aiosqlite.connect(_db.DB_PATH) as con:
            await con.execute(
                "INSERT INTO summaries(event_id,kind,lang,text_md,created_at) VALUES(?,?,?,?,?)",
                (event_id, "final", "ja", md, int(time.time())),
            )
            await con.execute(
                "INSERT INTO fts(event_id,title,text_ja,text_mt,summary_md) VALUES(?,?,?,?,?)",
                (event_id, "", "", "", md),
            )
            await con.commit()
    asyncio.run(_go())


def summarize_event_stream(event_id: str, emit) -> None:
    """要約の段階結果を emit(JSON文字列) で順次通知し、最後にDB保存する。"""
    import json
    import asyncio
    # 事前に全文取得
    segs = asyncio.run(db.list_segments(event_id))  # type: ignore[name-defined]
    full = "\n".join([s.get("text_ja") or s.get("text") or "" for s in segs])
    max_chars = int(os.getenv("M4_SUMMARY_CHUNK_CHARS", "4000"))
    chunks = _split_text_by_chars(full, max_chars) if len(full) > max_chars else [full]
    def _sum(txt: str) -> str:
        p = "以下の発話の要点を日本語の箇条書きで3-6項目に簡潔にまとめてください。\n\n"
        out = _run_ollama_openai(p, txt)
        return out if out else _run_llama(p, txt)

    bullets_list = []
    total = max(1, len(chunks))
    for i, ch in enumerate(chunks):
        b = _sum(ch)
        bullets_list.append(b)
        try:
            pct = int(min(95, max(1, (i + 1) * 100 // total))) if total > 1 else 50
            emit(json.dumps({"type": "partial", "text": "\n\n".join(bullets_list), "progress": pct}))
        except Exception:
            pass
    merged = "\n".join(bullets_list)
    md = _run_ollama_openai(PROMPT_FINAL, merged) or _run_llama(PROMPT_FINAL, merged)
    try:
        emit(json.dumps({"type": "final", "text": md, "progress": 100}))
    except Exception:
        pass
    # 保存
    import aiosqlite
    from backend.store import db as _db
    async def _save():
        async with aiosqlite.connect(_db.DB_PATH) as con:
            await con.execute(
                "INSERT INTO summaries(event_id,kind,lang,text_md,created_at) VALUES(?,?,?,?,?)",
                (event_id, "final", "ja", md or "", int(time.time())),
            )
            await con.execute(
                "INSERT INTO fts(event_id,title,text_ja,text_mt,summary_md) VALUES(?,?,?,?,?)",
                (event_id, "", "", "", md or ""),
            )
            await con.commit()
    asyncio.run(_save())
