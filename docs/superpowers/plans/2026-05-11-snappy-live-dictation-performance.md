# Snappy Live Dictation Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `snappy` live dictation profile that uses short, tolerable CPU bursts to reduce release-to-text latency, and improve diagnostics so live profile performance can be compared.

**Architecture:** Backend ASR profiles remain the source of truth in `services/asr/profiles.py`; the desktop UI keeps its existing local profile metadata mirror in `src/App.tsx`. Runtime diagnostics in `services/runtime/runner.py` will keep the existing three-line summary and append grouped live latency rows by profile/model/thread count.

**Tech Stack:** Python `unittest`, FastAPI runtime API, faster-whisper profile config, React 19, Vitest, Testing Library.

---

## File Structure

- Modify: `tests/test_asr_profiles.py`
  - Adds backend assertions for the new `snappy` profile.
- Modify: `services/asr/profiles.py`
  - Adds `snappy` as `small.en`, `int8`, 4 CPU threads, English-only, no speculation.
- Modify: `tests/test_runtime_runner.py`
  - Adds runtime session build assertions for `snappy`.
  - Adds diagnostics grouping assertions for recent profile/model/thread performance.
- Modify: `services/runtime/runner.py`
  - Adds grouped live latency summary helpers used by `summarize_runtime_log`.
- Modify: `src/App.test.tsx`
  - Adds dropdown and save-refresh coverage for `snappy`.
- Modify: `src/App.tsx`
  - Adds `snappy` to the frontend ASR profile options with English-only language support.

This workspace currently has no `.git` metadata, so execution should use verification checkpoints instead of commit checkpoints. If the plan is run from a real Git checkout, commit after each task using the suggested commit messages.

---

### Task 1: Backend ASR Profile

**Files:**
- Modify: `tests/test_asr_profiles.py`
- Modify: `services/asr/profiles.py`

- [ ] **Step 1: Write the failing profile test**

Update `tests/test_asr_profiles.py` so `test_runtime_profiles_capture_model_thread_and_compute_choices` resolves and checks `snappy`.

```python
    def test_runtime_profiles_capture_model_thread_and_compute_choices(self):
        from services.asr.profiles import resolve_asr_profile

        low_impact = resolve_asr_profile("low-impact")
        snappy = resolve_asr_profile("snappy")
        balanced = resolve_asr_profile("balanced")
        quality = resolve_asr_profile("quality")
        distil_small = resolve_asr_profile("distil-small-en")

        self.assertEqual(low_impact.model_name, "small.en")
        self.assertEqual(low_impact.cpu_threads, 2)
        self.assertEqual(low_impact.speculative_cpu_threads, 2)
        self.assertFalse(low_impact.speculative_enabled)
        self.assertEqual(low_impact.supported_languages, ("en",))
        self.assertEqual(snappy.model_name, "small.en")
        self.assertEqual(snappy.cpu_threads, 4)
        self.assertEqual(snappy.speculative_cpu_threads, 2)
        self.assertFalse(snappy.speculative_enabled)
        self.assertEqual(snappy.supported_languages, ("en",))
        self.assertEqual(balanced.model_name, "small.en")
        self.assertEqual(balanced.cpu_threads, 4)
        self.assertEqual(balanced.speculative_cpu_threads, 2)
        self.assertTrue(balanced.speculative_enabled)
        self.assertEqual(balanced.supported_languages, ("en",))
        self.assertEqual(quality.model_name, "distil-large-v3")
        self.assertEqual(quality.cpu_threads, 6)
        self.assertEqual(quality.speculative_cpu_threads, 2)
        self.assertTrue(quality.speculative_enabled)
        self.assertIsNone(quality.supported_languages)
        self.assertEqual(distil_small.model_name, "Systran/faster-distil-whisper-small.en")
        self.assertEqual(distil_small.cpu_threads, 2)
        self.assertEqual(distil_small.speculative_cpu_threads, 2)
        self.assertFalse(distil_small.speculative_enabled)
        self.assertEqual(distil_small.supported_languages, ("en",))
        self.assertEqual(
            {
                low_impact.compute_type,
                snappy.compute_type,
                balanced.compute_type,
                quality.compute_type,
                distil_small.compute_type,
            },
            {"int8"},
        )
```

Add a focused profile-name test:

```python
    def test_asr_profile_names_include_snappy(self):
        from services.asr.profiles import asr_profile_names

        self.assertIn("snappy", asr_profile_names())
```

- [ ] **Step 2: Run backend profile tests and confirm failure**

Run:

```powershell
py -3 -m unittest tests.test_asr_profiles -v
```

Expected: failure with `Unknown ASR profile: snappy` or missing profile-name assertion.

- [ ] **Step 3: Add the `snappy` profile**

Modify `ASR_PROFILES` in `services/asr/profiles.py` so the beginning of the dict reads:

```python
ASR_PROFILES: dict[str, AsrProfile] = {
    "low-impact": AsrProfile(
        name="low-impact",
        model_name="small.en",
        compute_type="int8",
        cpu_threads=2,
        speculative_cpu_threads=2,
        speculative_enabled=False,
        supported_languages=("en",),
    ),
    "snappy": AsrProfile(
        name="snappy",
        model_name="small.en",
        compute_type="int8",
        cpu_threads=4,
        speculative_cpu_threads=2,
        speculative_enabled=False,
        supported_languages=("en",),
    ),
    "balanced": AsrProfile(
        name="balanced",
        model_name="small.en",
        compute_type="int8",
        cpu_threads=4,
        speculative_cpu_threads=2,
        speculative_enabled=True,
        supported_languages=("en",),
    ),
```

- [ ] **Step 4: Run backend profile tests and confirm pass**

Run:

```powershell
py -3 -m unittest tests.test_asr_profiles -v
```

Expected: all tests in `tests.test_asr_profiles` pass.

- [ ] **Step 5: Checkpoint**

If executing in a Git checkout:

```powershell
git add tests/test_asr_profiles.py services/asr/profiles.py
git commit -m "feat: add snappy ASR profile"
```

In this workspace without `.git`, record that Task 1 passed `py -3 -m unittest tests.test_asr_profiles -v`.

---

### Task 2: Runtime Session Build Behavior

**Files:**
- Modify: `tests/test_runtime_runner.py`
- Verify: `services/runtime/runner.py`

- [ ] **Step 1: Write the failing runtime build test**

Add this test after `test_create_runtime_session_disables_speculation_for_low_impact_profile` in `tests/test_runtime_runner.py`:

```python
    def test_create_runtime_session_builds_snappy_without_speculation(self):
        import services.runtime.runner as runner_module

        original_build_pipeline = runner_module.build_pipeline

        class Pipeline:
            pass

        calls = []

        def fake_build_pipeline(**kwargs):
            calls.append(kwargs)
            return Pipeline()

        runner_module.build_pipeline = fake_build_pipeline
        try:
            session = runner_module.create_runtime_session(
                root=Path(__file__).resolve().parents[1],
                recorder_factory=lambda: object(),
                status=object(),
                asr_profile="snappy",
            )
        finally:
            runner_module.build_pipeline = original_build_pipeline

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["whisper_model_name"], "small.en")
        self.assertEqual(calls[0]["whisper_compute_type"], "int8")
        self.assertEqual(calls[0]["whisper_cpu_threads"], 4)
        self.assertIsNone(session.speculative_factory)
        self.assertIsNone(session.speculative_pipeline)
        self.assertEqual(session.logger.fields["asr_profile"], "snappy")
```

- [ ] **Step 2: Run runtime runner tests for the new behavior**

Run:

```powershell
py -3 -m unittest tests.test_runtime_runner.RuntimeRunnerTests.test_create_runtime_session_builds_snappy_without_speculation -v
```

Expected: pass after Task 1, because `create_runtime_session` already consumes profile metadata through `resolve_asr_profile`.

- [ ] **Step 3: Check CLI choices source**

No code change should be needed because `main()` already uses:

```python
choices=asr_profile_names()
```

Run:

```powershell
py -3 -m unittest tests.test_runtime_runner.RuntimeRunnerTests.test_run_dictation_script_invokes_runtime_runner -v
```

Expected: pass. The script accepts `$Profile` and forwards `--profile`; choices come from runtime code.

- [ ] **Step 4: Checkpoint**

If executing in a Git checkout:

```powershell
git add tests/test_runtime_runner.py
git commit -m "test: cover snappy runtime session wiring"
```

In this workspace without `.git`, record that the two Task 2 commands passed.

---

### Task 3: Frontend Profile Option

**Files:**
- Modify: `src/App.test.tsx`
- Modify: `src/App.tsx`

- [ ] **Step 1: Write the failing dropdown test**

Add this test after `shows the distil small English ASR profile in dictation settings` in `src/App.test.tsx`:

```tsx
  it("shows the snappy ASR profile in dictation settings", async () => {
    render(<App client={fakeClient()} />);

    await userEvent.click(await screen.findByRole("tab", { name: "Dictation" }));

    expect(screen.getByRole("option", { name: "snappy" })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the failing frontend test**

Run:

```powershell
npm test -- --runInBand src/App.test.tsx
```

If Vitest rejects `--runInBand`, use:

```powershell
npm test -- src/App.test.tsx
```

Expected: failure because the `snappy` option does not exist.

- [ ] **Step 3: Add `snappy` to frontend profile metadata**

Modify `ASR_PROFILE_OPTIONS` in `src/App.tsx`:

```tsx
const ASR_PROFILE_OPTIONS: AsrProfileOption[] = [
  { value: "low-impact", label: "low-impact", supportedLanguages: ["en"] },
  { value: "snappy", label: "snappy", supportedLanguages: ["en"] },
  { value: "balanced", label: "balanced", supportedLanguages: ["en"] },
  { value: "quality", label: "quality" },
  { value: "distil-small-en", label: "distil-small-en", supportedLanguages: ["en"] }
];
```

- [ ] **Step 4: Add English-only language test coverage for `snappy`**

Extend the existing `disables unsupported language options for English-only ASR profiles` test by changing the selected profile from `distil-small-en` to `snappy`:

```tsx
    fireEvent.change(screen.getByRole("combobox", { name: "ASR profile" }), {
      target: { value: "snappy" }
    });
```

This keeps the test focused on English-only behavior while `distil-small-en` remains covered by the dropdown test.

- [ ] **Step 5: Run frontend tests**

Run:

```powershell
npm test -- src/App.test.tsx
```

Expected: all tests in `src/App.test.tsx` pass.

- [ ] **Step 6: Checkpoint**

If executing in a Git checkout:

```powershell
git add src/App.test.tsx src/App.tsx
git commit -m "feat: expose snappy profile in settings"
```

In this workspace without `.git`, record that `npm test -- src/App.test.tsx` passed.

---

### Task 4: Runtime Diagnostics Grouping

**Files:**
- Modify: `tests/test_runtime_runner.py`
- Modify: `services/runtime/runner.py`

- [ ] **Step 1: Write the failing diagnostics grouping test**

Add this test after `test_summarize_runtime_log_reports_recent_diagnostics` in `tests/test_runtime_runner.py`:

```python
    def test_summarize_runtime_log_groups_live_latency_by_profile(self):
        from services.runtime.runner import summarize_runtime_log

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "runtime.jsonl"
            records = [
                {
                    "event": "dictation_success",
                    "duration_ms": 3000,
                    "recording_ms": 1200,
                    "timings_ms": {"asr_ms": 2800, "total_ms": 3000},
                    "asr_profile": "low-impact",
                    "asr_model": "small.en",
                    "asr_cpu_threads": 2,
                    "quiet_mode": False,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 2200,
                    "recording_ms": 1300,
                    "timings_ms": {"asr_ms": 2000, "total_ms": 2200},
                    "asr_profile": "snappy",
                    "asr_model": "small.en",
                    "asr_cpu_threads": 4,
                    "quiet_mode": False,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 1800,
                    "recording_ms": 900,
                    "timings_ms": {"asr_ms": 1600, "total_ms": 1800},
                    "asr_profile": "snappy",
                    "asr_model": "small.en",
                    "asr_cpu_threads": 4,
                    "quiet_mode": False,
                },
                {
                    "event": "dictation_success",
                    "duration_ms": 900,
                    "timings_ms": {"asr_ms": 700, "total_ms": 900},
                },
            ]
            log_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )

            lines = summarize_runtime_log(log_path)

        self.assertTrue(
            any(
                "Live profile latency: profile=snappy model=small.en threads=4 runs=2 "
                "avg_total_ms=2000 avg_asr_ms=1800 best_asr_ms=1600 avg_recording_ms=1100"
                in line
                for line in lines
            )
        )
        self.assertTrue(
            any(
                "Live profile latency: profile=low-impact model=small.en threads=2 runs=1 "
                "avg_total_ms=3000 avg_asr_ms=2800 best_asr_ms=2800 avg_recording_ms=1200"
                in line
                for line in lines
            )
        )
```

- [ ] **Step 2: Run the failing diagnostics test**

Run:

```powershell
py -3 -m unittest tests.test_runtime_runner.RuntimeRunnerTests.test_summarize_runtime_log_groups_live_latency_by_profile -v
```

Expected: failure because no `Live profile latency` lines exist yet.

- [ ] **Step 3: Add grouping helpers in `services/runtime/runner.py`**

Add this helper below `_last_record_with_any`:

```python
def _live_latency_lines(records: list[dict[str, Any]]) -> list[str]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        if record.get("event") not in {"dictation_success", "command_success"}:
            continue
        timings = record.get("timings_ms")
        if not isinstance(timings, dict):
            continue
        if not isinstance(record.get("duration_ms"), int | float):
            continue
        if not isinstance(timings.get("asr_ms"), int | float):
            continue

        profile = str(record.get("asr_profile") or "unknown")
        model = str(record.get("asr_model") or "unknown")
        threads = str(record.get("asr_cpu_threads") or "unknown")
        groups.setdefault((profile, model, threads), []).append(record)

    lines: list[str] = []
    for (profile, model, threads), group in sorted(
        groups.items(),
        key=lambda item: (
            _average(
                [
                    int(record["timings_ms"]["asr_ms"])
                    for record in item[1]
                    if isinstance(record.get("timings_ms"), dict)
                    and isinstance(record["timings_ms"].get("asr_ms"), int | float)
                ]
            )
            if isinstance(
                _average(
                    [
                        int(record["timings_ms"]["asr_ms"])
                        for record in item[1]
                        if isinstance(record.get("timings_ms"), dict)
                        and isinstance(record["timings_ms"].get("asr_ms"), int | float)
                    ]
                ),
                int,
            )
            else 999999,
            item[0],
        ),
    ):
        total_durations = [int(record["duration_ms"]) for record in group]
        asr_durations = [int(record["timings_ms"]["asr_ms"]) for record in group]
        recording_durations = [
            int(record["recording_ms"])
            for record in group
            if isinstance(record.get("recording_ms"), int | float)
        ]
        lines.append(
            "Live profile latency: "
            f"profile={profile} model={model} threads={threads} runs={len(group)} "
            f"avg_total_ms={_average(total_durations)} "
            f"avg_asr_ms={_average(asr_durations)} "
            f"best_asr_ms={min(asr_durations)} "
            f"avg_recording_ms={_average(recording_durations)}"
        )
    return lines
```

Then simplify the sort key before finalizing implementation if desired by introducing a local `avg_asr` variable. Keep behavior identical to the test.

- [ ] **Step 4: Append live latency lines to the summary**

Modify the return value of `summarize_runtime_log`:

```python
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
```

- [ ] **Step 5: Refine helper for readability before running the full test file**

Replace the verbose sort in `_live_latency_lines` with this clearer version:

```python
    summaries: list[tuple[int, str, str, str, list[dict[str, Any]]]] = []
    for (profile, model, threads), group in groups.items():
        asr_durations = [int(record["timings_ms"]["asr_ms"]) for record in group]
        avg_asr = _average(asr_durations)
        summaries.append(
            (
                avg_asr if isinstance(avg_asr, int) else 999999,
                profile,
                model,
                threads,
                group,
            )
        )

    lines: list[str] = []
    for _, profile, model, threads, group in sorted(summaries):
        total_durations = [int(record["duration_ms"]) for record in group]
        asr_durations = [int(record["timings_ms"]["asr_ms"]) for record in group]
        recording_durations = [
            int(record["recording_ms"])
            for record in group
            if isinstance(record.get("recording_ms"), int | float)
        ]
        lines.append(
            "Live profile latency: "
            f"profile={profile} model={model} threads={threads} runs={len(group)} "
            f"avg_total_ms={_average(total_durations)} "
            f"avg_asr_ms={_average(asr_durations)} "
            f"best_asr_ms={min(asr_durations)} "
            f"avg_recording_ms={_average(recording_durations)}"
        )
```

- [ ] **Step 6: Run diagnostics tests**

Run:

```powershell
py -3 -m unittest tests.test_runtime_runner.RuntimeRunnerTests.test_summarize_runtime_log_reports_recent_diagnostics tests.test_runtime_runner.RuntimeRunnerTests.test_summarize_runtime_log_groups_live_latency_by_profile -v
```

Expected: both tests pass.

- [ ] **Step 7: Checkpoint**

If executing in a Git checkout:

```powershell
git add tests/test_runtime_runner.py services/runtime/runner.py
git commit -m "feat: summarize live latency by ASR profile"
```

In this workspace without `.git`, record that the Task 4 diagnostics tests passed.

---

### Task 5: Profile Save Refresh for Snappy

**Files:**
- Modify: `src/App.test.tsx`
- Verify: `src/App.tsx`

- [ ] **Step 1: Convert the existing refresh test to use `snappy`**

Update `refreshes status and diagnostics after saving a dictation profile` in `src/App.test.tsx` so the second status and diagnostics responses use `snappy`:

```tsx
      .mockResolvedValueOnce({
        status: "ok",
        state: "idle",
        mode: "idle",
        profile: "snappy",
        quiet_mode: false,
        quality_fallback: false,
        last_error: null
      });
```

```tsx
      .mockResolvedValueOnce(["Runtime: profile=low-impact model=small.en"])
      .mockResolvedValueOnce(["Runtime: profile=snappy model=small.en threads=4"]);
```

Change the profile select event and expectations:

```tsx
    fireEvent.change(screen.getByRole("combobox", { name: "ASR profile" }), {
      target: { value: "snappy" }
    });
```

```tsx
    expect(screen.getByText("snappy")).toBeInTheDocument();
    expect(screen.getByText(/Runtime: profile=snappy/)).toBeInTheDocument();
    expect(screen.queryByText(/Runtime: profile=low-impact model=small\.en/)).not.toBeInTheDocument();
```

- [ ] **Step 2: Run frontend test file**

Run:

```powershell
npm test -- src/App.test.tsx
```

Expected: all tests in `src/App.test.tsx` pass.

- [ ] **Step 3: Checkpoint**

If executing in a Git checkout:

```powershell
git add src/App.test.tsx
git commit -m "test: cover snappy profile refresh"
```

In this workspace without `.git`, record that the frontend test file passed.

---

### Task 6: Full Verification

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run focused Python tests**

Run:

```powershell
py -3 -m unittest tests.test_asr_profiles tests.test_runtime_runner -v
```

Expected: all tests pass.

- [ ] **Step 2: Run full Python test suite**

Run:

```powershell
py -3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Run frontend tests**

Run:

```powershell
npm test
```

Expected: all Vitest tests pass.

- [ ] **Step 4: Run production frontend build**

Run:

```powershell
npm run build
```

Expected: TypeScript and Vite build complete successfully.

- [ ] **Step 5: Manual runtime smoke**

Start or use the existing runtime API, then in the desktop UI:

1. Open Dictation settings.
2. Select `snappy`.
3. Save settings.
4. Trigger warmup.
5. Dictate a short sentence into an editor.
6. Dictate a short sentence into a browser text field.
7. Open Diagnostics.

Expected diagnostics include at least one line shaped like:

```text
Live profile latency: profile=snappy model=small.en threads=4 runs=1 avg_total_ms=... avg_asr_ms=... best_asr_ms=... avg_recording_ms=...
```

- [ ] **Step 6: Compare live profile feel**

Switch back to `low-impact`, dictate one or two comparable short clips, then inspect Diagnostics.

Expected: diagnostics show both `low-impact` and `snappy` live latency groups when recent logs contain both. `snappy` should feel faster after warmup, and the short CPU burst should not make normal multi-app use feel overloaded.

---

## Self-Review Notes

- Spec coverage: `snappy` backend profile is covered by Tasks 1 and 2; UI exposure is covered by Tasks 3 and 5; grouped live diagnostics are covered by Task 4; verification and manual multi-app comfort checks are covered by Task 6.
- Scope check: this plan does not add streaming ASR, GPU work, automatic CPU-load switching, quality fallback changes, or another model search.
- Type consistency: profile fields match `AsrProfile`; diagnostics read existing `duration_ms`, `recording_ms`, `timings_ms.asr_ms`, `asr_profile`, `asr_model`, and `asr_cpu_threads` log fields.
