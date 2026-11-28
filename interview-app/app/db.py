"""SQLite data layer: documents, company profiles, Q&A pairs, history, settings."""
import sqlite3, threading, time, os

DB_PATH = os.environ.get("ISA_DB", os.path.join(os.path.dirname(__file__), "..", "data", "app.db"))

DOC_KINDS = ["履歴書", "職務経歴書", "自己分析", "自己PR", "転職理由", "退職理由", "志望動機",
             "業務経験", "成功体験", "失敗体験", "強み・弱み", "キャリアプラン", "企業情報", "求人票", "その他"]

_lock = threading.Lock()

def _conn():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS profiles(
          id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT NOT NULL,
          job_info TEXT DEFAULT '', notes TEXT DEFAULT '',
          created_at REAL, updated_at REAL);
        CREATE TABLE IF NOT EXISTS documents(
          id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, title TEXT NOT NULL,
          content TEXT NOT NULL, profile_id INTEGER,
          created_at REAL, updated_at REAL);
        CREATE TABLE IF NOT EXISTS qa_pairs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, answer TEXT NOT NULL,
          profile_id INTEGER, created_at REAL, updated_at REAL);
        CREATE TABLE IF NOT EXISTS history(
          id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, question TEXT,
          answer TEXT, source TEXT, created_at REAL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)

def _crud(table, data=None, row_id=None, delete=False):
    now = time.time()
    with _lock, _conn() as c:
        if delete:
            c.execute(f"DELETE FROM {table} WHERE id=?", (row_id,)); return {"deleted": row_id}
        if data is not None and row_id is not None:
            keys = [k for k in data if k != "id"]
            c.execute(f"UPDATE {table} SET {','.join(k+'=?' for k in keys)}, updated_at=? WHERE id=?",
                      [data[k] for k in keys] + [now, row_id])
            row_id_out = row_id
        elif data is not None:
            keys = [k for k in data if k != "id"]
            cur = c.execute(f"INSERT INTO {table} ({','.join(keys)}, created_at, updated_at) VALUES ({','.join('?'*len(keys))},?,?)",
                            [data[k] for k in keys] + [now, now])
            row_id_out = cur.lastrowid
        else:
            row_id_out = row_id
        row = c.execute(f"SELECT * FROM {table} WHERE id=?", (row_id_out,)).fetchone()
        return dict(row) if row else None

def _list(table, where="", params=()):
    with _lock, _conn() as c:
        rows = c.execute(f"SELECT * FROM {table} {where} ORDER BY id", params).fetchall()
        return [dict(r) for r in rows]

# profiles
def create_profile(d): return _crud("profiles", d)
def update_profile(i, d): return _crud("profiles", d, i)
def delete_profile(i): return _crud("profiles", row_id=i, delete=True)
def list_profiles(): return _list("profiles")

# documents
def create_document(d): return _crud("documents", d)
def update_document(i, d): return _crud("documents", d, i)
def delete_document(i): return _crud("documents", row_id=i, delete=True)
def list_documents(profile_id=None):
    if profile_id is None: return _list("documents")
    return _list("documents", "WHERE profile_id IS ? OR profile_id IS NULL", (profile_id,))

# qa pairs
def create_qa(d): return _crud("qa_pairs", d)
def update_qa(i, d): return _crud("qa_pairs", d, i)
def delete_qa(i): return _crud("qa_pairs", row_id=i, delete=True)
def list_qa(profile_id=None):
    if profile_id is None: return _list("qa_pairs")
    return _list("qa_pairs", "WHERE profile_id IS ? OR profile_id IS NULL", (profile_id,))

# history (saved only when the user enables history saving)
def add_history(session_id, question, answer, source):
    with _lock, _conn() as c:
        c.execute("INSERT INTO history(session_id, question, answer, source, created_at) VALUES (?,?,?,?,?)",
                  (session_id, question, answer, source, time.time()))
def list_history(): return _list("history", "ORDER BY id DESC")
def clear_history():
    with _lock, _conn() as c: c.execute("DELETE FROM history")

def delete_all_data():
    with _lock, _conn() as c:
        for t in ("profiles", "documents", "qa_pairs", "history"):
            c.execute(f"DELETE FROM {t}")

# settings
def get_setting(key, default=None):
    with _lock, _conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default
def set_setting(key, value):
    with _lock, _conn() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, str(value)))
