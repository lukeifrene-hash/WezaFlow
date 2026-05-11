from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from services.context.profiles import classify_app, is_browser_process
from services.pipeline.models import AppContext


_VISIBLE_TEXT_MAX_CHARS = 600
_VISIBLE_TEXT_MAX_ITEMS = 8
_VISIBLE_TEXT_MAX_DEPTH = 4
_BROWSER_URL_MAX_CONTROLS = 32


def get_active_app_context() -> AppContext:
    """Return active app context, falling back cleanly when desktop APIs are absent."""
    try:
        process_name, window_title = _read_active_window()
    except Exception:
        return _fallback_context()

    if not process_name:
        return _fallback_context()

    browser_url = None
    if is_browser_process(process_name):
        try:
            browser_url = _read_browser_url(process_name, window_title)
        except Exception:
            browser_url = None

    try:
        visible_text = _read_visible_text()
    except Exception:
        visible_text = []

    return AppContext(
        app_name=process_name,
        window_title=window_title,
        category=classify_app(process_name, window_title, browser_url=browser_url),
        browser_url=browser_url,
        visible_text=visible_text,
    )


def _fallback_context() -> AppContext:
    return AppContext(
        app_name="unknown",
        window_title="",
        category="other",
        browser_url=None,
        visible_text=[],
    )


def _read_active_window() -> tuple[str, str]:
    win32gui, win32process, psutil = _import_windows_window_dependencies()

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return "", ""

    window_title = win32gui.GetWindowText(hwnd) or ""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process_name = Path(psutil.Process(pid).name()).name
    return process_name, window_title


def _read_browser_url(process_name: str, window_title: str) -> str | None:
    del process_name, window_title

    try:
        Desktop = _import_pywinauto_desktop()
        active_window = Desktop(backend="uia").get_active()
        controls = active_window.descendants(control_type="Edit")
    except Exception:
        return None

    for control in controls[:_BROWSER_URL_MAX_CONTROLS]:
        browser_url = _coerce_browser_url(_control_text(control))
        if browser_url is not None:
            return browser_url

    return None


def _read_visible_text() -> list[str]:
    try:
        automation = _import_uiautomation()
        root = automation.GetForegroundControl()
    except Exception:
        return []

    return _collect_bounded_visible_text(root)


def _collect_bounded_visible_text(
    root: Any,
    *,
    max_chars: int = _VISIBLE_TEXT_MAX_CHARS,
    max_items: int = _VISIBLE_TEXT_MAX_ITEMS,
) -> list[str]:
    if root is None or max_chars <= 0 or max_items <= 0:
        return []

    snippets: list[str] = []
    remaining_chars = max_chars
    seen_elements: set[int] = set()
    seen_text: set[str] = set()
    queue: list[tuple[Any, int]] = [(root, 0)]

    while queue and remaining_chars > 0 and len(snippets) < max_items:
        element, depth = queue.pop(0)
        element_id = id(element)
        if element_id in seen_elements:
            continue
        seen_elements.add(element_id)

        text = _normalize_visible_text(_element_text(element))
        if text and text not in seen_text:
            seen_text.add(text)
            snippet = text[:remaining_chars]
            if snippet:
                snippets.append(snippet)
                remaining_chars -= len(snippet)

        if depth >= _VISIBLE_TEXT_MAX_DEPTH:
            continue

        for child in _element_children(element):
            queue.append((child, depth + 1))

    return snippets


def _import_windows_window_dependencies():
    import psutil  # type: ignore[import-not-found]
    import win32gui  # type: ignore[import-not-found]
    import win32process  # type: ignore[import-not-found]

    return win32gui, win32process, psutil


def _import_pywinauto_desktop():
    from pywinauto import Desktop  # type: ignore[import-not-found]

    return Desktop


def _import_uiautomation():
    import uiautomation  # type: ignore[import-not-found]

    return uiautomation


def _control_text(control: Any) -> str:
    for method_name in ("get_value", "window_text"):
        method = getattr(control, method_name, None)
        if callable(method):
            try:
                value = method()
            except Exception:
                continue
            if isinstance(value, str) and value.strip():
                return value.strip()

    return _element_text(control)


def _coerce_browser_url(candidate: str) -> str | None:
    value = candidate.strip()
    if not value:
        return None

    normalized = value.casefold()
    if normalized.startswith(("http://", "https://")):
        return value

    if normalized.startswith(("about:", "chrome:", "edge:", "brave:", "file:")):
        return value

    if "." in value and " " not in value:
        return f"https://{value}"

    return None


def _element_text(element: Any) -> str:
    for attr_name in ("Name", "CurrentName", "name"):
        value = getattr(element, attr_name, "")
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        if isinstance(value, str) and value.strip():
            return value

    return ""


def _element_children(element: Any) -> Iterable[Any]:
    for method_name in ("GetChildren", "GetChildrenControls", "children"):
        method = getattr(element, method_name, None)
        if not callable(method):
            continue
        try:
            children = method()
        except Exception:
            continue
        if children is not None:
            return children

    return ()


def _normalize_visible_text(value: str) -> str:
    return " ".join(value.split())
