"""Semantic search over registered Q&A pairs.

Backend strategy (switchable via env ISA_EMBEDDER):
  - "st"     : sentence-transformers with a lightweight multilingual model
               (intfloat/multilingual-e5-small). Used when the package and
               model are available locally.
  - "tfidf"  : character n-gram TF-IDF + Japanese concept normalisation.
               Zero-download fallback; always available.
  - "auto"   : try "st", fall back to "tfidf" (default).
"""
import math, os, re, threading
from collections import Counter, defaultdict

# --- Japanese concept normalisation -------------------------------------
# Maps surface variants to canonical concept tokens so that differently
# worded questions about the same topic score as similar.
CONCEPTS = [
    ("退職理由", ["退職理由", "転職理由", "辞めた理由", "辞める理由", "やめた理由",
                  "転職を決意", "転職のきっかけ", "前職を辞め", "退職した理由", "辞職"]),
    ("自己紹介", ["自己紹介", "自己ＰＲ", "自己PR", "ご自身について", "あなたのこと"]),
    ("志望動機", ["志望動機", "志望理由", "応募理由", "なぜ弊社", "なぜ当社", "どうして弊社", "志望した理由"]),
    ("強み", ["強み", "長所", "得意なこと", "アピールポイント"]),
    ("弱み", ["弱み", "短所", "苦手なこと", "改善したい点"]),
    ("成功体験", ["成功体験", "成果", "実績", "達成したこと", "うまくいった経験"]),
    ("失敗体験", ["失敗体験", "失敗したこと", "挫折", "うまくいかなかった"]),
    ("キャリアプラン", ["キャリアプラン", "将来の目標", "今後の展望", "将来像", "数年後"]),
    ("業務経験", ["業務経験", "職務経歴", "担当業務", "これまでの仕事", "仕事内容"]),
]

def normalize(text: str) -> str:
    t = text
    for canon, variants in CONCEPTS:
        for v in variants:
            t = t.replace(v, f" {canon} ")
    t = re.sub(r"[、。・？?！!「」『』（）()\[\]【】\s]+", " ", t)
    return t.strip()

def _ngrams(text: str, nmin=2, nmax=4):
    t = re.sub(r"\s+", "", text)
    grams = []
    for n in range(nmin, nmax + 1):
        grams += [t[i:i + n] for i in range(len(t) - n + 1)]
    return grams

class TfidfEmbedder:
    name = "tfidf-char-ngram"
    def __init__(self):
        self._idf = {}
        self._doc_vecs = []
    def fit(self, texts):
        docs = [_ngrams(normalize(t)) for t in texts]
        df = Counter()
        for d in docs:
            df.update(set(d))
        n = max(len(docs), 1)
        self._idf = {g: math.log((n + 1) / (c + 1)) + 1.0 for g, c in df.items()}
        self._doc_vecs = [self._vec(d) for d in docs]
        return self
    def _vec(self, grams):
        tf = Counter(grams)
        v = {g: (1 + math.log(c)) * self._idf.get(g, 1.0) for g, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {g: x / norm for g, x in v.items()}
    def encode_query(self, text):
        return self._vec(_ngrams(normalize(text)))
    def similarity(self, qv, idx):
        dv = self._doc_vecs[idx]
        if len(qv) > len(dv): qv, dv = dv, qv
        return sum(w * dv.get(g, 0.0) for g, w in qv.items())

class STEmbedder:
    """sentence-transformers backend (optional, lazy)."""
    name = "sentence-transformers"
    MODEL = os.environ.get("ISA_ST_MODEL", "intfloat/multilingual-e5-small")
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self.MODEL)
        self._doc_vecs = []
    def _enc(self, texts, prefix):
        import numpy as np
        v = self._model.encode([prefix + t for t in texts], normalize_embeddings=True)
        return [np.asarray(x) for x in v]
    def fit(self, texts):
        self._doc_vecs = self._enc([normalize(t) for t in texts], "passage: ")
        return self
    def encode_query(self, text):
        return self._enc([normalize(text)], "query: ")[0]
    def similarity(self, qv, idx):
        return float(qv @ self._doc_vecs[idx])

_embedder = None
_embedder_lock = threading.Lock()

def get_embedder():
    global _embedder
    if _embedder is not None:
        return _embedder
    with _embedder_lock:
        if _embedder is not None:
            return _embedder
        mode = os.environ.get("ISA_EMBEDDER", "auto")
        if mode in ("auto", "st"):
            try:
                _embedder = STEmbedder()
                return _embedder
            except Exception:
                if mode == "st":
                    raise
        _embedder = TfidfEmbedder()
        return _embedder

class QASearch:
    """Index over Q&A pairs; rebuild is cheap for interview-scale data."""
    def __init__(self, pairs):
        self.pairs = pairs
        self.embedder = get_embedder()
        self.embedder.fit([p["question"] for p in pairs]) if pairs else None
    def search(self, query, top_k=3):
        if not self.pairs:
            return []
        qv = self.embedder.encode_query(query)
        scored = [(self.embedder.similarity(qv, i), p) for i, p in enumerate(self.pairs)]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"score": round(float(s), 4), "qa": p} for s, p in scored[:top_k]]
