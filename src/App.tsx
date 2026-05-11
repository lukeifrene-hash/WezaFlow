import { useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import {
  Activity,
  BookOpen,
  ClipboardList,
  Keyboard,
  ListChecks,
  MessageSquareText,
  Play,
  Plus,
  RefreshCw,
  Save,
  Settings as SettingsIcon,
  Square,
  Trash2,
  Wrench
} from "lucide-react";

import {
  type CorrectionPair,
  type DependencyStatus,
  type LearningSuggestion,
  type PendingCorrection,
  RuntimeApiClient,
  type RuntimeStatus,
  type Settings,
  type SnippetRecord,
  type VocabularyTerm
} from "./lib/api";
import {
  canonicalizeHotkeySettings,
  shortcutListForEditing,
  shortcutFromKeyboardEvent,
  shortcutFromMouseButton,
  validateHotkeySettings
} from "./lib/shortcuts";
import {
  bringLocalFlowWindowForward,
  configureDesktopSettings,
  getDesktopWindowLabel,
  listenToRecordingBarState,
  type RecordingBarStatePayload
} from "./lib/tauri";
import wezaLogo from "./assets/Logo-no-bg.png";
import "./styles.css";

export type RuntimeClient = {
  getStatus(): Promise<RuntimeStatus>;
  getSettings(): Promise<Settings>;
  saveSettings(settings: Settings): Promise<Settings>;
  getDiagnostics(): Promise<string[]>;
  warmRuntime(): Promise<void>;
  checkRuntime(): Promise<DependencyStatus[]>;
  listVocabulary(): Promise<VocabularyTerm[]>;
  addVocabulary(word: string): Promise<VocabularyTerm[]>;
  deleteVocabulary(word: string): Promise<VocabularyTerm[]>;
  listCorrections(): Promise<CorrectionPair[]>;
  addCorrection(original: string, corrected: string): Promise<CorrectionPair[]>;
  deleteCorrection(original: string, corrected: string): Promise<CorrectionPair[]>;
  getPendingCorrections(): Promise<PendingCorrection[]>;
  confirmPendingCorrection(
    id: string,
    original: string,
    corrected: string
  ): Promise<CorrectionPair[]>;
  dismissPendingCorrection(id: string): Promise<void>;
  getLearningSuggestions(): Promise<LearningSuggestion[]>;
  listSnippets(): Promise<SnippetRecord[]>;
  saveSnippet(triggerPhrase: string, expansion: string): Promise<SnippetRecord[]>;
  deleteSnippet(triggerPhrase: string): Promise<SnippetRecord[]>;
};

type Tab = "status" | "hotkeys" | "dictation" | "vocabulary" | "snippets" | "diagnostics";

const TABS: Array<{ id: Tab; label: string; icon: typeof Activity }> = [
  { id: "status", label: "Status", icon: Activity },
  { id: "hotkeys", label: "Hotkeys", icon: Keyboard },
  { id: "dictation", label: "Dictation", icon: SettingsIcon },
  { id: "vocabulary", label: "Vocabulary", icon: BookOpen },
  { id: "snippets", label: "Snippets", icon: MessageSquareText },
  { id: "diagnostics", label: "Diagnostics", icon: ClipboardList }
];

type AsrProfileOption = {
  value: string;
  label: string;
  supportedLanguages?: readonly string[];
};

const ASR_PROFILE_OPTIONS: AsrProfileOption[] = [
  { value: "low-impact", label: "low-impact", supportedLanguages: ["en"] },
  { value: "snappy", label: "snappy", supportedLanguages: ["en"] },
  { value: "balanced", label: "balanced", supportedLanguages: ["en"] },
  { value: "quality", label: "quality" },
  { value: "distil-small-en", label: "distil-small-en", supportedLanguages: ["en"] }
];

const LANGUAGE_OPTIONS = [
  { value: "auto", label: "Auto detect" },
  { value: "en", label: "English (en)" },
  { value: "ar", label: "Arabic (ar)" },
  { value: "fr", label: "French (fr)" },
  { value: "de", label: "German (de)" },
  { value: "es", label: "Spanish (es)" }
] as const;

const DEFAULT_CLIENT = new RuntimeApiClient();

const RECORDING_BAR_LABELS: Record<RecordingBarStatePayload["state"], string> = {
  listening: "Listening",
  command: "Command",
  processing: "Processing",
  done: "Done",
  error: "Error"
};

function supportedLanguagesForProfile(profile: string): readonly string[] | null {
  return ASR_PROFILE_OPTIONS.find((item) => item.value === profile)?.supportedLanguages ?? null;
}

function coerceLanguageForProfile(language: string | null | undefined, profile: string): string {
  const supportedLanguages = supportedLanguagesForProfile(profile);
  if (!supportedLanguages) {
    return language || "auto";
  }
  return language && supportedLanguages.includes(language) ? language : supportedLanguages[0];
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

export function App({ client = DEFAULT_CLIENT }: { client?: RuntimeClient }) {
  if (getDesktopWindowLabel() === "recording-bar") {
    return <RecordingFeedbackBar />;
  }

  return <SettingsApp client={client} />;
}

function SettingsApp({ client = DEFAULT_CLIENT }: { client?: RuntimeClient }) {
  const [tab, setTab] = useState<Tab>("status");
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [diagnostics, setDiagnostics] = useState<string[]>([]);
  const [dependencies, setDependencies] = useState<DependencyStatus[]>([]);
  const [vocabulary, setVocabulary] = useState<VocabularyTerm[]>([]);
  const [corrections, setCorrections] = useState<CorrectionPair[]>([]);
  const [pendingCorrections, setPendingCorrections] = useState<PendingCorrection[]>([]);
  const [learningSuggestions, setLearningSuggestions] = useState<LearningSuggestion[]>([]);
  const [snippets, setSnippets] = useState<SnippetRecord[]>([]);
  const [word, setWord] = useState("");
  const [correctionOriginal, setCorrectionOriginal] = useState("");
  const [correctionFixed, setCorrectionFixed] = useState("");
  const [pendingOriginal, setPendingOriginal] = useState("");
  const [pendingCorrected, setPendingCorrected] = useState("");
  const [snippetTrigger, setSnippetTrigger] = useState("");
  const [snippetExpansion, setSnippetExpansion] = useState("");
  const [message, setMessage] = useState("Loading runtime state...");
  const [error, setError] = useState<string | null>(null);
  const promptedCorrectionId = useRef<string | null>(null);
  const currentPendingCorrection = pendingCorrections[0] ?? null;

  const hotkeyValidation = useMemo(
    () =>
      settings
        ? validateHotkeySettings(settings.hotkeys)
        : { valid: true, errors: {} },
    [settings]
  );

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    const poller = window.setInterval(() => {
      void refreshPendingCorrections();
    }, 2000);
    return () => window.clearInterval(poller);
  }, [client]);

  async function refreshAll() {
    try {
      setError(null);
      const [
        nextStatus,
        nextSettings,
        nextDiagnostics,
        nextDependencies,
        nextVocabulary,
        nextCorrections,
        nextPendingCorrections,
        nextLearningSuggestions,
        nextSnippets
      ] = await Promise.all([
        client.getStatus(),
        client.getSettings(),
        client.getDiagnostics(),
        client.checkRuntime(),
        client.listVocabulary(),
        client.listCorrections(),
        client.getPendingCorrections(),
        client.getLearningSuggestions(),
        client.listSnippets()
      ]);
      setStatus(nextStatus);
      setSettings(nextSettings);
      setDiagnostics(nextDiagnostics);
      setDependencies(nextDependencies);
      setVocabulary(nextVocabulary);
      setCorrections(nextCorrections);
      updatePendingCorrections(nextPendingCorrections);
      setLearningSuggestions(nextLearningSuggestions);
      setSnippets(nextSnippets);
      await configureDesktopSettings(nextSettings);
      void warmRuntime();
      setMessage("Runtime API connected");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setMessage("Runtime API unavailable");
    }
  }

  async function warmRuntime() {
    try {
      await client.warmRuntime();
    } catch {
      // Model warm-up is opportunistic; recording can still start if it fails.
    }
  }

  async function refreshPendingCorrections() {
    try {
      updatePendingCorrections(await client.getPendingCorrections());
    } catch {
      // Polling failures should not replace the main runtime status.
    }
  }

  function updatePendingCorrections(nextPendingCorrections: PendingCorrection[]) {
    setPendingCorrections(nextPendingCorrections);
    const nextCorrection = nextPendingCorrections[0] ?? null;
    if (!nextCorrection) {
      promptedCorrectionId.current = null;
      setPendingOriginal("");
      setPendingCorrected("");
      return;
    }

    if (nextCorrection.id !== promptedCorrectionId.current) {
      promptedCorrectionId.current = nextCorrection.id;
      setPendingOriginal(nextCorrection.original);
      setPendingCorrected("");
      void bringLocalFlowWindowForward();
    }
  }

  async function saveSettings() {
    if (!settings || !hotkeyValidation.valid) {
      return;
    }
    const canonicalSettings = settingsForSave(settings);
    const saved = await client.saveSettings(canonicalSettings);
    setSettings(saved);
    await configureDesktopSettings(saved);
    const [nextStatus, nextDiagnostics] = await Promise.all([
      client.getStatus(),
      client.getDiagnostics()
    ]);
    setStatus(nextStatus);
    setDiagnostics(nextDiagnostics);
    void warmRuntime();
    setMessage("Settings saved");
  }

  async function addVocabulary() {
    if (!word.trim()) {
      return;
    }
    setVocabulary(await client.addVocabulary(word));
    setWord("");
  }

  async function addCorrection() {
    if (!correctionOriginal.trim() || !correctionFixed.trim()) {
      return;
    }
    setCorrections(await client.addCorrection(correctionOriginal, correctionFixed));
    setCorrectionOriginal("");
    setCorrectionFixed("");
  }

  async function confirmPendingCorrection() {
    if (!currentPendingCorrection || !pendingOriginal.trim() || !pendingCorrected.trim()) {
      return;
    }
    await client.confirmPendingCorrection(
      currentPendingCorrection.id,
      pendingOriginal,
      pendingCorrected
    );
    const [nextCorrections, nextPendingCorrections, nextLearningSuggestions] = await Promise.all([
      client.listCorrections(),
      client.getPendingCorrections(),
      client.getLearningSuggestions()
    ]);
    setCorrections(nextCorrections);
    updatePendingCorrections(nextPendingCorrections);
    setLearningSuggestions(nextLearningSuggestions);
    setMessage("Correction confirmed");
  }

  async function dismissPendingCorrection() {
    if (!currentPendingCorrection) {
      return;
    }
    const dismissedId = currentPendingCorrection.id;
    await client.dismissPendingCorrection(dismissedId);
    setPendingCorrections((items) => items.filter((item) => item.id !== dismissedId));
    if (promptedCorrectionId.current === dismissedId) {
      promptedCorrectionId.current = null;
    }
    setPendingOriginal("");
    setPendingCorrected("");
    setMessage("Correction dismissed");
  }

  async function addSnippet() {
    if (!snippetTrigger.trim()) {
      return;
    }
    setSnippets(await client.saveSnippet(snippetTrigger, snippetExpansion));
    setSnippetTrigger("");
    setSnippetExpansion("");
  }

  return (
    <main className="shell">
      <header className="app-header">
        <div className="brand-lockup">
          <span className="brand-mark">
            <img className="brand-logo" src={wezaLogo} alt="WezaFlow logo" />
          </span>
          <div>
            <h1>WezaFlow</h1>
            <p>{message}</p>
          </div>
        </div>
        <button className="icon-button" type="button" onClick={refreshAll} aria-label="Refresh">
          <RefreshCw size={18} />
        </button>
      </header>

      {error ? <div className="alert">{error}</div> : null}

      {currentPendingCorrection ? (
        <PendingCorrectionPrompt
          correction={currentPendingCorrection}
          original={pendingOriginal}
          corrected={pendingCorrected}
          onOriginal={setPendingOriginal}
          onCorrected={setPendingCorrected}
          onConfirm={confirmPendingCorrection}
          onDismiss={dismissPendingCorrection}
        />
      ) : null}

      <LearningSuggestions suggestions={learningSuggestions} />

      <nav className="tabs" role="tablist" aria-label="Settings sections">
        {TABS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              role="tab"
              aria-selected={tab === item.id}
              className={tab === item.id ? "active" : ""}
              type="button"
              onClick={() => setTab(item.id)}
            >
              <Icon size={16} />
              {item.label}
            </button>
          );
        })}
      </nav>

      <section className="panel">
        {tab === "status" && (
          <StatusPanel status={status} dependencies={dependencies} diagnostics={diagnostics} />
        )}
        {tab === "hotkeys" && settings && (
          <HotkeyPanel
            settings={settings}
            validation={hotkeyValidation}
            onSettings={setSettings}
            onSave={saveSettings}
          />
        )}
        {tab === "dictation" && settings && (
          <DictationPanel settings={settings} onSettings={setSettings} onSave={saveSettings} />
        )}
        {tab === "vocabulary" && (
          <VocabularyPanel
            vocabulary={vocabulary}
            corrections={corrections}
            suggestions={learningSuggestions}
            word={word}
            correctionOriginal={correctionOriginal}
            correctionFixed={correctionFixed}
            onWord={setWord}
            onCorrectionOriginal={setCorrectionOriginal}
            onCorrectionFixed={setCorrectionFixed}
            onAddWord={addVocabulary}
            onDeleteWord={async (value) => setVocabulary(await client.deleteVocabulary(value))}
            onAddCorrection={addCorrection}
            onDeleteCorrection={async (original, corrected) =>
              setCorrections(await client.deleteCorrection(original, corrected))
            }
          />
        )}
        {tab === "snippets" && (
          <SnippetsPanel
            snippets={snippets}
            trigger={snippetTrigger}
            expansion={snippetExpansion}
            onTrigger={setSnippetTrigger}
            onExpansion={setSnippetExpansion}
            onSave={addSnippet}
            onDelete={async (trigger) => setSnippets(await client.deleteSnippet(trigger))}
          />
        )}
        {tab === "diagnostics" && <DiagnosticsPanel diagnostics={diagnostics} />}
      </section>
    </main>
  );
}

function RecordingFeedbackBar() {
  const [barState, setBarState] = useState<RecordingBarStatePayload>({
    state: "listening",
    mode: "dictation",
    message: null
  });
  const isRecording = barState.state === "listening" || barState.state === "command";

  useEffect(() => {
    document.documentElement.classList.add("recording-bar-window");
    document.body.classList.add("recording-bar-window");
    return () => {
      document.documentElement.classList.remove("recording-bar-window");
      document.body.classList.remove("recording-bar-window");
    };
  }, []);

  useEffect(() => {
    let active = true;
    const unlisten = listenToRecordingBarState((payload) => {
      if (!active) {
        return;
      }
      setBarState(payload);
    });
    return () => {
      active = false;
      void unlisten.then((removeListener) => removeListener());
    };
  }, []);

  const label = RECORDING_BAR_LABELS[barState.state];
  const statusMark =
    barState.state === "done" ? "OK" : barState.state === "error" ? "!" : "ON";

  return (
    <main className={`recording-bar-root state-${barState.state}`}>
      <section className="recording-pill" role="status" aria-label="Recording feedback">
        <span className="recording-live-dot" aria-hidden="true" />
        <span className="recording-waveform" aria-hidden="true">
          {[0, 1, 2, 3, 4].map((bar) => (
            <span key={bar} />
          ))}
        </span>
        <span className="recording-label">
          <strong>{label}</strong>
          {barState.message ? <small>{barState.message}</small> : null}
        </span>
        <span className="recording-status-mark" aria-hidden="true">
          {isRecording ? "ON" : statusMark}
        </span>
      </section>
    </main>
  );
}

function PendingCorrectionPrompt({
  correction,
  original,
  corrected,
  onOriginal,
  onCorrected,
  onConfirm,
  onDismiss
}: {
  correction: PendingCorrection;
  original: string;
  corrected: string;
  onOriginal(value: string): void;
  onCorrected(value: string): void;
  onConfirm(): void;
  onDismiss(): void;
}) {
  return (
    <section className="correction-prompt" aria-label="Pending correction">
      <div>
        <h2>Did this edit fix dictation?</h2>
        <p>
          {correction.app_name}
          {correction.window_title ? ` - ${correction.window_title}` : ""}
        </p>
      </div>
      <div className="grid two">
        <label>
          Original dictated phrase
          <input value={original} onChange={(event) => onOriginal(event.target.value)} />
        </label>
        <label>
          Corrected phrase for pending edit
          <input
            required
            value={corrected}
            onChange={(event) => onCorrected(event.target.value)}
          />
        </label>
      </div>
      <div className="row">
        <button type="button" onClick={onConfirm} disabled={!corrected.trim()}>
          <Wrench size={16} />
          Confirm correction
        </button>
        <button className="secondary-button" type="button" onClick={onDismiss}>
          <Square size={14} />
          Dismiss correction
        </button>
      </div>
    </section>
  );
}

function LearningSuggestions({ suggestions }: { suggestions: LearningSuggestion[] }) {
  if (!suggestions.length) {
    return null;
  }

  return (
    <section className="suggestions-strip" aria-label="Learning suggestions">
      <h2>Learning suggestions</h2>
      <ul>
        {suggestions.slice(0, 4).map((suggestion) => (
          <li key={`${suggestion.kind}-${suggestion.kind === "vocabulary" ? suggestion.phrase : suggestion.expansion}`}>
            <strong>
              {suggestion.kind === "vocabulary" ? "Suggested vocabulary" : "Suggested snippet"}
            </strong>
            <span>
              {suggestion.kind === "vocabulary" ? suggestion.phrase : suggestion.expansion} (
              {suggestion.count})
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function StatusPanel({
  status,
  dependencies,
  diagnostics
}: {
  status: RuntimeStatus | null;
  dependencies: DependencyStatus[];
  diagnostics: string[];
}) {
  return (
    <div className="grid two">
      <div className="section">
        <h2>Runtime</h2>
        <dl className="facts">
          <dt>State</dt>
          <dd>{status?.state ?? "unknown"}</dd>
          <dt>Profile</dt>
          <dd>{status?.profile ?? "unknown"}</dd>
          <dt>Quiet mode</dt>
          <dd>{status?.quiet_mode ? "on" : "off"}</dd>
          <dt>Quality fallback</dt>
          <dd>{status?.quality_fallback ? "on" : "off"}</dd>
        </dl>
      </div>
      <div className="section">
        <h2>Checks</h2>
        <ul className="list">
          {dependencies.map((dependency) => (
            <li key={dependency.name}>
              <span>{dependency.name}</span>
              <strong className={dependency.available ? "ok" : "warn"}>
                {dependency.available ? "ok" : "missing"}
              </strong>
            </li>
          ))}
        </ul>
        <pre>{diagnostics.slice(0, 2).join("\n")}</pre>
      </div>
    </div>
  );
}

function HotkeyPanel({
  settings,
  validation,
  onSettings,
  onSave
}: {
  settings: Settings;
  validation: ReturnType<typeof validateHotkeySettings>;
  onSettings: (settings: Settings) => void;
  onSave: () => void;
}) {
  const [capturing, setCapturing] = useState<{
    field: "dictation" | "command_mode";
    index: number;
  } | null>(null);
  const dictation = shortcutListForEditing(settings.hotkeys.dictation);
  const commandMode = shortcutListForEditing(settings.hotkeys.command_mode);

  function updateHotkey(
    field: "dictation" | "command_mode",
    index: number,
    value: string
  ) {
    const values = shortcutListForEditing(settings.hotkeys[field]);
    values[index] = value;
    onSettings({
      ...settings,
      hotkeys: { ...settings.hotkeys, [field]: values }
    });
  }

  function addHotkey(field: "dictation" | "command_mode") {
    const values = shortcutListForEditing(settings.hotkeys[field]);
    onSettings({
      ...settings,
      hotkeys: { ...settings.hotkeys, [field]: [...values, ""] }
    });
  }

  function removeHotkey(field: "dictation" | "command_mode", index: number) {
    const values = shortcutListForEditing(settings.hotkeys[field]).filter((_, item) => item !== index);
    onSettings({
      ...settings,
      hotkeys: { ...settings.hotkeys, [field]: values.length ? values : [""] }
    });
  }

  function captureKeyboard(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!capturing) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const shortcut = shortcutFromKeyboardEvent(event.nativeEvent);
    if (shortcut) {
      updateHotkey(capturing.field, capturing.index, shortcut);
      setCapturing(null);
    }
  }

  function captureMouse(event: React.MouseEvent<HTMLInputElement>) {
    if (!capturing) {
      return;
    }
    const shortcut = shortcutFromMouseButton(event.button);
    if (!shortcut) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    updateHotkey(capturing.field, capturing.index, shortcut);
    setCapturing(null);
  }

  return (
    <div className="section">
      <h2>Hotkeys</h2>
      <HotkeyList
        label="Dictation hotkeys"
        field="dictation"
        values={dictation}
        capturing={capturing}
        onCapture={setCapturing}
        onKeyboard={captureKeyboard}
        onMouse={captureMouse}
        onAdd={addHotkey}
        onRemove={removeHotkey}
        onUpdate={updateHotkey}
      />
      {validation.errors.dictation ? <p className="field-error">{validation.errors.dictation}</p> : null}
      <HotkeyList
        label="Command mode hotkeys"
        field="command_mode"
        values={commandMode}
        capturing={capturing}
        onCapture={setCapturing}
        onKeyboard={captureKeyboard}
        onMouse={captureMouse}
        onAdd={addHotkey}
        onRemove={removeHotkey}
        onUpdate={updateHotkey}
      />
      {validation.errors.command_mode ? (
        <p className="field-error">{validation.errors.command_mode}</p>
      ) : null}
      <button type="button" onClick={onSave} disabled={!validation.valid}>
        <Save size={16} />
        Save settings
      </button>
    </div>
  );
}

function HotkeyList(props: {
  label: string;
  field: "dictation" | "command_mode";
  values: string[];
  capturing: { field: "dictation" | "command_mode"; index: number } | null;
  onCapture(value: { field: "dictation" | "command_mode"; index: number } | null): void;
  onKeyboard(event: React.KeyboardEvent<HTMLInputElement>): void;
  onMouse(event: React.MouseEvent<HTMLInputElement>): void;
  onAdd(field: "dictation" | "command_mode"): void;
  onRemove(field: "dictation" | "command_mode", index: number): void;
  onUpdate(field: "dictation" | "command_mode", index: number, value: string): void;
}) {
  return (
    <fieldset className="hotkey-group">
      <legend>{props.label}</legend>
      {props.values.map((value, index) => {
        const isCapturing = props.capturing?.field === props.field && props.capturing.index === index;
        return (
          <div className="hotkey-row" key={`${props.field}-${index}`}>
            <input
              aria-label={`${props.label} ${index + 1}`}
              value={isCapturing ? "Press keys or mouse button..." : value}
              onChange={(event) => props.onUpdate(props.field, index, event.target.value)}
              onKeyDown={props.onKeyboard}
              onMouseDown={props.onMouse}
              readOnly={isCapturing}
            />
            <button
              type="button"
              onClick={() => props.onCapture(isCapturing ? null : { field: props.field, index })}
            >
              <Keyboard size={16} />
              {isCapturing ? "Cancel" : "Capture"}
            </button>
            <button type="button" onClick={() => props.onRemove(props.field, index)} aria-label={`Remove ${props.label} ${index + 1}`}>
              <Trash2 size={16} />
            </button>
          </div>
        );
      })}
      <button type="button" onClick={() => props.onAdd(props.field)}>
        <Plus size={16} />
        Add hotkey
      </button>
    </fieldset>
  );
}

function DictationPanel({
  settings,
  onSettings,
  onSave
}: {
  settings: Settings;
  onSettings: (settings: Settings) => void;
  onSave: () => void;
}) {
  const language = coerceLanguageForProfile(
    settings.runtime.language,
    settings.runtime.profile
  );

  return (
    <div className="section">
      <h2>Dictation</h2>
      <div className="grid two">
        <label>
          ASR profile
          <select
            value={settings.runtime.profile}
            onChange={(event) =>
              onSettings({
                ...settings,
                runtime: {
                  ...settings.runtime,
                  profile: event.target.value,
                  language: coerceLanguageForProfile(settings.runtime.language, event.target.value)
                }
              })
            }
          >
            {ASR_PROFILE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Language
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
        </label>
      </div>
      <div className="toggles">
        <label>
          <input
            type="checkbox"
            checked={settings.runtime.quiet_mode ?? false}
            onChange={(event) =>
              onSettings({
                ...settings,
                runtime: { ...settings.runtime, quiet_mode: event.target.checked }
              })
            }
          />
          Quiet mode
        </label>
        <label>
          <input
            type="checkbox"
            checked={settings.runtime.quality_fallback ?? false}
            onChange={(event) =>
              onSettings({
                ...settings,
                runtime: { ...settings.runtime, quality_fallback: event.target.checked }
              })
            }
          />
          Quality fallback
        </label>
      </div>
      <div className="audio-ducking">
        <label>
          <input
            type="checkbox"
            checked={settings.runtime.system_audio_ducking ?? true}
            onChange={(event) =>
              onSettings({
                ...settings,
                runtime: { ...settings.runtime, system_audio_ducking: event.target.checked }
              })
            }
          />
          System audio ducking
        </label>
        <label>
          Ducked system volume
          <div className="range-row">
            <input
              type="range"
              min="0"
              max="30"
              step="1"
              value={settings.runtime.system_audio_duck_volume ?? 8}
              onChange={(event) =>
                onSettings({
                  ...settings,
                  runtime: {
                    ...settings.runtime,
                    system_audio_duck_volume: Number(event.target.value)
                  }
                })
              }
            />
            <output>{settings.runtime.system_audio_duck_volume ?? 8}%</output>
          </div>
        </label>
      </div>
      <button type="button" onClick={onSave}>
        <Save size={16} />
        Save settings
      </button>
    </div>
  );
}

function VocabularyPanel(props: {
  vocabulary: VocabularyTerm[];
  corrections: CorrectionPair[];
  suggestions: LearningSuggestion[];
  word: string;
  correctionOriginal: string;
  correctionFixed: string;
  onWord(value: string): void;
  onCorrectionOriginal(value: string): void;
  onCorrectionFixed(value: string): void;
  onAddWord(): void;
  onDeleteWord(value: string): void;
  onAddCorrection(): void;
  onDeleteCorrection(original: string, corrected: string): void;
}) {
  return (
    <div className="grid two">
      <div className="section">
        <h2>Vocabulary</h2>
        <div className="row">
          <input
            aria-label="Vocabulary term"
            value={props.word}
            onChange={(event) => props.onWord(event.target.value)}
          />
          <button type="button" onClick={props.onAddWord}>
            <ListChecks size={16} />
            Add
          </button>
        </div>
        <ul className="list">
          {props.vocabulary.map((term) => (
            <li key={term.word}>
              <span>{term.word}</span>
              <button type="button" onClick={() => props.onDeleteWord(term.word)}>
                <Square size={14} />
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="section">
        <h2>Corrections</h2>
        <input
          aria-label="Original phrase"
          placeholder="local flow"
          value={props.correctionOriginal}
          onChange={(event) => props.onCorrectionOriginal(event.target.value)}
        />
        <input
          aria-label="Corrected phrase"
          placeholder="LocalFlow"
          value={props.correctionFixed}
          onChange={(event) => props.onCorrectionFixed(event.target.value)}
        />
        <button type="button" onClick={props.onAddCorrection}>
          <Wrench size={16} />
          Add correction
        </button>
        <ul className="list">
          {props.corrections.map((correction) => (
            <li key={`${correction.original}-${correction.corrected}`}>
              <span>
                {correction.original}
                {" -> "}
                {correction.corrected}
              </span>
              <button
                type="button"
                onClick={() => props.onDeleteCorrection(correction.original, correction.corrected)}
              >
                <Square size={14} />
              </button>
            </li>
          ))}
        </ul>
      </div>
      {props.suggestions.length ? (
        <div className="section">
          <h2>Learning suggestions</h2>
          <ul className="list">
            {props.suggestions.map((suggestion) => (
              <li
                key={`${suggestion.kind}-${suggestion.kind === "vocabulary" ? suggestion.phrase : suggestion.expansion}`}
              >
                <span>
                  {suggestion.kind === "vocabulary"
                    ? `Suggested vocabulary: ${suggestion.phrase} (${suggestion.count})`
                    : `Suggested snippet: ${suggestion.expansion} (${suggestion.count})`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function SnippetsPanel(props: {
  snippets: SnippetRecord[];
  trigger: string;
  expansion: string;
  onTrigger(value: string): void;
  onExpansion(value: string): void;
  onSave(): void;
  onDelete(trigger: string): void;
}) {
  return (
    <div className="section">
      <h2>Snippets</h2>
      <div className="grid two">
        <input
          aria-label="Snippet trigger"
          placeholder="insert my email"
          value={props.trigger}
          onChange={(event) => props.onTrigger(event.target.value)}
        />
        <input
          aria-label="Snippet expansion"
          placeholder="user@example.com"
          value={props.expansion}
          onChange={(event) => props.onExpansion(event.target.value)}
        />
      </div>
      <button type="button" onClick={props.onSave}>
        <Play size={16} />
        Save snippet
      </button>
      <ul className="list">
        {props.snippets.map((snippet) => (
          <li key={snippet.trigger_phrase}>
            <span>
              {snippet.trigger_phrase}
              {" -> "}
              {snippet.expansion}
            </span>
            <button type="button" onClick={() => props.onDelete(snippet.trigger_phrase)}>
              <Square size={14} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DiagnosticsPanel({ diagnostics }: { diagnostics: string[] }) {
  return (
    <div className="section">
      <h2>Diagnostics</h2>
      <pre>{diagnostics.join("\n")}</pre>
    </div>
  );
}
