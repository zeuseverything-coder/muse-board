"""FastAPI application: REST API + WebSocket sync + static frontend.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8765
LAN-only by design (design doc 11/14): no internet exposure, session token
required for the WebSocket and for phone joins.
"""
import asyncio, io, json, os, time
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .sessions import create_session, get_session, end_session
from .pipeline import Pipeline
from .vad import Segmenter, get_vad
from .transcribe import StreamingTranscriber, available as whisper_available
from .audio_sources import MicSource, WasapiLoopbackSource

BASE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="リアルタイムAI面接支援")

db.init_db()

# ---------------------------------------------------------------- helpers
def _qr_png(url: str) -> bytes:
    import qrcode
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

async def broadcast(session, event):
    if event.get("type") not in ("audio_level",):
        session.events.append(event)
    dead = []
    for ws in list(session.clients):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        session.clients.discard(ws)

def pipeline_for(session):
    if not hasattr(session, "_pipeline"):
        session._pipeline = Pipeline(session, lambda ev: broadcast(session, ev))
    return session._pipeline

# ---------------------------------------------------------------- profiles
class ProfileIn(BaseModel):
    company_name: str
    job_info: str = ""
    notes: str = ""

@app.get("/api/profiles")
def profiles_list(): return db.list_profiles()

@app.post("/api/profiles")
def profiles_create(p: ProfileIn): return db.create_profile(p.model_dump())

@app.put("/api/profiles/{pid}")
def profiles_update(pid: int, p: ProfileIn): return db.update_profile(pid, p.model_dump())

@app.delete("/api/profiles/{pid}")
def profiles_delete(pid: int): return db.delete_profile(pid)

# ---------------------------------------------------------------- documents
class DocIn(BaseModel):
    kind: str
    title: str
    content: str
    profile_id: int | None = None

@app.get("/api/documents")
def docs_list(profile_id: int | None = None): return db.list_documents(profile_id)

@app.post("/api/documents")
def docs_create(d: DocIn): return db.create_document(d.model_dump())

@app.put("/api/documents/{did}")
def docs_update(did: int, d: DocIn): return db.update_document(did, d.model_dump())

@app.delete("/api/documents/{did}")
def docs_delete(did: int): return db.delete_document(did)

def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith((".txt", ".md", ".markdown")):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".json"):
        obj = json.loads(data.decode("utf-8"))
        if isinstance(obj, list):
            return "\n".join(json.dumps(x, ensure_ascii=False) for x in obj)
        return json.dumps(obj, ensure_ascii=False, indent=1)
    if name.endswith(".csv"):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in r.pages)
    if name.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs)
    raise HTTPException(400, f"未対応の形式です: {filename}")

@app.post("/api/documents/import")
async def docs_import(kind: str = Form(...), profile_id: int | None = Form(None),
                      file: UploadFile = File(...)):
    data = await file.read()
    text = extract_text(file.filename, data)
    if file.filename.lower().endswith(".csv"):
        # CSV of Q&A pairs: columns question,answer -> register as QA pairs
        import csv as _csv
        rows = list(_csv.reader(io.StringIO(text)))
        made = 0
        for row in rows:
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                if row[0].strip() in ("question", "質問"):
                    continue
                db.create_qa({"question": row[0].strip(), "answer": row[1].strip(),
                              "profile_id": profile_id})
                made += 1
        if made:
            return {"imported_qa": made}
    return db.create_document({"kind": kind, "title": file.filename,
                               "content": text, "profile_id": profile_id})

# ---------------------------------------------------------------- qa pairs
class QAIn(BaseModel):
    question: str
    answer: str
    profile_id: int | None = None

@app.get("/api/qa")
def qa_list(profile_id: int | None = None): return db.list_qa(profile_id)

@app.post("/api/qa")
def qa_create(q: QAIn): return db.create_qa(q.model_dump())

@app.put("/api/qa/{qid}")
def qa_update(qid: int, q: QAIn): return db.update_qa(qid, q.model_dump())

@app.delete("/api/qa/{qid}")
def qa_delete(qid: int): return db.delete_qa(qid)

class SearchIn(BaseModel):
    query: str
    profile_id: int | None = None

@app.post("/api/qa/search")
def qa_search(body: SearchIn):
    from .qa_search import QASearch
    t0 = time.time()
    res = QASearch(db.list_qa(body.profile_id)).search(body.query, top_k=3)
    return {"results": res, "elapsed_ms": round((time.time() - t0) * 1000, 1)}

# ---------------------------------------------------------------- sessions
class SessionIn(BaseModel):
    profile_id: int | None = None

@app.post("/api/sessions")
def session_create(body: SessionIn, ):
    s = create_session(body.profile_id)
    return {"session_id": s.id, "token": s.token, "profile_id": s.profile_id}

@app.get("/api/sessions/{sid}/qr")
def session_qr(sid: str, base: str):
    s = get_session(sid)
    if not s or not s.active:
        raise HTTPException(404, "セッションが存在しません")
    url = f"{base}/?session={s.id}&token={s.token}"
    return Response(content=_qr_png(url), media_type="image/png")

@app.post("/api/sessions/{sid}/end")
def session_end(sid: str):
    s = end_session(sid)
    return {"ended": bool(s)}

class ManualIn(BaseModel):
    text: str
    source: str = "manual"
    force: bool = False

@app.post("/api/sessions/{sid}/manual-input")
async def manual_input(sid: str, body: ManualIn):
    s = get_session(sid)
    if not s or not s.active:
        raise HTTPException(404, "セッションが存在しません")
    src = "interviewer" if body.source in ("manual", "interviewer") else body.source
    await pipeline_for(s).handle_utterance(body.text, source=src, force=body.force)
    return {"accepted": True}

# ------------------------------------------------------- host audio control
_host_tasks = {}

@app.get("/api/audio/devices")
def audio_devices():
    devs = []
    try: devs += MicSource.list_devices()
    except Exception: pass
    try: devs += WasapiLoopbackSource.list_devices()
    except Exception: pass
    return {"devices": devs}

@app.post("/api/sessions/{sid}/audio/start")
async def audio_start(sid: str, kind: str = Form(...), device_index: int | None = Form(None)):
    """Start a host-side audio source (Windows loopback / mic on the PC)."""
    s = get_session(sid)
    if not s or not s.active:
        raise HTTPException(404, "セッションが存在しません")
    key = (sid, kind)
    if key in _host_tasks:
        return {"started": True, "note": "already running"}
    role = "interviewer" if kind == "wasapi_loopback" else "user"
    try:
        if kind == "wasapi_loopback":
            src = WasapiLoopbackSource(device_index=device_index)
        elif kind == "mic":
            src = MicSource(device_index=device_index, role="user")
        else:
            raise HTTPException(400, f"unknown kind {kind}")
    except Exception as e:
        raise HTTPException(400, f"音声ソースを開始できません: {e}")
    seg = Segmenter()
    tr = StreamingTranscriber()
    pipe = pipeline_for(s)
    async def run():
        try:
            async for chunk in src.chunks():
                for audio, is_final in seg.feed(chunk):
                    if not whisper_available():
                        await broadcast(s, {"type": "status", "text": "音声認識モデルが未導入です"})
                        return
                    r = await asyncio.to_thread(tr.handle_segment, audio, is_final)
                    if r["interim"]:
                        await broadcast(s, {"type": "transcript_interim", "text": r["interim"],
                                            "source": role, "ts": time.time()})
                    if r["final"]:
                        await pipe.handle_utterance(r["final"], source=role)
        finally:
            _host_tasks.pop(key, None)
    _host_tasks[key] = (src, asyncio.create_task(run()))
    return {"started": True, "kind": kind, "role": role}

@app.post("/api/sessions/{sid}/audio/stop")
async def audio_stop(sid: str, kind: str = Form(...)):
    item = _host_tasks.pop((sid, kind), None)
    if item:
        item[0].stop(); item[1].cancel()
    return {"stopped": True}

# ---------------------------------------------------------------- settings / history / system
@app.get("/api/settings")
def settings_get():
    keys = ["save_history", "whisper_model", "answer_length", "qa_threshold"]
    return {k: db.get_setting(k) for k in keys}

class SettingIn(BaseModel):
    key: str
    value: str

@app.put("/api/settings")
def settings_put(body: SettingIn):
    db.set_setting(body.key, body.value)
    return {"ok": True}

@app.get("/api/history")
def history_list(): return db.list_history()

@app.delete("/api/history")
def history_clear():
    db.clear_history(); return {"cleared": True}

@app.delete("/api/all-data")
def all_data_delete():
    db.delete_all_data(); return {"deleted": True}

@app.get("/api/system/status")
async def system_status():
    from .generator import OllamaGenerator
    from .qa_search import get_embedder
    ollama_ok = await OllamaGenerator().available()
    return {
        "whisper_available": whisper_available(),
        "whisper_model": os.environ.get("ISA_WHISPER_MODEL", "base"),
        "ollama_available": ollama_ok,
        "ollama_model": os.environ.get("ISA_OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M"),
        "generator": "ollama" if ollama_ok else "mock",
        "embedder": get_embedder().name,
        "vad": get_vad().name,
        "platform": os.name,
    }

# ---------------------------------------------------------------- websocket
@app.websocket("/ws/{sid}")
async def ws_endpoint(ws: WebSocket, sid: str, token: str = ""):
    s = get_session(sid)
    if not s or not s.check_token(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    s.clients.add(ws)
    # replay recent events so a reconnecting phone restores state
    for ev in list(s.events):
        try: await ws.send_json(ev)
        except Exception: break
    await ws.send_json({"type": "status", "text": "接続しました", "clients": len(s.clients)})
    pipe = pipeline_for(s)
    seg = Segmenter()
    tr = StreamingTranscriber()
    try:
        while True:
            msg = await ws.receive()
            if msg.get("bytes") is not None:
                # browser-captured mic audio: float32 mono 16kHz
                chunk = np.frombuffer(msg["bytes"], dtype=np.float32)
                await broadcast(s, {"type": "audio_level",
                                    "level": float(min(1.0, np.sqrt(np.mean(chunk ** 2)) * 4)) if len(chunk) else 0.0,
                                    "source": "interviewer"})
                for audio, is_final in seg.feed(chunk):
                    if not whisper_available():
                        await ws.send_json({"type": "status", "text": "音声認識モデルが未導入のため文字起こしできません（手動入力は利用可）"})
                        continue
                    r = await asyncio.to_thread(tr.handle_segment, audio, is_final)
                    if r["interim"]:
                        await broadcast(s, {"type": "transcript_interim", "text": r["interim"],
                                            "source": "interviewer", "ts": time.time()})
                    if r["final"]:
                        await pipe.handle_utterance(r["final"], source="interviewer")
            elif msg.get("text"):
                data = json.loads(msg["text"])
                t = data.get("type")
                if t == "manual_text":
                    src = "interviewer" if data.get("source", "interviewer") != "user" else "user"
                    await pipe.handle_utterance(data.get("text", ""), source=src,
                                                force=bool(data.get("force")))
                elif t == "pause":
                    pipe.paused = True
                    await broadcast(s, {"type": "status", "text": "認識を一時停止しました"})
                elif t == "resume":
                    pipe.paused = False
                    await broadcast(s, {"type": "status", "text": "認識を再開しました"})
                elif t == "regenerate":
                    await pipe.answer_question(data.get("question", ""))
                elif t == "ping":
                    await ws.send_json({"type": "pong", "ts": time.time()})
    except Exception:
        pass  # disconnect / abrupt close
    finally:
        s.clients.discard(ws)

# ---------------------------------------------------------------- frontend
app.mount("/", StaticFiles(directory=os.path.join(BASE, "..", "static"), html=True), name="static")
