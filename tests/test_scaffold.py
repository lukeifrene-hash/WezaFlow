import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


class ScaffoldContractTests(unittest.TestCase):
    def test_project_paths_resolve_core_directories(self):
        from services.common.paths import ProjectPaths

        paths = ProjectPaths.from_repo_root(Path(__file__).resolve().parents[1])

        self.assertEqual(paths.config_dir.name, "config")
        self.assertEqual(paths.db_dir.name, "db")
        self.assertEqual(paths.scripts_dir.name, "scripts")
        self.assertEqual(paths.services_dir.name, "services")

    def test_schema_initializes_expected_tables(self):
        schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
        schema = schema_path.read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "localflow.db"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(schema)
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            finally:
                conn.close()

        tables = {row[0] for row in rows}
        self.assertEqual(
            {
                "vocabulary",
                "app_profiles",
                "snippets",
                "transcription_history",
                "corrections",
            },
            tables,
        )

    def test_default_settings_contain_pipeline_controls(self):
        from services.config.settings import load_default_settings

        settings = load_default_settings()

        self.assertEqual(settings["audio"]["sample_rate"], 16000)
        self.assertEqual(settings["audio"]["channels"], 1)
        self.assertEqual(settings["models"]["whisper"], "small.en")
        self.assertEqual(settings["models"]["whisper_cpu_threads"], 2)
        self.assertIn("dictation", settings["hotkeys"])
        self.assertIn("command_mode", settings["hotkeys"])
        self.assertEqual(settings["runtime"]["profile"], "low-impact")

    def test_tasks_script_exposes_desktop_dev_and_build(self):
        script = Path(__file__).resolve().parents[1] / "tasks.ps1"

        content = script.read_text(encoding="utf-8")

        self.assertIn('"Dev"', content)
        self.assertIn('"Build"', content)
        self.assertIn("npm run tauri", content)

    def test_pipeline_contract_serializes_to_json(self):
        from services.pipeline.models import AppContext, PipelineRequest

        request = PipelineRequest(
            wav_path="sample.wav",
            context=AppContext(
                app_name="Code.exe",
                window_title="LocalFlow",
                category="code",
                browser_url=None,
                visible_text=["LocalFlow"],
            ),
            language="en",
        )

        encoded = json.dumps(request.to_dict())

        self.assertIn("sample.wav", encoded)
        self.assertIn("Code.exe", encoded)
        self.assertIn('"language": "en"', encoded)


if __name__ == "__main__":
    unittest.main()
