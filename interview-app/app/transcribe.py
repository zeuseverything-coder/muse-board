"""Japanese transcription with faster-whisper.

Streaming strategy: the Segmenter emits partial segments while the speaker
talks; each partial is transcribed and merged with the previous partial via
longest-overlap deduplication, giving low-latency interim text. The final
segment produces the confirmed utterance.
If faster-whisper (or its model) is unavailable, `available()` is False and
the rest of the pipeline (manual input etc.) keeps working.
"""
import os, re, threading
import numpy as np

MODEL_SIZE = os.environ.get("ISA_WHISPER_MODEL", "base")

# Common Whisper mis-recognitions / fillers corrected post-hoc (extensible).
CORRECTIONS = {
    "えーっと": "", "あのー": "", "えー": "",
}
_model = None
_model_lock = threading.Lock()

def _load_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
        return _model

def available():
    try:
        _load_model()
        return True
    except Exception:
        return False

def transcribe_audio(audio_f32: np.ndarray, sample_rate=16000) -> str:
    model = _load_model()
    segments, _info = model.transcribe(
        audio_f32, language="ja", beam_size=1, vad_filter=False,
        condition_on_previous_text=False)
    text = "".join(s.text for s in segments).strip()
    for k, v in CORRECTIONS.items():
        text = text.replace(k, v)
    return re.sub(r"\s+", "", text)

def merge_overlap(prev: str, new: str) -> str:
    """Deduplicate overlap between consecutive partial transcriptions:
    if `new` restarts `prev` (typical for growing windows) keep `new`;
    otherwise append only the non-overlapping suffix."""
    if not prev:
        return new
    if new.startswith(prev):
        return new
    if prev.startswith(new):
        return prev
    max_k = 0
    for k in range(1, min(len(prev), len(new)) + 1):
        if prev[-k:] == new[:k]:
            max_k = k
    return prev + new[max_k:] if max_k else (new if len(new) >= len(prev) else prev)

class StreamingTranscriber:
    """Stateful per-source transcriber: partials -> merged interim text,
    final -> confirmed utterance (and interim state reset)."""
    def __init__(self):
        self.interim = ""
    def handle_segment(self, audio_f32, is_final):
        if not is_final and len(audio_f32) > 16000 * 10:
            audio_f32 = audio_f32[-16000 * 10:]  # cap partial window at 10s
        text = transcribe_audio(audio_f32)
        if is_final:
            final = merge_overlap(self.interim, text) if self.interim else text
            self.interim = ""
            return {"interim": None, "final": final}
        self.interim = merge_overlap(self.interim, text)
        return {"interim": self.interim, "final": None}
