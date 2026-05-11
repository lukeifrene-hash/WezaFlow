from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SpeculativeConfig:
    sample_rate: int = 16000
    min_recording_ms: int = 2000
    trailing_silence_ms: int = 1500
    max_reuse_tail_ms: int = 250
    silence_threshold: float = 0.02
    poll_interval_ms: int = 200
    release_wait_ms: int = 0


class SpeculativeTranscriptionSession:
    def __init__(
        self,
        *,
        pipeline: Any,
        recorder: Any,
        logger: Any,
        config: SpeculativeConfig | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.recorder = recorder
        self.logger = logger
        self.config = config or SpeculativeConfig()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._monitor_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._snapshot_sample_count = 0
        self._result = None
        self._error: Exception | None = None
        self._started_at: float | None = None

    def start(self, *, language: str | None = None) -> None:
        self._monitor_thread = threading.Thread(
            target=self._monitor,
            kwargs={"language": language},
            name="localflow-speculative-asr-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def maybe_start_snapshot(self, *, language: str | None = None) -> bool:
        with self._lock:
            if self._worker_thread is not None:
                return False

        samples = self._snapshot_samples()
        if not self._is_ready_for_snapshot(samples):
            return False

        self._start_worker(samples, language=language)
        return True

    def wait(self, timeout: float | None = None) -> None:
        worker = self._worker_thread
        if worker is not None:
            worker.join(timeout=timeout)

    def stop(self, final_audio: Any):
        self._stop_event.set()
        self._join_monitor()
        fields = self._base_fields()

        if self._worker_thread is None:
            fields["speculative_status"] = "not_started"
            return None, fields

        final_samples = _as_samples(final_audio)
        if not self._final_audio_matches_snapshot(final_samples):
            fields["speculative_status"] = self._discard_status(final_samples)
            return None, fields

        wait_started = time.perf_counter()
        self._worker_thread.join(timeout=self.config.release_wait_ms / 1000)
        fields["speculative_wait_ms"] = int((time.perf_counter() - wait_started) * 1000)

        if self._worker_thread.is_alive():
            fields["speculative_status"] = "pending"
            return None, fields
        if self._error is not None:
            fields["speculative_status"] = "error"
            fields["speculative_error"] = str(self._error)
            return None, fields
        if self._result is None:
            fields["speculative_status"] = "no_result"
            return None, fields

        fields["speculative_reused"] = True
        fields["speculative_status"] = "reused"
        return self._result, fields

    def cancel(self) -> None:
        self._stop_event.set()
        self._join_monitor()

    def _monitor(self, *, language: str | None) -> None:
        while not self._stop_event.is_set():
            if self.maybe_start_snapshot(language=language):
                return
            self._stop_event.wait(self.config.poll_interval_ms / 1000)

    def _join_monitor(self) -> None:
        monitor = self._monitor_thread
        if monitor is not None and monitor.is_alive():
            monitor.join(timeout=1)

    def _start_worker(self, samples: list[float], *, language: str | None) -> None:
        with self._lock:
            if self._worker_thread is not None:
                return
            self._snapshot_sample_count = len(samples)
            self._started_at = time.perf_counter()
            self.logger.log(
                "speculative_asr_started",
                sample_count=len(samples),
                language=language or "auto",
            )
            self._worker_thread = threading.Thread(
                target=self._process_snapshot,
                args=(samples, language),
                name="localflow-speculative-asr-worker",
                daemon=True,
            )
            self._worker_thread.start()

    def _process_snapshot(self, samples: list[float], language: str | None) -> None:
        try:
            self._result = self.pipeline.process_audio(samples, language=language, inject=False)
        except Exception as exc:
            self._error = exc
            self.logger.log("speculative_asr_error", error=str(exc))
            return

        duration_ms = 0
        if self._started_at is not None:
            duration_ms = int((time.perf_counter() - self._started_at) * 1000)
        self.logger.log(
            "speculative_asr_success",
            duration_ms=duration_ms,
            result_present=self._result is not None,
            snapshot_sample_count=self._snapshot_sample_count,
        )

    def _snapshot_samples(self) -> list[float]:
        snapshot = getattr(self.recorder, "snapshot_samples", None)
        if not callable(snapshot):
            return []
        return _as_samples(snapshot())

    def _is_ready_for_snapshot(self, samples: list[float]) -> bool:
        min_samples = int(self.config.sample_rate * self.config.min_recording_ms / 1000)
        silence_samples = int(self.config.sample_rate * self.config.trailing_silence_ms / 1000)
        if len(samples) < min_samples or len(samples) < silence_samples:
            return False
        tail = samples[-silence_samples:]
        return all(abs(float(sample)) < self.config.silence_threshold for sample in tail)

    def _final_audio_matches_snapshot(self, final_samples: list[float]) -> bool:
        if self._snapshot_sample_count <= 0:
            return False
        tail_count = len(final_samples) - self._snapshot_sample_count
        max_tail = int(self.config.sample_rate * self.config.max_reuse_tail_ms / 1000)
        if tail_count < 0 or tail_count > max_tail:
            return False
        tail = final_samples[self._snapshot_sample_count :]
        return all(abs(float(sample)) < self.config.silence_threshold for sample in tail)

    def _discard_status(self, final_samples: list[float]) -> str:
        tail_count = len(final_samples) - self._snapshot_sample_count
        max_tail = int(self.config.sample_rate * self.config.max_reuse_tail_ms / 1000)
        if tail_count > max_tail:
            return "discarded_new_tail"
        return "discarded_new_speech"

    def _base_fields(self) -> dict[str, Any]:
        return {
            "speculative_reused": False,
            "speculative_snapshot_sample_count": self._snapshot_sample_count,
        }


def _as_samples(audio: Any) -> list[float]:
    if isinstance(audio, list):
        return audio
    try:
        return [float(sample) for sample in audio]
    except TypeError:
        return []
