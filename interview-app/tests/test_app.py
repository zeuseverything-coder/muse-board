"""Automated tests: REST API, Q&A search grouping, question detection,
WebSocket sync latency between two clients (design doc 16)."""
import os, sys, time, asyncio, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["ISA_DB"] = "/tmp/isa_test.db"
os.environ["ISA_EMBEDDER"] = "tfidf"
if os.path.exists("/tmp/isa_test.db"):
    os.remove("/tmp/isa_test.db")

from fastapi.testclient import TestClient
from app.main import app
from app.question_detector import detect

client = TestClient(app)

def test_crud_and_search():
    r = client.post("/api/profiles", json={"company_name": "テスト株式会社", "job_info": "業務改善担当", "notes": ""})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post("/api/documents", json={"kind": "職務経歴書", "title": "経歴書",
                                            "content": "法人営業として案件管理と業務改善を担当しました。", "profile_id": None})
    assert r.status_code == 200
    r = client.post("/api/qa", json={"question": "退職理由を教えてください",
                                     "answer": "スキルアップと新しい挑戦のため退職しました。", "profile_id": None})
    assert r.status_code == 200
    # The three differently-worded questions from the design doc must all
    # hit the same registered Q&A as the top result.
    for q in ["なぜ前職を辞めたのですか？", "転職を決意した背景を教えてください。", "退職理由について説明してください。"]:
        r = client.post("/api/qa/search", json={"query": q})
        res = r.json()["results"]
        assert res and "退職理由" in res[0]["qa"]["question"], (q, res)
        assert r.json()["elapsed_ms"] < 500, r.json()
    return pid

def test_detector():
    assert not detect("おはようございます。よろしくお願いします。")["is_question"]
    assert not detect("はい、なるほど。")["is_question"]
    assert not detect("当社は製造業の会社でして、事業内容を説明します")["is_question"]
    assert detect("自己紹介をお願いできますか")["is_question"]
    assert detect("その実績について、もう少し詳しく教えていただけますか？")["is_question"]
    assert detect("なぜその仕事を選んだのですか？具体的な経験も教えてください")["is_question"]

def test_ws_sync_latency():
    pid = test_crud_and_search()
    test_detector()
    r = client.post("/api/sessions", json={"profile_id": pid})
    sid, token = r.json()["session_id"], r.json()["token"]
    # QR endpoint
    r = client.get(f"/api/sessions/{sid}/qr", params={"base": "http://localhost:8765"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    # bad token rejected
    try:
        with client.websocket_connect(f"/ws/{sid}?token=wrong") as ws:
            ws.receive_json()
        raise AssertionError("bad token accepted")
    except Exception:
        pass
    async def run():
        import websockets
        uri = f"ws://localhost:8899/ws/{sid}?token={token}"
        async with websockets.connect(uri) as a, websockets.connect(uri) as b:
            t0 = time.time()
            await a.send(json.dumps({"type": "manual_text", "text": "なぜ前職を辞めたのですか？", "force": False}))
            got_b, got_a = [], []
            while time.time() - t0 < 10:
                try:
                    msg = json.loads(await asyncio.wait_for(b.recv(), timeout=5))
                    got_b.append((time.time(), msg["type"]))
                    if msg["type"] == "answer_done":
                        break
                except asyncio.TimeoutError:
                    break
            types_b = [t for _, t in got_b]
            assert "answer_start" in types_b and "answer_done" in types_b, types_b
            first_answer_latency = next(t for t, ty in got_b if ty == "answer_start") - t0
            assert first_answer_latency < 3.0, first_answer_latency
            return first_answer_latency
    return run

if __name__ == "__main__":
    import threading, uvicorn
    run = test_ws_sync_latency()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8899, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    time.sleep(2)
    lat = asyncio.run(run())
    print(f"ALL TESTS PASSED (ws answer_start latency to 2nd client: {lat*1000:.0f} ms)")
    srv.should_exit = True
