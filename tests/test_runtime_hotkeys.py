import importlib
import sys
import unittest
from unittest import mock


class FakeHotkeyBackend:
    def __init__(self):
        self.press_handlers = {}
        self.release_handlers = {}
        self.unhooked = []
        self._next_hook = 0

    def on_press(self, key, callback):
        hook = f"press-{key}-{self._next_hook}"
        self._next_hook += 1
        self.press_handlers[key] = callback
        return hook

    def on_release(self, key, callback):
        hook = f"release-{key}-{self._next_hook}"
        self._next_hook += 1
        self.release_handlers[key] = callback
        return hook

    def unhook(self, hook):
        self.unhooked.append(hook)

    def press(self, key):
        self.press_handlers[key](object())

    def release(self, key):
        self.release_handlers[key](object())


class RuntimeHotkeyTests(unittest.TestCase):
    def test_module_import_does_not_import_keyboard(self):
        sys.modules.pop("services.runtime.hotkeys", None)
        sys.modules.pop("keyboard", None)

        importlib.import_module("services.runtime.hotkeys")

        self.assertNotIn("keyboard", sys.modules)

    def test_hold_controller_fires_press_and_release_once_per_hold(self):
        from services.runtime.hotkeys import HoldHotkeyController

        backend = FakeHotkeyBackend()
        calls = []
        controller = HoldHotkeyController(
            backend=backend,
            hold_key="ctrl+space",
            on_press=lambda: calls.append("press"),
            on_release=lambda: calls.append("release"),
            on_cancel=lambda: calls.append("cancel"),
        )

        controller.start()
        backend.press("ctrl+space")
        backend.press("ctrl+space")
        backend.release("ctrl+space")
        backend.release("ctrl+space")

        self.assertEqual(calls, ["press", "release"])

    def test_hold_controller_fires_cancel_on_escape(self):
        from services.runtime.hotkeys import HoldHotkeyController

        backend = FakeHotkeyBackend()
        calls = []
        controller = HoldHotkeyController(
            backend=backend,
            hold_key="ctrl+space",
            on_press=lambda: calls.append("press"),
            on_release=lambda: calls.append("release"),
            on_cancel=lambda: calls.append("cancel"),
        )

        controller.start()
        backend.press("ctrl+space")
        backend.press("esc")
        backend.release("ctrl+space")

        self.assertEqual(calls, ["press", "cancel"])

    def test_stop_unhooks_registered_handlers(self):
        from services.runtime.hotkeys import HoldHotkeyController

        backend = FakeHotkeyBackend()
        controller = HoldHotkeyController(
            backend=backend,
            hold_key="ctrl+space",
            on_press=lambda: None,
            on_release=lambda: None,
            on_cancel=lambda: None,
        )

        controller.start()
        hooks = list(controller.hooks)
        controller.stop()

        self.assertEqual(backend.unhooked, hooks)
        self.assertEqual(controller.hooks, [])

    def test_keyboard_backend_reports_missing_optional_dependency(self):
        from services.runtime.hotkeys import KeyboardHotkeyBackend

        with mock.patch("importlib.import_module", side_effect=ImportError("missing")):
            with self.assertRaisesRegex(RuntimeError, "pip install keyboard"):
                KeyboardHotkeyBackend()

    def test_keyboard_backend_combo_release_waits_until_all_combo_keys_are_released(self):
        from services.runtime.hotkeys import KeyboardHotkeyBackend

        class Event:
            def __init__(self, name, event_type):
                self.name = name
                self.event_type = event_type

        class KeyboardModule:
            KEY_DOWN = "down"
            KEY_UP = "up"

            def __init__(self):
                self.handlers = []
                self.unhooked = []

            def hook(self, callback):
                self.handlers.append(callback)
                return callback

            def unhook(self, hook):
                self.unhooked.append(hook)

        keyboard = KeyboardModule()
        backend = KeyboardHotkeyBackend(keyboard_module=keyboard)
        calls = []

        press_hook = backend.on_press("ctrl+alt+space", lambda: calls.append("press"))
        release_hook = backend.on_release("ctrl+alt+space", lambda: calls.append("release"))

        for event in [
            Event("ctrl", "down"),
            Event("alt", "down"),
            Event("space", "down"),
            Event("space", "up"),
        ]:
            for handler in list(keyboard.handlers):
                handler(event)

        self.assertEqual(calls, ["press"])

        for event in [
            Event("alt", "up"),
            Event("ctrl", "up"),
        ]:
            for handler in list(keyboard.handlers):
                handler(event)

        self.assertEqual(calls, ["press", "release"])
        backend.unhook(press_hook)
        backend.unhook(release_hook)
        self.assertEqual(keyboard.unhooked, [press_hook, release_hook])


if __name__ == "__main__":
    unittest.main()
