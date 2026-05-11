import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DesktopShellTests(unittest.TestCase):
    def test_windows_release_app_uses_gui_subsystem(self):
        main_rs = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")

        self.assertIn('windows_subsystem = "windows"', main_rs)

    def test_tauri_shell_uses_weza_branding(self):
        config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

        self.assertEqual(config["productName"], "WezaFlow")
        self.assertEqual(config["app"]["windows"][0]["title"], "WezaFlow")

    def test_header_uses_transparent_logo_without_square_mark(self):
        app = (ROOT / "src" / "App.tsx").read_text(encoding="utf-8")
        css = (ROOT / "src" / "styles.css").read_text(encoding="utf-8")
        brand_mark_block = css.split(".brand-mark {", 1)[1].split("}", 1)[0]

        self.assertIn("Logo-no-bg.png", app)
        self.assertNotIn("background:", brand_mark_block)
        self.assertNotIn("border:", brand_mark_block)
        self.assertNotIn("box-shadow:", brand_mark_block)
        self.assertIn("overflow: visible", brand_mark_block)

    def test_recording_bar_chrome_css_is_transparent(self):
        css = (ROOT / "src" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("html.recording-bar-window", css)
        self.assertIn("background: transparent", css)
        self.assertIn("min-height: 72px", css)

    def test_app_icon_is_generated_from_full_logo(self):
        icon = ROOT / "src-tauri" / "icons" / "icon.ico"

        self.assertGreater(icon.stat().st_size, 10_000)

    def test_macos_icon_is_available_for_tauri_bundles(self):
        icon = ROOT / "src-tauri" / "icons" / "icon.icns"

        self.assertGreater(icon.stat().st_size, 10_000)

    def test_recording_bar_window_is_configured_as_hidden_overlay(self):
        config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

        windows = {window["label"]: window for window in config["app"]["windows"]}
        self.assertIn("recording-bar", windows)
        recording_bar = windows["recording-bar"]

        self.assertEqual(recording_bar["title"], "WezaFlow Recording")
        self.assertFalse(recording_bar["visible"])
        self.assertFalse(recording_bar["decorations"])
        self.assertTrue(recording_bar["transparent"])
        self.assertTrue(recording_bar["alwaysOnTop"])
        self.assertFalse(recording_bar["resizable"])
        self.assertTrue(recording_bar["skipTaskbar"])
        self.assertFalse(recording_bar["focus"])
        self.assertGreaterEqual(recording_bar["width"], 220)
        self.assertLessEqual(recording_bar["width"], 300)
        self.assertGreaterEqual(recording_bar["height"], 38)
        self.assertLessEqual(recording_bar["height"], 72)

    def test_recording_bar_state_events_are_emitted_from_rust_shell(self):
        lib_rs = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

        self.assertIn('"recording-bar"', lib_rs)
        self.assertIn('"recording-bar-state"', lib_rs)
        for state in ["listening", "command", "error"]:
            self.assertIn(f'"{state}"', lib_rs)

    def test_recording_bar_hides_immediately_when_hotkey_is_released(self):
        lib_rs = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        stop_body = lib_rs.split("fn stop_runtime_mode", 1)[1].split(
            "fn handle_mouse_button", 1
        )[0]

        self.assertIn("hide_recording_bar(app);", stop_body)
        self.assertNotIn("RECORDING_STATE_PROCESSING", stop_body)
        self.assertNotIn("RECORDING_STATE_DONE", stop_body)
        self.assertNotIn("hide_recording_bar_after", stop_body)

    def test_main_window_close_hides_to_tray_instead_of_exiting(self):
        lib_rs = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

        self.assertIn("CloseRequested", lib_rs)
        self.assertIn("prevent_close", lib_rs)
        self.assertIn(".hide()", lib_rs)

    def test_runtime_compatibility_requires_current_capability_endpoint(self):
        lib_rs = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

        self.assertIn('"/runtime/capabilities"', lib_rs)

    def test_start_services_records_runtime_api_pid(self):
        script = (ROOT / "scripts" / "start_services.ps1").read_text(encoding="utf-8")

        self.assertIn("desktop-python-api.pid", script)
        self.assertIn("-PassThru", script)
        self.assertIn("Set-Content", script)

    def test_macos_setup_script_and_github_workflow_are_present(self):
        setup_script = ROOT / "scripts" / "setup_macos.sh"
        workflow = ROOT / ".github" / "workflows" / "build-macos.yml"

        self.assertTrue(setup_script.exists())
        self.assertTrue(workflow.exists())
        self.assertIn("services/injection/requirements-macos.txt", setup_script.read_text(encoding="utf-8"))
        self.assertIn("macos-latest", workflow.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
