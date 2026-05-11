from __future__ import annotations

from collections.abc import Callable
from time import sleep as default_sleep
from uuid import uuid4

from services.injection.hotkeys import copy_shortcut


ClipboardGet = Callable[[], str]
ClipboardSet = Callable[[str], None]
Hotkey = Callable[..., None]
Sleep = Callable[[float], None]


def read_selected_text(
    copy: ClipboardGet,
    paste: ClipboardSet,
    hotkey: Hotkey,
    sleep: Sleep = default_sleep,
    copy_delay_seconds: float = 0.05,
    platform: str | None = None,
) -> str:
    """Read selected text via the platform copy shortcut while restoring the clipboard."""
    previous = copy()
    sentinel = f"__LOCALFLOW_SELECTION_SENTINEL_{uuid4()}__"

    try:
        paste(sentinel)
        hotkey(*copy_shortcut(platform))
        sleep(copy_delay_seconds)
        selected = copy()
        if selected == sentinel:
            return ""
        return selected
    finally:
        paste(previous)
