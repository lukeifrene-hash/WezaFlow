import unittest


class AppProfileTests(unittest.TestCase):
    def test_classify_app_recognizes_common_desktop_apps(self):
        from services.context.profiles import classify_app

        cases = {
            "Code.exe": "code",
            "Cursor.exe": "code",
            "OUTLOOK.EXE": "email",
            "Teams.exe": "work_chat",
            "WhatsApp.exe": "personal_chat",
            "chrome.exe": "browser",
            "some-tool.exe": "other",
        }

        for process_name, expected_category in cases.items():
            with self.subTest(process_name=process_name):
                self.assertEqual(classify_app(process_name), expected_category)

    def test_classify_app_uses_browser_url_when_available(self):
        from services.context.profiles import classify_app

        self.assertEqual(
            classify_app("chrome.exe", browser_url="https://mail.google.com/mail/u/0/"),
            "email",
        )
        self.assertEqual(
            classify_app("msedge.exe", browser_url="https://app.slack.com/client/T123"),
            "work_chat",
        )
        self.assertEqual(
            classify_app("firefox.exe", browser_url="https://web.whatsapp.com/"),
            "personal_chat",
        )
        self.assertEqual(
            classify_app("firefox.exe", browser_url="https://example.com/"),
            "browser",
        )

    def test_get_active_app_context_falls_back_without_windows_apis(self):
        import services.context.app_context as app_context_module
        from services.pipeline.models import AppContext

        original_reader = app_context_module._read_active_window
        app_context_module._read_active_window = lambda: (_ for _ in ()).throw(ImportError())
        try:
            context = app_context_module.get_active_app_context()
        finally:
            app_context_module._read_active_window = original_reader

        self.assertIsInstance(context, AppContext)
        self.assertEqual(context.app_name, "unknown")
        self.assertEqual(context.category, "other")
        self.assertIsNone(context.browser_url)
        self.assertEqual(context.visible_text, [])

    def test_get_active_app_context_uses_browser_url_and_visible_text_helpers(self):
        import services.context.app_context as app_context_module

        calls = []
        original_reader = app_context_module._read_active_window
        had_url_reader = hasattr(app_context_module, "_read_browser_url")
        original_url_reader = getattr(app_context_module, "_read_browser_url", None)
        had_visible_reader = hasattr(app_context_module, "_read_visible_text")
        original_visible_reader = getattr(app_context_module, "_read_visible_text", None)

        def fake_browser_url(process_name, window_title):
            calls.append((process_name, window_title))
            return "https://mail.google.com/mail/u/0/"

        app_context_module._read_active_window = lambda: ("chrome.exe", "Gmail - Inbox")
        app_context_module._read_browser_url = fake_browser_url
        app_context_module._read_visible_text = lambda: ["Compose", "Inbox"]
        try:
            context = app_context_module.get_active_app_context()
        finally:
            app_context_module._read_active_window = original_reader
            if had_url_reader:
                app_context_module._read_browser_url = original_url_reader
            else:
                delattr(app_context_module, "_read_browser_url")
            if had_visible_reader:
                app_context_module._read_visible_text = original_visible_reader
            else:
                delattr(app_context_module, "_read_visible_text")

        self.assertEqual(calls, [("chrome.exe", "Gmail - Inbox")])
        self.assertEqual(context.browser_url, "https://mail.google.com/mail/u/0/")
        self.assertEqual(context.category, "email")
        self.assertEqual(context.visible_text, ["Compose", "Inbox"])

    def test_collect_bounded_visible_text_caps_total_characters(self):
        import services.context.app_context as app_context_module

        self.assertTrue(hasattr(app_context_module, "_collect_bounded_visible_text"))

        class FakeElement:
            def __init__(self, name="", children=None):
                self.Name = name
                self._children = children or []

            def GetChildren(self):
                return self._children

        root = FakeElement(
            children=[
                FakeElement("A" * 40),
                FakeElement("B" * 40),
                FakeElement("C" * 40),
            ]
        )

        snippets = app_context_module._collect_bounded_visible_text(
            root,
            max_chars=70,
            max_items=10,
        )

        self.assertEqual(snippets, ["A" * 40, "B" * 30])
        self.assertLessEqual(sum(len(snippet) for snippet in snippets), 70)


class ClipboardInjectionTests(unittest.TestCase):
    def test_paste_shortcut_uses_command_on_macos(self):
        from services.injection.hotkeys import paste_shortcut

        self.assertEqual(paste_shortcut("darwin"), ("command", "v"))
        self.assertEqual(paste_shortcut("win32"), ("ctrl", "v"))

    def test_clipboard_injector_pastes_text_and_restores_previous_clipboard(self):
        from services.injection.clipboard import ClipboardInjector

        calls = []
        clipboard = {"value": "before"}

        injector = ClipboardInjector(
            clipboard_get=lambda: clipboard["value"],
            clipboard_set=lambda value: clipboard.update(value=value),
            hotkey=lambda *keys: calls.append(keys),
            sleep=lambda seconds: calls.append(("sleep", seconds)),
        )

        injector.inject("hello")

        self.assertEqual(calls[0], ("ctrl", "v"))
        self.assertEqual(clipboard["value"], "before")

    def test_clipboard_injector_uses_macos_paste_shortcut(self):
        from services.injection.clipboard import ClipboardInjector

        calls = []
        clipboard = {"value": "before"}

        injector = ClipboardInjector(
            clipboard_get=lambda: clipboard["value"],
            clipboard_set=lambda value: clipboard.update(value=value),
            hotkey=lambda *keys: calls.append(keys),
            sleep=lambda seconds: None,
            platform="darwin",
        )

        injector.inject("hello")

        self.assertEqual(calls[0], ("command", "v"))
        self.assertEqual(clipboard["value"], "before")

    def test_clipboard_injector_can_leave_injected_text_on_clipboard(self):
        from services.injection.clipboard import ClipboardInjector

        clipboard = {"value": "before"}
        injector = ClipboardInjector(
            clipboard_get=lambda: clipboard["value"],
            clipboard_set=lambda value: clipboard.update(value=value),
            hotkey=lambda *keys: None,
            sleep=lambda seconds: None,
            preserve_previous_clipboard=False,
        )

        injector.inject("replacement")

        self.assertEqual(clipboard["value"], "replacement")

    def test_read_selected_text_uses_sentinel_and_restores_clipboard(self):
        from services.injection.selection_reader import read_selected_text

        calls = []
        clipboard = {"value": "before"}

        def set_clipboard(value):
            clipboard["value"] = value
            calls.append(("set", value))

        def hotkey(*keys):
            calls.append(("hotkey", keys))
            clipboard["value"] = "selected text"

        selected = read_selected_text(
            copy=lambda: clipboard["value"],
            paste=set_clipboard,
            hotkey=hotkey,
            sleep=lambda seconds: calls.append(("sleep", seconds)),
        )

        self.assertEqual(selected, "selected text")
        self.assertEqual(clipboard["value"], "before")
        self.assertEqual(calls[0][0], "set")
        self.assertEqual(calls[1], ("hotkey", ("ctrl", "c")))

    def test_read_selected_text_uses_command_c_on_macos(self):
        from services.injection.selection_reader import read_selected_text

        calls = []
        clipboard = {"value": "before"}

        def set_clipboard(value):
            clipboard["value"] = value
            calls.append(("set", value))

        def hotkey(*keys):
            calls.append(("hotkey", keys))
            clipboard["value"] = "selected text"

        selected = read_selected_text(
            copy=lambda: clipboard["value"],
            paste=set_clipboard,
            hotkey=hotkey,
            sleep=lambda seconds: None,
            platform="darwin",
        )

        self.assertEqual(selected, "selected text")
        self.assertEqual(calls[1], ("hotkey", ("command", "c")))

    def test_read_selected_text_returns_empty_string_when_selection_does_not_change_clipboard(self):
        from services.injection.selection_reader import read_selected_text

        clipboard = {"value": "before"}

        selected = read_selected_text(
            copy=lambda: clipboard["value"],
            paste=lambda value: clipboard.update(value=value),
            hotkey=lambda *keys: None,
            sleep=lambda seconds: None,
        )

        self.assertEqual(selected, "")
        self.assertEqual(clipboard["value"], "before")


if __name__ == "__main__":
    unittest.main()
