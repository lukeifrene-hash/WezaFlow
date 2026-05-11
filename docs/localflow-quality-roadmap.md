# LocalFlow Quality Roadmap

## Summary
- Treat `low-impact` as the product baseline: `small.en`, 2 CPU threads, no speculative ASR.
- Shift focus from ASR model search to Wispr Flow-style quality infrastructure: cleanup, context, vocabulary, corrections, command mode, and whisper/quiet robustness.
- Keep the default path local-first and lightweight; heavier `balanced` / `quality` modes remain fallback probes, not the center of the product.

## Phase Roadmap

### Phase 1 - Deterministic Quality Pass v1
- Add a local cleanup layer behind `TextFormatter` without changing `TextFormatter.format(...)`.
- Handle spoken punctuation: `comma`, `period`, `question mark`, `new paragraph`, `newline`.
- Improve self-correction cleanup: `wait no`, `actually`, `scratch that`, `no make that`.
- Normalize common dictation forms: `three thirty` -> `3:30`, `fifty K` -> `50k`, lightweight capitalization.
- Make formatting app-aware:
  - `code`: minimal prose cleanup, preserve technical terms, avoid forced sentence punctuation.
  - `email` / `work_chat`: normal sentence punctuation and filler removal.
  - `other`: current general cleanup plus the new correction rules.
- Acceptance: benchmark pack WER must not regress; live low-impact release-to-text should stay around the current ~2s range.

### Phase 2 - Vocabulary And Correction Hints
- Wire `VocabularyStore` into the runtime pipeline so top vocabulary and corrections become formatter hints.
- Add ASR initial-prompt support in the pipeline using existing `Transcriber.transcribe(..., initial_prompt=...)`.
- Use vocabulary hints for proper noun cleanup such as `local flow` -> `LocalFlow`, `wispr flow` -> `Wispr Flow`.
- Correction watching is scoped to a 30-second window after successful dictation insertion only; command mode and later edits do not create prompts.
- Add simple scripts for manual management:
  - add vocabulary term
  - add correction pair
  - list current learned terms
- Acceptance: user-added terms affect future dictation without restarting the app where practical, or after restart if simpler for v1.

### Phase 3 - Context Awareness Upgrade
- Improve Windows context capture beyond process name/window title.
- For browsers, extract URL when feasible and classify Gmail, Slack, Teams, WhatsApp, etc. through `browser_url`.
- Add bounded visible-text extraction for active window context, capped to a small safe token budget.
- Feed `app_context.category`, `browser_url`, and visible text snippets into the cleanup/formatter layer.
- Acceptance: Chrome/Edge Gmail is classified as `email`, Slack/Teams as `work_chat`, and VS Code/Cursor as `code`.

### Phase 4 - Runtime Command Mode
- Wire the existing `process_command(...)` pipeline to a real hotkey.
- Use current selection reader to capture selected text, then record a spoken edit command.
- Support deterministic local commands first: concise, bullet list, uppercase/lowercase, rewrite lightly.
- Keep optional Ollama command editing behind an explicit flag, not default.
- Acceptance: selected text can be transformed and replaced in Notepad/VS Code/browser text fields.

### Phase 5 - Whisper / Quiet Speech Mode
- Add a runtime option for quiet dictation that lowers VAD thresholds and/or preserves more padding.
- Log whether quiet mode is active.
- Keep it profile-compatible, especially with `low-impact`.
- Acceptance: quiet speech is detected without increasing normal-mode false positives.

### Phase 6 - Optional Quality Fallback
- Keep local deterministic cleanup as default.
- Add an optional fallback path for hard cases:
  - local Ollama if enabled and available
  - `quality` ASR profile retry only when the user explicitly requests it or a later confidence heuristic says quality is poor
- Do not make cloud processing part of the default roadmap.
- Acceptance: fallback never slows normal low-impact dictation unless explicitly enabled.

### Phase 7 - Settings And UX Surface
- Expose profile, quiet mode, vocabulary, snippets, and command mode in the eventual desktop UI.
- Keep CLI/script support as the source of truth until Tauri UI work resumes.
- Add a small diagnostics view or command that summarizes recent latency, active profile, model, thread count, and error/no-speech counts.
- Acceptance: users can understand what mode they are in and why dictation feels fast or slow.

## Public Interfaces And Contracts
- Keep `TextFormatter.format(raw_text, app_context, vocabulary_hints=None)` stable.
- Add an internal cleanup engine with deterministic tests; expose it only through `TextFormatter`.
- Extend pipeline ASR calls to accept generated `initial_prompt` hints.
- Add runtime config/script options only when a phase needs them:
  - command mode hotkey
  - quiet mode flag
  - vocabulary/correction scripts
- Preserve current ASR profiles:
  - `low-impact`: default candidate, no speculation
  - `balanced`: optional speed/quality comparison
  - `quality`: fallback profile

## Test Plan
- Unit tests for cleanup rules:
  - fillers removed
  - spoken punctuation converted
  - self-corrections resolved
  - time/number normalization
  - code context avoids unwanted prose punctuation
- Integration tests for pipeline:
  - vocabulary hints reach formatter
  - ASR initial prompts are passed to transcriber
  - app context changes formatting behavior
- Runtime tests:
  - command mode reads selected text and injects edited text
  - quiet mode changes VAD config
  - logs include profile/context/fallback fields
- Manual acceptance after each phase:
  - run benchmark pack
  - dictate into Notepad, VS Code/Cursor, browser text field
  - compare latest `runtime.jsonl` timings and subjective error rate

## Assumptions
- Local-first and low machine impact remain the default product principles.
- `low-impact` is good enough to be the baseline until real mistakes prove otherwise.
- We prioritize quality infrastructure before more ASR model comparison.
- We do not add cloud services by default.
