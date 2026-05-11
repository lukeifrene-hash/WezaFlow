from __future__ import annotations

import re
import time
from typing import Any, Protocol

from services.llm.cleanup import clean_dictation_text
from services.pipeline.models import AppContext, FormatResult


class FormatterBackend(Protocol):
    model: str

    def format(
        self,
        raw_text: str,
        app_context: AppContext,
        vocabulary_hints: list[str] | None = None,
    ) -> str:
        ...


class TextFormatter:
    def __init__(self, backend: FormatterBackend | None = None) -> None:
        self.backend = backend

    def format(
        self,
        raw_text: str,
        app_context: AppContext,
        vocabulary_hints: list[str] | None = None,
    ) -> FormatResult:
        started = time.perf_counter()
        if self.backend is not None:
            text = self.backend.format(raw_text, app_context, vocabulary_hints=vocabulary_hints)
            return FormatResult(
                text=text,
                model=getattr(self.backend, "model", "injected-backend"),
                duration_ms=self._elapsed_ms(started),
            )

        return FormatResult(
            text=self._local_format(raw_text, app_context, vocabulary_hints=vocabulary_hints),
            model="local-fallback",
            duration_ms=self._elapsed_ms(started),
        )

    def command_edit(self, selected_text: str, command_text: str) -> FormatResult:
        started = time.perf_counter()
        command = command_text.strip().lower()

        if "upper" in command:
            text = selected_text.upper()
        elif "lower" in command:
            text = selected_text.lower()
        elif "bullet" in command:
            text = self._bullet_list(selected_text)
        elif "concise" in command or "shorter" in command:
            text = self._concise(selected_text)
        elif "rewrite" in command and "light" in command:
            text = self._concise(selected_text)
        elif self.backend is not None and hasattr(self.backend, "command_edit"):
            text = self.backend.command_edit(selected_text, command_text)  # type: ignore[attr-defined]
        else:
            text = selected_text

        return FormatResult(text=text, model="local-fallback", duration_ms=self._elapsed_ms(started))

    @staticmethod
    def _local_format(
        raw_text: str,
        app_context: AppContext,
        vocabulary_hints: list[str] | None = None,
    ) -> str:
        return clean_dictation_text(raw_text, app_context, vocabulary_hints=vocabulary_hints)

    @staticmethod
    def _concise(text: str) -> str:
        words_to_remove = {"very", "really", "basically", "actually", "just"}
        words = [word for word in text.split() if word.strip(".,!?;:").lower() not in words_to_remove]
        result = " ".join(words).strip()
        return result or text.strip()

    @staticmethod
    def _bullet_list(text: str) -> str:
        parts = [part.strip(" ,;") for part in re.split(r"(?:\r?\n|,|;|\band\b)", text) if part.strip(" ,;")]
        if len(parts) == 1:
            parts = [part for part in parts[0].split() if part]
        return "\n".join(f"- {part}" for part in parts)

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


class OllamaBackend:
    model = "ollama"

    def __init__(self, model: str = "llama3.2", host: str = "http://localhost:11434") -> None:
        self.model = model
        self.host = host.rstrip("/")

    def format(
        self,
        raw_text: str,
        app_context: AppContext,
        vocabulary_hints: list[str] | None = None,
    ) -> str:
        try:
            import httpx  # type: ignore
        except ImportError as exc:
            raise RuntimeError("httpx is required to use OllamaBackend") from exc

        hints = ", ".join(vocabulary_hints or [])
        browser_url = app_context.browser_url or "none"
        visible_text = " | ".join(app_context.visible_text[:3]) if app_context.visible_text else "none"
        prompt = (
            "Polish this dictation text for insertion. "
            f"App category: {app_context.category}. Vocabulary hints: {hints}. "
            f"Browser URL: {browser_url}. Visible text: {visible_text}. "
            f"Text: {raw_text}"
        )
        response = httpx.post(
            f"{self.host}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=10,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
