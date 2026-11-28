"""Utterance pipeline: transcript -> question detection -> Q&A search ->
(answer now | local-AI generation) -> WebSocket broadcast to all devices.

Latency targets (design doc 12): registered answer < 0.5s after the
question is finalised; sync fan-out < 0.5s (LAN, in-process broadcast).
"""
import asyncio, time
from . import db
from .qa_search import QASearch
from .question_detector import detect
from .generator import get_generator, MockGenerator

QA_HIT_THRESHOLD = float(__import__("os").environ.get("ISA_QA_THRESHOLD", "0.30"))

class Pipeline:
    def __init__(self, session, broadcast):
        self.session = session
        self.broadcast = broadcast  # async fn(event_dict)
        self.paused = False
        self._gen_task = None

    def _profile(self):
        if self.session.profile_id:
            for p in db.list_profiles():
                if p["id"] == self.session.profile_id:
                    return p
        return None

    def _docs(self):
        return db.list_documents(self.session.profile_id)

    async def handle_utterance(self, text, source="interviewer", force=False):
        """source: 'interviewer' (loopback) | 'user' (own mic) | 'manual'."""
        text = (text or "").strip()
        if not text or self.paused:
            return
        await self.broadcast({"type": "transcript_final", "text": text, "source": source,
                              "ts": time.time()})
        if source == "user":
            return  # never generate answers for the user's own speech
        det = detect(text)
        if not force and not det["is_question"]:
            await self.broadcast({"type": "question_skipped", "text": text,
                                  "reason": det["reason"]})
            return
        await self.answer_question(text)

    async def answer_question(self, text):
        t0 = time.time()
        pairs = db.list_qa(self.session.profile_id)
        search = QASearch(pairs)
        results = search.search(text, top_k=1)
        hit = results[0] if results and results[0]["score"] >= QA_HIT_THRESHOLD else None
        search_ms = (time.time() - t0) * 1000
        profile = self._profile()
        history_ctx = "\n".join(
            f"Q: {c['question']}\nA: {c['answer'][:300]}" for c in self.session.context[-3:])
        qid = f"q{int(t0*1000)}"
        if hit:
            qa = hit["qa"]
            await self.broadcast({"type": "answer_start", "qid": qid, "question": text,
                                  "source_kind": "registered", "score": hit["score"],
                                  "search_ms": round(search_ms, 1), "ts": time.time()})
            # Registered answer: show immediately (points = first sentences).
            import re as _re
            sents = [s.strip() for s in _re.split(r"[。\n]", qa["answer"]) if len(s.strip()) >= 5]
            await self.broadcast({"type": "answer_points", "qid": qid, "items": sents[:3]})
            await self.broadcast({"type": "answer_chunk", "qid": qid, "text": qa["answer"]})
            await self.broadcast({"type": "answer_supplement", "qid": qid,
                                  "text": f"登録済み想定問答「{qa['question']}」（類似度 {hit['score']}）"})
            await self.broadcast({"type": "answer_done", "qid": qid})
            self._record(text, qa["answer"], "registered")
            return
        gen = await get_generator()
        await self.broadcast({"type": "answer_start", "qid": qid, "question": text,
                              "source_kind": "ai" if gen.name == "ollama" else "ai_mock",
                              "score": results[0]["score"] if results else 0.0,
                              "search_ms": round(search_ms, 1), "ts": time.time()})
        full = []
        async for ev in gen.generate(text, self._docs(), None, profile, history_ctx):
            if ev["type"] == "points":
                await self.broadcast({"type": "answer_points", "qid": qid, "items": ev["items"]})
            elif ev["type"] == "answer_chunk":
                full.append(ev["text"])
                await self.broadcast({"type": "answer_chunk", "qid": qid, "text": ev["text"]})
            elif ev["type"] == "supplement":
                await self.broadcast({"type": "answer_supplement", "qid": qid, "text": ev["text"]})
            elif ev["type"] == "followups":
                await self.broadcast({"type": "answer_followups", "qid": qid, "items": ev["items"]})
            elif ev["type"] == "done":
                await self.broadcast({"type": "answer_done", "qid": qid})
        self._record(text, "".join(full), gen.name)

    def _record(self, question, answer, source):
        self.session.context.append({"question": question, "answer": answer})
        if db.get_setting("save_history", "0") == "1":
            db.add_history(self.session.id, question, answer, source)
