# ASR Profile Language Options Design

## Summary

Add a new ASR profile for the Hugging Face CTranslate2 model `Systran/faster-distil-whisper-small.en` and replace the Dictation tab's free-text language field with a constrained dropdown.

The language dropdown remains a single shared control for all ASR profiles, but each option is enabled or disabled based on the selected profile's supported languages. English-only profiles keep non-English options visible and unselectable.

## Goals

- Add an ASR profile that uses `Systran/faster-distil-whisper-small.en`.
- Preserve existing profiles and aliases.
- Make language selection safer in the desktop UI by using a dropdown.
- Disable unsupported language options for English-only Whisper models.
- Prevent saving an invalid language when the user switches from a multilingual profile to an English-only profile.
- Cover profile metadata and UI behavior with tests.

## Non-Goals

- No model download management UI.
- No backend API for dynamic model metadata discovery.
- No language auto-detection for English-only `.en` models.
- No redesign of the Dictation tab.

## Architecture

`services/asr/profiles.py` remains the source of truth for available runtime ASR profiles. The new profile will use the exact Hugging Face repo ID as its `model_name`, keep CPU/int8 execution consistent with existing faster-whisper profiles, and expose metadata describing supported languages.

The frontend will keep a local mirror of profile-to-language support for rendering the Dictation settings form. This is acceptable for this slice because the existing ASR profile list is already hard-coded in `src/App.tsx`; a later API metadata endpoint can remove that duplication.

## Profile Behavior

Add a profile named `distil-small-en` with:

- `model_name`: `Systran/faster-distil-whisper-small.en`
- `compute_type`: `int8`
- `cpu_threads`: `2`
- `speculative_cpu_threads`: `2`
- `speculative_enabled`: `False`
- supported language: `en`

The profile should be available through `asr_profile_names()`, `resolve_asr_profile("distil-small-en")`, runtime CLI choices, runtime settings, and the desktop ASR profile dropdown.

## Language Dropdown

Replace the Dictation tab language input with a `<select>`.

Initial options:

- Auto detect (`auto`)
- English (`en`)
- Arabic (`ar`)
- French (`fr`)
- German (`de`)
- Spanish (`es`)

When the selected ASR profile supports only English:

- English remains enabled.
- Auto detect and non-English languages render disabled.
- If current `settings.runtime.language` is unsupported, the UI coerces it to `en` when saving or when the profile changes.

When the selected ASR profile is multilingual:

- All listed options are enabled.
- `auto` is saved as `auto`, preserving the existing backend behavior where `normalize_language_arg("auto")` becomes `None` at runtime.

## Error Handling

Unsupported profile names continue to raise `ValueError` through `resolve_asr_profile`.

The UI should avoid invalid saved state by coercing unsupported languages to the first supported language for the selected profile. This keeps persisted `settings.yaml` usable even if a user changes profile after selecting another language.

## Testing

Backend tests:

- `tests/test_asr_profiles.py` verifies the new profile model name, thread settings, speculation setting, and supported languages.
- Existing runtime runner tests continue to confirm `asr_profile_names()` feeds CLI choices.

Frontend tests:

- `src/App.test.tsx` verifies the new profile appears in the ASR profile dropdown.
- `src/App.test.tsx` verifies non-English language options become disabled after selecting the English-only profile.
- `src/App.test.tsx` verifies saving after selecting the English-only profile persists `runtime.language` as `en` when the previous value was unsupported.

## Rollout

This is a local settings/profile change. Existing users keep the `low-impact` default profile unless they select the new profile in the Dictation tab or pass it through the runtime CLI.
