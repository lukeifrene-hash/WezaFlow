from __future__ import annotations

from threading import RLock
from time import perf_counter
from typing import Any

from services.pipeline.models import AsrResult


class FasterWhisperBackend:
    def __init__(
        self,
        model_name: str = "large-v3-turbo",
        numpy_module: Any | None = None,
        **model_kwargs: Any,
    ) -> None:
        self.model_name = model_name
        self.model_kwargs = model_kwargs
        self._numpy = numpy_module
        self._model = None
        self._model_lock = RLock()

    @property
    def model(self):
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    from faster_whisper import WhisperModel

                    self._model = WhisperModel(self.model_name, **self.model_kwargs)
        return self._model

    def warm_up(self, language: str | None = None) -> None:
        del language
        _ = self.model

    def transcribe(self, audio, language=None, initial_prompt=None):
        return self.model.transcribe(
            self._coerce_audio(audio),
            language=language,
            initial_prompt=initial_prompt,
        )

    def _coerce_audio(self, audio):
        if isinstance(audio, (list, tuple)):
            numpy = self._numpy or _import_numpy()
            return numpy.asarray(audio, dtype=numpy.float32)
        return audio


class Transcriber:
    def __init__(self, backend=None, model_name: str = "large-v3-turbo", **model_kwargs: Any) -> None:
        self.backend = backend
        self.model_name = model_name
        self.model_kwargs = model_kwargs
        self._lock = RLock()

    def transcribe(self, audio, language: str | None = None, initial_prompt: str | None = None) -> AsrResult:
        started = perf_counter()
        with self._lock:
            backend = self._backend()
            raw_result = backend.transcribe(
                audio,
                language=language,
                initial_prompt=initial_prompt,
            )
        elapsed_ms = int((perf_counter() - started) * 1000)
        return self._to_asr_result(raw_result, fallback_language=language, elapsed_ms=elapsed_ms)

    def warm_up(self, language: str | None = None) -> None:
        with self._lock:
            backend = self._backend()
            warm_up = getattr(backend, "warm_up", None)
            if callable(warm_up):
                warm_up(language=language)
            else:
                getattr(backend, "model", None)

    def _backend(self):
        if self.backend is None:
            self.backend = FasterWhisperBackend(self.model_name, **self.model_kwargs)
        return self.backend

    @staticmethod
    def _to_asr_result(raw_result, fallback_language: str | None, elapsed_ms: int) -> AsrResult:
        if isinstance(raw_result, AsrResult):
            return raw_result

        if isinstance(raw_result, dict):
            return AsrResult(
                text=str(raw_result.get("text", "")).strip(),
                language=raw_result.get("language", fallback_language),
                duration_ms=int(raw_result.get("duration_ms", elapsed_ms)),
            )

        if isinstance(raw_result, tuple) and len(raw_result) == 2:
            segments, info = raw_result
            text = "".join(getattr(segment, "text", str(segment)) for segment in segments).strip()
            duration = getattr(info, "duration", None)
            duration_ms = int(duration * 1000) if duration is not None else elapsed_ms
            return AsrResult(
                text=text,
                language=getattr(info, "language", fallback_language),
                duration_ms=duration_ms,
            )

        return AsrResult(text=str(raw_result).strip(), language=fallback_language, duration_ms=elapsed_ms)


def _import_numpy():
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("numpy is required to transcribe in-memory audio samples") from exc
    return numpy
