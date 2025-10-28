import os
from typing import Optional
import ctranslate2
import sentencepiece as spm
from loguru import logger
from backend.store import db


class Translator:
    def __init__(self):
        ct2_dir = os.getenv("M4_CT2_DIR", "")
        self.translator = None
        self.spm = None
        if os.path.exists(ct2_dir):
            try:
                self.translator = ctranslate2.Translator(ct2_dir, device="auto")
                # 多くのCT2変換済みモデルは sentencepiece.model を同梱
                spm_path = os.path.join(ct2_dir, "sentencepiece.model")
                if os.path.exists(spm_path):
                    self.spm = spm.SentencePieceProcessor()
                    self.spm.load(spm_path)
            except Exception as e:
                logger.bind(tag="mt.init").exception(e)

    def _encode(self, text: str):
        if self.spm:
            return self.spm.encode(text, out_type=str)
        return text.split()

    def _decode(self, toks):
        if self.spm:
            return self.spm.decode(toks)
        return " ".join(toks)

    def maybe_translate(self, text: str, src="ja", tgt: Optional[str] = None) -> Optional[str]:
        if not text.strip():
            return None
        if self.translator is None:
            return None
        target_lang = tgt or os.getenv("DEFAULT_MT_TARGET", "en")
        toks = self._encode(f"{text}")
        res = self.translator.translate_batch([toks], beam_size=3)
        out = res[0].hypotheses[0]
        return self._decode(out)


def retranslate_event(event_id: str):
    """全セグメントを再翻訳する。
    - 既存設計に合わせて追記で保存（フロントで重複を抑制）。
    - ターゲット言語は events.translate_to を参照。未設定時は DEFAULT_MT_TARGET。
    - ASGIイベントループから呼ぶ場合はルート側でスレッド実行すること。
    """
    import asyncio
    t = Translator()

    async def _go():
        ev = await db.get_event(event_id)
        tgt = (ev or {}).get("translate_to") or None
        segs = await db.list_segments(event_id)
        for s in segs:
            mt = t.maybe_translate(s["text_ja"], tgt=tgt) or ""
            await db.insert_segment(event_id, s["start"], s["end"], s["speaker"], s["text_ja"], mt, s["origin"])

    asyncio.run(_go())
