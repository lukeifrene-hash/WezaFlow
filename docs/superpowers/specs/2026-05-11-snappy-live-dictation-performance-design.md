# Snappy Live Dictation Performance Design

## Goal

Make LocalFlow feel as fast as practical during real dictation while preserving reliable transcription quality and keeping the workstation usable with multiple apps open.

The work optimizes live release-to-text latency, not isolated model benchmark throughput. Existing model and thread tests in `docs/asr-model-thread-test-report.md` are the decision baseline.

## Constraints

- Keep the app local-first.
- Keep `small.en`, `int8`, CPU as the primary reliable ASR path because it had the best measured word error rate in the current benchmark pack.
- Allow short CPU spikes, but avoid making the default profile feel overwhelming while other apps are open.
- Preserve `low-impact` as the smooth fallback profile.
- Do not re-run a broad model search as part of this slice.

## Selected Approach

Add a `snappy` runtime profile using:

- model: `small.en`
- compute type: `int8`
- device: CPU
- CPU threads: 4
- speculative ASR: disabled for the first implementation pass
- supported languages: English only

This profile is the fast default candidate. It keeps the same ASR model and measured benchmark quality as `low-impact`, but uses a short four-thread CPU burst to reduce transcription latency. `low-impact` remains available for heavy multitasking or battery-sensitive sessions.

## Architecture

`services/asr/profiles.py` remains the backend source of truth for ASR profile definitions. The new `snappy` profile sits between `low-impact` and the heavier `quality` profile.

The desktop settings UI continues to mirror profile metadata locally in `src/App.tsx`, matching the current implementation pattern. It should expose `snappy` as a selectable profile with a clear label.

The runtime API keeps rebuilding the session when profile settings change. No new long-running service boundary is needed.

Diagnostics become part of the performance feature: live runtime history should summarize recent latency grouped by profile, model, and thread count so `low-impact` and `snappy` can be compared from real dictation rather than only benchmark clips.

## Data Flow

1. User selects the `snappy` profile in Dictation settings.
2. Settings are saved to `config/settings.yaml`.
3. Runtime API detects the profile change and resets the runtime session when safe.
4. The next session builds a `small.en` transcriber with 4 CPU threads.
5. Warmup runs in the background as it does today.
6. Each successful dictation logs profile, model, thread count, total latency, ASR latency, recording length, and existing diagnostics.
7. Diagnostics summarize recent live results by profile so the user can see whether `snappy` improves release-to-text latency enough to justify its CPU burst.

## Error Handling

Unknown profile names continue to raise the existing `ValueError` path.

If the runtime API cannot rebuild the session immediately because recording is active, it keeps the existing pending-reset behavior and applies the new profile after recording ends.

If warmup fails, the existing warmup error logging is enough for this slice. The first transcription can still load the model lazily.

If `snappy` feels too heavy in live use, the user can switch back to `low-impact` without losing settings compatibility.

## Testing

Backend tests should cover:

- `resolve_asr_profile("snappy")` returns `small.en`, `int8`, 4 threads, no speculation, English-only language support.
- `asr_profile_names()` includes `snappy`.
- CLI profile choices include `snappy` automatically through the existing profile-name source.

Frontend tests should cover:

- The Dictation settings profile dropdown includes `snappy`.
- English-only language constraints apply to `snappy`.
- Saving the `snappy` profile refreshes status and diagnostics like existing profile changes.

Runtime diagnostics tests should cover:

- Recent successful dictations are grouped by profile/model/thread count.
- Summaries include count, average total latency, average ASR latency, best ASR latency, and recent recording count.
- Diagnostics still behave when older log rows do not include every field.

Manual verification should cover:

- Run the existing Python unit test suite.
- Run the frontend test suite.
- Start the runtime, select `snappy`, warm up, and dictate into at least an editor and a browser text field.
- Compare recent diagnostics for `low-impact` and `snappy`.
- Confirm the machine remains comfortable with normal multi-app use during short transcription bursts.

## Out of Scope

- New model search.
- GPU acceleration.
- Streaming or incremental ASR architecture.
- Automatic CPU-load based profile switching.
- Changing `quality` fallback behavior.
- Making `snappy` the default before live measurements confirm it is comfortable.

## Acceptance Criteria

- `snappy` is available from backend runtime profiles and the desktop Dictation settings.
- Selecting `snappy` builds a 4-thread `small.en` runtime session.
- Live diagnostics can compare recent release-to-text timings by profile.
- Existing `low-impact` behavior remains unchanged.
- Automated tests pass.
- Manual live use shows faster release-to-text than `low-impact` without making common multitasking feel overloaded.
