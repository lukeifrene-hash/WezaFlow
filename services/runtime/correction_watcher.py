from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable


ContextProvider = Callable[[], Any]
Clock = Callable[[], float]
IdFactory = Callable[[], str]


@dataclass(frozen=True)
class PendingCorrectionCandidate:
    id: str
    original: str
    raw_transcript: str
    app_name: str
    window_title: str
    detected_at: float


@dataclass(frozen=True)
class _ActiveWatch:
    original_text: str
    raw_transcript: str
    app_name: str
    window_title: str
    expires_at: float


class CorrectionWatcher:
    def __init__(
        self,
        *,
        context_provider: ContextProvider,
        now: Clock | None = None,
        window_seconds: float = 30,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._context_provider = context_provider
        self._now = now or time.time
        self._window_seconds = window_seconds
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._active_watch: _ActiveWatch | None = None
        self._pending: list[PendingCorrectionCandidate] = []

    def start(self, result: Any) -> None:
        raw_transcript = getattr(result, "raw_transcript", None)
        polished_text = getattr(result, "polished_text", None)
        app_context = getattr(result, "app_context", None)
        app_name = getattr(app_context, "app_name", None)
        window_title = getattr(app_context, "window_title", None)
        if not raw_transcript or not polished_text or app_name is None or window_title is None:
            self._active_watch = None
            return

        self._active_watch = _ActiveWatch(
            original_text=polished_text,
            raw_transcript=raw_transcript,
            app_name=app_name,
            window_title=window_title,
            expires_at=self._now() + self._window_seconds,
        )

    def observe_event(self, key_name: str | None) -> PendingCorrectionCandidate | None:
        return self.observe_key(key_name)

    def observe_key(self, key_name: str | None) -> PendingCorrectionCandidate | None:
        if not self._is_edit_like_key(key_name):
            return None
        watch = self._active_watch
        if watch is None:
            return None
        detected_at = self._now()
        if detected_at > watch.expires_at:
            self._active_watch = None
            return None
        if not self._current_context_matches(watch):
            return None

        candidate = PendingCorrectionCandidate(
            id=self._id_factory(),
            original=watch.original_text,
            raw_transcript=watch.raw_transcript,
            app_name=watch.app_name,
            window_title=watch.window_title,
            detected_at=detected_at,
        )
        self._pending.append(candidate)
        self._active_watch = None
        return candidate

    def list_pending(self) -> list[PendingCorrectionCandidate]:
        return list(self._pending)

    def confirm(self, candidate_id: str) -> PendingCorrectionCandidate | None:
        return self._remove_pending(candidate_id)

    def confirm_pending(self, candidate_id: str) -> PendingCorrectionCandidate | None:
        return self.confirm(candidate_id)

    def dismiss(self, candidate_id: str) -> PendingCorrectionCandidate | None:
        return self._remove_pending(candidate_id)

    def dismiss_pending(self, candidate_id: str) -> PendingCorrectionCandidate | None:
        return self.dismiss(candidate_id)

    def _remove_pending(self, candidate_id: str) -> PendingCorrectionCandidate | None:
        for index, candidate in enumerate(self._pending):
            if candidate.id == candidate_id:
                return self._pending.pop(index)
        return None

    def _current_context_matches(self, watch: _ActiveWatch) -> bool:
        current = self._context_provider()
        return (
            getattr(current, "app_name", None) == watch.app_name
            and getattr(current, "window_title", None) == watch.window_title
        )

    @staticmethod
    def _is_edit_like_key(key_name: str | None) -> bool:
        if key_name is None:
            return False
        normalized = key_name.casefold().strip()
        if len(normalized) == 1 and normalized.isprintable():
            return True
        return normalized in {"backspace", "delete", "space", "enter"}
