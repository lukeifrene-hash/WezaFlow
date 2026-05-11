from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from types import ModuleType


ImportModule = Callable[[str], ModuleType]


def primary_modifier(platform: str | None = None) -> str:
    return "command" if (platform or sys.platform) == "darwin" else "ctrl"


def copy_shortcut(platform: str | None = None) -> tuple[str, str]:
    return (primary_modifier(platform), "c")


def paste_shortcut(platform: str | None = None) -> tuple[str, str]:
    return (primary_modifier(platform), "v")


def send_hotkey(
    *keys: str,
    platform: str | None = None,
    import_module: ImportModule = importlib.import_module,
) -> None:
    if (platform or sys.platform) == "darwin":
        pyautogui = import_module("pyautogui")
        pyautogui.hotkey(*keys)
        return

    keyboard = import_module("keyboard")
    keyboard.press_and_release("+".join(keys))
