from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from services.asr.transcriber import Transcriber
from services.asr.vad import VADFilter
from services.common.paths import ProjectPaths
from services.config.settings import load_default_settings
from services.context.app_context import get_active_app_context
from services.injection.clipboard import ClipboardInjector
from services.llm.formatter import OllamaBackend, TextFormatter
from services.pipeline.models import AppContext
from services.pipeline.orchestrator import PipelineOrchestrator
from services.snippets.engine import SnippetEngine
from services.vocabulary.store import VocabularyStore


def build_pipeline(
    *,
    root: str | Path | None = None,
    vad: Any | None = None,
    transcriber: Any | None = None,
    formatter: Any | None = None,
    context_provider: Callable[[], AppContext] | None = None,
    injector: Any | None = None,
    snippets: Any | None = None,
    use_ollama: bool = False,
    whisper_model_name: str | None = None,
    whisper_compute_type: str | None = None,
    whisper_cpu_threads: int | None = None,
    quiet_mode: bool = False,
    vocabulary_store: Any | None = None,
) -> PipelineOrchestrator:
    repo_root = Path(root).resolve() if root is not None else ProjectPaths.discover().repo_root
    paths = ProjectPaths.from_repo_root(repo_root)
    settings = load_default_settings()

    vad_settings = settings["vad"]
    audio_settings = settings["audio"]
    model_settings = settings["models"]

    vad_threshold = vad_settings["quiet_threshold"] if quiet_mode else vad_settings["threshold"]
    trim_threshold = (
        vad_settings["quiet_trim_threshold"] if quiet_mode else vad_settings["trim_threshold"]
    )
    trim_padding_ms = (
        vad_settings["quiet_trim_padding_ms"] if quiet_mode else vad_settings["trim_padding_ms"]
    )

    resolved_vad = vad or VADFilter(
        threshold=vad_threshold,
        min_duration_ms=vad_settings["min_speech_duration_ms"],
        sample_rate=audio_settings["sample_rate"],
        trim_padding_ms=trim_padding_ms,
        trim_threshold=trim_threshold,
    )
    resolved_transcriber = transcriber or Transcriber(
        model_name=whisper_model_name or model_settings["whisper"],
        device="cpu",
        compute_type=whisper_compute_type or model_settings["whisper_compute_type"],
        cpu_threads=whisper_cpu_threads
        if whisper_cpu_threads is not None
        else model_settings["whisper_cpu_threads"],
    )
    resolved_formatter = formatter or TextFormatter(
        backend=OllamaBackend(model=model_settings["ollama"]) if use_ollama else None
    )
    resolved_context_provider = context_provider or get_active_app_context
    resolved_injector = injector or ClipboardInjector(
        preserve_previous_clipboard=True,
        paste_delay_seconds=settings["injection"]["paste_delay_ms"] / 1000,
    )
    resolved_snippets = snippets or SnippetEngine(
        load_snippet_records(paths.config_dir / "snippets.yaml")
    )
    resolved_vocabulary_store = (
        vocabulary_store
        if vocabulary_store is not None
        else VocabularyStore(paths.db_dir / "localflow.db")
    )

    return PipelineOrchestrator(
        vad=resolved_vad,
        transcriber=resolved_transcriber,
        formatter=resolved_formatter,
        context_provider=resolved_context_provider,
        injector=resolved_injector,
        snippets=resolved_snippets,
        vocabulary_store=resolved_vocabulary_store,
    )


def load_snippet_records(path: str | Path) -> list[dict[str, str]]:
    snippet_path = Path(path)
    if not snippet_path.exists():
        return []

    text = snippet_path.read_text(encoding="utf-8")
    parsed = _load_yaml_if_available(text)
    if isinstance(parsed, dict) and isinstance(parsed.get("snippets"), list):
        return [
            {
                "trigger_phrase": str(record["trigger_phrase"]),
                "expansion": str(record["expansion"]),
            }
            for record in parsed["snippets"]
            if isinstance(record, dict)
            and "trigger_phrase" in record
            and "expansion" in record
        ]

    return _parse_simple_snippet_yaml(text)


def _load_yaml_if_available(text: str) -> Any | None:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    return yaml.safe_load(text)


def _parse_simple_snippet_yaml(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_snippets = False

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "snippets:":
            in_snippets = True
            continue
        if not in_snippets:
            continue
        if stripped.startswith("- "):
            if current:
                records.append(current)
            current = {}
            stripped = stripped[2:].strip()
            if stripped:
                _parse_key_value_into(current, stripped)
            continue
        if current is not None:
            _parse_key_value_into(current, stripped)

    if current:
        records.append(current)

    return [
        record
        for record in records
        if record.get("trigger_phrase") and record.get("expansion")
    ]


def _parse_key_value_into(record: dict[str, str], line: str) -> None:
    if ":" not in line:
        return
    key, value = line.split(":", 1)
    record[key.strip()] = value.strip().strip("'\"")
