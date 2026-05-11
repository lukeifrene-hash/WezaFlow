import json
import tempfile
import unittest
from pathlib import Path


class FakeSession:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.cancelled = 0

    def start_recording(self, language=None):
        self.started += 1
        self.language = language

    def stop_and_process(self, language=None):
        self.stopped += 1
        self.language = language

    def cancel(self):
        self.cancelled += 1


class FakeBackend:
    def __init__(self):
        self.press = {}
        self.release = {}
        self.unhooked = []

    def on_press(self, key, callback):
        self.press[key] = callback
        return ("press", key)

    def on_release(self, key, callback):
        self.release[key] = callback
        return ("release", key)

    def unhook(self, hook):
        self.unhooked.append(hook)


class FakeKeyboardModule:
    KEY_DOWN = "down"
    KEY_UP = "up"

    def __init__(self):
        self.handler = None
        self.unhooked = []

    def hook(self, handler):
        self.handler = handler
        return "keyboard-hook"

    def unhook(self, hook):
        self.unhooked.append(hook)


class RuntimeRunnerTests(unittest.TestCase):
    def test_dependency_readiness_reports_required_packages(self):
        from services.runtime.runner import dependency_readiness

        results = dependency_readiness(
            find_spec=lambda name: object() if name in {"keyboard", "pyperclip"} else None,
            platform="win32",
        )

        by_name = {result.name: result for result in results}
        self.assertTrue(by_name["keyboard"].available)
        self.assertTrue(by_name["pyperclip"].available)
        self.assertFalse(by_name["sounddevice"].available)
        self.assertFalse(by_name["faster_whisper"].available)
        self.assertFalse(by_name["ollama"].required)

    def test_dependency_readiness_uses_pyautogui_for_macos_injection(self):
        from services.runtime.runner import dependency_readiness

        results = dependency_readiness(
            find_spec=lambda name: object() if name in {"pyautogui", "pyperclip"} else None,
            platform="darwin",
        )

        by_name = {result.name: result for result in results}
        self.assertTrue(by_name["pyautogui"].required)
        self.assertTrue(by_name["pyautogui"].available)
        self.assertFalse(by_name["keyboard"].required)

    def test_check_command_prints_dependency_readiness_without_starting_hotkeys(self):
        from services.runtime.runner import main

        lines = []

        exit_code = main(
            ["--check"],
            output=lines.append,
            find_spec=lambda name: object() if name == "keyboard" else None,
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(any("keyboard" in line for line in lines))
        self.assertTrue(any("sounddevice" in line for line in lines))

    def test_create_hotkey_controller_wires_session_callbacks(self):
        from services.runtime.runner import create_hotkey_controller

        backend = FakeBackend()
        session = FakeSession()
        controller = create_hotkey_controller(
            session,
            backend=backend,
            hotkey="ctrl+alt+space",
            cancel_key="esc",
            language="en",
        )

        controller.start()
        backend.press["ctrl+alt+space"]()
        backend.release["ctrl+alt+space"]()
        backend.press["ctrl+alt+space"]()
        backend.press["esc"]()
        controller.stop()

        self.assertEqual(session.started, 2)
        self.assertEqual(session.stopped, 1)
        self.assertEqual(session.cancelled, 1)
        self.assertEqual(session.language, "en")
        self.assertEqual(len(backend.unhooked), 3)

    def test_create_runtime_hotkey_controller_wires_dictation_and_command_callbacks(self):
        from services.runtime.runner import create_runtime_hotkey_controller

        backend = FakeBackend()

        class CommandSession(FakeSession):
            def __init__(self):
                super().__init__()
                self.command_started = 0

            def start_command_recording(self, language=None):
                self.command_started += 1
                self.language = language

        session = CommandSession()
        controller = create_runtime_hotkey_controller(
            session,
            backend=backend,
            hotkey="ctrl+alt+space",
            command_hotkey="ctrl+alt+e",
            cancel_key="esc",
            language="en",
        )

        controller.start()
        backend.press["ctrl+alt+space"]()
        backend.release["ctrl+alt+space"]()
        backend.press["ctrl+alt+e"]()
        backend.release["ctrl+alt+e"]()
        controller.stop()

        self.assertEqual(session.started, 1)
        self.assertEqual(session.stopped, 2)
        self.assertEqual(session.command_started, 1)
        self.assertEqual(len(backend.unhooked), 6)

    def test_correction_key_observer_forwards_keyboard_event_names(self):
        from services.runtime.runner import CorrectionKeyObserver

        class Watcher:
            def __init__(self):
                self.keys = []

            def observe_key(self, key):
                self.keys.append(key)

        keyboard = FakeKeyboardModule()
        watcher = Watcher()
        observer = CorrectionKeyObserver(watcher, keyboard_module=keyboard)

        observer.start()
        keyboard.handler(type("Event", (), {"name": "backspace"})())
        observer.stop()

        self.assertEqual(watcher.keys, ["backspace"])
        self.assertEqual(keyboard.unhooked, ["keyboard-hook"])

    def test_correction_key_observer_ignores_key_release_events(self):
        from services.runtime.runner import CorrectionKeyObserver

        class Watcher:
            def __init__(self):
                self.keys = []

            def observe_key(self, key):
                self.keys.append(key)

        keyboard = FakeKeyboardModule()
        watcher = Watcher()
        observer = CorrectionKeyObserver(watcher, keyboard_module=keyboard)

        observer.start()
        keyboard.handler(type("Event", (), {"name": "space", "event_type": "up"})())
        keyboard.handler(type("Event", (), {"name": "backspace", "event_type": "down"})())

        self.assertEqual(watcher.keys, ["backspace"])

    def test_language_arg_defaults_to_english_and_allows_auto_detection(self):
        from services.runtime.runner import normalize_language_arg

        self.assertEqual(normalize_language_arg("en"), "en")
        self.assertEqual(normalize_language_arg(""), None)
        self.assertEqual(normalize_language_arg("auto"), None)

    def test_warm_pipeline_in_background_calls_transcriber_warm_up(self):
        from services.runtime.runner import warm_pipeline_in_background

        class Logger:
            def __init__(self):
                self.events = []

            def log(self, event, **fields):
                self.events.append((event, fields))

        class Transcriber:
            def __init__(self):
                self.languages = []

            def warm_up(self, language=None):
                self.languages.append(language)

        class Pipeline:
            def __init__(self):
                self.transcriber = Transcriber()

        pipeline = Pipeline()
        logger = Logger()

        thread = warm_pipeline_in_background(pipeline, logger, language="en")
        thread.join(timeout=1)

        self.assertEqual(pipeline.transcriber.languages, ["en"])
        self.assertEqual(logger.events[-1][0], "pipeline_warmup_success")

    def test_warm_pipeline_in_background_logs_pipeline_role(self):
        from services.runtime.runner import warm_pipeline_in_background

        class Logger:
            def __init__(self):
                self.events = []

            def log(self, event, **fields):
                self.events.append((event, fields))

        class Transcriber:
            def warm_up(self, language=None):
                pass

        class Pipeline:
            transcriber = Transcriber()

        logger = Logger()
        thread = warm_pipeline_in_background(
            Pipeline(),
            logger,
            language="en",
            role="speculative",
        )
        thread.join(timeout=1)

        self.assertEqual(logger.events[0][1]["role"], "speculative")

    def test_create_runtime_session_enables_speculative_transcription(self):
        from services.runtime.runner import create_runtime_session

        class Pipeline:
            pass

        session = create_runtime_session(
            pipeline=Pipeline(),
            recorder_factory=lambda: object(),
            status=object(),
            asr_profile="balanced",
        )

        self.assertIsNotNone(session.speculative_factory)

    def test_create_runtime_session_defaults_to_low_impact_without_speculation(self):
        from services.runtime.runner import create_runtime_session

        class Pipeline:
            pass

        session = create_runtime_session(
            pipeline=Pipeline(),
            recorder_factory=lambda: object(),
            status=object(),
        )

        self.assertIsNone(session.speculative_factory)
        self.assertIsNone(session.speculative_pipeline)
        self.assertEqual(session.logger.fields["asr_profile"], "low-impact")

    def test_create_runtime_session_can_use_distinct_speculative_pipeline(self):
        from services.runtime.runner import create_runtime_session

        class Pipeline:
            pass

        class Logger:
            def log(self, event, **fields):
                pass

        final_pipeline = Pipeline()
        speculative_pipeline = Pipeline()
        session = create_runtime_session(
            pipeline=final_pipeline,
            speculative_pipeline=speculative_pipeline,
            recorder_factory=lambda: object(),
            status=object(),
        )

        speculative_session = session.speculative_factory(object(), final_pipeline, Logger())

        self.assertIs(session.pipeline, final_pipeline)
        self.assertIs(session.speculative_pipeline, speculative_pipeline)
        self.assertIs(speculative_session.pipeline, speculative_pipeline)

    def test_create_runtime_session_builds_profiled_main_and_speculative_pipelines(self):
        import services.runtime.runner as runner_module

        original_build_pipeline = runner_module.build_pipeline

        class Pipeline:
            pass

        calls = []

        def fake_build_pipeline(**kwargs):
            calls.append(kwargs)
            return Pipeline()

        runner_module.build_pipeline = fake_build_pipeline
        try:
            runner_module.create_runtime_session(
                root=Path(__file__).resolve().parents[1],
                recorder_factory=lambda: object(),
                status=object(),
                asr_profile="balanced",
            )
        finally:
            runner_module.build_pipeline = original_build_pipeline

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["whisper_model_name"], "small.en")
        self.assertEqual(calls[0]["whisper_compute_type"], "int8")
        self.assertEqual(calls[0]["whisper_cpu_threads"], 4)
        self.assertEqual(calls[1]["whisper_model_name"], "small.en")
        self.assertEqual(calls[1]["whisper_compute_type"], "int8")
        self.assertEqual(calls[1]["whisper_cpu_threads"], 2)

    def test_create_runtime_session_disables_speculation_for_low_impact_profile(self):
        import services.runtime.runner as runner_module

        original_build_pipeline = runner_module.build_pipeline

        class Pipeline:
            pass

        calls = []

        def fake_build_pipeline(**kwargs):
            calls.append(kwargs)
            return Pipeline()

        runner_module.build_pipeline = fake_build_pipeline
        try:
            session = runner_module.create_runtime_session(
                root=Path(__file__).resolve().parents[1],
                recorder_factory=lambda: object(),
                status=object(),
                asr_profile="low-impact",
            )
        finally:
            runner_module.build_pipeline = original_build_pipeline

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["whisper_model_name"], "small.en")
        self.assertEqual(calls[0]["whisper_cpu_threads"], 2)
        self.assertIsNone(session.speculative_factory)
        self.assertIsNone(session.speculative_pipeline)

    def test_create_runtime_session_builds_snappy_without_speculation(self):
        import services.runtime.runner as runner_module

        original_build_pipeline = runner_module.build_pipeline

        class Pipeline:
            pass

        calls = []

        def fake_build_pipeline(**kwargs):
            calls.append(kwargs)
            return Pipeline()

        runner_module.build_pipeline = fake_build_pipeline
        try:
            session = runner_module.create_runtime_session(
                root=Path(__file__).resolve().parents[1],
                recorder_factory=lambda: object(),
                status=object(),
                asr_profile="snappy",
            )
        finally:
            runner_module.build_pipeline = original_build_pipeline

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["whisper_model_name"], "small.en")
        self.assertEqual(calls[0]["whisper_compute_type"], "int8")
        self.assertEqual(calls[0]["whisper_cpu_threads"], 4)
        self.assertIsNone(session.speculative_factory)
        self.assertIsNone(session.speculative_pipeline)
        self.assertEqual(session.logger.fields["asr_profile"], "snappy")

    def test_create_runtime_session_passes_quiet_mode_to_pipeline_and_logs_it(self):
        import services.runtime.runner as runner_module

        original_build_pipeline = runner_module.build_pipeline

        class Pipeline:
            pass

        calls = []

        def fake_build_pipeline(**kwargs):
            calls.append(kwargs)
            return Pipeline()

        runner_module.build_pipeline = fake_build_pipeline
        try:
            session = runner_module.create_runtime_session(
                root=Path(__file__).resolve().parents[1],
                recorder_factory=lambda: object(),
                status=object(),
                quiet_mode=True,
            )
        finally:
            runner_module.build_pipeline = original_build_pipeline

        self.assertTrue(calls[0]["quiet_mode"])
        self.assertTrue(session.logger.fields["quiet_mode"])

    def test_create_runtime_session_builds_quality_fallback_only_when_enabled(self):
        import services.runtime.runner as runner_module

        original_build_pipeline = runner_module.build_pipeline

        class Pipeline:
            pass

        calls = []

        def fake_build_pipeline(**kwargs):
            calls.append(kwargs)
            return Pipeline()

        runner_module.build_pipeline = fake_build_pipeline
        try:
            session = runner_module.create_runtime_session(
                root=Path(__file__).resolve().parents[1],
                recorder_factory=lambda: object(),
                status=object(),
                quality_fallback=True,
            )
        finally:
            runner_module.build_pipeline = original_build_pipeline

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["whisper_model_name"], "small.en")
        self.assertEqual(calls[0]["whisper_cpu_threads"], 2)
        self.assertEqual(calls[1]["whisper_model_name"], "distil-large-v3")
        self.assertEqual(calls[1]["whisper_cpu_threads"], 6)
        self.assertTrue(session.logger.fields["quality_fallback_enabled"])

    def test_summarize_runtime_log_reports_recent_diagnostics(self):
        from services.runtime.runner import summarize_runtime_log

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "runtime.jsonl"
            records = [
                {
                    "event": "recording_started",
                    "asr_profile": "low-impact",
                    "asr_model": "small.en",
                    "asr_cpu_threads": 2,
                    "quiet_mode": True,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 120,
                    "timings_ms": {"asr_ms": 80, "total_ms": 120},
                    "asr_profile": "low-impact",
                    "asr_model": "small.en",
                    "asr_cpu_threads": 2,
                    "quiet_mode": True,
                },
                {"event": "dictation_no_speech"},
                {"event": "dictation_error", "error": "boom"},
            ]
            log_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )

            lines = summarize_runtime_log(log_path)

        self.assertIn("profile=low-impact", lines[0])
        self.assertIn("model=small.en", lines[0])
        self.assertIn("threads=2", lines[0])
        self.assertIn("quiet=True", lines[0])
        self.assertTrue(any("success=1" in line for line in lines))
        self.assertTrue(any("no_speech=1" in line for line in lines))
        self.assertTrue(any("errors=1" in line for line in lines))
        self.assertTrue(any("avg_total_ms=120" in line for line in lines))

    def test_summarize_runtime_log_groups_live_latency_by_profile(self):
        from services.runtime.runner import summarize_runtime_log

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "runtime.jsonl"
            records = [
                {
                    "event": "dictation_success",
                    "duration_ms": 900,
                    "timings_ms": {"asr_ms": 700, "total_ms": 900},
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 3000,
                    "recording_ms": 1200,
                    "timings_ms": {"asr_ms": 2800, "total_ms": 3000},
                    "asr_profile": "low-impact",
                    "asr_model": "small.en",
                    "asr_cpu_threads": 2,
                    "quiet_mode": False,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 2200,
                    "recording_ms": 1300,
                    "timings_ms": {"asr_ms": 2000, "total_ms": 2200},
                    "asr_profile": "snappy",
                    "asr_model": "small.en",
                    "asr_cpu_threads": 4,
                    "quiet_mode": False,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 1800,
                    "recording_ms": 900,
                    "timings_ms": {"asr_ms": 1600, "total_ms": 1800},
                    "asr_profile": "snappy",
                    "asr_model": "small.en",
                    "asr_cpu_threads": 4,
                    "quiet_mode": False,
                },
            ]
            log_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )

            lines = summarize_runtime_log(log_path)

        self.assertTrue(
            any(
                "Live profile latency: profile=snappy model=small.en threads=4 runs=2 "
                "avg_total_ms=2000 avg_asr_ms=1800 best_asr_ms=1600 avg_recording_ms=1100"
                in line
                for line in lines
            )
        )
        self.assertTrue(
            any(
                "Live profile latency: profile=low-impact model=small.en threads=2 runs=1 "
                "avg_total_ms=3000 avg_asr_ms=2800 best_asr_ms=2800 avg_recording_ms=1200"
                in line
                for line in lines
            )
        )

    def test_summarize_runtime_log_skips_malformed_live_latency_rows(self):
        from services.runtime.runner import summarize_runtime_log

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "runtime.jsonl"
            records = [
                {
                    "event": "dictation_success",
                    "duration_ms": 900,
                    "timings_ms": {"asr_ms": 700, "total_ms": 900},
                },
                {
                    "event": "command_success",
                    "duration_ms": 1000,
                    "recording_ms": 400,
                    "timings_ms": {"asr_ms": 800, "total_ms": 1000},
                    "asr_profile": "command",
                    "asr_model": "small.en",
                    "asr_cpu_threads": 3,
                },
                {
                    "event": "dictation_success",
                    "timings_ms": {"asr_ms": 10},
                    "asr_profile": "malformed",
                    "asr_model": "missing-duration",
                    "asr_cpu_threads": 1,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 10,
                    "asr_profile": "malformed",
                    "asr_model": "missing-timings",
                    "asr_cpu_threads": 1,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 10,
                    "timings_ms": "damaged",
                    "asr_profile": "malformed",
                    "asr_model": "damaged-timings",
                    "asr_cpu_threads": 1,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 10,
                    "timings_ms": {"asr_ms": "slow"},
                    "asr_profile": "malformed",
                    "asr_model": "nonnumeric-asr",
                    "asr_cpu_threads": 1,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": True,
                    "timings_ms": {"asr_ms": 5},
                    "asr_profile": "malformed",
                    "asr_model": "boolean-duration",
                    "asr_cpu_threads": 1,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 5,
                    "timings_ms": {"asr_ms": False},
                    "asr_profile": "malformed",
                    "asr_model": "boolean-asr",
                    "asr_cpu_threads": 1,
                },
            ]
            log_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )

            lines = summarize_runtime_log(log_path)

        live_lines = [line for line in lines if line.startswith("Live profile latency:")]
        self.assertTrue(
            any(
                "Live profile latency: profile=unknown model=unknown threads=unknown runs=1 "
                "avg_total_ms=900 avg_asr_ms=700 best_asr_ms=700 avg_recording_ms=n/a"
                in line
                for line in live_lines
            )
        )
        self.assertTrue(
            any(
                "Live profile latency: profile=command model=small.en threads=3 runs=1 "
                "avg_total_ms=1000 avg_asr_ms=800 best_asr_ms=800 avg_recording_ms=400"
                in line
                for line in live_lines
            )
        )
        self.assertFalse(any("profile=malformed" in line for line in live_lines))

    def test_diagnostics_command_prints_log_summary_without_starting_hotkeys(self):
        from services.runtime.runner import main

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "runtime.jsonl"
            log_path.write_text(
                json.dumps({"event": "dictation_no_speech"}) + "\n",
                encoding="utf-8",
            )
            lines = []

            exit_code = main(["--diagnostics", "--log", str(log_path)], output=lines.append)

        self.assertEqual(exit_code, 0)
        self.assertTrue(any("no_speech=1" in line for line in lines))

    def test_run_dictation_script_invokes_runtime_runner(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_dictation.ps1"

        content = script.read_text(encoding="utf-8")

        self.assertIn("services.runtime.runner", content)
        self.assertIn(".venv", content)
        self.assertIn("Scripts\\python.exe", content)
        self.assertIn("--hotkey", content)
        self.assertIn("ctrl+alt+space", content)
        self.assertIn('[string]$Language = "en"', content)
        self.assertIn('[string]$Profile = "low-impact"', content)
        self.assertIn("--profile", content)
        self.assertIn('[string]$CommandHotkey = "ctrl+alt+e"', content)
        self.assertIn("--command-hotkey", content)
        self.assertIn("[switch]$Quiet", content)
        self.assertIn("--quiet", content)
        self.assertIn("[switch]$Diagnostics", content)
        self.assertIn("--diagnostics", content)
        self.assertIn("[switch]$QualityFallback", content)
        self.assertIn("--quality-fallback", content)

    def test_run_dictation_cmd_launches_powershell_script(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_dictation.cmd"

        content = script.read_text(encoding="utf-8")

        self.assertIn("powershell.exe", content)
        self.assertIn("-ExecutionPolicy Bypass", content)
        self.assertIn("-File", content)
        self.assertIn("run_dictation.ps1", content)


if __name__ == "__main__":
    unittest.main()
