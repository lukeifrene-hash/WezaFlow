from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only in minimal installs
    yaml = None


DEFAULT_SETTINGS: dict[str, Any] = {
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "blocksize": 1024,
    },
    "vad": {
        "threshold": 0.012,
        "min_speech_duration_ms": 250,
        "trim_padding_ms": 700,
        "trim_threshold": 0.004,
        "quiet_threshold": 0.006,
        "quiet_trim_padding_ms": 1000,
        "quiet_trim_threshold": 0.002,
    },
    "models": {
        "whisper": "small.en",
        "whisper_compute_type": "int8",
        "whisper_cpu_threads": 2,
        "whisper_speculative_cpu_threads": 2,
        "ollama": "qwen3.5:4b",
    },
    "hotkeys": {
        "dictation": ["Ctrl+Alt+Space"],
        "command_mode": ["Ctrl+Alt+E"],
    },
    "injection": {
        "method": "clipboard",
        "paste_delay_ms": 80,
    },
    "history": {
        "enabled": True,
        "max_rows": 10000,
    },
    "runtime": {
        "profile": "low-impact",
        "language": "en",
        "quiet_mode": False,
        "quality_fallback": False,
        "system_audio_ducking": True,
        "system_audio_duck_volume": 8,
        "use_ollama": False,
    },
}


def load_default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)


def load_settings(path: str | Path) -> dict[str, Any]:
    settings_path = Path(path)
    settings = load_default_settings()
    if not settings_path.exists():
        return settings

    parsed = _load_yaml(settings_path.read_text(encoding="utf-8"))
    if isinstance(parsed, dict):
        _deep_merge(settings, parsed)
    return settings


def save_settings(path: str | Path, settings: dict[str, Any]) -> dict[str, Any]:
    settings_path = Path(path)
    merged = load_default_settings()
    _deep_merge(merged, settings)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(_dump_yaml(merged), encoding="utf-8")
    return merged


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)
    return target


def _load_yaml(text: str) -> Any:
    if yaml is not None:
        return yaml.safe_load(text) or {}
    return _parse_simple_yaml(text)


def _dump_yaml(data: dict[str, Any]) -> str:
    if yaml is not None:
        return yaml.safe_dump(data, sort_keys=False)
    return _dump_simple_yaml(data)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    current_list_key: str | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("    - ") and current is not None and current_list_key:
            current[current_list_key].append(_parse_scalar(raw_line.strip()[2:].strip()))
            continue
        if not raw_line.startswith(" ") and raw_line.endswith(":"):
            key = raw_line[:-1].strip()
            current = {}
            result[key] = current
            current_list_key = None
            continue
        if current is None or ":" not in raw_line:
            continue
        if raw_line.startswith("  ") and raw_line.strip().endswith(":"):
            key = raw_line.strip()[:-1].strip()
            current[key] = []
            current_list_key = key
            continue
        key, value = raw_line.strip().split(":", 1)
        current[key.strip()] = _parse_scalar(value.strip())
        current_list_key = None
    return result


def _parse_scalar(value: str) -> Any:
    normalized = value.strip().strip("'\"")
    if normalized.lower() == "true":
        return True
    if normalized.lower() == "false":
        return False
    try:
        return int(normalized)
    except ValueError:
        return normalized


def _dump_simple_yaml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for section, values in data.items():
        lines.append(f"{section}:")
        if isinstance(values, dict):
            for key, value in values.items():
                if isinstance(value, list):
                    lines.append(f"  {key}:")
                    for item in value:
                        lines.append(f"    - {_format_scalar(item)}")
                else:
                    lines.append(f"  {key}: {_format_scalar(value)}")
        else:
            lines.append(f"  value: {_format_scalar(values)}")
    return "\n".join(lines) + "\n"


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
