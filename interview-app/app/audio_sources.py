"""Audio acquisition abstraction.

Sources emit float32 mono 16kHz PCM chunks via an async iterator and report
an input level (0..1) through a callback. Interviewer audio and the user's
own audio are separated BY SOURCE (loopback = interviewer, mic = user).

Implementations:
  - WasapiLoopbackSource : Windows only, PyAudioWPatch loopback of the
        default playback device (works with headphones/earphones).
  - MicSource            : sounddevice input (any OS with a microphone).
  - BrowserStreamSource  : audio captured in the browser (getUserMedia) and
        pushed over the WebSocket; the server-side queue lives in main.py.
  - FileSource           : replays a WAV file (tests / mock interviews).
  - Manual text input is handled as text, not audio (see /api/manual-input).
"""
import asyncio, sys
import numpy as np

TARGET_SR = 16000

def _to_f32_mono(pcm_bytes, fmt, channels, src_sr):
    if fmt == "f32":
        a = np.frombuffer(pcm_bytes, dtype=np.float32)
    elif fmt == "i16":
        a = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        raise ValueError(f"unsupported fmt {fmt}")
    if channels > 1:
        a = a.reshape(-1, channels).mean(axis=1)
    if src_sr != TARGET_SR:
        n = int(len(a) * TARGET_SR / src_sr)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a

def level_of(chunk: np.ndarray) -> float:
    if len(chunk) == 0:
        return 0.0
    return float(min(1.0, np.sqrt(np.mean(chunk ** 2)) * 4))

class AudioSource:
    kind = "base"
    role = "interviewer"  # or "user"
    def __init__(self, on_level=None):
        self.on_level = on_level or (lambda lv: None)
        self._stop = asyncio.Event()
    def stop(self):
        self._stop.set()
    async def chunks(self):
        raise NotImplementedError
        yield  # pragma: no cover
    @staticmethod
    def list_devices():
        return []

class WasapiLoopbackSource(AudioSource):
    """Windows WASAPI loopback via PyAudioWPatch (interviewer audio)."""
    kind = "wasapi_loopback"
    role = "interviewer"
    def __init__(self, on_level=None, device_index=None):
        super().__init__(on_level)
        if sys.platform != "win32":
            raise RuntimeError("WASAPIループバックはWindows専用です")
        import pyaudiowpatch as pyaudio  # Windows-only package
        self._pa = pyaudio.PyAudio()
        if device_index is None:
            device = self._pa.get_default_wasapi_loopback()
            device_index = device["index"]
        self._device_index = device_index
        info = self._pa.get_device_info_by_index(device_index)
        self._sr = int(info["defaultSampleRate"])
        self._channels = int(info["maxInputChannels"])
    @staticmethod
    def list_devices():
        if sys.platform != "win32":
            return []
        import pyaudiowpatch as pyaudio
        pa = pyaudio.PyAudio()
        out = []
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d.get("isLoopbackDevice"):
                out.append({"index": i, "name": d["name"], "kind": "loopback"})
        return out
    async def chunks(self):
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        def cb(in_data, frame_count, time_info, status):
            loop.call_soon_threadsafe(queue.put_nowait, in_data)
            import pyaudiowpatch as pyaudio
            return (None, pyaudio.paContinue)
        stream = self._pa.open(format=self._pa.get_format_from_width(2),
                               channels=self._channels, rate=self._sr,
                               frames_per_buffer=1024, input=True,
                               input_device_index=self._device_index,
                               stream_callback=cb)
        stream.start_stream()
        try:
            while not self._stop.is_set():
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                f32 = _to_f32_mono(data, "i16", self._channels, self._sr)
                self.on_level(level_of(f32))
                yield f32
        finally:
            stream.stop_stream(); stream.close(); self._pa.terminate()

class MicSource(AudioSource):
    """Microphone via sounddevice (user's own voice by default)."""
    kind = "mic"
    role = "user"
    def __init__(self, on_level=None, device_index=None, role="user"):
        super().__init__(on_level)
        import sounddevice as sd  # raises if unavailable
        self._sd = sd
        self.role = role
        self._device_index = device_index
    @staticmethod
    def list_devices():
        try:
            import sounddevice as sd
            return [{"index": i, "name": d["name"], "kind": "mic"}
                    for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
        except Exception:
            return []
    async def chunks(self):
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        def cb(indata, frames, time_info, status):
            loop.call_soon_threadsafe(queue.put_nowait, indata.copy())
        with self._sd.InputStream(samplerate=TARGET_SR, channels=1, dtype="float32",
                                  blocksize=1024, device=self._device_index, callback=cb):
            while not self._stop.is_set():
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                f32 = data.reshape(-1).astype(np.float32)
                self.on_level(level_of(f32))
                yield f32

class FileSource(AudioSource):
    """Replays a WAV file as if it were live audio (tests / mock mode)."""
    kind = "file"
    role = "interviewer"
    def __init__(self, path, on_level=None, realtime=False):
        super().__init__(on_level)
        self.path = path
        self.realtime = realtime
    async def chunks(self):
        import soundfile as sf
        data, sr = sf.read(self.path, dtype="float32", always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != TARGET_SR:
            n = int(len(data) * TARGET_SR / sr)
            data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype(np.float32)
        step = 1024
        for off in range(0, len(data), step):
            if self._stop.is_set():
                break
            chunk = data[off:off + step]
            self.on_level(level_of(chunk))
            yield chunk
            if self.realtime:
                await asyncio.sleep(step / TARGET_SR)

SOURCE_KINDS = {
    "wasapi_loopback": WasapiLoopbackSource,
    "mic": MicSource,
    "file": FileSource,
}
