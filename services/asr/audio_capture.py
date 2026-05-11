from __future__ import annotations

import io
import threading
import wave
from collections.abc import Callable, Iterable
from typing import Any


StreamFactory = Callable[[Callable[..., None], int, int], Any]


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        blocksize: int = 1024,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self._stream_factory = stream_factory
        self._stream = None
        self._frames: list[float] = []
        self._lock = threading.Lock()
        self._is_recording = False

    @classmethod
    def microphone(cls, sample_rate: int = 16000, blocksize: int = 1024) -> "AudioRecorder":
        return cls(
            sample_rate=sample_rate,
            blocksize=blocksize,
            stream_factory=create_sounddevice_stream,
        )

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start(self) -> None:
        with self._lock:
            self._frames = []
        self._is_recording = True
        if self._stream_factory is not None:
            self._stream = self._stream_factory(self._callback, self.sample_rate, self.blocksize)
            self._stream.start()

    def stop(self) -> bytes:
        if self._stream is not None:
            try:
                self._stream.stop()
            finally:
                self._stream.close()
                self._stream = None
        self._is_recording = False
        with self._lock:
            frames = list(self._frames)
        return self.float_samples_to_wav_bytes(frames, sample_rate=self.sample_rate)

    def snapshot_samples(self) -> list[float]:
        with self._lock:
            return list(self._frames)

    def inject_frame(self, samples: Iterable[float]) -> None:
        if self._is_recording:
            with self._lock:
                self._frames.extend(float(sample) for sample in samples)

    def _callback(self, indata, frames=None, time=None, status=None) -> None:
        del frames, time, status
        self.inject_frame(_flatten_mono_samples(indata))

    @staticmethod
    def float_samples_to_wav_bytes(
        samples: Iterable[float], sample_rate: int = 16000
    ) -> bytes:
        pcm = bytearray()
        for sample in samples:
            clipped = max(-1.0, min(1.0, float(sample)))
            value = int(round(clipped * 32767))
            pcm.extend(value.to_bytes(2, "little", signed=True))

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(bytes(pcm))
        return buffer.getvalue()


def create_sounddevice_stream(callback: Callable[..., None], sample_rate: int, blocksize: int):
    try:
        import sounddevice as sd  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("sounddevice is required for microphone capture") from exc

    return sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        callback=callback,
        blocksize=blocksize,
    )


def _flatten_mono_samples(indata) -> list[float]:
    samples: list[float] = []
    for sample in indata:
        if isinstance(sample, (list, tuple)):
            samples.append(float(sample[0]))
        else:
            try:
                samples.append(float(sample[0]))
            except (TypeError, IndexError):
                samples.append(float(sample))
    return samples
