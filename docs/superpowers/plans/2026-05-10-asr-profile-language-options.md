# ASR Profile Language Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `Systran/faster-distil-whisper-small.en` ASR profile and make the Dictation language dropdown disable unsupported languages for English-only profiles.

**Architecture:** `services/asr/profiles.py` remains the backend source of truth for runtime profile settings and gains supported-language metadata. `src/App.tsx` keeps the existing hard-coded settings UI pattern, adds a local profile/language metadata table, and sanitizes language settings when profile changes or settings are saved. Tests cover backend profile metadata and frontend dropdown behavior.

**Tech Stack:** Python `unittest`, React 19, TypeScript, Vitest, React Testing Library.

**Repository Note:** `C:\Users\adami\projects\WEZZA` is not a Git repository, so commit steps are intentionally omitted for this workspace.

---

### Task 1: Backend ASR Profile Metadata

**Files:**
- Modify: `services/asr/profiles.py`
- Test: `tests/test_asr_profiles.py`

- [ ] **Step 1: Write the failing backend tests**

Add assertions in `tests/test_asr_profiles.py` so profile metadata includes English-only support for `.en` profiles and the new Hugging Face model profile:

```python
distil_small = resolve_asr_profile("distil-small-en")

self.assertEqual(distil_small.model_name, "Systran/faster-distil-whisper-small.en")
self.assertEqual(distil_small.cpu_threads, 2)
self.assertEqual(distil_small.speculative_cpu_threads, 2)
self.assertFalse(distil_small.speculative_enabled)
self.assertEqual(distil_small.compute_type, "int8")
self.assertEqual(distil_small.supported_languages, ("en",))
self.assertEqual(low_impact.supported_languages, ("en",))
self.assertEqual(balanced.supported_languages, ("en",))
self.assertIsNone(quality.supported_languages)
```

- [ ] **Step 2: Run backend test to verify it fails**

Run:

```powershell
py -3 -m unittest tests.test_asr_profiles -v
```

Expected: fail because `distil-small-en` is unknown or `supported_languages` is missing.

- [ ] **Step 3: Implement backend metadata**

Update `AsrProfile` in `services/asr/profiles.py`:

```python
supported_languages: tuple[str, ...] | None = None
```

Set `supported_languages=("en",)` on `low-impact`, `balanced`, and `distil-small-en`; leave `quality` as `None`. Add:

```python
"distil-small-en": AsrProfile(
    name="distil-small-en",
    model_name="Systran/faster-distil-whisper-small.en",
    compute_type="int8",
    cpu_threads=2,
    speculative_cpu_threads=2,
    speculative_enabled=False,
    supported_languages=("en",),
),
```

- [ ] **Step 4: Run backend test to verify it passes**

Run:

```powershell
py -3 -m unittest tests.test_asr_profiles -v
```

Expected: all tests in `tests.test_asr_profiles` pass.

### Task 2: Frontend Dictation Dropdown Behavior

**Files:**
- Modify: `src/App.tsx`
- Test: `src/App.test.tsx`

- [ ] **Step 1: Write the failing frontend tests**

Add tests in `src/App.test.tsx`:

```tsx
it("shows the distil small English ASR profile in dictation settings", async () => {
  render(<App client={fakeClient()} />);

  await userEvent.click(await screen.findByRole("tab", { name: "Dictation" }));

  expect(screen.getByRole("option", { name: "distil-small-en" })).toBeInTheDocument();
});
```

```tsx
it("disables unsupported language options for English-only ASR profiles", async () => {
  render(<App client={fakeClient()} />);

  await userEvent.click(await screen.findByRole("tab", { name: "Dictation" }));
  fireEvent.change(screen.getByRole("combobox", { name: "ASR profile" }), {
    target: { value: "distil-small-en" }
  });

  expect(screen.getByRole("option", { name: "English (en)" })).not.toBeDisabled();
  expect(screen.getByRole("option", { name: "Auto detect" })).toBeDisabled();
  expect(screen.getByRole("option", { name: "Arabic (ar)" })).toBeDisabled();
  expect(screen.getByRole("option", { name: "French (fr)" })).toBeDisabled();
});
```

```tsx
it("coerces unsupported languages to English before saving an English-only ASR profile", async () => {
  const saveSettings = vi.fn(async (settings) => settings);
  render(
    <App
      client={fakeClient({
        saveSettings,
        getSettings: vi.fn(async () => ({
          hotkeys: { dictation: "Ctrl+Alt+Space", command_mode: "Ctrl+Alt+E" },
          models: { whisper: "small.en", whisper_cpu_threads: 2 },
          runtime: {
            profile: "quality",
            language: "ar",
            quiet_mode: false,
            quality_fallback: false,
            system_audio_ducking: true,
            system_audio_duck_volume: 8,
            use_ollama: false
          }
        }))
      })}
    />
  );

  await userEvent.click(await screen.findByRole("tab", { name: "Dictation" }));
  fireEvent.change(screen.getByRole("combobox", { name: "ASR profile" }), {
    target: { value: "distil-small-en" }
  });
  await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

  await waitFor(() => expect(saveSettings).toHaveBeenCalled());
  expect(saveSettings.mock.calls[0][0].runtime.profile).toBe("distil-small-en");
  expect(saveSettings.mock.calls[0][0].runtime.language).toBe("en");
});
```

- [ ] **Step 2: Run frontend tests to verify they fail**

Run:

```powershell
npm test -- src/App.test.tsx
```

Expected: fail because the new profile option and language dropdown constraints do not exist.

- [ ] **Step 3: Implement frontend profile and language metadata**

Add constants near the tab definitions in `src/App.tsx`:

```tsx
const ASR_PROFILE_OPTIONS = [
  { value: "low-impact", label: "low-impact", supportedLanguages: ["en"] },
  { value: "balanced", label: "balanced", supportedLanguages: ["en"] },
  { value: "quality", label: "quality" },
  { value: "distil-small-en", label: "distil-small-en", supportedLanguages: ["en"] }
] as const;

const LANGUAGE_OPTIONS = [
  { value: "auto", label: "Auto detect" },
  { value: "en", label: "English (en)" },
  { value: "ar", label: "Arabic (ar)" },
  { value: "fr", label: "French (fr)" },
  { value: "de", label: "German (de)" },
  { value: "es", label: "Spanish (es)" }
] as const;
```

Add helpers:

```tsx
function supportedLanguagesForProfile(profile: string): readonly string[] | null {
  const metadata = ASR_PROFILE_OPTIONS.find((item) => item.value === profile);
  return metadata && "supportedLanguages" in metadata ? metadata.supportedLanguages : null;
}

function coerceLanguageForProfile(language: string, profile: string): string {
  const supportedLanguages = supportedLanguagesForProfile(profile);
  if (!supportedLanguages) {
    return language || "auto";
  }
  return supportedLanguages.includes(language) ? language : supportedLanguages[0];
}

function isLanguageDisabledForProfile(language: string, profile: string): boolean {
  const supportedLanguages = supportedLanguagesForProfile(profile);
  return Boolean(supportedLanguages && !supportedLanguages.includes(language));
}

function settingsForSave(settings: Settings): Settings {
  return {
    ...settings,
    hotkeys: canonicalizeHotkeySettings(settings.hotkeys),
    runtime: {
      ...settings.runtime,
      language: coerceLanguageForProfile(settings.runtime.language, settings.runtime.profile)
    }
  };
}
```

Use `settingsForSave(settings)` in `saveSettings()`.

- [ ] **Step 4: Replace the Dictation language input**

Update `DictationPanel` in `src/App.tsx` to render ASR profiles from `ASR_PROFILE_OPTIONS` and render Language as a `<select>`. On ASR profile change, coerce language for the new profile:

```tsx
const language = coerceLanguageForProfile(settings.runtime.language, settings.runtime.profile);
```

Use:

```tsx
<select
  value={language}
  onChange={(event) =>
    onSettings({
      ...settings,
      runtime: { ...settings.runtime, language: event.target.value }
    })
  }
>
  {LANGUAGE_OPTIONS.map((option) => (
    <option
      key={option.value}
      value={option.value}
      disabled={isLanguageDisabledForProfile(option.value, settings.runtime.profile)}
    >
      {option.label}
    </option>
  ))}
</select>
```

- [ ] **Step 5: Run frontend tests to verify they pass**

Run:

```powershell
npm test -- src/App.test.tsx
```

Expected: all `src/App.test.tsx` tests pass.

### Task 3: Final Verification

**Files:**
- Verify: `tests/test_asr_profiles.py`
- Verify: `src/App.test.tsx`

- [ ] **Step 1: Run focused backend verification**

Run:

```powershell
py -3 -m unittest tests.test_asr_profiles -v
```

Expected: all tests pass.

- [ ] **Step 2: Run focused frontend verification**

Run:

```powershell
npm test -- src/App.test.tsx
```

Expected: all tests pass.

- [ ] **Step 3: Run broader frontend verification**

Run:

```powershell
npm test
```

Expected: all frontend tests pass.
