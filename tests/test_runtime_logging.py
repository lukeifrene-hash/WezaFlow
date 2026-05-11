import json
import sys
import tempfile
import unittest
from pathlib import Path


class JsonlLoggerTests(unittest.TestCase):
    def test_log_creates_parent_dirs_and_appends_json_lines(self):
        from services.runtime.logging import JsonlLogger

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "nested" / "runtime.jsonl"
            logger = JsonlLogger(log_path)

            logger.log("recording_started", mode="dictation")
            logger.log("success", characters=12)

            lines = log_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        second = json.loads(lines[1])
        self.assertEqual(first["event"], "recording_started")
        self.assertEqual(first["mode"], "dictation")
        self.assertIn("timestamp", first)
        self.assertEqual(second["event"], "success")
        self.assertEqual(second["characters"], 12)


class RuntimeStatusTests(unittest.TestCase):
    def test_format_user_error_maps_missing_optional_dependencies(self):
        from services.runtime.status import format_user_error

        self.assertEqual(
            format_user_error(ModuleNotFoundError(name="sounddevice")),
            "Audio dependency missing: install sounddevice, then rerun setup.",
        )
        self.assertEqual(
            format_user_error(ModuleNotFoundError(name="keyboard")),
            "Hotkey dependency missing: install keyboard and run from an elevated terminal if needed.",
        )
        self.assertEqual(
            format_user_error(ModuleNotFoundError(name="faster_whisper")),
            "Whisper dependency missing: install faster-whisper or enable the ASR environment.",
        )

    def test_format_user_error_maps_runtime_failures(self):
        from services.runtime.status import format_user_error

        cases = {
            "Connection refused while calling Ollama": "Ollama is not reachable: start Ollama and confirm the local model is available.",
            "No speech detected in recording": "No speech detected: try again closer to the microphone.",
            "clipboard injection failed": "Text injection failed: focus the target app and try again.",
        }

        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(format_user_error(RuntimeError(message)), expected)

    def test_console_status_reporter_writes_injected_output(self):
        from services.runtime.status import ConsoleStatusReporter

        messages = []
        reporter = ConsoleStatusReporter(output=messages.append)

        reporter.idle()
        reporter.recording()
        reporter.processing()
        reporter.success("hello")
        reporter.no_speech()
        reporter.error(RuntimeError("injection failure"))

        self.assertEqual(
            messages,
            [
                "Idle: press the dictation hotkey to start.",
                "Recording...",
                "Processing...",
                "Inserted: hello",
                "No speech detected: try again closer to the microphone.",
                "Text injection failed: focus the target app and try again.",
            ],
        )

    def test_runtime_imports_do_not_load_optional_dependencies(self):
        sys.modules.pop("sounddevice", None)
        sys.modules.pop("keyboard", None)
        sys.modules.pop("faster_whisper", None)

        import services.runtime.logging  # noqa: F401
        import services.runtime.status  # noqa: F401

        self.assertNotIn("sounddevice", sys.modules)
        self.assertNotIn("keyboard", sys.modules)
        self.assertNotIn("faster_whisper", sys.modules)


if __name__ == "__main__":
    unittest.main()
