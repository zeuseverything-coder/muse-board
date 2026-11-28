"""Answer generation: Ollama (local LLM) with a deterministic mock fallback.

Output protocol (both backends): an async generator of section events:
  {"type": "points", "items": [..]}       # 要点 (<=3)
  {"type": "answer_chunk", "text": ".."}  # 回答例 streaming
  {"type": "supplement", "text": ".."}    # 補足 (根拠資料)
  {"type": "followups", "items": [..]}    # 想定深掘り (<=3)
  {"type": "done"}
The Ollama backend is prompted to emit the same structure with markers
[POINTS] [ANSWER] [SUPPLEMENT] [FOLLOWUPS]; the parser below converts the
stream into events incrementally so the UI shows points first.
"""
import asyncio, json, os, re
import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("ISA_OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")

SYSTEM_RULES = """あなたはWeb面接の回答作成を支援するアシスタントです。以下のルールを厳守してください。
- 登録資料にない経歴、実績、数値を捏造しない。本人が経験していないことを回答に含めない。
- 過去の回答と矛盾する内容を書かない。
- 応募先企業の求人内容や求める人物像を考慮する。
- 質問の意図に直接回答する。過度に抽象的な表現を避ける。
- 不自然な敬語やAI特有の文章を避け、実際に口頭で話しやすい自然な日本語にする。
- 過剰な自己評価や誇張を避ける。
- 不明な情報は推測で補わず、「情報不足」と明示する。
- 本人の価値観や仕事に対する考え方を尊重し、面接官に好印象を与えるためだけに本人の意向と異なる回答を生成しない。
- PREP法やSTAR法は内容に合う場合のみ使い、機械的に全ての回答へ適用しない。
出力形式は厳密に次の通り:
[POINTS]
- 要点1
- 要点2
- 要点3
[ANSWER]
30〜60秒で話せる回答例の本文
[SUPPLEMENT]
根拠となる登録資料の要約(なければ「該当する登録資料なし」)
[FOLLOWUPS]
- 想定される深掘り質問1
- 想定される深掘り質問2
- 想定される深掘り質問3"""

def build_context(question, docs, qa_hit, profile, history_ctx):
    parts = []
    if profile:
        parts.append(f"# 応募先企業: {profile.get('company_name','')}\n求人情報: {profile.get('job_info','')}\nメモ: {profile.get('notes','')}")
    if qa_hit:
        parts.append(f"# 参考になる登録済み想定問答\n質問: {qa_hit['question']}\n回答: {qa_hit['answer']}")
    for d in docs[:8]:
        parts.append(f"# 資料[{d['kind']}] {d['title']}\n{d['content'][:1500]}")
    if history_ctx:
        parts.append("# 直前までの質疑応答(矛盾防止のため参照)\n" + history_ctx)
    parts.append(f"# 面接官の質問\n{question}")
    return "\n\n".join(parts)

SECTION_MARKERS = ["[POINTS]", "[ANSWER]", "[SUPPLEMENT]", "[FOLLOWUPS]"]

async def _parse_stream(text_stream):
    """Convert marker-delimited text stream into section events."""
    buf, current = "", None
    emitted_points = False
    async for chunk in text_stream:
        buf += chunk
        while True:
            nxt, npos = None, len(buf)
            for m in SECTION_MARKERS:
                p = buf.find(m)
                if p != -1 and p < npos:
                    nxt, npos = m, p
            if nxt is None:
                break
            body, buf = buf[:npos], buf[npos + len(nxt):]
            if current == "[POINTS]":
                items = [re.sub(r"^[-・\s]+", "", l) for l in body.strip().splitlines() if l.strip()]
                yield {"type": "points", "items": items[:3]}; emitted_points = True
            elif current == "[ANSWER]" and body.strip():
                yield {"type": "answer_chunk", "text": body}
            elif current == "[SUPPLEMENT]" and body.strip():
                yield {"type": "supplement", "text": body.strip()}
            elif current == "[FOLLOWUPS]":
                items = [re.sub(r"^[-・\s]+", "", l) for l in body.strip().splitlines() if l.strip()]
                yield {"type": "followups", "items": items[:3]}
            current = nxt
        # flush answer text progressively (keep tail for possible marker)
        if current == "[ANSWER]" and len(buf) > 40:
            yield {"type": "answer_chunk", "text": buf[:-20]}
            buf = buf[-20:]
    if current == "[POINTS]" and buf.strip():
        items = [re.sub(r"^[-・\s]+", "", l) for l in buf.strip().splitlines() if l.strip()]
        yield {"type": "points", "items": items[:3]}
    elif current == "[ANSWER]" and buf.strip():
        yield {"type": "answer_chunk", "text": buf}
    elif current == "[SUPPLEMENT]" and buf.strip():
        yield {"type": "supplement", "text": buf.strip()}
    elif current == "[FOLLOWUPS]" and buf.strip():
        items = [re.sub(r"^[-・\s]+", "", l) for l in buf.strip().splitlines() if l.strip()]
        yield {"type": "followups", "items": items[:3]}
    yield {"type": "done"}

class OllamaGenerator:
    name = "ollama"
    def __init__(self):
        self.model = OLLAMA_MODEL
    async def available(self):
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"{OLLAMA_URL}/api/tags")
                return r.status_code == 200
        except Exception:
            return False
    async def generate(self, question, docs, qa_hit, profile, history_ctx, length="normal"):
        ctx = build_context(question, docs, qa_hit, profile, history_ctx)
        payload = {"model": self.model, "stream": True,
                   "messages": [{"role": "system", "content": SYSTEM_RULES},
                                {"role": "user", "content": ctx}],
                   "options": {"temperature": 0.3}}
        async def stream():
            async with httpx.AsyncClient(timeout=120.0) as c:
                async with c.stream("POST", f"{OLLAMA_URL}/api/generate", json={
                        "model": self.model, "stream": True,
                        "prompt": SYSTEM_RULES + "\n\n" + ctx}) as r:
                    async for line in r.aiter_lines():
                        if line:
                            yield json.loads(line).get("response", "")
        async for ev in _parse_stream(stream()):
            yield ev

class MockGenerator:
    """Deterministic offline generator used when Ollama is not running.
    Builds an answer ONLY from registered data (never invents facts) and
    streams it section by section so the whole pipeline can be exercised."""
    name = "mock"
    async def available(self):
        return True
    async def generate(self, question, docs, qa_hit, profile, history_ctx, length="normal"):
        base = qa_hit["answer"] if qa_hit else ""
        doc_bits = []
        for d in docs:
            for line in d["content"].splitlines():
                line = line.strip()
                if len(line) >= 8:
                    doc_bits.append((d, line))
        points = []
        if base:
            sents = [s for s in re.split(r"[。\n]", base) if len(s.strip()) >= 5]
            points = [s.strip() for s in sents[:3]]
        for d, line in doc_bits:
            if len(points) >= 3: break
            if line not in points: points.append(line[:60])
        if not points:
            points = ["登録資料に該当情報が不足しています（情報不足）"]
        yield {"type": "points", "items": points}
        if base:
            answer = base
        elif doc_bits:
            answer = "。".join(l for _, l in doc_bits[:3]) + "。"
        else:
            answer = ("この質問に直接答えられる登録資料がありません。情報不足のため、"
                      "推測で補わず、関連する経験の範囲で答えるのが安全です。")
        for i in range(0, len(answer), 12):
            yield {"type": "answer_chunk", "text": answer[i:i + 12]}
            await asyncio.sleep(0.01)
        sup = []
        if qa_hit: sup.append(f"想定問答「{qa_hit['question']}」")
        sup += [f"{d['kind']}「{d['title']}」" for d in docs[:3]]
        yield {"type": "supplement", "text": "根拠資料: " + ("、".join(sup) if sup else "該当する登録資料なし")}
        yield {"type": "followups", "items": [
            "その経験の中で最も苦労した点は何ですか？",
            "具体的な数字や成果で示すとどうなりますか？",
            "その経験を弊社でどう活かせますか？"]}
        yield {"type": "done"}

async def get_generator():
    g = OllamaGenerator()
    if await g.available():
        return g
    return MockGenerator()
