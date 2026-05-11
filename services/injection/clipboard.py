from __future__ import annotations

from collections.abc import Callable
from time import sleep as default_sleep

from services.injection.hotkeys import paste_shortcut, send_hotkey


ClipboardGet = Callable[[], str]
ClipboardSet = Callable[[str], None]
Hotkey = Callable[..., None]
Sleep = Callable[[float], None]


class ClipboardInjector:
    def __init__(
        self,
        clipboard_get: ClipboardGet | None = None,
        clipboard_set: ClipboardSet | None = None,
        hotkey: Hotkey | None = None,
        sleep: Sleep = default_sleep,
        preserve_previous_clipboard: bool = True,
        paste_delay_seconds: float = 0.05,
        platform: str | None = None,
    ) -> None:
        self._clipboard_get = clipboard_get or _default_clipboard_get
        self._clipboard_set = clipboard_set or _default_clipboard_set
        self._hotkey = hotkey or _default_hotkey
        self._sleep = sleep
        self._preserve_previous_clipboard = preserve_previous_clipboard
        self._paste_delay_seconds = paste_delay_seconds
        self._paste_shortcut = paste_shortcut(platform)

    def inject(self, text: str) -> None:
        previous = self._clipboard_get() if self._preserve_previous_clipboard else None

        try:
            self._clipboard_set(text)
            self._hotkey(*self._paste_shortcut)
            self._sleep(self._paste_delay_seconds)
        finally:
            if self._preserve_previous_clipboard:
                self._clipboard_set(previous or "")


def _default_clipboard_get() -> str:
    try:
        import pyperclip  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("pyperclip is required for default clipboard reads") from exc

    value = pyperclip.paste()
    return "" if value is None else str(value)


def _default_clipboard_set(text: str) -> None:
    try:
        import pyperclip  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("pyperclip is required for default clipboard writes") from exc

    pyperclip.copy(text)


def _default_hotkey(*keys: str) -> None:
    try:
        send_hotkey(*keys)
    except ImportError as exc:
        raise RuntimeError(
            "keyboard is required for default hotkey injection on Windows/Linux; "
            "pyautogui is required on macOS"
        ) from exc
