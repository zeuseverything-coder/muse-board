"""Heuristic detector: does this utterance need an answer draft?

Design: score-based. Explicit question/request markers raise the score;
greetings, back-channels and company-explanation openers lower it.
Manual trigger in the UI bypasses this entirely.
"""
import re

QUESTION_MARKERS = [
    (r"[？?]\s*$", 3), (r"ですか", 3), (r"ますか", 3), (r"でしょうか", 3),
    (r"教えてください", 3), (r"お聞かせください", 3), (r"聞かせてください", 3),
    (r"説明してください", 3), (r"お話しいただけ", 3), (r"いただけますか", 3),
    (r"自己紹介", 3), (r"について教えて", 3), (r"についてお聞", 2),
    (r"経験を", 2), (r"実績を", 2), (r"どのように", 2), (r"どうして", 2),
    (r"なぜ", 2), (r"どういった", 2), (r"どんな", 1), (r"ありますか", 2),
    (r"いらっしゃいますか", 2), (r"具体的には", 1), (r"もう少し詳しく", 2),
    (r"その点", 1), (r"お考えですか", 3), (r"と思いますか", 3),
    (r"お願いできますか", 2), (r"いただけますでしょうか", 3),
]
NON_QUESTION = [
    (r"^(おはようございます|こんにちは|はじめまして|よろしくお願い(いた)?します)[。．]*$", -5),
    (r"^(はい|ええ|うん|なるほど|そうですね|ありがとうございます)[。．]*$", -5),
    (r"^(では|それでは)、?(まず|最初に)?(当社|弊社|会社)の(説明|概要|事業)", -4),
    (r"(当社|弊社)は.{0,30}(会社|企業)で(す|して)", -2),
    (r"本日は(お時間|ご参加)", -3),
    (r"少し雑談", -3),
]

def detect(text: str):
    t = (text or "").strip()
    if len(t) < 4:
        return {"is_question": False, "score": 0, "reason": "短すぎる発言"}
    score, reasons = 0, []
    for pat, w in QUESTION_MARKERS:
        if re.search(pat, t):
            score += w; reasons.append(pat)
    for pat, w in NON_QUESTION:
        if re.search(pat, t):
            score += w; reasons.append("non-question:" + pat)
    # multiple questions in one utterance
    if t.count("？") + t.count("?") >= 2:
        score += 1; reasons.append("複数質問")
    return {"is_question": score >= 3, "score": score,
            "reason": "質問マーカー一致" if score >= 3 else "質問マーカー不足",
            "matched": reasons}
