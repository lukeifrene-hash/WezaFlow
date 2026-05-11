import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None

from services.pipeline.models import AppContext, PipelineResult


class FakeRuntimeSession:
    def __init__(self):
        self.state = "idle"
        self.last_error = None
        self.calls = []
        self.result = PipelineResult(
            raw_transcript="hello",
            polished_text="Hello.",
            app_context=AppContext(
                app_name="Code.exe",
                window_title="LocalFlow",
                category="code",
            ),
            duration_ms=42,
        )

    def start_recording(self, language=None):
        self.calls.append(("start_recording", language))
        self.state = "recording"
        return True

    def start_command_recording(self, language=None):
        self.calls.append(("start_command_recording", language))
        self.state = "recording"
        return True

    def stop_and_process(self, language=None):
        self.calls.append(("stop_and_process", language))
        self.state = "idle"
        return self.result

    def cancel(self):
        self.calls.append(("cancel", None))
        self.state = "idle"
        return True


class FakeCorrectionWatcher:
    def __init__(self):
        self.pending = [
            {
                "id": "pending-1",
                "original": "local flow",
                "raw_transcript": "local flow",
                "app_name": "Code.exe",
                "window_title": "LocalFlow",
                "detected_at": "2026-05-10T12:00:00Z",
            }
        ]
        self.confirmed = []
        self.dismissed = []

    def list_pending(self):
        return list(self.pending)

    def confirm_pending(self, pending_id):
        self.confirmed.append(pending_id)
        for index, item in enumerate(self.pending):
            if item["id"] == pending_id:
                return self.pending.pop(index)
        return None

    def dismiss_pending(self, pending_id):
        self.dismissed.append(pending_id)
        for index, item in enumerate(self.pending):
            if item["id"] == pending_id:
                self.pending.pop(index)
                return True
        return False


class FakeRuntimeSessionWithCorrectionWatcher(FakeRuntimeSession):
    def __init__(self):
        super().__init__()
        self.correction_watcher = FakeCorrectionWatcher()


class RuntimeApiStateSessionTests(unittest.TestCase):
    def test_saving_runtime_settings_rebuilds_next_session_with_new_profile(self):
        from services.config.settings import load_settings
        from services.runtime.api import RuntimeApiState

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            state = RuntimeApiState(
                root=root,
                log_path=root / "runtime.jsonl",
                find_spec=lambda _name: None,
            )
            sessions = [FakeRuntimeSession(), FakeRuntimeSession()]

            with patch(
                "services.runtime.api.create_runtime_session",
                side_effect=sessions,
            ) as create_session:
                self.assertIs(state.ensure_session(), sessions[0])

                settings = load_settings(state.settings_path)
                settings["runtime"]["profile"] = "distil-small-en"
                state.save_runtime_settings(settings)

                self.assertIsNone(state.session)
                self.assertIs(state.ensure_session(), sessions[1])

        self.assertEqual(create_session.call_args_list[0].kwargs["asr_profile"], "low-impact")
        self.assertEqual(create_session.call_args_list[1].kwargs["asr_profile"], "distil-small-en")

    def test_diagnostics_report_configured_profile_after_settings_change(self):
        from services.config.settings import load_settings
        from services.runtime.api import RuntimeApiState

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            log_path = root / "runtime.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "recording_started",
                        "asr_profile": "low-impact",
                        "asr_model": "small.en",
                        "asr_cpu_threads": 2,
                        "quiet_mode": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            state = RuntimeApiState(root=root, log_path=log_path, find_spec=lambda _name: None)

            settings = load_settings(state.settings_path)
            settings["runtime"]["profile"] = "distil-small-en"
            state.save_runtime_settings(settings)

            diagnostics = state.diagnostic_lines()

        self.assertTrue(diagnostics[0].startswith("Configured runtime: profile=distil-small-en "))
        self.assertNotIn("profile=low-impact", diagnostics[0])
        self.assertTrue(diagnostics[1].startswith("Last recording: profile=low-impact "))

    def test_runtime_api_capabilities_advertise_profile_session_refresh(self):
        from services.runtime.api import RUNTIME_API_CAPABILITIES

        self.assertIn("profile-session-refresh", RUNTIME_API_CAPABILITIES)
        self.assertIn("configured-runtime-diagnostics", RUNTIME_API_CAPABILITIES)
        self.assertIn("runtime-warmup", RUNTIME_API_CAPABILITIES)

    def test_created_session_warms_selected_pipeline_in_background(self):
        from services.config.settings import load_settings, save_settings
        from services.runtime.api import RuntimeApiState

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            settings = load_settings(root / "config" / "settings.yaml")
            settings["runtime"]["profile"] = "distil-small-en"
            settings["runtime"]["language"] = "en"
            save_settings(root / "config" / "settings.yaml", settings)

            session = FakeRuntimeSession()
            session.pipeline = object()
            session.logger = object()
            state = RuntimeApiState(
                root=root,
                log_path=root / "runtime.jsonl",
                find_spec=lambda _name: None,
            )

            with patch("services.runtime.api.create_runtime_session", return_value=session):
                with patch("services.runtime.api.warm_pipeline_in_background") as warm:
                    self.assertIs(state.ensure_session(), session)

        warm.assert_called_once_with(session.pipeline, session.logger, language="en", role="main")


class RuntimeApiTests(unittest.TestCase):
    def setUp(self):
        if TestClient is None:
            self.skipTest("fastapi is not installed in this Python environment")

    def test_status_reports_runtime_envelope(self):
        from services.runtime.api import create_app

        session = FakeRuntimeSession()
        client = TestClient(create_app(session=session, find_spec=lambda _name: None))

        payload = client.get("/status").json()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["state"], "idle")
        self.assertEqual(payload["mode"], "idle")
        self.assertEqual(payload["profile"], "low-impact")
        self.assertFalse(payload["quiet_mode"])
        self.assertFalse(payload["quality_fallback"])
        self.assertIsNone(payload["last_error"])

    def test_runtime_api_allows_tauri_cors_preflight(self):
        from services.runtime.api import create_app

        client = TestClient(create_app(session=FakeRuntimeSession(), find_spec=lambda _name: None))

        response = client.options(
            "/status",
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://tauri.localhost")

    def test_start_stop_cancel_runtime_calls_session(self):
        from services.runtime.api import create_app

        session = FakeRuntimeSession()
        client = TestClient(create_app(session=session, find_spec=lambda _name: None))

        start = client.post("/runtime/start", json={"mode": "dictation", "language": "en"}).json()
        stop = client.post("/runtime/stop", json={"language": "en"}).json()
        command = client.post("/runtime/start", json={"mode": "command", "language": "en"}).json()
        cancel = client.post("/runtime/cancel").json()

        self.assertEqual(start["state"], "recording")
        self.assertEqual(stop["result"]["polished_text"], "Hello.")
        self.assertEqual(command["mode"], "command")
        self.assertEqual(cancel["state"], "idle")
        self.assertEqual(
            session.calls,
            [
                ("start_recording", "en"),
                ("stop_and_process", "en"),
                ("start_command_recording", "en"),
                ("cancel", None),
            ],
        )

    def test_check_and_diagnostics_are_available_without_hotkeys(self):
        from services.runtime.api import create_app

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "runtime.jsonl"
            log_path.write_text(
                json.dumps({"event": "dictation_success", "duration_ms": 100}) + "\n",
                encoding="utf-8",
            )
            client = TestClient(
                create_app(
                    session=FakeRuntimeSession(),
                    log_path=log_path,
                    find_spec=lambda name: object() if name == "keyboard" else None,
                )
            )

            check = client.get("/runtime/check").json()
            diagnostics = client.get("/runtime/diagnostics").json()

        by_name = {item["name"]: item for item in check["dependencies"]}
        self.assertTrue(by_name["keyboard"]["available"])
        self.assertFalse(by_name["sounddevice"]["available"])
        self.assertTrue(any("success=1" in line for line in diagnostics["lines"]))

    def test_settings_roundtrip_persists_to_yaml(self):
        from services.runtime.api import create_app

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            client = TestClient(
                create_app(root=root, session=FakeRuntimeSession(), find_spec=lambda _name: None)
            )

            settings = client.get("/settings").json()["settings"]
            settings["hotkeys"]["dictation"] = "Ctrl+Shift+Space"
            settings["models"]["whisper_cpu_threads"] = 4
            updated = client.put("/settings", json={"settings": settings}).json()

            persisted = (root / "config" / "settings.yaml").read_text(encoding="utf-8")

        self.assertEqual(updated["settings"]["hotkeys"]["dictation"], "Ctrl+Shift+Space")
        self.assertIn("Ctrl+Shift+Space", persisted)
        self.assertIn("whisper_cpu_threads", persisted)

    def test_settings_roundtrip_accepts_multiple_hotkeys(self):
        from services.runtime.api import create_app

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            client = TestClient(
                create_app(root=root, session=FakeRuntimeSession(), find_spec=lambda _name: None)
            )

            settings = client.get("/settings").json()["settings"]
            settings["hotkeys"]["dictation"] = ["Ctrl+Alt+Space", "MouseX1"]
            settings["hotkeys"]["command_mode"] = ["Ctrl+Alt+E", "MouseX2"]
            updated = client.put("/settings", json={"settings": settings}).json()

            persisted = (root / "config" / "settings.yaml").read_text(encoding="utf-8")

        self.assertEqual(updated["settings"]["hotkeys"]["dictation"], ["Ctrl+Alt+Space", "MouseX1"])
        self.assertIn("- MouseX1", persisted)
        self.assertIn("- MouseX2", persisted)

    def test_settings_defaults_enable_system_audio_ducking(self):
        from services.runtime.api import create_app

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            client = TestClient(
                create_app(root=root, session=FakeRuntimeSession(), find_spec=lambda _name: None)
            )

            settings = client.get("/settings").json()["settings"]

        self.assertTrue(settings["runtime"]["system_audio_ducking"])
        self.assertEqual(settings["runtime"]["system_audio_duck_volume"], 8)

    def test_vocabulary_and_corrections_crud(self):
        from services.runtime.api import create_app

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "db").mkdir()
            client = TestClient(
                create_app(root=root, session=FakeRuntimeSession(), find_spec=lambda _name: None)
            )

            client.post("/vocabulary/terms", json={"word": "LocalFlow"})
            terms = client.get("/vocabulary/terms").json()["terms"]
            client.delete("/vocabulary/terms/LocalFlow")
            deleted_terms = client.get("/vocabulary/terms").json()["terms"]

            client.post(
                "/vocabulary/corrections",
                json={"original": "local flow", "corrected": "LocalFlow"},
            )
            corrections = client.get("/vocabulary/corrections").json()["corrections"]
            client.delete(
                "/vocabulary/corrections",
                params={"original": "local flow", "corrected": "LocalFlow"},
            )
            deleted_corrections = client.get("/vocabulary/corrections").json()["corrections"]

        self.assertEqual(terms[0]["word"], "localflow")
        self.assertEqual(deleted_terms, [])
        self.assertEqual(corrections[0]["corrected"], "LocalFlow")
        self.assertEqual(deleted_corrections, [])

    def test_pending_corrections_list_confirm_and_dismiss(self):
        from services.runtime.api import create_app

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "db").mkdir()
            session = FakeRuntimeSessionWithCorrectionWatcher()
            client = TestClient(create_app(root=root, session=session, find_spec=lambda _name: None))

            pending = client.get("/corrections/pending").json()["pending"]
            confirmed = client.post(
                "/corrections/pending/pending-1/confirm",
                json={"original": "local flow", "corrected": "LocalFlow"},
            ).json()
            after_confirm = client.get("/corrections/pending").json()["pending"]
            missing_confirm = client.post(
                "/corrections/pending/missing/confirm",
                json={"original": "missing", "corrected": "Missing"},
            )

            session.correction_watcher.pending.append(
                {
                    "id": "pending-2",
                    "original": "wispr flow",
                    "raw_transcript": "wispr flow",
                    "app_name": None,
                    "window_title": None,
                    "detected_at": "2026-05-10T12:01:00Z",
                }
            )
            dismissed = client.post("/corrections/pending/pending-2/dismiss").json()
            after_dismiss = client.get("/corrections/pending").json()["pending"]

        self.assertEqual(pending[0]["id"], "pending-1")
        self.assertEqual(pending[0]["app_name"], "Code.exe")
        self.assertEqual(confirmed["status"], "ok")
        self.assertEqual(confirmed["corrections"][0]["corrected"], "LocalFlow")
        self.assertEqual(session.correction_watcher.confirmed, ["pending-1"])
        self.assertEqual(after_confirm, [])
        self.assertEqual(missing_confirm.status_code, 404)
        self.assertEqual(dismissed, {"status": "ok"})
        self.assertEqual(session.correction_watcher.dismissed, ["pending-2"])
        self.assertEqual(after_dismiss, [])

    def test_pending_correction_mutations_404_without_watcher(self):
        from services.runtime.api import create_app

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "db").mkdir()
            client = TestClient(
                create_app(root=root, session=FakeRuntimeSession(), find_spec=lambda _name: None)
            )

            pending = client.get("/corrections/pending").json()
            confirmed = client.post(
                "/corrections/pending/unknown/confirm",
                json={"original": "local flow", "corrected": "LocalFlow"},
            )
            dismissed = client.post("/corrections/pending/unknown/dismiss")

        self.assertEqual(pending, {"status": "ok", "pending": []})
        self.assertEqual(confirmed.status_code, 404)
        self.assertEqual(dismissed.status_code, 404)

    def test_learning_suggestions_endpoint_returns_store_suggestions(self):
        from services.runtime.api import create_app

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "db").mkdir()
            client = TestClient(
                create_app(root=root, session=FakeRuntimeSession(), find_spec=lambda _name: None)
            )

            for _ in range(3):
                client.post(
                    "/vocabulary/corrections",
                    json={
                        "original": "sign off",
                        "corrected": "Thank you for your time and consideration.",
                    },
                )
            suggestions = client.get("/learning/suggestions").json()["suggestions"]

        self.assertEqual(suggestions[0]["kind"], "snippet")
        self.assertEqual(suggestions[0]["expansion"], "Thank you for your time and consideration.")
        self.assertEqual(suggestions[1]["kind"], "vocabulary")
        self.assertEqual(suggestions[1]["phrase"], "Thank you for your time and consideration.")

    def test_snippets_crud_persists_yaml(self):
        from services.runtime.api import create_app

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            client = TestClient(
                create_app(root=root, session=FakeRuntimeSession(), find_spec=lambda _name: None)
            )

            client.post(
                "/snippets",
                json={"trigger_phrase": "insert my email", "expansion": "user@example.com"},
            )
            created = client.get("/snippets").json()["snippets"]
            client.post(
                "/snippets",
                json={"trigger_phrase": "insert my email", "expansion": "me@example.com"},
            )
            updated = client.get("/snippets").json()["snippets"]
            client.delete("/snippets/insert%20my%20email")
            deleted = client.get("/snippets").json()["snippets"]
            persisted = (root / "config" / "snippets.yaml").read_text(encoding="utf-8")

        self.assertEqual(created[0]["expansion"], "user@example.com")
        self.assertEqual(updated[0]["expansion"], "me@example.com")
        self.assertEqual(deleted, [])
        self.assertIn("snippets:", persisted)

    def test_start_services_script_launches_runtime_api(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "start_services.ps1"

        content = script.read_text(encoding="utf-8")

        self.assertIn("services.runtime.api", content)
        self.assertIn("src-tauri", content)
        self.assertIn("localflow.exe", content)
        self.assertIn("desktop-python-api.pid", content)
        self.assertIn("-PassThru", content)
        self.assertIn("Set-Content", content)


if __name__ == "__main__":
    unittest.main()
