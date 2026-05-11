from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from services.pipeline.models import AppContext, PipelineResult


class PipelineOrchestrator:
    def __init__(
        self,
        *,
        vad: Any,
        transcriber: Any,
        formatter: Any,
        context_provider: Callable[[], AppContext],
        injector: Any,
        snippets: Any | None = None,
        vocabulary_store: Any | None = None,
    ) -> None:
        self.vad = vad
        self.transcriber = transcriber
        self.formatter = formatter
        self.context_provider = context_provider
        self.injector = injector
        self.snippets = snippets
        self.vocabulary_store = vocabulary_store

    def process_audio(
        self,
        audio: Any,
        *,
        language: str | None = None,
        inject: bool = True,
        vocabulary_hints: list[str] | None = None,
    ) -> PipelineResult | None:
        started = time.perf_counter()
        phase_started = time.perf_counter()
        app_context = self.context_provider()
        context_ms = self._elapsed_ms(phase_started)

        phase_started = time.perf_counter()
        filtered_audio = self.vad.filter(audio)
        vad_ms = self._elapsed_ms(phase_started)
        if filtered_audio is None:
            return None

        phase_started = time.perf_counter()
        formatter_hints = self._formatter_hints(vocabulary_hints)
        asr_result = self.transcriber.transcribe(
            filtered_audio,
            language=language,
            initial_prompt=self._asr_initial_prompt(vocabulary_hints),
        )
        asr_ms = self._elapsed_ms(phase_started)

        phase_started = time.perf_counter()
        polished_text = self._expand_or_format(
            asr_result.text,
            app_context,
            vocabulary_hints=formatter_hints,
        )
        format_ms = self._elapsed_ms(phase_started)

        phase_started = time.perf_counter()
        if inject:
            self.injector.inject(polished_text)
        inject_ms = self._elapsed_ms(phase_started)
        total_ms = self._elapsed_ms(started)

        return PipelineResult(
            raw_transcript=asr_result.text,
            polished_text=polished_text,
            app_context=app_context,
            duration_ms=total_ms,
            timings_ms={
                "context_ms": context_ms,
                "vad_ms": vad_ms,
                "asr_ms": asr_ms,
                "format_ms": format_ms,
                "inject_ms": inject_ms,
                "total_ms": total_ms,
            },
            diagnostics=self._diagnostics(),
        )

    def process_command(
        self,
        selected_text: str,
        audio: Any,
        *,
        language: str | None = None,
        inject: bool = True,
    ) -> PipelineResult | None:
        started = time.perf_counter()
        phase_started = time.perf_counter()
        app_context = self.context_provider()
        context_ms = self._elapsed_ms(phase_started)

        phase_started = time.perf_counter()
        filtered_audio = self.vad.filter(audio)
        vad_ms = self._elapsed_ms(phase_started)
        if filtered_audio is None:
            return None

        phase_started = time.perf_counter()
        asr_result = self.transcriber.transcribe(
            filtered_audio,
            language=language,
            initial_prompt=self._asr_initial_prompt(None),
        )
        asr_ms = self._elapsed_ms(phase_started)

        phase_started = time.perf_counter()
        edit_result = self.formatter.command_edit(selected_text, asr_result.text)
        format_ms = self._elapsed_ms(phase_started)

        phase_started = time.perf_counter()
        if inject:
            self.injector.inject(edit_result.text)
        inject_ms = self._elapsed_ms(phase_started)
        total_ms = self._elapsed_ms(started)

        return PipelineResult(
            raw_transcript=asr_result.text,
            polished_text=edit_result.text,
            app_context=app_context,
            duration_ms=total_ms,
            timings_ms={
                "context_ms": context_ms,
                "vad_ms": vad_ms,
                "asr_ms": asr_ms,
                "format_ms": format_ms,
                "inject_ms": inject_ms,
                "total_ms": total_ms,
            },
            diagnostics=self._diagnostics(),
        )

    def _diagnostics(self) -> dict[str, Any]:
        vad_stats = getattr(self.vad, "last_stats", None)
        if isinstance(vad_stats, dict):
            return {"vad": dict(vad_stats)}
        return {}

    def inject_result(self, result: PipelineResult) -> None:
        self.injector.inject(result.polished_text)

    def _expand_or_format(
        self,
        raw_text: str,
        app_context: AppContext,
        *,
        vocabulary_hints: list[str] | None,
    ) -> str:
        if self.snippets is not None:
            expansion = self.snippets.expand(raw_text)
            if expansion:
                return expansion
        format_result = self.formatter.format(
            raw_text,
            app_context,
            vocabulary_hints=vocabulary_hints,
        )
        return format_result.text

    def _formatter_hints(self, explicit_hints: list[str] | None) -> list[str] | None:
        hints: list[str] = []
        formatter_hints = getattr(self.vocabulary_store, "formatter_hints", None)
        if callable(formatter_hints):
            hints.extend(str(hint) for hint in formatter_hints() if str(hint).strip())
        if explicit_hints:
            hints.extend(explicit_hints)
        return _dedupe_non_empty(hints) or None

    def _asr_initial_prompt(self, explicit_hints: list[str] | None) -> str | None:
        hints: list[str] = []
        asr_hints = getattr(self.vocabulary_store, "asr_hints", None)
        if callable(asr_hints):
            store_hints = str(asr_hints()).strip()
            if store_hints:
                hints.extend(part.strip() for part in store_hints.split(","))
        if explicit_hints:
            hints.extend(explicit_hints)
        deduped = _dedupe_non_empty(hints)
        return ", ".join(deduped) if deduped else None

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


def _dedupe_non_empty(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result
