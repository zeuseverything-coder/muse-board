import sys, time
sys.path.insert(0, '.')
import numpy as np, soundfile as sf
from app.vad import Segmenter
from app.transcribe import StreamingTranscriber

for name in ("q1", "q2"):
    data, sr = sf.read(f"tests/audio/{name}.wav", dtype="float32")
    if data.ndim > 1: data = data.mean(axis=1)
    if sr != 16000:
        n = int(len(data) * 16000 / sr)
        data = np.interp(np.linspace(0, len(data)-1, n), np.arange(len(data)), data).astype(np.float32)
    seg, tr = Segmenter(), StreamingTranscriber()
    t0 = time.time(); finals = []
    step = 480
    padded = np.concatenate([data, np.zeros(16000)])
    for off in range(0, len(padded), step):
        for audio, is_final in seg.feed(padded[off:off+step]):
            r = tr.handle_segment(audio, is_final)
            if r["final"]: finals.append(r["final"])
    for audio, is_final in seg.flush():
        r = tr.handle_segment(audio, is_final)
        if r["final"]: finals.append(r["final"])
    print(name, "elapsed", round(time.time()-t0, 1), "s ->", finals)
