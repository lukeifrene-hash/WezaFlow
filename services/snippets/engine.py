from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class SnippetEngine:
    def __init__(self, snippets: Mapping[str, str] | Sequence[Mapping[str, Any]] | None = None) -> None:
        self._snippets: dict[str, str] = {}
        if snippets:
            self.load(snippets)

    def load(self, snippets: Mapping[str, str] | Sequence[Mapping[str, Any]]) -> None:
        if isinstance(snippets, Mapping):
            for trigger_phrase, expansion in snippets.items():
                self._add(str(trigger_phrase), str(expansion))
            return

        for record in snippets:
            trigger_phrase = record.get("trigger_phrase", record.get("trigger"))
            expansion = record.get("expansion", record.get("text"))
            if trigger_phrase is not None and expansion is not None:
                self._add(str(trigger_phrase), str(expansion))

    def expand(self, text: str) -> str | None:
        return self._snippets.get(self._key(text))

    def _add(self, trigger_phrase: str, expansion: str) -> None:
        trigger_phrase = trigger_phrase.strip()
        if trigger_phrase:
            self._snippets[self._key(trigger_phrase)] = expansion

    @staticmethod
    def _key(text: str) -> str:
        return " ".join(text.casefold().strip().split())
