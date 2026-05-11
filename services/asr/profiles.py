from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AsrProfile:
    name: str
    model_name: str
    compute_type: str
    cpu_threads: int
    speculative_cpu_threads: int
    speculative_enabled: bool
    supported_languages: tuple[str, ...] | None = None

    def pipeline_kwargs(self, *, speculative: bool = False) -> dict[str, object]:
        return {
            "whisper_model_name": self.model_name,
            "whisper_compute_type": self.compute_type,
            "whisper_cpu_threads": (
                self.speculative_cpu_threads if speculative else self.cpu_threads
            ),
        }

    def log_fields(self) -> dict[str, object]:
        return {
            "asr_profile": self.name,
            "asr_model": self.model_name,
            "asr_compute_type": self.compute_type,
            "asr_cpu_threads": self.cpu_threads,
            "asr_speculative_enabled": self.speculative_enabled,
            "asr_speculative_cpu_threads": (
                self.speculative_cpu_threads if self.speculative_enabled else None
            ),
        }


DEFAULT_ASR_PROFILE = "low-impact"

ASR_PROFILES: dict[str, AsrProfile] = {
    "low-impact": AsrProfile(
        name="low-impact",
        model_name="small.en",
        compute_type="int8",
        cpu_threads=2,
        speculative_cpu_threads=2,
        speculative_enabled=False,
        supported_languages=("en",),
    ),
    "snappy": AsrProfile(
        name="snappy",
        model_name="small.en",
        compute_type="int8",
        cpu_threads=4,
        speculative_cpu_threads=2,
        speculative_enabled=False,
        supported_languages=("en",),
    ),
    "balanced": AsrProfile(
        name="balanced",
        model_name="small.en",
        compute_type="int8",
        cpu_threads=4,
        speculative_cpu_threads=2,
        speculative_enabled=True,
        supported_languages=("en",),
    ),
    "quality": AsrProfile(
        name="quality",
        model_name="distil-large-v3",
        compute_type="int8",
        cpu_threads=6,
        speculative_cpu_threads=2,
        speculative_enabled=True,
    ),
    "distil-small-en": AsrProfile(
        name="distil-small-en",
        model_name="Systran/faster-distil-whisper-small.en",
        compute_type="int8",
        cpu_threads=2,
        speculative_cpu_threads=2,
        speculative_enabled=False,
        supported_languages=("en",),
    ),
}

_ALIASES = {
    "low": "low-impact",
    "low_impact": "low-impact",
    "default": DEFAULT_ASR_PROFILE,
}


def asr_profile_names() -> tuple[str, ...]:
    return tuple(ASR_PROFILES)


def resolve_asr_profile(name: str | AsrProfile | None) -> AsrProfile:
    if isinstance(name, AsrProfile):
        return name

    normalized = (name or DEFAULT_ASR_PROFILE).strip().lower()
    normalized = _ALIASES.get(normalized, normalized)
    try:
        return ASR_PROFILES[normalized]
    except KeyError as exc:
        choices = ", ".join(asr_profile_names())
        raise ValueError(f"Unknown ASR profile: {name}. Available profiles: {choices}") from exc
