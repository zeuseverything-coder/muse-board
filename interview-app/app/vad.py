"""Voice activity detection.

Default: energy-based VAD (no dependencies, works everywhere).
Optional: Silero VAD when torch + silero-vad are installed (ISA_VAD=silero).
Audio is handled as float32 mono 16kHz numpy arrays in 30ms frames.
"""
import os
import numpy as np

FRAME_MS = 30

class EnergyVAD:
    name = "energy"
    def __init__(self, threshold=0.012, hangover_frames=10):
        self.threshold = threshold
        self.hangover = hangover_frames
        self._silent_run = 0
    def is_speech(self, frame: np.ndarray) -> bool:
        level = float(np.sqrt(np.mean(frame ** 2))) if len(frame) else 0.0
        if level >= self.threshold:
            self._silent_run = 0
            return True
        self._silent_run += 1
        return self._silent_run <= self.hangover  # keep trailing context

class SileroVAD:
    name = "silero"
    def __init__(self):
        import torch  # noqa
        from silero_vad import load_silero_vad
        self._torch = torch
        self._model = load_silero_vad()
        self._hang = EnergyVAD()  # hangover handling shared
    def is_speech(self, frame):
        import torch
        with torch.no_grad():
            prob = float(self._model(torch.tensor(frame), 16000).item())
        if prob >= 0.5:
            self._hang._silent_run = 0
            return True
        self._hang._silent_run += 1
        return self._hang._silent_run <= self._hang.hangover

def get_vad():
    if os.environ.get("ISA_VAD", "energy") == "silero":
        try:
            return SileroVAD()
        except Exception:
            pass
    return EnergyVAD()

class Segmenter:
    """Groups frames into utterances; emits (audio, is_final) segments.
    Partial segments are emitted every `partial_sec` of speech so the UI can
    show interim transcription; a final segment follows after silence."""
    def __init__(self, vad=None, sample_rate=16000, partial_sec=2.0,
                 end_silence_sec=0.8, max_utterance_sec=30.0):
        self.vad = vad or get_vad()
        self.sr = sample_rate
        self.frame_len = int(sample_rate * FRAME_MS / 1000)
        self.partial_frames = int(partial_sec * 1000 / FRAME_MS)
        self.end_silence_frames = int(end_silence_sec * 1000 / FRAME_MS)
        self.max_frames = int(max_utterance_sec * 1000 / FRAME_MS)
        self._buf = []
        self._speech_frames = 0
        self._trailing_silence = 0
        self._since_partial = 0
    def feed(self, pcm_f32: np.ndarray):
        """Feed arbitrary-length audio; yields (segment_audio, is_final)."""
        out = []
        for off in range(0, len(pcm_f32) - self.frame_len + 1, self.frame_len):
            frame = pcm_f32[off:off + self.frame_len]
            speech = self.vad.is_speech(frame)
            if speech:
                self._buf.append(frame)
                self._speech_frames += 1
                self._trailing_silence = 0
                self._since_partial += 1
                if self._since_partial >= self.partial_frames and self._speech_frames > 0:
                    out.append((np.concatenate(self._buf), False))
                    self._since_partial = 0
                if len(self._buf) >= self.max_frames:
                    out.append((np.concatenate(self._buf), True))
                    self._reset()
            else:
                if self._buf:
                    self._buf.append(frame)
                    self._trailing_silence += 1
                    if self._trailing_silence >= self.end_silence_frames:
                        out.append((np.concatenate(self._buf), True))
                        self._reset()
        return out
    def flush(self):
        if self._buf and self._speech_frames > 0:
            seg = np.concatenate(self._buf)
            self._reset()
            return [(seg, True)]
        self._reset()
        return []
    def _reset(self):
        self._buf, self._speech_frames = [], 0
        self._trailing_silence, self._since_partial = 0, 0
