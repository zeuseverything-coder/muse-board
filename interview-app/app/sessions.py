"""Interview sessions: token auth, WebSocket fan-out, event replay buffer.

A session is created on the PC (host). Phones join with the session token
(shown as a QR code). Ending the session invalidates the token. Recent
events are kept in an in-memory ring buffer so a reconnecting client can
restore the answer history (nothing is written to disk unless the user
enabled history saving in settings).
"""
import secrets, time
from collections import deque

class Session:
    def __init__(self, profile_id=None):
        self.id = secrets.token_urlsafe(9)
        self.token = secrets.token_urlsafe(24)
        self.profile_id = profile_id
        self.active = True
        self.created_at = time.time()
        self.clients = set()          # WebSocket objects
        self.events = deque(maxlen=300)  # replay buffer
        self.context = []             # [{question, answer}] for follow-ups
    def check_token(self, token):
        return self.active and secrets.compare_digest(token or "", self.token)

_sessions = {}

def create_session(profile_id=None):
    s = Session(profile_id)
    _sessions[s.id] = s
    return s

def get_session(session_id):
    return _sessions.get(session_id)

def end_session(session_id):
    s = _sessions.pop(session_id, None)
    if s:
        s.active = False
    return s
