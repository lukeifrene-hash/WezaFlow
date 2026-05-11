# WezaFlow

WezaFlow is a local-first desktop dictation pipeline inspired by Wispr Flow.
The implementation is organized as a Tauri desktop shell plus Python services for
audio capture, speech recognition, context detection, LLM formatting, and text
injection.

The first implementation slice focuses on stable module boundaries:

- `services/asr`: microphone capture, VAD, and Whisper transcription
- `services/context`: active app and browser context detection
- `services/llm`: local Ollama-based text formatting
- `services/injection`: clipboard and keyboard text insertion
- `services/pipeline`: shared contracts and orchestration
- `db`: SQLite schema for vocabulary, snippets, profiles, corrections, and history
- `scripts`: platform setup, startup, and test helpers

## Windows

Run the scaffold tests with:

```powershell
py -3 -m unittest discover -s tests -v
```

Build the Windows Tauri release with:

```powershell
npm run tauri -- build
```

## macOS test build

The macOS path is intended for developer testing from a GitHub checkout. It uses
the same Tauri shell and Python runtime, with macOS-specific Command+C/Command+V
text injection through `pyautogui`.

From a Mac:

```bash
bash scripts/setup_macos.sh
npm run tauri -- dev
```

For a local macOS release build:

```bash
npm run tauri -- build
```

On first use, macOS may prompt for Microphone and Accessibility permissions.
Grant Accessibility to the terminal during dev runs, or to WezaFlow when running
the built app. The GitHub workflow in `.github/workflows/build-macos.yml` can
produce a downloadable unsigned macOS test artifact from GitHub Actions. See
`docs/macos-test-build.md` for current limits.
