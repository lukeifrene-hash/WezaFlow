from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


AppCategory = Literal["email", "work_chat", "personal_chat", "code", "browser", "other"]


@dataclass(frozen=True)
class AppContext:
    app_name: str
    window_title: str
    category: AppCategory
    browser_url: str | None = None
    visible_text: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineRequest:
    wav_path: str
    context: AppContext
    language: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["context"] = self.context.to_dict()
        return data


@dataclass(frozen=True)
class AsrResult:
    text: str
    language: str | None
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FormatResult:
    text: str
    model: str
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    raw_transcript: str
    polished_text: str
    app_context: AppContext
    duration_ms: int
    timings_ms: dict[str, int] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["app_context"] = self.app_context.to_dict()
        return data
