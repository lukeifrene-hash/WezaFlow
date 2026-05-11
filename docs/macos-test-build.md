# macOS Test Build

This is the first macOS lane for WezaFlow. It is meant for a developer-style
GitHub checkout, not a signed public installer.

## What Works First

- Tauri desktop shell builds on macOS through GitHub Actions.
- Python runtime API starts from the repo-local `.venv`.
- Dictation uses the same ASR profiles, including `snappy`.
- Text insertion uses the macOS Command+V shortcut through `pyautogui`.
- Command mode selection reads use Command+C.
- Windows-only app-context APIs fall back to an unknown app context instead of
  stopping dictation.

## Known Limits

- The artifact is unsigned, so macOS Gatekeeper may require manual approval.
- The app is not notarized.
- Mouse side-button hotkeys are Windows-only for now; use keyboard shortcuts on
  macOS.
- Context detection is basic on macOS until native accessibility readers are
  added.
- The app currently expects a source checkout with `.venv` and model cache
  setup, rather than a self-contained Python bundle.

## Local Mac Setup

```bash
bash scripts/setup_macos.sh
npm run tauri -- dev
```

For a release bundle:

```bash
npm run tauri -- build
```

The built `.app` appears under `src-tauri/target/release/bundle/macos/`.

## Permissions

macOS may request Microphone access for recording. It may also require
Accessibility access for the terminal during development, or for WezaFlow when
running the built app, so that `pyautogui` can paste text into the focused app.

## GitHub Artifact

The workflow at `.github/workflows/build-macos.yml` can be run manually from the
Actions tab. It uploads `WezaFlow-macOS-test-build`, containing the unsigned
macOS bundle produced by Tauri.
