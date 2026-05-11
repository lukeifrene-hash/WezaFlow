from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from pathlib import Path

from services.asr.audio_capture import AudioRecorder


def record_wav(
    path: str | Path,
    seconds: float = 3.0,
    recorder_factory: Callable[[], AudioRecorder] = AudioRecorder.microphone,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    recorder = recorder_factory()
    try:
        recorder.start()
    except Exception as exc:
        raise RuntimeError(
            "Unable to start microphone recording. Install sounddevice and check "
            "microphone permissions/device availability."
        ) from exc

    sleep(seconds)
    wav_bytes = recorder.stop()
    output_path.write_bytes(wav_bytes)
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record a short microphone WAV smoke test.")
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--output", type=Path, default=Path("artifacts/test.wav"))
    args = parser.parse_args(argv)

    output_path = record_wav(args.output, seconds=args.seconds)
    print(f"Recorded {args.seconds:g}s WAV to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
