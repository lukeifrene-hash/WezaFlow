# Recording Feedback Bar Design

## Summary

Add a compact Wispr Flow-style floating feedback bar that appears while WezaFlow is recording from the global dictation or command-mode hotkey. The bar should be visible outside the settings window, because recording is triggered globally while the user works in other apps.

## Goals

- Show immediate visual feedback when recording starts.
- Keep the feedback surface small and sleek.
- Show recording, processing, done, and error states.
- Reuse the existing Tauri hotkey press/release flow.
- Avoid adding manual recording controls to the feedback bar.
- Preserve the existing settings window layout.
- Rebuild the release desktop app after implementation.

## Non-Goals

- No live microphone amplitude analysis in this slice.
- No draggable or configurable overlay position.
- No transcript preview inside the overlay.
- No new settings screen for overlay customization.
- No redesign of the main WezaFlow shell.

## User Experience

The feedback bar is a small always-on-top pill near the bottom center of the screen. It should be compact enough to stay out of the way while still confirming that WezaFlow is listening.

Target visual shape:

- Width around `220px` to `280px`.
- Height around `38px` to `44px`.
- Frameless dark surface with a subtle shadow.
- Small green live dot for active recording.
- Short animated waveform with 4 to 6 bars.
- Brief label: `Listening`, `Command`, `Processing`, `Done`, or `Error`.
- Small timer while recording.

Lifecycle:

- Hidden by default.
- On dictation hotkey press: show `Listening` with animated waveform and timer.
- On command-mode hotkey press: show `Command` with animated waveform and timer.
- On hotkey release: show `Processing`.
- After runtime stop returns successfully: show `Done` briefly, then hide.
- If runtime start/stop fails: show `Error` briefly, then hide.

## Architecture

Add a second Tauri window labeled `recording-bar`. The window is hidden at startup, frameless, transparent, always on top, non-resizable, and not shown in the taskbar. The existing React app will render a dedicated overlay component when it detects the `recording-bar` window label; otherwise it renders the current settings UI.

Rust remains the source of truth for hotkey-driven overlay lifecycle because it already handles global keyboard and mouse press/release events. The Rust shell will emit overlay state events to the `recording-bar` window and show/hide that window around existing runtime start/stop calls.

React overlay code should stay small and presentation-focused. It listens for Tauri events, starts a local timer when recording begins, renders the compact pill, and resets itself when hidden.

## Desktop Window Behavior

Add a Tauri window in `src-tauri/tauri.conf.json`:

- label: `recording-bar`
- title: `WezaFlow Recording`
- width: about `300`
- height: about `72`
- visible: `false`
- decorations: `false`
- transparent: `true`
- alwaysOnTop: `true`
- resizable: `false`
- skipTaskbar: `true`
- focus: `false`

The Rust shell will position it near the bottom center of the primary monitor before showing it. If monitor geometry is unavailable, it can fall back to the configured window position.

## Event Contract

Emit a `recording-bar-state` event with:

- `state`: `listening`, `command`, `processing`, `done`, or `error`
- `mode`: `dictation` or `command`
- `message`: optional short message for error details

The event payload should be serializable from Rust and easy for React to consume.

## Error Handling

If the runtime API call fails during start, the overlay shows `Error` briefly and then hides. If runtime stop fails, it still restores system audio and hides after showing `Error`.

Overlay failures should not block recording behavior. If the overlay window cannot be found or shown, Rust should continue the existing runtime start/stop path.

## Testing

Frontend tests:

- `src/App.test.tsx` verifies the overlay view renders a compact recording bar when the app is mounted as the `recording-bar` window.
- `src/App.test.tsx` verifies the normal settings UI still renders in the main window.

Desktop shell tests:

- `tests/test_desktop_shell.py` verifies `recording-bar` exists in `tauri.conf.json`.
- `tests/test_desktop_shell.py` verifies the overlay window is hidden, frameless, transparent, always on top, and skipped from the taskbar.
- `tests/test_desktop_shell.py` verifies Rust emits `recording-bar-state` events and references the `recording-bar` label.

Verification:

- Run the focused frontend tests.
- Run the desktop shell tests.
- Run full Python unittest discovery.
- Run full Vitest suite.
- Run `npm run tauri build` to regenerate `src-tauri/target/release/localflow.exe`.

## Rollout

The release executable should be rebuilt after implementation. Users can test by running `src-tauri/target/release/localflow.exe`, pressing the configured dictation hotkey, and confirming the compact bottom-center bar appears while recording.
