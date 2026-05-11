from __future__ import annotations

from typing import Any

from services.pipeline.factory import build_pipeline
from services.pipeline.models import PipelineResult
from services.runtime.api import create_app as create_runtime_api_app


def serialize_result(result: PipelineResult | None) -> dict[str, Any]:
    if result is None:
        return {"status": "no_speech"}
    payload = result.to_dict()
    payload["status"] = "ok"
    return payload


def create_app(pipeline: Any | None = None):
    try:
        from fastapi import HTTPException
    except ImportError as exc:
        raise RuntimeError("fastapi is required to run the LocalFlow pipeline server") from exc

    app = create_runtime_api_app()
    active_pipeline = pipeline or build_pipeline()

    @app.post("/process_samples")
    def process_samples(payload: dict[str, Any]) -> dict[str, Any]:
        samples = payload.get("samples")
        if not isinstance(samples, list):
            raise HTTPException(status_code=400, detail="samples must be a list of floats")
        result = active_pipeline.process_audio(
            samples,
            language=payload.get("language"),
            inject=bool(payload.get("inject", True)),
            vocabulary_hints=payload.get("vocabulary_hints"),
        )
        return serialize_result(result)

    @app.post("/command")
    def command(payload: dict[str, Any]) -> dict[str, Any]:
        selected_text = payload.get("selected_text")
        samples = payload.get("samples")
        if not isinstance(selected_text, str):
            raise HTTPException(status_code=400, detail="selected_text must be a string")
        if not isinstance(samples, list):
            raise HTTPException(status_code=400, detail="samples must be a list of floats")
        result = active_pipeline.process_command(
            selected_text,
            samples,
            language=payload.get("language"),
            inject=bool(payload.get("inject", True)),
        )
        return serialize_result(result)

    return app


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("uvicorn is required to run the LocalFlow pipeline server") from exc

    uvicorn.run(create_app(), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
