from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only in minimal installs
    yaml = None


SnippetRecord = dict[str, str]


def list_snippets(path: str | Path) -> list[SnippetRecord]:
    snippet_path = Path(path)
    if not snippet_path.exists():
        return []

    text = snippet_path.read_text(encoding="utf-8")
    parsed = _load_yaml(text)
    records = parsed.get("snippets") if isinstance(parsed, dict) else None
    if not isinstance(records, list):
        return []

    snippets: list[SnippetRecord] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        trigger_phrase = str(record.get("trigger_phrase", "")).strip()
        expansion = str(record.get("expansion", ""))
        if trigger_phrase:
            snippets.append({"trigger_phrase": trigger_phrase, "expansion": expansion})
    return snippets


def upsert_snippet(path: str | Path, trigger_phrase: str, expansion: str) -> list[SnippetRecord]:
    normalized = _normalize_trigger(trigger_phrase)
    if not normalized:
        raise ValueError("trigger_phrase is required")

    snippets = list_snippets(path)
    updated = False
    for snippet in snippets:
        if _normalize_trigger(snippet["trigger_phrase"]) == normalized:
            snippet["trigger_phrase"] = trigger_phrase.strip()
            snippet["expansion"] = expansion
            updated = True
            break
    if not updated:
        snippets.append({"trigger_phrase": trigger_phrase.strip(), "expansion": expansion})

    save_snippets(path, snippets)
    return snippets


def delete_snippet(path: str | Path, trigger_phrase: str) -> bool:
    normalized = _normalize_trigger(trigger_phrase)
    snippets = list_snippets(path)
    remaining = [
        snippet
        for snippet in snippets
        if _normalize_trigger(snippet["trigger_phrase"]) != normalized
    ]
    save_snippets(path, remaining)
    return len(remaining) != len(snippets)


def save_snippets(path: str | Path, snippets: list[SnippetRecord]) -> None:
    snippet_path = Path(path)
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(_dump_yaml({"snippets": snippets}), encoding="utf-8")


def _normalize_trigger(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _load_yaml(text: str) -> Any:
    if yaml is not None:
        return yaml.safe_load(text) or {}

    records: list[SnippetRecord] = []
    current: SnippetRecord | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped == "snippets:":
            continue
        if stripped.startswith("- "):
            if current:
                records.append(current)
            current = {}
            stripped = stripped[2:].strip()
        if current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = value.strip().strip("'\"")
    if current:
        records.append(current)
    return {"snippets": records}


def _dump_yaml(data: dict[str, Any]) -> str:
    if yaml is not None:
        return yaml.safe_dump(data, sort_keys=False)

    lines = ["snippets:"]
    for record in data.get("snippets", []):
        lines.append(f"  - trigger_phrase: {record['trigger_phrase']}")
        lines.append(f"    expansion: {record['expansion']}")
    return "\n".join(lines) + "\n"
