from __future__ import annotations

import io
import time
import wave
from enum import Enum
from urllib.parse import urlparse
from typing import Any, Callable


class RuntimeState(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"
    ERROR = "error"


class RuntimeSession:
    def __init__(
        self,
        *,
        recorder_factory: Callable[[], Any],
        pipeline: Any,
        status: Any | None = None,
        logger: Any | None = None,
        speculative_factory: Callable[[Any, Any, Any], Any] | None = None,
        speculative_pipeline: Any | None = None,
        log_fields: dict[str, Any] | None = None,
        selection_reader: Callable[[], str] | None = None,
        fallback_pipeline: Any | None = None,
        fallback_profile: str | None = None,
        correction_watcher: Any | None = None,
    ) -> None:
        self.recorder_factory = recorder_factory
        self.pipeline = pipeline
        self.status = status or NullStatusReporter()
        self.logger = ContextLogger(logger or NullLogger(), log_fields or {})
        self.speculative_factory = speculative_factory
        self.speculative_pipeline = speculative_pipeline
        self.fallback_pipeline = fallback_pipeline
        self.fallback_profile = fallback_profile
        self.correction_watcher = correction_watcher
        self.selection_reader = selection_reader
        self.state = RuntimeState.IDLE
        self.recorder: Any | None = None
        self.speculative: Any | None = None
        self.last_error: Exception | None = None
        self._recording_started_at: float | None = None
        self._recording_mode = "dictation"
        self._selected_text = ""

    def start_recording(self, *, language: str | None = None) -> bool:
        return self._start_recording(mode="dictation", selected_text="", language=language)

    def start_command_recording(self, *, language: str | None = None) -> bool:
        if self.state is not RuntimeState.IDLE:
            return False

        if self.selection_reader is None:
            self.logger.log("command_no_selection", reason="selection_reader_unavailable")
            self.status.idle()
            return False

        try:
            selected_text = self.selection_reader()
        except Exception as exc:
            self.state = RuntimeState.ERROR
            self.last_error = exc
            self.status.error(exc)
            self.logger.log("dictation_error", phase="read_selection", error=str(exc))
            self.state = RuntimeState.IDLE
            self.status.idle()
            return False

        if not selected_text.strip():
            self.logger.log("command_no_selection")
            self.status.idle()
            return False

        return self._start_recording(
            mode="command",
            selected_text=selected_text,
            language=language,
        )

    def _start_recording(
        self,
        *,
        mode: str,
        selected_text: str,
        language: str | None,
    ) -> bool:
        if self.state is not RuntimeState.IDLE:
            return False

        self.last_error = None
        self.recorder = self.recorder_factory()
        try:
            self.recorder.start()
        except Exception as exc:
            self.state = RuntimeState.ERROR
            self.last_error = exc
            self.status.error(exc)
            self.logger.log("dictation_error", phase="start_recording", error=str(exc))
            self.state = RuntimeState.IDLE
            return False

        self._recording_started_at = time.perf_counter()
        self._recording_mode = mode
        self._selected_text = selected_text
        self.state = RuntimeState.RECORDING
        self.status.recording()
        self.logger.log("recording_started", mode=mode)
        if mode == "dictation":
            self._start_speculative(language=language)
        return True

    def stop_and_process(self, *, language: str | None = None):
        if self.state is not RuntimeState.RECORDING or self.recorder is None:
            return None

        recorder = self.recorder
        mode = self._recording_mode
        selected_text = self._selected_text
        self.recorder = None
        self.state = RuntimeState.PROCESSING
        self.status.processing()
        recording_ms = self._recording_duration_ms()

        try:
            audio = normalize_audio_for_pipeline(recorder.stop())
            speculative_fields: dict[str, Any] = {}
            result = None
            if self.speculative is not None:
                result, speculative_fields = self.speculative.stop(audio)
                self.speculative = None
            if result is not None:
                self._inject_result(result)
            else:
                if mode == "command":
                    result = self.pipeline.process_command(selected_text, audio, language=language)
                else:
                    result = self.pipeline.process_audio(audio, language=language)
                    if result is None and self.fallback_pipeline is not None:
                        result = self.fallback_pipeline.process_audio(audio, language=language)
                        speculative_fields.update(
                            {
                                "fallback_attempted": True,
                                "fallback_profile": self.fallback_profile,
                                "fallback_used": result is not None,
                            }
                        )
        except Exception as exc:
            self.state = RuntimeState.ERROR
            self.last_error = exc
            self._recording_started_at = None
            self.speculative = None
            self._reset_recording_mode()
            self.status.error(exc)
            self.logger.log("dictation_error", phase="process", error=str(exc))
            self.state = RuntimeState.IDLE
            self.status.idle()
            return None

        if result is None:
            self.status.no_speech()
            event = "command_no_speech" if mode == "command" else "dictation_no_speech"
            self.logger.log(
                event,
                recording_ms=recording_ms,
                **audio_stats(audio),
                **speculative_fields,
            )
        else:
            self.status.success(result)
            if mode == "dictation" and self.correction_watcher is not None:
                self.correction_watcher.start(result)
            event = "command_success" if mode == "command" else "dictation_success"
            self.logger.log(
                event,
                **self._success_log_fields(result, audio, recording_ms, speculative_fields),
            )

        self.state = RuntimeState.IDLE
        self._reset_recording_mode()
        self.status.idle()
        return result

    def cancel(self) -> bool:
        if self.state is RuntimeState.RECORDING and self.recorder is not None:
            recorder = self.recorder
            self.recorder = None
            try:
                if self.speculative is not None:
                    self.speculative.cancel()
                    self.speculative = None
                recorder.stop()
            except Exception as exc:
                self.last_error = exc
                self.logger.log("dictation_error", phase="cancel", error=str(exc))
            mode = self._recording_mode
            self.state = RuntimeState.IDLE
            self._recording_started_at = None
            self._reset_recording_mode()
            self.logger.log("command_cancelled" if mode == "command" else "dictation_cancelled")
            self.status.idle()
            return True

        if self.state is RuntimeState.PROCESSING:
            self.logger.log("dictation_cancel_requested", phase="processing")
            return False

        return False

    def _reset_recording_mode(self) -> None:
        self._recording_mode = "dictation"
        self._selected_text = ""

    def _start_speculative(self, *, language: str | None) -> None:
        if self.speculative_factory is None or self.recorder is None:
            return
        self.speculative = self.speculative_factory(self.recorder, self.pipeline, self.logger)
        self.speculative.start(language=language)

    def _recording_duration_ms(self) -> int:
        if self._recording_started_at is None:
            return 0
        elapsed_ms = int((time.perf_counter() - self._recording_started_at) * 1000)
        self._recording_started_at = None
        return elapsed_ms

    def _success_log_fields(
        self,
        result: Any,
        audio: Any,
        recording_ms: int,
        speculative_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stats = audio_stats(audio)
        fields: dict[str, Any] = {
            "recording_ms": recording_ms,
            "audio_sample_count": stats["sample_count"],
            "audio_max_abs": stats["max_abs"],
        }
        if speculative_fields:
            fields.update(speculative_fields)
        duration_ms = getattr(result, "duration_ms", None)
        timings_ms = getattr(result, "timings_ms", None)
        diagnostics = getattr(result, "diagnostics", None)
        raw_transcript = getattr(result, "raw_transcript", None)
        polished_text = getattr(result, "polished_text", None)
        app_context = getattr(result, "app_context", None)
        if duration_ms is not None:
            fields["duration_ms"] = duration_ms
        if timings_ms is not None:
            fields["timings_ms"] = timings_ms
        if diagnostics:
            fields["diagnostics"] = diagnostics
        if raw_transcript is not None:
            fields["raw_characters"] = len(raw_transcript)
        if polished_text is not None:
            fields["polished_characters"] = len(polished_text)
        if app_context is not None:
            category = getattr(app_context, "category", None)
            app_name = getattr(app_context, "app_name", None)
            browser_url = getattr(app_context, "browser_url", None)
            if category is not None:
                fields["app_category"] = category
            if app_name is not None:
                fields["app_name"] = app_name
            if browser_url:
                fields["browser_host"] = urlparse(browser_url).netloc or browser_url
        return fields

    def _inject_result(self, result: Any) -> None:
        inject_result = getattr(self.pipeline, "inject_result", None)
        if callable(inject_result):
            inject_result(result)
            return
        injector = getattr(self.pipeline, "injector", None)
        if injector is None:
            raise RuntimeError("Speculative result cannot be injected by this pipeline")
        injector.inject(result.polished_text)


class NullLogger:
    def log(self, event: str, **fields: Any) -> None:
        del event, fields


class ContextLogger:
    def __init__(self, logger: Any, fields: dict[str, Any]) -> None:
        self.logger = logger
        self.fields = dict(fields)

    def log(self, event: str, **fields: Any) -> None:
        self.logger.log(event, **{**self.fields, **fields})


class NullStatusReporter:
    def recording(self) -> None:
        pass

    def processing(self) -> None:
        pass

    def success(self, result: Any) -> None:
        del result

    def no_speech(self) -> None:
        pass

    def error(self, error: Exception) -> None:
        del error

    def idle(self) -> None:
        pass


def normalize_audio_for_pipeline(audio: Any) -> Any:
    if isinstance(audio, bytes):
        return wav_bytes_to_float_samples(audio)
    return audio


def wav_bytes_to_float_samples(wav_bytes: bytes) -> list[float]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise RuntimeError("Only 16-bit PCM WAV audio is supported by the runtime pipeline")

    samples: list[float] = []
    frame_width = sample_width * channels
    for offset in range(0, len(frames), frame_width):
        channel_total = 0
        for channel in range(channels):
            sample_offset = offset + channel * sample_width
            value = int.from_bytes(
                frames[sample_offset : sample_offset + sample_width],
                "little",
                signed=True,
            )
            channel_total += value
        samples.append((channel_total / channels) / 32768.0)
    return samples


def audio_stats(audio: Any) -> dict[str, int | float]:
    try:
        samples = list(audio)
    except TypeError:
        return {"sample_count": 0, "max_abs": 0.0}
    return {
        "sample_count": len(samples),
        "max_abs": max((abs(float(sample)) for sample in samples), default=0.0),
    }
