from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from services.asr.profiles import resolve_asr_profile
from services.common.paths import ProjectPaths
from services.config.settings import load_settings, save_settings as persist_settings
from services.pipeline.models import PipelineResult
from services.runtime.runner import (
    DEFAULT_ASR_PROFILE,
    CorrectionKeyObserver,
    create_runtime_session,
    create_selection_reader,
    dependency_readiness,
    normalize_language_arg,
    summarize_runtime_log,
    warm_pipeline_in_background,
)
from services.snippets.store import delete_snippet, list_snippets, upsert_snippet
from services.vocabulary.store import VocabularyStore


FindSpec = Callable[[str], Any]

RUNTIME_API_CAPABILITIES = (
    "profile-session-refresh",
    "configured-runtime-diagnostics",
    "runtime-warmup",
)


@dataclass
class RuntimeApiState:
    root: Path
    log_path: Path
    find_spec: FindSpec
    session: Any | None = None
    profile: str = DEFAULT_ASR_PROFILE
    quiet_mode: bool = False
    quality_fallback: bool = False
    active_mode: str = "idle"
    correction_observer: Any | None = None
    pending_session_reset: bool = False

    @property
    def settings_path(self) -> Path:
        return self.root / "config" / "settings.yaml"

    @property
    def snippets_path(self) -> Path:
        return self.root / "config" / "snippets.yaml"

    @property
    def db_path(self) -> Path:
        return self.root / "db" / "localflow.db"

    def load_runtime_settings(self) -> dict[str, Any]:
        settings = load_settings(self.settings_path)
        self._apply_runtime_settings(settings)
        return settings

    def save_runtime_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        previous_config = _runtime_session_config(load_settings(self.settings_path))
        saved = persist_settings(self.settings_path, settings)
        next_config = _runtime_session_config(saved)
        self._apply_runtime_settings(saved)
        if next_config != previous_config:
            self.request_session_reset()
        return saved

    def request_session_reset(self) -> None:
        if self.session is None:
            self.pending_session_reset = False
            return
        if _state_value(getattr(self.session, "state", "idle")) == "recording":
            self.pending_session_reset = True
            return
        self.reset_session()

    def reset_session(self) -> None:
        if self.correction_observer is not None:
            try:
                self.correction_observer.stop()
            except Exception:
                pass
        self.correction_observer = None
        self.session = None
        self.pending_session_reset = False

    def diagnostic_lines(self, *, limit: int = 100) -> list[str]:
        self.load_runtime_settings()
        lines = summarize_runtime_log(self.log_path, limit=limit)
        if lines and lines[0].startswith("Runtime: "):
            history = [f"Last recording: {lines[0].removeprefix('Runtime: ')}", *lines[1:]]
        else:
            history = lines
        return [self._runtime_summary_line(), *history]

    def _apply_runtime_settings(self, settings: dict[str, Any]) -> None:
        runtime = settings.get("runtime", {})
        if isinstance(runtime, dict):
            self.profile = str(runtime.get("profile", self.profile) or DEFAULT_ASR_PROFILE)
            self.quiet_mode = bool(runtime.get("quiet_mode", self.quiet_mode))
            self.quality_fallback = bool(
                runtime.get("quality_fallback", self.quality_fallback)
            )

    def _runtime_summary_line(self) -> str:
        try:
            profile = resolve_asr_profile(self.profile)
            model = profile.model_name
            threads: int | str = profile.cpu_threads
        except ValueError:
            model = "unknown"
            threads = "unknown"
        return (
            f"Configured runtime: profile={self.profile} model={model} "
            f"threads={threads} quiet={self.quiet_mode}"
        )

    def ensure_session(self) -> Any:
        if self.session is not None:
            if (
                self.pending_session_reset
                and _state_value(getattr(self.session, "state", "idle")) != "recording"
            ):
                self.reset_session()
            else:
                return self.session

        settings = self.load_runtime_settings()
        runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
        self.session = create_runtime_session(
            root=self.root,
            use_ollama=bool(runtime.get("use_ollama", False)),
            logger_path=self.log_path,
            asr_profile=self.profile,
            quiet_mode=self.quiet_mode,
            quality_fallback=self.quality_fallback,
            selection_reader=_optional_selection_reader(),
        )
        self.correction_observer = _optional_correction_observer(self.session)
        self.warm_session(settings)
        return self.session

    def warm_session(self, settings: dict[str, Any] | None = None) -> None:
        if self.session is None:
            return
        settings = settings or self.load_runtime_settings()
        runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
        language = normalize_language_arg(runtime.get("language"))
        logger = getattr(self.session, "logger", None)
        if logger is None:
            return
        pipeline = getattr(self.session, "pipeline", None)
        if pipeline is not None:
            warm_pipeline_in_background(pipeline, logger, language=language, role="main")
        speculative_pipeline = getattr(self.session, "speculative_pipeline", None)
        if speculative_pipeline is not None:
            warm_pipeline_in_background(
                speculative_pipeline,
                logger,
                language=language,
                role="speculative",
            )

    def envelope(self) -> dict[str, Any]:
        self.load_runtime_settings()
        state = _state_value(getattr(self.session, "state", "idle")) if self.session else "idle"
        if self.pending_session_reset and state != "recording":
            self.reset_session()
            state = "idle"
        if state != "recording":
            self.active_mode = "idle"
        last_error = getattr(self.session, "last_error", None) if self.session else None
        return {
            "status": "ok",
            "state": state,
            "mode": self.active_mode,
            "profile": self.profile,
            "quiet_mode": self.quiet_mode,
            "quality_fallback": self.quality_fallback,
            "last_error": str(last_error) if last_error else None,
        }


def create_app(
    *,
    root: str | Path | None = None,
    session: Any | None = None,
    log_path: str | Path | None = None,
    find_spec: FindSpec = importlib.util.find_spec,
):
    try:
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:
        raise RuntimeError("fastapi is required to run the LocalFlow runtime API") from exc

    repo_root = _resolve_root(root)
    state = RuntimeApiState(
        root=repo_root,
        log_path=Path(log_path) if log_path is not None else repo_root / "artifacts" / "logs" / "runtime.jsonl",
        find_spec=find_spec,
        session=session,
    )
    app = FastAPI(title="LocalFlow Runtime API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=(
            r"^(https?://tauri\.localhost|tauri://localhost|"
            r"http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?)$"
        ),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status")
    def status() -> dict[str, Any]:
        return state.envelope()

    @app.post("/runtime/start")
    def start_runtime(payload: dict[str, Any]) -> dict[str, Any]:
        mode = str(payload.get("mode", "dictation") or "dictation")
        language = normalize_language_arg(payload.get("language"))
        session_obj = state.ensure_session()
        if mode == "command":
            started = session_obj.start_command_recording(language=language)
        elif mode == "dictation":
            started = session_obj.start_recording(language=language)
        else:
            raise HTTPException(status_code=400, detail="mode must be dictation or command")
        if started:
            state.active_mode = mode
        return state.envelope()

    @app.post("/runtime/stop")
    def stop_runtime(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        language = normalize_language_arg((payload or {}).get("language"))
        result = state.ensure_session().stop_and_process(language=language)
        response = state.envelope()
        response["result"] = _serialize_result(result)
        return response

    @app.post("/runtime/cancel")
    def cancel_runtime() -> dict[str, Any]:
        state.ensure_session().cancel()
        state.active_mode = "idle"
        return state.envelope()

    @app.get("/runtime/check")
    def check_runtime() -> dict[str, Any]:
        return {
            "status": "ok",
            "dependencies": [
                {
                    "name": dependency.name,
                    "available": dependency.available,
                    "required": dependency.required,
                    "install_hint": dependency.install_hint,
                }
                for dependency in dependency_readiness(state.find_spec)
            ],
        }

    @app.get("/runtime/capabilities")
    def runtime_capabilities() -> dict[str, Any]:
        return {"status": "ok", "capabilities": list(RUNTIME_API_CAPABILITIES)}

    @app.post("/runtime/warmup")
    def runtime_warmup() -> dict[str, Any]:
        state.ensure_session()
        return state.envelope()

    @app.get("/runtime/diagnostics")
    def runtime_diagnostics(limit: int = 100) -> dict[str, Any]:
        return {
            "status": "ok",
            "lines": state.diagnostic_lines(limit=limit),
        }

    @app.get("/settings")
    def get_settings() -> dict[str, Any]:
        return {"status": "ok", "settings": load_settings(state.settings_path)}

    @app.put("/settings")
    def put_settings(payload: dict[str, Any]) -> dict[str, Any]:
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            raise HTTPException(status_code=400, detail="settings must be an object")
        return {"status": "ok", "settings": state.save_runtime_settings(settings)}

    @app.get("/vocabulary/terms")
    def get_vocabulary_terms(limit: int | None = None) -> dict[str, Any]:
        return {"status": "ok", "terms": _vocabulary_store(state).list_vocabulary(limit=limit)}

    @app.post("/vocabulary/terms")
    def post_vocabulary_term(payload: dict[str, Any]) -> dict[str, Any]:
        word = str(payload.get("word", "")).strip()
        if not word:
            raise HTTPException(status_code=400, detail="word is required")
        store = _vocabulary_store(state)
        store.add_word(word)
        return {"status": "ok", "terms": store.list_vocabulary()}

    @app.delete("/vocabulary/terms/{word:path}")
    def delete_vocabulary_term(word: str) -> dict[str, Any]:
        store = _vocabulary_store(state)
        deleted = store.delete_word(word)
        return {"status": "ok", "deleted": deleted, "terms": store.list_vocabulary()}

    @app.get("/vocabulary/corrections")
    def get_corrections(limit: int | None = None) -> dict[str, Any]:
        return {
            "status": "ok",
            "corrections": _vocabulary_store(state).list_correction_pairs(limit=limit),
        }

    @app.post("/vocabulary/corrections")
    def post_correction(payload: dict[str, Any]) -> dict[str, Any]:
        original = str(payload.get("original", "")).strip()
        corrected = str(payload.get("corrected", "")).strip()
        if not original or not corrected:
            raise HTTPException(status_code=400, detail="original and corrected are required")
        store = _vocabulary_store(state)
        store.record_correction(original, corrected)
        return {"status": "ok", "corrections": store.list_correction_pairs()}

    @app.delete("/vocabulary/corrections")
    def delete_correction_pair(
        original: str = Query(...),
        corrected: str = Query(...),
    ) -> dict[str, Any]:
        store = _vocabulary_store(state)
        deleted = store.delete_correction(original, corrected)
        return {"status": "ok", "deleted": deleted, "corrections": store.list_correction_pairs()}

    @app.get("/corrections/pending")
    def get_pending_corrections() -> dict[str, Any]:
        watcher = _correction_watcher(state)
        if watcher is None or not hasattr(watcher, "list_pending"):
            return {"status": "ok", "pending": []}
        return {
            "status": "ok",
            "pending": [
                _serialize_pending_correction(item) for item in watcher.list_pending()
            ],
        }

    @app.post("/corrections/pending/{pending_id}/confirm")
    def confirm_pending_correction(pending_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        watcher = _correction_watcher(state)
        if watcher is None or not hasattr(watcher, "confirm_pending"):
            raise HTTPException(status_code=404, detail="pending correction not found")
        if not _pending_correction_exists(watcher, pending_id):
            raise HTTPException(status_code=404, detail="pending correction not found")

        original = str(payload.get("original", "")).strip()
        corrected = str(payload.get("corrected", "")).strip()
        if not original or not corrected:
            raise HTTPException(status_code=400, detail="original and corrected are required")

        result = watcher.confirm_pending(pending_id)
        if result is False:
            raise HTTPException(status_code=404, detail="pending correction not found")

        store = _vocabulary_store(state)
        store.record_correction(original, corrected)
        return {"status": "ok", "corrections": store.list_correction_pairs()}

    @app.post("/corrections/pending/{pending_id}/dismiss")
    def dismiss_pending_correction(pending_id: str) -> dict[str, Any]:
        watcher = _correction_watcher(state)
        if watcher is None or not hasattr(watcher, "dismiss_pending"):
            raise HTTPException(status_code=404, detail="pending correction not found")
        if not _pending_correction_exists(watcher, pending_id):
            raise HTTPException(status_code=404, detail="pending correction not found")

        result = watcher.dismiss_pending(pending_id)
        if result is False:
            raise HTTPException(status_code=404, detail="pending correction not found")
        return {"status": "ok"}

    @app.get("/learning/suggestions")
    def get_learning_suggestions() -> dict[str, Any]:
        return {
            "status": "ok",
            "suggestions": _vocabulary_store(state).learning_suggestions(),
        }

    @app.get("/snippets")
    def get_snippets() -> dict[str, Any]:
        return {"status": "ok", "snippets": list_snippets(state.snippets_path)}

    @app.post("/snippets")
    def post_snippet(payload: dict[str, Any]) -> dict[str, Any]:
        trigger_phrase = str(payload.get("trigger_phrase", "")).strip()
        expansion = str(payload.get("expansion", ""))
        if not trigger_phrase:
            raise HTTPException(status_code=400, detail="trigger_phrase is required")
        snippets = upsert_snippet(state.snippets_path, trigger_phrase, expansion)
        return {"status": "ok", "snippets": snippets}

    @app.delete("/snippets/{trigger_phrase:path}")
    def delete_snippet_endpoint(trigger_phrase: str) -> dict[str, Any]:
        deleted = delete_snippet(state.snippets_path, trigger_phrase)
        return {"status": "ok", "deleted": deleted, "snippets": list_snippets(state.snippets_path)}

    return app


def _resolve_root(root: str | Path | None) -> Path:
    if root is not None:
        return Path(root).resolve()
    return ProjectPaths.discover().repo_root


def _vocabulary_store(state: RuntimeApiState) -> VocabularyStore:
    return VocabularyStore(state.db_path)


def _correction_watcher(state: RuntimeApiState) -> Any | None:
    session = state.ensure_session()
    return getattr(session, "correction_watcher", None)


def _runtime_session_config(settings: dict[str, Any]) -> tuple[str, bool, bool, bool]:
    runtime = settings.get("runtime", {}) if isinstance(settings.get("runtime"), dict) else {}
    return (
        str(runtime.get("profile", DEFAULT_ASR_PROFILE) or DEFAULT_ASR_PROFILE),
        bool(runtime.get("use_ollama", False)),
        bool(runtime.get("quiet_mode", False)),
        bool(runtime.get("quality_fallback", False)),
    )


def _pending_correction_exists(watcher: Any, pending_id: str) -> bool:
    if not hasattr(watcher, "list_pending"):
        return True
    return any(
        str(_pending_correction_value(item, "id") or "") == pending_id
        for item in watcher.list_pending()
    )


def _serialize_pending_correction(item: Any) -> dict[str, str | None]:
    return {
        "id": str(_pending_correction_value(item, "id") or ""),
        "original": str(_pending_correction_value(item, "original") or ""),
        "raw_transcript": str(_pending_correction_value(item, "raw_transcript") or ""),
        "app_name": _optional_pending_string(item, "app_name"),
        "window_title": _optional_pending_string(item, "window_title"),
        "detected_at": str(_pending_correction_value(item, "detected_at") or ""),
    }


def _optional_pending_string(item: Any, key: str) -> str | None:
    value = _pending_correction_value(item, key)
    return str(value) if value is not None else None


def _pending_correction_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _optional_selection_reader() -> Callable[[], str] | None:
    try:
        return create_selection_reader()
    except RuntimeError:
        return None


def _optional_correction_observer(session: Any) -> Any | None:
    watcher = getattr(session, "correction_watcher", None)
    if watcher is None:
        return None
    try:
        observer = CorrectionKeyObserver(watcher)
        observer.start()
        return observer
    except Exception:
        return None


def _serialize_result(result: PipelineResult | None) -> dict[str, Any]:
    if result is None:
        return {"status": "no_speech"}
    payload = result.to_dict()
    payload["status"] = "ok"
    return payload


def _state_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("uvicorn is required to run the LocalFlow runtime API") from exc

    uvicorn.run(create_app(), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
