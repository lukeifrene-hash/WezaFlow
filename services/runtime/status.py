"""User-facing runtime status and error messages."""

from __future__ import annotations

from typing import Callable


_MISSING_DEPENDENCY_MESSAGES = {
    "sounddevice": "Audio dependency missing: install sounddevice, then rerun setup.",
    "keyboard": "Hotkey dependency missing: install keyboard and run from an elevated terminal if needed.",
    "pyautogui": "macOS text injection dependency missing: install pyautogui, then grant Accessibility permission if prompted.",
    "faster_whisper": "Whisper dependency missing: install faster-whisper or enable the ASR environment.",
}


def format_user_error(error: BaseException | str) -> str:
    """Return a concise, actionable message for common runtime failures."""

    if isinstance(error, ModuleNotFoundError):
        dependency_name = error.name
        if dependency_name in _MISSING_DEPENDENCY_MESSAGES:
            return _MISSING_DEPENDENCY_MESSAGES[dependency_name]

    message = str(error)
    normalized = message.lower().replace("-", "_")

    if "sounddevice" in normalized:
        return _MISSING_DEPENDENCY_MESSAGES["sounddevice"]
    if "keyboard" in normalized:
        return _MISSING_DEPENDENCY_MESSAGES["keyboard"]
    if "pyautogui" in normalized:
        return _MISSING_DEPENDENCY_MESSAGES["pyautogui"]
    if "faster_whisper" in normalized or "faster whisper" in normalized:
        return _MISSING_DEPENDENCY_MESSAGES["faster_whisper"]
    if "ollama" in normalized and (
        "refused" in normalized
        or "connection" in normalized
        or "connect" in normalized
        or "10061" in normalized
    ):
        return "Ollama is not reachable: start Ollama and confirm the local model is available."
    if "no speech" in normalized or "no_speech" in normalized:
        return "No speech detected: try again closer to the microphone."
    if "inject" in normalized or "clipboard" in normalized:
        return "Text injection failed: focus the target app and try again."

    return f"Runtime error: {message}" if message else "Runtime error: try again."


class ConsoleStatusReporter:
    """Write dictation runner state changes to an injectable output function."""

    def __init__(self, output: Callable[[str], None] = print):
        self._output = output

    def idle(self) -> None:
        self._output("Idle: press the dictation hotkey to start.")

    def recording(self) -> None:
        self._output("Recording...")

    def processing(self) -> None:
        self._output("Processing...")

    def success(self, text: str | None = None) -> None:
        if text:
            self._output(f"Inserted: {text}")
        else:
            self._output("Inserted dictation.")

    def no_speech(self) -> None:
        self._output(format_user_error("no speech"))

    def error(self, error: BaseException | str) -> None:
        self._output(format_user_error(error))
