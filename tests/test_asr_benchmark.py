import json
import tempfile
import unittest
from pathlib import Path

from services.pipeline.models import AsrResult


class FakeClock:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0)


class FakeTranscriber:
    def __init__(self, text="hello world"):
        self.text = text
        self.warmups = []
        self.calls = []

    def warm_up(self, language=None):
        self.warmups.append(language)

    def transcribe(self, audio, language=None):
        self.calls.append((audio, language))
        return AsrResult(text=self.text, language=language, duration_ms=1)


class FakeResourceMonitor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def usage(self):
        from services.asr.benchmark import ResourceUsage

        return ResourceUsage(
            process_cpu_ms=500,
            process_cpu_percent=50.0,
            peak_memory_mb=123.4,
            avg_gpu_percent=20.0,
            peak_gpu_memory_mb=512.0,
        )


class AsrBenchmarkTests(unittest.TestCase):
    def test_current_config_uses_default_whisper_settings(self):
        from services.asr.benchmark import current_config

        config = current_config()

        self.assertEqual(config.label, "current")
        self.assertEqual(config.model_name, "small.en")
        self.assertEqual(config.compute_type, "int8")
        self.assertEqual(config.cpu_threads, 2)
        self.assertEqual(config.language, "en")

    def test_parse_config_spec_overrides_current_defaults(self):
        from services.asr.benchmark import parse_config_spec

        config = parse_config_spec(
            "label=threads8,model=large-v3-turbo,threads=8,compute=int8,language=auto"
        )

        self.assertEqual(config.label, "threads8")
        self.assertEqual(config.model_name, "large-v3-turbo")
        self.assertEqual(config.cpu_threads, 8)
        self.assertEqual(config.compute_type, "int8")
        self.assertIsNone(config.language)

    def test_smoothness_cpu_preset_compares_thread_caps_without_model_changes(self):
        from services.asr.benchmark import preset_configs

        configs = preset_configs("smoothness-cpu")

        self.assertEqual([config.cpu_threads for config in configs], [2, 4, 6, 8])
        self.assertEqual([config.label for config in configs], ["threads2", "threads4", "threads6", "threads8"])
        self.assertEqual({config.model_name for config in configs}, {"small.en"})
        self.assertEqual({config.compute_type for config in configs}, {"int8"})

    def test_unknown_benchmark_preset_is_rejected(self):
        from services.asr.benchmark import preset_configs

        with self.assertRaises(ValueError):
            preset_configs("mystery")

    def test_load_benchmark_manifest_resolves_audio_and_expected_text(self):
        from services.asr.benchmark import load_benchmark_manifest

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio_path = root / "short.wav"
            audio_path.write_bytes(b"RIFF")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "samples": [
                            {
                                "label": "short",
                                "audio": "short.wav",
                                "expected": "Hello world.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            samples = load_benchmark_manifest(manifest_path)

        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].label, "short")
        self.assertEqual(samples[0].audio_path, audio_path)
        self.assertEqual(samples[0].expected_text, "Hello world.")

    def test_load_benchmark_manifest_accepts_utf8_bom_from_powershell(self):
        from services.asr.benchmark import load_benchmark_manifest

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio_path = root / "short.wav"
            audio_path.write_bytes(b"RIFF")
            manifest_path = root / "manifest.json"
            manifest_path.write_bytes(
                b"\xef\xbb\xbf"
                + json.dumps(
                    {
                        "samples": [
                            {
                                "label": "short",
                                "audio": "short.wav",
                                "expected": "Hello world.",
                            }
                        ]
                    }
                ).encode("utf-8")
            )

            samples = load_benchmark_manifest(manifest_path)

        self.assertEqual(samples[0].label, "short")

    def test_word_error_rate_ignores_case_and_punctuation(self):
        from services.asr.benchmark import score_transcription

        score = score_transcription("Hello, world!", "hello world")

        self.assertEqual(score.word_error_rate, 0.0)
        self.assertEqual(score.word_accuracy, 1.0)

    def test_word_error_rate_counts_insertions(self):
        from services.asr.benchmark import score_transcription

        score = score_transcription("hello world", "hello brave world")

        self.assertEqual(score.word_error_rate, 0.5)
        self.assertEqual(score.word_accuracy, 0.5)

    def test_run_benchmark_calculates_elapsed_and_realtime_factor(self):
        from services.asr.benchmark import AsrBenchmarkConfig, run_benchmark

        fake_transcriber = FakeTranscriber()
        results = run_benchmark(
            audio=[0.1, 0.2],
            audio_seconds=2.0,
            audio_path=Path("sample.wav"),
            config=AsrBenchmarkConfig(label="fake", cpu_threads=4),
            runs=2,
            transcriber_factory=lambda config: fake_transcriber,
            clock=FakeClock([10.0, 11.0, 20.0, 22.0]),
            resource_monitor_factory=FakeResourceMonitor,
            sample_label="short",
            expected_text="hello brave world",
        )

        self.assertEqual([result.elapsed_ms for result in results], [1000, 2000])
        self.assertEqual([result.realtime_factor for result in results], [0.5, 1.0])
        self.assertEqual([result.text for result in results], ["hello world", "hello world"])
        self.assertEqual([result.sample_label for result in results], ["short", "short"])
        self.assertEqual([result.word_error_rate for result in results], [0.333, 0.333])
        self.assertEqual([result.word_accuracy for result in results], [0.667, 0.667])
        self.assertEqual([result.process_cpu_ms for result in results], [500, 500])
        self.assertEqual([result.process_cpu_percent for result in results], [50.0, 50.0])
        self.assertEqual([result.peak_memory_mb for result in results], [123.4, 123.4])
        self.assertEqual([result.avg_gpu_percent for result in results], [20.0, 20.0])
        self.assertEqual([result.peak_gpu_memory_mb for result in results], [512.0, 512.0])
        self.assertEqual(fake_transcriber.warmups, ["en"])

    def test_write_jsonl_writes_result_records(self):
        from services.asr.benchmark import AsrBenchmarkResult, write_jsonl

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "nested" / "results.jsonl"
            write_jsonl(
                output,
                [
                    AsrBenchmarkResult(
                        audio_path="sample.wav",
                        audio_seconds=2.0,
                        config_label="current",
                        backend="faster-whisper",
                        model_name="large-v3-turbo",
                        device="cpu",
                        compute_type="int8",
                        cpu_threads=12,
                        language="en",
                        run_index=1,
                        elapsed_ms=4000,
                        realtime_factor=2.0,
                        text="hello",
                        sample_label="short",
                        expected_text="hello",
                        word_error_rate=0.0,
                        word_accuracy=1.0,
                        process_cpu_ms=500,
                        process_cpu_percent=50.0,
                        peak_memory_mb=123.4,
                        avg_gpu_percent=20.0,
                        peak_gpu_memory_mb=512.0,
                    )
                ],
            )

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(records[0]["config_label"], "current")
        self.assertEqual(records[0]["elapsed_ms"], 4000)
        self.assertEqual(records[0]["sample_label"], "short")
        self.assertEqual(records[0]["expected_text"], "hello")
        self.assertEqual(records[0]["word_error_rate"], 0.0)
        self.assertEqual(records[0]["word_accuracy"], 1.0)
        self.assertEqual(records[0]["process_cpu_ms"], 500)
        self.assertEqual(records[0]["process_cpu_percent"], 50.0)
        self.assertEqual(records[0]["peak_memory_mb"], 123.4)
        self.assertEqual(records[0]["avg_gpu_percent"], 20.0)
        self.assertEqual(records[0]["peak_gpu_memory_mb"], 512.0)

    def test_format_summary_table_includes_config_and_speed(self):
        from services.asr.benchmark import AsrBenchmarkResult, format_summary_table

        table = format_summary_table(
            [
                AsrBenchmarkResult(
                    audio_path="sample.wav",
                    audio_seconds=2.0,
                    config_label="current",
                    backend="faster-whisper",
                    model_name="large-v3-turbo",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=12,
                    language="en",
                    run_index=1,
                    elapsed_ms=4000,
                    realtime_factor=2.0,
                    text="hello",
                    sample_label="short",
                    expected_text="hello",
                    word_error_rate=0.0,
                    word_accuracy=1.0,
                    process_cpu_ms=500,
                    process_cpu_percent=50.0,
                    peak_memory_mb=123.4,
                    avg_gpu_percent=20.0,
                    peak_gpu_memory_mb=512.0,
                )
            ]
        )

        self.assertIn("cpu%", table)
        self.assertIn("mem_mb", table)
        self.assertIn("gpu%", table)
        self.assertIn("sample", table)
        self.assertIn("wer", table)
        self.assertIn("acc", table)
        self.assertIn("current", table)
        self.assertIn("short", table)
        self.assertIn("4000", table)
        self.assertIn("2.00x", table)
        self.assertIn("0.000", table)
        self.assertIn("1.000", table)
        self.assertIn("50.0", table)
        self.assertIn("123.4", table)
        self.assertIn("20.0", table)

    def test_summarize_results_groups_runs_and_classifies_machine_impact(self):
        from services.asr.benchmark import AsrBenchmarkResult, summarize_results

        summaries = summarize_results(
            [
                AsrBenchmarkResult(
                    audio_path="sample.wav",
                    audio_seconds=2.0,
                    config_label="threads4",
                    backend="faster-whisper",
                    model_name="large-v3-turbo",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=4,
                    language="en",
                    run_index=1,
                    elapsed_ms=3000,
                    realtime_factor=1.5,
                    text="hello",
                    sample_label="short",
                    expected_text="hello",
                    word_error_rate=0.0,
                    word_accuracy=1.0,
                    process_cpu_ms=9000,
                    process_cpu_percent=300.0,
                    peak_memory_mb=900.0,
                ),
                AsrBenchmarkResult(
                    audio_path="sample.wav",
                    audio_seconds=2.0,
                    config_label="threads4",
                    backend="faster-whisper",
                    model_name="large-v3-turbo",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=4,
                    language="en",
                    run_index=2,
                    elapsed_ms=5000,
                    realtime_factor=2.5,
                    text="hello",
                    sample_label="long",
                    expected_text="hello there",
                    word_error_rate=0.5,
                    word_accuracy=0.5,
                    process_cpu_ms=15000,
                    process_cpu_percent=300.0,
                    peak_memory_mb=950.0,
                ),
                AsrBenchmarkResult(
                    audio_path="sample.wav",
                    audio_seconds=2.0,
                    config_label="threads12",
                    backend="faster-whisper",
                    model_name="large-v3-turbo",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=12,
                    language="en",
                    run_index=1,
                    elapsed_ms=2400,
                    realtime_factor=1.2,
                    text="hello",
                    sample_label="short",
                    expected_text="hello",
                    word_error_rate=0.0,
                    word_accuracy=1.0,
                    process_cpu_ms=26000,
                    process_cpu_percent=1080.0,
                    peak_memory_mb=1500.0,
                ),
            ]
        )

        self.assertEqual([summary.config_label for summary in summaries], ["threads4", "threads12"])
        self.assertEqual(summaries[0].runs, 2)
        self.assertEqual(summaries[0].avg_elapsed_ms, 4000)
        self.assertEqual(summaries[0].best_elapsed_ms, 3000)
        self.assertEqual(summaries[0].avg_realtime_factor, 2.0)
        self.assertEqual(summaries[0].avg_process_cpu_percent, 300.0)
        self.assertEqual(summaries[0].peak_memory_mb, 950.0)
        self.assertEqual(summaries[0].avg_word_error_rate, 0.25)
        self.assertEqual(summaries[0].avg_word_accuracy, 0.75)
        self.assertEqual(summaries[0].machine_impact, "low")
        self.assertEqual(summaries[1].machine_impact, "high")

    def test_format_decision_table_includes_smoothness_summary(self):
        from services.asr.benchmark import AsrBenchmarkResult, format_decision_table

        table = format_decision_table(
            [
                AsrBenchmarkResult(
                    audio_path="sample.wav",
                    audio_seconds=2.0,
                    config_label="threads4",
                    backend="faster-whisper",
                    model_name="large-v3-turbo",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=4,
                    language="en",
                    run_index=1,
                    elapsed_ms=3000,
                    realtime_factor=1.5,
                    text="hello",
                    sample_label="short",
                    expected_text="hello",
                    word_error_rate=0.0,
                    word_accuracy=1.0,
                    process_cpu_ms=9000,
                    process_cpu_percent=300.0,
                    peak_memory_mb=900.0,
                )
            ]
        )

        self.assertIn("impact", table)
        self.assertIn("avg_elapsed_ms", table)
        self.assertIn("avg_wer", table)
        self.assertIn("avg_acc", table)
        self.assertIn("threads4", table)
        self.assertIn("low", table)

    def test_benchmark_script_uses_project_virtualenv(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_asr.ps1"

        content = script.read_text(encoding="utf-8")

        self.assertIn(".venv", content)
        self.assertIn("Scripts\\python.exe", content)
        self.assertIn("services.asr.benchmark", content)
        self.assertIn("--preset", content)
        self.assertIn("--manifest", content)

    def test_benchmark_cmd_launches_powershell_script(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_asr.cmd"

        content = script.read_text(encoding="utf-8")

        self.assertIn("powershell.exe", content)
        self.assertIn("-ExecutionPolicy Bypass", content)
        self.assertIn("benchmark_asr.ps1", content)


if __name__ == "__main__":
    unittest.main()
