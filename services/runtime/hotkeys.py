from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, Protocol


Callback = Callable[[], None]


class HotkeyBackend(Protocol):
    def on_press(self, key: str, callback: Callable[..., None]) -> Any:
        raise NotImplementedError

    def on_release(self, key: str, callback: Callable[..., None]) -> Any:
        raise NotImplementedError

    def unhook(self, hook: Any) -> None:
        raise NotImplementedError


class KeyboardHotkeyBackend:
    """Adapter around the optional keyboard package."""

    def __init__(self, keyboard_module: Any | None = None):
        if keyboard_module is None:
            try:
                keyboard_module = importlib.import_module("keyboard")
            except ImportError as exc:
                raise RuntimeError(
                    "The optional 'keyboard' package is required for runtime hotkeys. "
                    "Install it with: pip install keyboard"
                ) from exc
        self._keyboard = keyboard_module

    def on_press(self, key: str, callback: Callable[..., None]) -> Any:
        if "+" in key:
            return self._hook_combo(key, callback, trigger="press")
        return self._keyboard.on_press_key(key, callback)

    def on_release(self, key: str, callback: Callable[..., None]) -> Any:
        if "+" in key:
            return self._hook_combo(key, callback, trigger="release")
        return self._keyboard.on_release_key(key, callback)

    def unhook(self, hook: Any) -> None:
        if hasattr(self._keyboard, "unhook"):
            self._keyboard.unhook(hook)
            return
        self._keyboard.remove_hotkey(hook)

    def _hook_combo(self, key: str, callback: Callable[..., None], *, trigger: str) -> Any:
        required = {_normalize_key_name(part) for part in key.split("+") if part.strip()}
        pressed: set[str] = set()
        active = False
        key_down = getattr(self._keyboard, "KEY_DOWN", "down")
        key_up = getattr(self._keyboard, "KEY_UP", "up")

        def handler(event) -> None:
            nonlocal active
            name = _normalize_key_name(getattr(event, "name", ""))
            event_type = getattr(event, "event_type", "")
            if name not in required:
                return
            if event_type == key_down:
                pressed.add(name)
                if not active and required.issubset(pressed):
                    active = True
                    if trigger == "press":
                        callback()
                return
            if event_type == key_up:
                was_active = active
                pressed.discard(name)
                if was_active and not pressed.intersection(required):
                    active = False
                    if trigger == "release":
                        callback()

        return self._keyboard.hook(handler)


def _normalize_key_name(name: str) -> str:
    normalized = name.casefold().strip().replace(" ", "")
    aliases = {
        "control": "ctrl",
        "leftctrl": "ctrl",
        "rightctrl": "ctrl",
        "leftalt": "alt",
        "rightalt": "alt",
        "escape": "esc",
    }
    return aliases.get(normalized, normalized)


class HoldHotkeyController:
    def __init__(
        self,
        *,
        backend: HotkeyBackend | None = None,
        hold_key: str,
        on_press: Callback,
        on_release: Callback,
        on_cancel: Callback,
        cancel_key: str = "esc",
    ):
        self._backend = backend
        self._hold_key = hold_key
        self._cancel_key = cancel_key
        self._on_press = on_press
        self._on_release = on_release
        self._on_cancel = on_cancel
        self._held = False
        self.hooks: list[Any] = []

    def start(self) -> None:
        if self.hooks:
            return
        backend = self._get_backend()
        self.hooks = [
            backend.on_press(self._hold_key, self._handle_press),
            backend.on_release(self._hold_key, self._handle_release),
            backend.on_press(self._cancel_key, self._handle_cancel),
        ]

    def stop(self) -> None:
        backend = self._get_backend()
        for hook in self.hooks:
            backend.unhook(hook)
        self.hooks = []
        self._held = False

    def _get_backend(self) -> HotkeyBackend:
        if self._backend is None:
            self._backend = KeyboardHotkeyBackend()
        return self._backend

    def _handle_press(self, *_args: Any) -> None:
        if self._held:
            return
        self._held = True
        self._on_press()

    def _handle_release(self, *_args: Any) -> None:
        if not self._held:
            return
        self._held = False
        self._on_release()

    def _handle_cancel(self, *_args: Any) -> None:
        if not self._held:
            return
        self._held = False
        self._on_cancel()
