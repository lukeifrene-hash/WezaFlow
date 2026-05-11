from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from services.runtime.audio_smoke import record_wav


Output = Callable[[str], None]
Input = Callable[[str], str]
Record = Callable[..., Path]


@dataclass(frozen=True)
class BenchmarkPrompt:
    label: str
    text: str
    seconds: float


DEFAULT_PROMPTS: tuple[BenchmarkPrompt, ...] = (
    BenchmarkPrompt(
        label="short",
        text="Let's meet on Thursday afternoon.",
        seconds=4.0,
    ),
    BenchmarkPrompt(
        label="long",
        text=(
            "I want LocalFlow to feel fast enough that I can keep typing in my "
            "editor without noticing the transcription work in the background."
        ),
        seconds=10.0,
    ),
    BenchmarkPrompt(
        label="coding",
        text="Create a Python function named process audio that returns a pipeline result or none.",
        seconds=7.0,
    ),
    BenchmarkPrompt(
        label="correction",
        text="Actually make that next Friday at three thirty instead of Thursday morning.",
        seconds=6.0,
    ),
)


def _safe_filename(label: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip()).strip("_")
    return safe or "sample"


def record_benchmark_pack(
    output_dir: str | Path,
    *,
    prompts: Iterable[BenchmarkPrompt] = DEFAULT_PROMPTS,
    record: Record = record_wav,
    input_fn: Input = input,
    output: Output = print,
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    samples: list[dict[str, object]] = []
    for prompt in prompts:
        filename = f"{_safe_filename(prompt.label)}.wav"
        audio_path = output_path / filename
        output("")
        output(f"[{prompt.label}]")
        output(prompt.text)
        output(f"Recording duration: {prompt.seconds:g}s")
        input_fn("Press Enter when ready...")
        record(audio_path, seconds=prompt.seconds)
        samples.append(
            {
                "label": prompt.label,
                "audio": filename,
                "expected": prompt.text,
            }
        )
        output(f"Recorded {audio_path}")

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"samples": samples}, indent=2),
        encoding="utf-8",
    )
    output("")
    output(f"Wrote benchmark manifest to {manifest_path}")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record a LocalFlow dictation benchmark pack.")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/benchmark_pack"))
    parser.add_argument("--list", action="store_true", help="Print prompts without recording.")
    args = parser.parse_args(argv)

    if args.list:
        for prompt in DEFAULT_PROMPTS:
            print(f"{prompt.label} ({prompt.seconds:g}s): {prompt.text}")
        return 0

    record_benchmark_pack(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
