from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Any, Callable

from services.asr.profiles import DEFAULT_ASR_PROFILE, AsrProfile, asr_profile_names, resolve_asr_profile
from services.asr.audio_capture import AudioRecorder
from services.context.app_context import get_active_app_context
from services.injection.hotkeys import send_hotkey
from services.injection.selection_reader import read_selected_text
from services.pipeline.factory import build_pipeline
from services.runtime.correction_watcher import CorrectionWatcher
from services.runtime.hotkeys import HoldHotkeyController, HotkeyBackend
from services.runtime.logging import JsonlLogger
from services.runtime.session import RuntimeSession
from services.runtime.speculative import SpeculativeTranscriptionSession
from services.runtime.status import ConsoleStatusReporter, format_user_error


FindSpec = Callable[[str], Any]
Output = Callable[[str], None]


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    available: bool
    required: bool
    install_hint: str


BASE_DEPENDENCIES: tuple[DependencyStatus, ...] = (
    DependencyStatus("sounddevice", False, True, "pip install sounddevice"),
    DependencyStatus("faster_whisper", False, True, "pip install faster-whisper"),
    DependencyStatus("pyperclip", False, True, "pip install pyperclip"),
    DependencyStatus("ollama", False, False, "pip install ollama"),
)


def dependency_requirements(platform: str | None = None) -> tuple[DependencyStatus, ...]:
    platform_name = platform or sys.platform
    hotkey_dependency = (
        DependencyStatus("pyautogui", False, True, "pip install pyautogui")
        if platform_name == "darwin"
        else DependencyStatus("keyboard", False, True, "pip install keyboard")
    )
    optional_keyboard = (
        (DependencyStatus("keyboard", False, False, "pip install keyboard"),)
        if platform_name == "darwin"
        else ()
    )
    return (hotkey_dependency, *optional_keyboard, *BASE_DEPENDENCIES)


def dependency_readiness(
    find_spec: FindSpec = importlib.util.find_spec,
    platform: str | None = None,
) -> list[DependencyStatus]:
    results: list[DependencyStatus] = []
    for dependency in dependency_requirements(platform):
        results.append(
            DependencyStatus(
                name=dependency.name,
                available=find_spec(dependency.name) is not None,
                required=dependency.required,
                install_hint=dependency.install_hint,
            )
        )
    return results


def print_dependency_readiness(
    *,
    output: Output = print,
    find_spec: FindSpec = importlib.util.find_spec,
    platform: str | None = None,
) -> None:
    for dependency in dependency_readiness(find_spec, platform=platform):
        marker = "ok" if dependency.available else "missing"
        required = "required" if dependency.required else "optional"
        hint = "" if dependency.available else f" ({dependency.install_hint})"
        output(f"{dependency.name}: {marker} [{required}]{hint}")


def normalize_language_arg(language: str | None) -> str | None:
    if language is None:
        return None
    normalized = language.strip()
    if normalized.lower() in {"", "auto", "none"}:
        return None
    return normalized


def warm_pipeline_in_background(
    pipeline: Any,
    logger: Any,
    *,
    language: str | None,
    role: str = "main",
) -> Thread | None:
    transcriber = getattr(pipeline, "transcriber", None)
    warm_up = getattr(transcriber, "warm_up", None)
    if not callable(warm_up):
        return None

    def target() -> None:
        started = time.perf_counter()
        logger.log("pipeline_warmup_started", language=language or "auto", role=role)
        try:
            warm_up(language=language)
        except Exception as exc:
            logger.log("pipeline_warmup_error", error=str(exc), role=role)
            return
        logger.log(
            "pipeline_warmup_success",
            language=language or "auto",
            role=role,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    thread = Thread(target=target, name=f"localflow-whisper-{role}-warmup", daemon=True)
    thread.start()
    return thread


def create_runtime_session(
    *,
    root: str | Path | None = None,
    use_ollama: bool = False,
    logger_path: str | Path = "artifacts/logs/runtime.jsonl",
    status: Any | None = None,
    pipeline: Any | None = None,
    speculative_pipeline: Any | None = None,
    asr_profile: str | AsrProfile | None = DEFAULT_ASR_PROFILE,
    recorder_factory: Callable[[], Any] = AudioRecorder.microphone,
    quiet_mode: bool = False,
    selection_reader: Callable[[], str] | None = None,
    quality_fallback: bool = False,
) -> RuntimeSession:
    profile = resolve_asr_profile(asr_profile)
    log_fields = {
        **profile.log_fields(),
        "quiet_mode": quiet_mode,
        "quality_fallback_enabled": quality_fallback,
    }
    resolved_pipeline = pipeline or build_pipeline(
        root=root,
        use_ollama=use_ollama,
        quiet_mode=quiet_mode,
        **profile.pipeline_kwargs(),
    )
    use_speculative = profile.speculative_enabled or speculative_pipeline is not None
    resolved_speculative_pipeline = None
    speculative_factory = None
    if use_speculative:
        resolved_speculative_pipeline = speculative_pipeline
        if resolved_speculative_pipeline is None and pipeline is None:
            resolved_speculative_pipeline = build_pipeline(
                root=root,
                use_ollama=use_ollama,
                quiet_mode=quiet_mode,
                **profile.pipeline_kwargs(speculative=True),
            )
        elif resolved_speculative_pipeline is None:
            resolved_speculative_pipeline = resolved_pipeline
        speculative_factory = (
            lambda recorder, _pipeline, logger: create_speculative_session(
                recorder,
                resolved_speculative_pipeline,
                logger,
            )
        )

    fallback_pipeline = None
    fallback_profile_name = None
    if quality_fallback:
        fallback_profile = resolve_asr_profile("quality")
        fallback_profile_name = fallback_profile.name
        fallback_pipeline = build_pipeline(
            root=root,
            use_ollama=use_ollama,
            quiet_mode=quiet_mode,
            **fallback_profile.pipeline_kwargs(),
        )

    context_provider = getattr(resolved_pipeline, "context_provider", get_active_app_context)
    correction_watcher = CorrectionWatcher(context_provider=context_provider)
    return RuntimeSession(
        recorder_factory=recorder_factory,
        pipeline=resolved_pipeline,
        status=status or ConsoleStatusReporter(),
        logger=JsonlLogger(logger_path),
        speculative_factory=speculative_factory,
        speculative_pipeline=resolved_speculative_pipeline,
        log_fields=log_fields,
        selection_reader=selection_reader,
        fallback_pipeline=fallback_pipeline,
        fallback_profile=fallback_profile_name,
        correction_watcher=correction_watcher,
    )


def create_speculative_session(recorder: Any, pipeline: Any, logger: Any) -> SpeculativeTranscriptionSession:
    return SpeculativeTranscriptionSession(
        recorder=recorder,
        pipeline=pipeline,
        logger=logger,
    )


def create_hotkey_controller(
    session: RuntimeSession,
    *,
    backend: HotkeyBackend | None = None,
    hotkey: str = "ctrl+alt+space",
    cancel_key: str = "esc",
    language: str | None = None,
) -> HoldHotkeyController:
    return HoldHotkeyController(
        backend=backend,
        hold_key=hotkey,
        cancel_key=cancel_key,
        on_press=lambda: session.start_recording(language=language),
        on_release=lambda: session.stop_and_process(language=language),
        on_cancel=session.cancel,
    )


class CompositeHotkeyController:
    def __init__(self, controllers: list[HoldHotkeyController]) -> None:
        self.controllers = controllers

    def start(self) -> None:
        for controller in self.controllers:
            controller.start()

    def stop(self) -> None:
        for controller in reversed(self.controllers):
            controller.stop()


class CorrectionKeyObserver:
    def __init__(self, watcher: Any, *, keyboard_module: Any | None = None) -> None:
        self._watcher = watcher
        self._keyboard = keyboard_module
        self._hook: Any | None = None

    def start(self) -> None:
        if self._hook is not None:
            return
        keyboard_module = self._get_keyboard_module()
        key_down = getattr(keyboard_module, "KEY_DOWN", "down")

        def handler(event: Any) -> None:
            if getattr(event, "event_type", key_down) != key_down:
                return
            self._watcher.observe_key(getattr(event, "name", None))

        self._hook = keyboard_module.hook(handler)

    def stop(self) -> None:
        if self._hook is None:
            return
        keyboard_module = self._get_keyboard_module()
        keyboard_module.unhook(self._hook)
        self._hook = None

    def _get_keyboard_module(self) -> Any:
        if self._keyboard is None:
            import keyboard  # type: ignore

            self._keyboard = keyboard
        return self._keyboard


def create_runtime_hotkey_controller(
    session: RuntimeSession,
    *,
    backend: HotkeyBackend | None = None,
    hotkey: str = "ctrl+alt+space",
    command_hotkey: str = "ctrl+alt+e",
    cancel_key: str = "esc",
    language: str | None = None,
) -> CompositeHotkeyController:
    return CompositeHotkeyController(
        [
            create_hotkey_controller(
                session,
                backend=backend,
                hotkey=hotkey,
                cancel_key=cancel_key,
                language=language,
            ),
            HoldHotkeyController(
                backend=backend,
                hold_key=command_hotkey,
                cancel_key=cancel_key,
                on_press=lambda: session.start_command_recording(language=language),
                on_release=lambda: session.stop_and_process(language=language),
                on_cancel=session.cancel,
            ),
        ]
    )


def create_selection_reader() -> Callable[[], str]:
    try:
        import pyperclip  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Command mode requires pyperclip and the platform hotkey package."
        ) from exc

    return lambda: read_selected_text(
        copy=pyperclip.paste,
        paste=pyperclip.copy,
        hotkey=send_hotkey,
    )


def summarize_runtime_log(path: str | Path, *, limit: int = 100) -> list[str]:
    log_path = Path(path)
    if not log_path.exists():
        return [f"No runtime log found at {log_path}."]

    records: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)

    if not records:
        return [f"No runtime events found in {log_path}."]

    recent = records[-limit:]
    context = _last_record_with_any(
        recent,
        ("asr_profile", "asr_model", "asr_cpu_threads", "quiet_mode"),
    )
    profile = context.get("asr_profile", "unknown")
    model = context.get("asr_model", "unknown")
    threads = context.get("asr_cpu_threads", "unknown")
    quiet = context.get("quiet_mode", False)

    success_count = sum(1 for record in recent if record.get("event") == "dictation_success")
    command_success_count = sum(1 for record in recent if record.get("event") == "command_success")
    no_speech_count = sum(
        1
        for record in recent
        if record.get("event") in {"dictation_no_speech", "command_no_speech"}
    )
    error_count = sum(1 for record in recent if record.get("event") == "dictation_error")
    total_durations = [
        int(record["duration_ms"])
        for record in recent
        if _is_number(record.get("duration_ms"))
    ]
    asr_durations = [
        int(timings["asr_ms"])
        for record in recent
        if isinstance((timings := record.get("timings_ms")), dict)
        and _is_number(timings.get("asr_ms"))
    ]

    return [
        f"Runtime: profile={profile} model={model} threads={threads} quiet={quiet}",
        (
            f"Events: success={success_count} command_success={command_success_count} "
            f"no_speech={no_speech_count} errors={error_count}"
        ),
        (
            f"Latency: avg_total_ms={_average(total_durations)} "
            f"avg_asr_ms={_average(asr_durations)} recent_events={len(recent)}"
        ),
        *_live_latency_lines(recent),
    ]


def _last_record_with_any(records: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any]:
    for record in reversed(records):
        if any(key in record for key in keys):
            return record
    return {}


def _live_latency_lines(records: list[dict[str, Any]]) -> list[str]:
    groups: dict[tuple[Any, Any, Any], dict[str, list[int]]] = {}
    for record in records:
        if record.get("event") not in {"dictation_success", "command_success"}:
            continue
        timings = record.get("timings_ms")
        duration_ms = record.get("duration_ms")
        if not isinstance(timings, dict):
            continue
        if not _is_number(duration_ms):
            continue
        asr_ms = timings.get("asr_ms")
        if not _is_number(asr_ms):
            continue

        key = (
            record.get("asr_profile", "unknown"),
            record.get("asr_model", "unknown"),
            record.get("asr_cpu_threads", "unknown"),
        )
        group = groups.setdefault(key, {"total": [], "asr": [], "recording": []})
        group["total"].append(int(duration_ms))
        group["asr"].append(int(asr_ms))
        recording_ms = record.get("recording_ms")
        if _is_number(recording_ms):
            group["recording"].append(int(recording_ms))

    sorted_groups = sorted(
        groups.items(),
        key=lambda item: (
            _average(item[1]["asr"]),
            str(item[0][0]),
            str(item[0][1]),
            str(item[0][2]),
        ),
    )
    return [
        (
            f"Live profile latency: profile={profile} model={model} threads={threads} "
            f"runs={len(values['asr'])} avg_total_ms={_average(values['total'])} "
            f"avg_asr_ms={_average(values['asr'])} best_asr_ms={min(values['asr'])} "
            f"avg_recording_ms={_average(values['recording'])}"
        )
        for (profile, model, threads), values in sorted_groups
    ]


def _average(values: list[int]) -> int | str:
    if not values:
        return "n/a"
    return round(sum(values) / len(values))


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def main(
    argv: list[str] | None = None,
    *,
    output: Output = print,
    find_spec: FindSpec = importlib.util.find_spec,
) -> int:
    parser = argparse.ArgumentParser(description="Run LocalFlow push-to-talk dictation.")
    parser.add_argument("--hotkey", default="ctrl+alt+space")
    parser.add_argument("--command-hotkey", default="ctrl+alt+e")
    parser.add_argument("--cancel-key", default="esc")
    parser.add_argument(
        "--language",
        default="en",
        help="Language hint for Whisper. Use 'auto' to enable language detection.",
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--use-ollama", action="store_true")
    parser.add_argument("--log", type=Path, default=Path("artifacts/logs/runtime.jsonl"))
    parser.add_argument(
        "--profile",
        "--asr-profile",
        dest="asr_profile",
        default=DEFAULT_ASR_PROFILE,
        choices=asr_profile_names(),
        help=f"ASR profile. Available: {', '.join(asr_profile_names())}.",
    )
    parser.add_argument("--check", action="store_true", help="Print dependency readiness and exit.")
    parser.add_argument("--quiet", action="store_true", help="Use quiet dictation VAD settings.")
    parser.add_argument(
        "--quality-fallback",
        action="store_true",
        help="Retry no-speech dictation once with the quality ASR profile.",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print a summary of recent runtime log events and exit.",
    )
    args = parser.parse_args(argv)

    if args.check:
        print_dependency_readiness(output=output, find_spec=find_spec)
        return 0
    if args.diagnostics:
        for line in summarize_runtime_log(args.log):
            output(line)
        return 0

    try:
        language = normalize_language_arg(args.language)
        session = create_runtime_session(
            root=args.root,
            use_ollama=args.use_ollama,
            logger_path=args.log,
            asr_profile=args.asr_profile,
            quiet_mode=args.quiet,
            quality_fallback=args.quality_fallback,
            selection_reader=create_selection_reader(),
        )
        warm_pipeline_in_background(session.pipeline, session.logger, language=language, role="main")
        if session.speculative_pipeline is not None and session.speculative_pipeline is not session.pipeline:
            warm_pipeline_in_background(
                session.speculative_pipeline,
                session.logger,
                language=language,
                role="speculative",
            )
        controller = create_runtime_hotkey_controller(
            session,
            hotkey=args.hotkey,
            command_hotkey=args.command_hotkey,
            cancel_key=args.cancel_key,
            language=language,
        )
        correction_observer = CorrectionKeyObserver(session.correction_watcher)
        controller.start()
        correction_observer.start()
    except Exception as exc:
        output(format_user_error(exc))
        return 1

    output(
        f"LocalFlow running with {args.asr_profile} ASR profile. Hold {args.hotkey} to dictate, "
        f"hold {args.command_hotkey} to edit selected text, press {args.cancel_key} to cancel, "
        f"Ctrl+C to exit."
    )
    try:
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        output("LocalFlow stopped.")
        return 0
    finally:
        correction_observer.stop()
        controller.stop()


if __name__ == "__main__":
    raise SystemExit(main())
