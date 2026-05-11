from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import threading
import time
import wave
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable

from services.asr.transcriber import Transcriber
from services.config.settings import load_default_settings


Clock = Callable[[], float]
TranscriberFactory = Callable[["AsrBenchmarkConfig"], Any]
ResourceMonitorFactory = Callable[[], Any]
_WORD_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class AsrBenchmarkConfig:
    label: str = "current"
    backend: str = "faster-whisper"
    model_name: str = "small.en"
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = 2
    language: str | None = "en"


@dataclass(frozen=True)
class BenchmarkSample:
    label: str
    audio_path: Path
    expected_text: str | None = None


@dataclass(frozen=True)
class TranscriptScore:
    word_error_rate: float
    word_accuracy: float


@dataclass(frozen=True)
class GpuSample:
    utilization_percent: float | None = None
    memory_mb: float | None = None


@dataclass(frozen=True)
class ResourceUsage:
    process_cpu_ms: int = 0
    process_cpu_percent: float = 0.0
    peak_memory_mb: float | None = None
    avg_gpu_percent: float | None = None
    peak_gpu_memory_mb: float | None = None


@dataclass(frozen=True)
class AsrBenchmarkResult:
    audio_path: str
    audio_seconds: float
    config_label: str
    backend: str
    model_name: str
    device: str
    compute_type: str
    cpu_threads: int
    language: str | None
    run_index: int
    elapsed_ms: int
    realtime_factor: float
    text: str
    sample_label: str = ""
    expected_text: str | None = None
    word_error_rate: float | None = None
    word_accuracy: float | None = None
    process_cpu_ms: int = 0
    process_cpu_percent: float = 0.0
    peak_memory_mb: float | None = None
    avg_gpu_percent: float | None = None
    peak_gpu_memory_mb: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AsrBenchmarkSummary:
    config_label: str
    model_name: str
    device: str
    compute_type: str
    cpu_threads: int
    runs: int
    avg_elapsed_ms: int
    best_elapsed_ms: int
    worst_elapsed_ms: int
    avg_realtime_factor: float
    avg_process_cpu_percent: float
    avg_process_cpu_ms: int
    peak_memory_mb: float | None
    avg_gpu_percent: float | None
    peak_gpu_memory_mb: float | None
    avg_word_error_rate: float | None
    avg_word_accuracy: float | None
    machine_impact: str


def _round_optional(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _format_optional_number(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}"


def _format_optional_score(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}"


def _parse_metric_value(value: str) -> float | None:
    cleaned = "".join(char for char in value if char.isdigit() or char in ".-")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def transcript_words(text: str) -> list[str]:
    return _WORD_PATTERN.findall(text.lower().replace("_", " "))


def _word_edit_distance(expected_words: list[str], actual_words: list[str]) -> int:
    previous = list(range(len(actual_words) + 1))
    for expected_index, expected_word in enumerate(expected_words, start=1):
        current = [expected_index]
        for actual_index, actual_word in enumerate(actual_words, start=1):
            cost = 0 if expected_word == actual_word else 1
            current.append(
                min(
                    previous[actual_index] + 1,
                    current[actual_index - 1] + 1,
                    previous[actual_index - 1] + cost,
                )
            )
        previous = current
    return previous[-1]


def score_transcription(expected_text: str, actual_text: str) -> TranscriptScore:
    expected_words = transcript_words(expected_text)
    actual_words = transcript_words(actual_text)
    if not expected_words:
        word_error_rate = 0.0 if not actual_words else 1.0
    else:
        word_error_rate = _word_edit_distance(expected_words, actual_words) / len(expected_words)
    word_error_rate = round(word_error_rate, 3)
    return TranscriptScore(
        word_error_rate=word_error_rate,
        word_accuracy=round(max(0.0, 1.0 - word_error_rate), 3),
    )


def read_process_memory_mb() -> float | None:
    try:
        import psutil  # type: ignore[import-not-found]
    except Exception:
        return None

    try:
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return None


class NvidiaSmiGpuProbe:
    def __init__(self, executable: str = "nvidia-smi") -> None:
        self.executable = executable

    def sample(self) -> GpuSample | None:
        try:
            completed = subprocess.run(
                [
                    self.executable,
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=1.0,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if completed.returncode != 0:
            return None

        utilization_values: list[float] = []
        memory_values: list[float] = []
        for line in completed.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 2:
                continue
            utilization = _parse_metric_value(parts[0])
            memory = _parse_metric_value(parts[1])
            if utilization is not None:
                utilization_values.append(utilization)
            if memory is not None:
                memory_values.append(memory)

        if not utilization_values and not memory_values:
            return None

        average_utilization = (
            sum(utilization_values) / len(utilization_values) if utilization_values else None
        )
        total_memory = sum(memory_values) if memory_values else None
        return GpuSample(utilization_percent=average_utilization, memory_mb=total_memory)


def default_gpu_probe() -> NvidiaSmiGpuProbe | None:
    if shutil.which("nvidia-smi") is None:
        return None
    return NvidiaSmiGpuProbe()


class ResourceMonitor:
    def __init__(
        self,
        *,
        clock: Clock = time.perf_counter,
        process_clock: Clock = time.process_time,
        memory_reader: Callable[[], float | None] = read_process_memory_mb,
        gpu_probe: Any | None = None,
        sample_interval_s: float = 0.25,
    ) -> None:
        self.clock = clock
        self.process_clock = process_clock
        self.memory_reader = memory_reader
        self.gpu_probe = default_gpu_probe() if gpu_probe is None else gpu_probe
        self.sample_interval_s = sample_interval_s
        self._lock = threading.Lock()
        self._memory_samples: list[float] = []
        self._gpu_utilization_samples: list[float] = []
        self._gpu_memory_samples: list[float] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._start_wall = 0.0
        self._end_wall = 0.0
        self._start_cpu = 0.0
        self._end_cpu = 0.0

    def __enter__(self) -> "ResourceMonitor":
        self._start_wall = self.clock()
        self._start_cpu = self.process_clock()
        self._running = True
        self._sample_once()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=self.sample_interval_s + 0.2)
        self._sample_once()
        self._end_wall = self.clock()
        self._end_cpu = self.process_clock()

    def usage(self) -> ResourceUsage:
        end_wall = self._end_wall or self.clock()
        end_cpu = self._end_cpu or self.process_clock()
        wall_seconds = max(end_wall - self._start_wall, 0.0)
        process_cpu_seconds = max(end_cpu - self._start_cpu, 0.0)
        process_cpu_percent = (
            (process_cpu_seconds / wall_seconds) * 100 if wall_seconds else 0.0
        )

        with self._lock:
            peak_memory_mb = max(self._memory_samples) if self._memory_samples else None
            average_gpu_percent = (
                sum(self._gpu_utilization_samples) / len(self._gpu_utilization_samples)
                if self._gpu_utilization_samples
                else None
            )
            peak_gpu_memory_mb = (
                max(self._gpu_memory_samples) if self._gpu_memory_samples else None
            )

        return ResourceUsage(
            process_cpu_ms=int(process_cpu_seconds * 1000),
            process_cpu_percent=round(process_cpu_percent, 1),
            peak_memory_mb=_round_optional(peak_memory_mb),
            avg_gpu_percent=_round_optional(average_gpu_percent),
            peak_gpu_memory_mb=_round_optional(peak_gpu_memory_mb),
        )

    def _sample_loop(self) -> None:
        while self._running:
            time.sleep(self.sample_interval_s)
            if self._running:
                self._sample_once()

    def _sample_once(self) -> None:
        memory_mb = self.memory_reader()
        gpu_sample = self.gpu_probe.sample() if self.gpu_probe is not None else None

        with self._lock:
            if memory_mb is not None:
                self._memory_samples.append(memory_mb)
            if gpu_sample is not None:
                if gpu_sample.utilization_percent is not None:
                    self._gpu_utilization_samples.append(gpu_sample.utilization_percent)
                if gpu_sample.memory_mb is not None:
                    self._gpu_memory_samples.append(gpu_sample.memory_mb)


def current_config() -> AsrBenchmarkConfig:
    settings = load_default_settings()
    models = settings["models"]
    return AsrBenchmarkConfig(
        label="current",
        model_name=models["whisper"],
        device="cpu",
        compute_type=models["whisper_compute_type"],
        cpu_threads=models["whisper_cpu_threads"],
        language="en",
    )


def preset_configs(name: str) -> list[AsrBenchmarkConfig]:
    normalized = name.strip().lower()
    if normalized != "smoothness-cpu":
        raise ValueError(
            f"Unsupported ASR benchmark preset: {name}. Available presets: smoothness-cpu"
        )

    base = current_config()
    thread_caps = [base.cpu_threads, 4, 6, 8]
    configs: list[AsrBenchmarkConfig] = []
    seen_thread_caps: set[int] = set()
    for thread_cap in thread_caps:
        if thread_cap in seen_thread_caps:
            continue
        seen_thread_caps.add(thread_cap)
        configs.append(replace(base, label=f"threads{thread_cap}", cpu_threads=thread_cap))
    return configs


def load_benchmark_manifest(path: str | Path) -> list[BenchmarkSample]:
    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8-sig") as handle:
        manifest = json.load(handle)

    raw_samples = manifest.get("samples", manifest) if isinstance(manifest, dict) else manifest
    if not isinstance(raw_samples, list):
        raise ValueError("Benchmark manifest must contain a list or a 'samples' list")

    samples: list[BenchmarkSample] = []
    for index, raw_sample in enumerate(raw_samples, start=1):
        if not isinstance(raw_sample, dict):
            raise ValueError(f"Benchmark sample #{index} must be an object")
        audio_value = raw_sample.get("audio") or raw_sample.get("audio_path")
        if not audio_value:
            raise ValueError(f"Benchmark sample #{index} is missing an audio path")
        audio_path = Path(str(audio_value))
        if not audio_path.is_absolute():
            audio_path = manifest_path.parent / audio_path
        label = str(raw_sample.get("label") or audio_path.stem)
        expected_text = raw_sample.get("expected", raw_sample.get("expected_text"))
        samples.append(
            BenchmarkSample(
                label=label,
                audio_path=audio_path,
                expected_text=str(expected_text) if expected_text is not None else None,
            )
        )
    return samples


def parse_config_spec(spec: str) -> AsrBenchmarkConfig:
    if spec == "current":
        return current_config()

    base = current_config()
    values: dict[str, str] = {}
    for item in spec.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError(f"Invalid ASR benchmark config item: {item!r}")
        key, value = item.split("=", 1)
        values[key.strip().lower()] = value.strip()

    label = values.get("label", base.label)
    model_name = values.get("model", values.get("model_name", base.model_name))
    backend = values.get("backend", base.backend)
    if backend != "faster-whisper":
        raise ValueError(f"Unsupported ASR benchmark backend: {backend}")
    language = values.get("language", base.language)
    if language is not None and language.lower() in {"auto", "none", ""}:
        language = None

    return AsrBenchmarkConfig(
        label=label,
        backend=backend,
        model_name=model_name,
        device=values.get("device", base.device),
        compute_type=values.get("compute", values.get("compute_type", base.compute_type)),
        cpu_threads=int(values.get("threads", values.get("cpu_threads", base.cpu_threads))),
        language=language,
    )


def load_wav_samples(path: str | Path) -> tuple[list[float], float]:
    audio_path = Path(path)
    with wave.open(str(audio_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        frames = wav.readframes(frame_count)

    if sample_width != 2:
        raise RuntimeError("Only 16-bit PCM WAV audio is supported by the ASR benchmark")

    samples: list[float] = []
    frame_width = sample_width * channels
    for offset in range(0, len(frames), frame_width):
        channel_total = 0
        for channel in range(channels):
            sample_offset = offset + channel * sample_width
            channel_total += int.from_bytes(
                frames[sample_offset : sample_offset + sample_width],
                "little",
                signed=True,
            )
        samples.append((channel_total / channels) / 32768.0)
    return samples, frame_count / sample_rate


def create_transcriber(config: AsrBenchmarkConfig) -> Transcriber:
    if config.backend != "faster-whisper":
        raise ValueError(f"Unsupported ASR benchmark backend: {config.backend}")
    return Transcriber(
        model_name=config.model_name,
        device=config.device,
        compute_type=config.compute_type,
        cpu_threads=config.cpu_threads,
    )


def run_benchmark(
    *,
    audio: list[float],
    audio_seconds: float,
    audio_path: Path,
    config: AsrBenchmarkConfig,
    runs: int,
    transcriber_factory: TranscriberFactory = create_transcriber,
    clock: Clock = time.perf_counter,
    resource_monitor_factory: ResourceMonitorFactory = ResourceMonitor,
    warmup: bool = True,
    sample_label: str = "",
    expected_text: str | None = None,
) -> list[AsrBenchmarkResult]:
    transcriber = transcriber_factory(config)
    if warmup:
        transcriber.warm_up(language=config.language)

    results: list[AsrBenchmarkResult] = []
    for run_index in range(1, runs + 1):
        with resource_monitor_factory() as resource_monitor:
            started = clock()
            asr_result = transcriber.transcribe(audio, language=config.language)
            elapsed_ms = int((clock() - started) * 1000)
        resource_usage = resource_monitor.usage()
        transcript_score = (
            score_transcription(expected_text, asr_result.text)
            if expected_text is not None
            else None
        )
        realtime_factor = round((elapsed_ms / 1000) / audio_seconds, 3) if audio_seconds else 0.0
        results.append(
            AsrBenchmarkResult(
                audio_path=str(audio_path),
                audio_seconds=round(audio_seconds, 3),
                config_label=config.label,
                backend=config.backend,
                model_name=config.model_name,
                device=config.device,
                compute_type=config.compute_type,
                cpu_threads=config.cpu_threads,
                language=config.language,
                run_index=run_index,
                elapsed_ms=elapsed_ms,
                realtime_factor=realtime_factor,
                text=asr_result.text,
                sample_label=sample_label or audio_path.stem,
                expected_text=expected_text,
                word_error_rate=(
                    transcript_score.word_error_rate if transcript_score is not None else None
                ),
                word_accuracy=(
                    transcript_score.word_accuracy if transcript_score is not None else None
                ),
                process_cpu_ms=resource_usage.process_cpu_ms,
                process_cpu_percent=resource_usage.process_cpu_percent,
                peak_memory_mb=resource_usage.peak_memory_mb,
                avg_gpu_percent=resource_usage.avg_gpu_percent,
                peak_gpu_memory_mb=resource_usage.peak_gpu_memory_mb,
            )
        )
    return results


def write_jsonl(path: str | Path, results: list[AsrBenchmarkResult]) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for result in results:
            json.dump(result.to_dict(), handle, ensure_ascii=False)
            handle.write("\n")
    return output_path


def format_summary_table(results: list[AsrBenchmarkResult]) -> str:
    if not results:
        return "No benchmark results."

    lines = [
        "| config | sample | run | audio_s | elapsed_ms | rtf | wer | acc | cpu% | cpu_ms | mem_mb | gpu% | gpu_mem_mb | chars | text |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        text = result.text.replace("|", "\\|")
        if len(text) > 80:
            text = f"{text[:77]}..."
        lines.append(
            "| "
            f"{result.config_label} | "
            f"{result.sample_label or Path(result.audio_path).stem} | "
            f"{result.run_index} | "
            f"{result.audio_seconds:.3f} | "
            f"{result.elapsed_ms} | "
            f"{result.realtime_factor:.2f}x | "
            f"{_format_optional_score(result.word_error_rate)} | "
            f"{_format_optional_score(result.word_accuracy)} | "
            f"{result.process_cpu_percent:.1f} | "
            f"{result.process_cpu_ms} | "
            f"{_format_optional_number(result.peak_memory_mb)} | "
            f"{_format_optional_number(result.avg_gpu_percent)} | "
            f"{_format_optional_number(result.peak_gpu_memory_mb)} | "
            f"{len(result.text)} | "
            f"{text} |"
        )
    return "\n".join(lines)


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _average_optional(values: list[float | None]) -> float | None:
    present_values = [value for value in values if value is not None]
    if not present_values:
        return None
    return sum(present_values) / len(present_values)


def _max_optional(values: list[float | None]) -> float | None:
    present_values = [value for value in values if value is not None]
    if not present_values:
        return None
    return max(present_values)


def classify_machine_impact(avg_cpu_percent: float, peak_memory_mb: float | None) -> str:
    memory_mb = peak_memory_mb or 0.0
    if avg_cpu_percent <= 300 and memory_mb <= 1024:
        return "low"
    if avg_cpu_percent <= 700 and memory_mb <= 2048:
        return "medium"
    return "high"


def summarize_results(results: list[AsrBenchmarkResult]) -> list[AsrBenchmarkSummary]:
    grouped: dict[str, list[AsrBenchmarkResult]] = {}
    for result in results:
        grouped.setdefault(result.config_label, []).append(result)

    summaries: list[AsrBenchmarkSummary] = []
    for config_label, config_results in grouped.items():
        first = config_results[0]
        avg_cpu_percent = round(
            _average([result.process_cpu_percent for result in config_results]),
            1,
        )
        peak_memory_mb = _round_optional(
            _max_optional([result.peak_memory_mb for result in config_results])
        )
        summaries.append(
            AsrBenchmarkSummary(
                config_label=config_label,
                model_name=first.model_name,
                device=first.device,
                compute_type=first.compute_type,
                cpu_threads=first.cpu_threads,
                runs=len(config_results),
                avg_elapsed_ms=int(
                    round(_average([result.elapsed_ms for result in config_results]))
                ),
                best_elapsed_ms=min(result.elapsed_ms for result in config_results),
                worst_elapsed_ms=max(result.elapsed_ms for result in config_results),
                avg_realtime_factor=round(
                    _average([result.realtime_factor for result in config_results]),
                    3,
                ),
                avg_process_cpu_percent=avg_cpu_percent,
                avg_process_cpu_ms=int(
                    round(_average([result.process_cpu_ms for result in config_results]))
                ),
                peak_memory_mb=peak_memory_mb,
                avg_gpu_percent=_round_optional(
                    _average_optional([result.avg_gpu_percent for result in config_results])
                ),
                peak_gpu_memory_mb=_round_optional(
                    _max_optional([result.peak_gpu_memory_mb for result in config_results])
                ),
                avg_word_error_rate=_round_optional(
                    _average_optional([result.word_error_rate for result in config_results]),
                    digits=3,
                ),
                avg_word_accuracy=_round_optional(
                    _average_optional([result.word_accuracy for result in config_results]),
                    digits=3,
                ),
                machine_impact=classify_machine_impact(avg_cpu_percent, peak_memory_mb),
            )
        )
    return summaries


def format_decision_table(results: list[AsrBenchmarkResult]) -> str:
    summaries = summarize_results(results)
    if not summaries:
        return "No benchmark results."

    impact_rank = {"low": 0, "medium": 1, "high": 2}
    summaries = sorted(
        summaries,
        key=lambda summary: (
            impact_rank.get(summary.machine_impact, 99),
            summary.avg_elapsed_ms,
        ),
    )

    lines = [
        "| config | impact | runs | threads | avg_elapsed_ms | best_ms | avg_rtf | avg_wer | avg_acc | avg_cpu% | avg_cpu_ms | peak_mem_mb | avg_gpu% | peak_gpu_mem_mb |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in summaries:
        lines.append(
            "| "
            f"{summary.config_label} | "
            f"{summary.machine_impact} | "
            f"{summary.runs} | "
            f"{summary.cpu_threads} | "
            f"{summary.avg_elapsed_ms} | "
            f"{summary.best_elapsed_ms} | "
            f"{summary.avg_realtime_factor:.2f}x | "
            f"{_format_optional_score(summary.avg_word_error_rate)} | "
            f"{_format_optional_score(summary.avg_word_accuracy)} | "
            f"{summary.avg_process_cpu_percent:.1f} | "
            f"{summary.avg_process_cpu_ms} | "
            f"{_format_optional_number(summary.peak_memory_mb)} | "
            f"{_format_optional_number(summary.avg_gpu_percent)} | "
            f"{_format_optional_number(summary.peak_gpu_memory_mb)} |"
        )
    return "\n".join(lines)


def benchmark_audio_files(
    *,
    audio_paths: list[Path],
    configs: list[AsrBenchmarkConfig],
    runs: int,
    warmup: bool = True,
) -> list[AsrBenchmarkResult]:
    samples = [
        BenchmarkSample(label=audio_path.stem, audio_path=audio_path)
        for audio_path in audio_paths
    ]
    return benchmark_samples(samples=samples, configs=configs, runs=runs, warmup=warmup)


def benchmark_samples(
    *,
    samples: list[BenchmarkSample],
    configs: list[AsrBenchmarkConfig],
    runs: int,
    warmup: bool = True,
) -> list[AsrBenchmarkResult]:
    all_results: list[AsrBenchmarkResult] = []
    for sample in samples:
        audio, audio_seconds = load_wav_samples(sample.audio_path)
        for config in configs:
            all_results.extend(
                run_benchmark(
                    audio=audio,
                    audio_seconds=audio_seconds,
                    audio_path=sample.audio_path,
                    config=config,
                    runs=runs,
                    warmup=warmup,
                    sample_label=sample.label,
                    expected_text=sample.expected_text,
                )
            )
    return all_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark LocalFlow ASR configurations.")
    parser.add_argument("--audio", type=Path, action="append", default=None)
    parser.add_argument("--manifest", type=Path, action="append", default=None)
    parser.add_argument("--config", action="append", default=None)
    parser.add_argument("--preset", action="append", default=None)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/benchmarks/asr_benchmark.jsonl"),
    )
    parser.add_argument("--no-warmup", action="store_true")
    args = parser.parse_args(argv)

    samples: list[BenchmarkSample] = []
    for manifest_path in args.manifest or []:
        samples.extend(load_benchmark_manifest(manifest_path))
    for audio_path in args.audio or []:
        samples.append(BenchmarkSample(label=audio_path.stem, audio_path=audio_path))
    if not samples:
        samples = [BenchmarkSample(label="test", audio_path=Path("artifacts/test.wav"))]

    configs: list[AsrBenchmarkConfig] = []
    for preset in args.preset or []:
        configs.extend(preset_configs(preset))
    for spec in args.config or []:
        configs.append(parse_config_spec(spec))
    if not configs:
        configs = [current_config()]
    results = benchmark_samples(
        samples=samples,
        configs=configs,
        runs=args.runs,
        warmup=not args.no_warmup,
    )
    write_jsonl(args.output, results)
    print(format_summary_table(results))
    print()
    print("Smoothness summary")
    print(format_decision_table(results))
    print(f"Wrote {len(results)} result(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
