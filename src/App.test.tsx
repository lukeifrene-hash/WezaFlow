import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App, type RuntimeClient } from "./App";
import { bringLocalFlowWindowForward } from "./lib/tauri";

const tauriMocks = vi.hoisted(() => ({
  bringLocalFlowWindowForward: vi.fn(async () => undefined),
  configureDesktopSettings: vi.fn(async () => undefined),
  getDesktopWindowLabel: vi.fn(() => "main"),
  listenToRecordingBarState: vi.fn(async () => () => undefined)
}));

vi.mock("./lib/tauri", () => ({
  bringLocalFlowWindowForward: tauriMocks.bringLocalFlowWindowForward,
  configureDesktopSettings: tauriMocks.configureDesktopSettings,
  getDesktopWindowLabel: tauriMocks.getDesktopWindowLabel,
  listenToRecordingBarState: tauriMocks.listenToRecordingBarState
}));

function fakeClient(overrides: Partial<RuntimeClient> = {}): RuntimeClient {
  return {
    getStatus: vi.fn(async () => ({
      status: "ok",
      state: "idle",
      mode: "idle",
      profile: "low-impact",
      quiet_mode: false,
      quality_fallback: false,
      last_error: null
    })),
    getSettings: vi.fn(async () => ({
      hotkeys: { dictation: "Ctrl+Alt+Space", command_mode: "Ctrl+Alt+E" },
      models: { whisper: "small.en", whisper_cpu_threads: 2 },
      runtime: {
        profile: "low-impact",
        language: "en",
        quiet_mode: false,
        quality_fallback: false,
        system_audio_ducking: true,
        system_audio_duck_volume: 8,
        use_ollama: false
      }
    })),
    saveSettings: vi.fn(async (settings) => settings),
    getDiagnostics: vi.fn(async () => ["Runtime: profile=low-impact"]),
    warmRuntime: vi.fn(async () => undefined),
    checkRuntime: vi.fn(async () => []),
    listVocabulary: vi.fn(async () => []),
    addVocabulary: vi.fn(async () => []),
    deleteVocabulary: vi.fn(async () => []),
    listCorrections: vi.fn(async () => []),
    addCorrection: vi.fn(async () => []),
    deleteCorrection: vi.fn(async () => []),
    listSnippets: vi.fn(async () => []),
    saveSnippet: vi.fn(async () => []),
    deleteSnippet: vi.fn(async () => []),
    getPendingCorrections: vi.fn(async () => []),
    confirmPendingCorrection: vi.fn(async () => []),
    dismissPendingCorrection: vi.fn(async () => undefined),
    getLearningSuggestions: vi.fn(async () => []),
    ...overrides
  };
}

describe("App", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
    tauriMocks.getDesktopWindowLabel.mockReturnValue("main");
  });

  it("renders only the compact recording bar in the recording-bar window", () => {
    tauriMocks.getDesktopWindowLabel.mockReturnValue("recording-bar");

    render(<App client={fakeClient()} />);

    expect(screen.getByRole("status", { name: "Recording feedback" })).toBeInTheDocument();
    expect(screen.getByText("Listening")).toBeInTheDocument();
    expect(screen.queryByText(/^\d+:\d{2}$/)).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: "Settings sections" })).not.toBeInTheDocument();
  });

  it("renders the normal settings shell in the main window", async () => {
    render(<App client={fakeClient()} />);

    expect(await screen.findByText("WezaFlow")).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "Settings sections" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Recording feedback" })).not.toBeInTheDocument();
  });

  it("renders status and diagnostics tabs from the runtime API", async () => {
    render(<App client={fakeClient()} />);

    expect(await screen.findByText("WezaFlow")).toBeInTheDocument();
    expect(screen.getByAltText("WezaFlow logo")).toBeInTheDocument();
    expect(screen.getByText("low-impact")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Diagnostics" }));

    expect(await screen.findByText("Runtime: profile=low-impact")).toBeInTheDocument();
  });

  it("uses the transparent logo asset in the header", async () => {
    render(<App client={fakeClient()} />);

    const logo = await screen.findByAltText("WezaFlow logo");

    expect(logo).toHaveAttribute("src", expect.stringContaining("Logo-no-bg.png"));
  });

  it("marks the document and body as transparent recording-bar chrome", () => {
    tauriMocks.getDesktopWindowLabel.mockReturnValue("recording-bar");

    render(<App client={fakeClient()} />);

    expect(document.documentElement).toHaveClass("recording-bar-window");
    expect(document.body).toHaveClass("recording-bar-window");
  });

  it("requests runtime warmup after loading settings", async () => {
    const warmRuntime = vi.fn(async () => undefined);
    render(<App client={fakeClient({ warmRuntime })} />);

    await screen.findByText("Runtime API connected");

    await waitFor(() => expect(warmRuntime).toHaveBeenCalledTimes(1));
  });

  it("saves edited hotkeys through the runtime API", async () => {
    const saveSettings = vi.fn(async (settings) => settings);
    render(<App client={fakeClient({ saveSettings })} />);

    await userEvent.click(await screen.findByRole("tab", { name: "Hotkeys" }));
    const dictation = await screen.findByLabelText("Dictation hotkeys 1");
    fireEvent.change(dictation, { target: { value: "Ctrl+Shift+Space" } });
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(saveSettings).toHaveBeenCalled());
    expect(saveSettings.mock.calls[0][0].hotkeys.dictation).toEqual(["Ctrl+Shift+Space"]);
  });

  it("captures a mouse side button as a hotkey", async () => {
    const saveSettings = vi.fn(async (settings) => settings);
    render(<App client={fakeClient({ saveSettings })} />);

    await userEvent.click(await screen.findByRole("tab", { name: "Hotkeys" }));
    await userEvent.click(screen.getAllByRole("button", { name: "Capture" })[0]);
    fireEvent.mouseDown(await screen.findByLabelText("Dictation hotkeys 1"), { button: 3 });
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(saveSettings).toHaveBeenCalled());
    expect(saveSettings.mock.calls[0][0].hotkeys.dictation).toEqual(["MouseX1"]);
  });

  it("saves audio ducking settings from the dictation tab", async () => {
    const saveSettings = vi.fn(async (settings) => settings);
    render(<App client={fakeClient({ saveSettings })} />);

    await userEvent.click(await screen.findByRole("tab", { name: "Dictation" }));
    await userEvent.click(await screen.findByLabelText("System audio ducking"));
    fireEvent.change(screen.getByLabelText("Ducked system volume"), { target: { value: "12" } });
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(saveSettings).toHaveBeenCalled());
    expect(saveSettings.mock.calls[0][0].runtime.system_audio_ducking).toBe(false);
    expect(saveSettings.mock.calls[0][0].runtime.system_audio_duck_volume).toBe(12);
  });

  it("shows the distil small English ASR profile in dictation settings", async () => {
    render(<App client={fakeClient()} />);

    await userEvent.click(await screen.findByRole("tab", { name: "Dictation" }));

    expect(screen.getByRole("option", { name: "distil-small-en" })).toBeInTheDocument();
  });

  it("shows the snappy ASR profile in dictation settings", async () => {
    render(<App client={fakeClient()} />);

    await userEvent.click(await screen.findByRole("tab", { name: "Dictation" }));

    expect(screen.getByRole("option", { name: "snappy" })).toBeInTheDocument();
  });

  it("disables unsupported language options for English-only ASR profiles", async () => {
    render(<App client={fakeClient()} />);

    await userEvent.click(await screen.findByRole("tab", { name: "Dictation" }));
    fireEvent.change(screen.getByRole("combobox", { name: "ASR profile" }), {
      target: { value: "snappy" }
    });

    expect(screen.getByRole("option", { name: "English (en)" })).not.toBeDisabled();
    expect(screen.getByRole("option", { name: "Auto detect" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "Arabic (ar)" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "French (fr)" })).toBeDisabled();
  });

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
      target: { value: "snappy" }
    });
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(saveSettings).toHaveBeenCalled());
    expect(saveSettings.mock.calls[0][0].runtime.profile).toBe("snappy");
    expect(saveSettings.mock.calls[0][0].runtime.language).toBe("en");
  });

  it("refreshes status and diagnostics after saving a dictation profile", async () => {
    const getStatus = vi
      .fn()
      .mockResolvedValueOnce({
        status: "ok",
        state: "idle",
        mode: "idle",
        profile: "low-impact",
        quiet_mode: false,
        quality_fallback: false,
        last_error: null
      })
      .mockResolvedValueOnce({
        status: "ok",
        state: "idle",
        mode: "idle",
        profile: "snappy",
        quiet_mode: false,
        quality_fallback: false,
        last_error: null
      });
    const getDiagnostics = vi
      .fn()
      .mockResolvedValueOnce(["Runtime: profile=low-impact model=small.en"])
      .mockResolvedValueOnce(["Runtime: profile=snappy model=small.en threads=4"]);
    const saveSettings = vi.fn(async (settings) => settings);

    const warmRuntime = vi.fn(async () => undefined);

    render(<App client={fakeClient({ getStatus, getDiagnostics, saveSettings, warmRuntime })} />);

    await screen.findByText("low-impact");
    await userEvent.click(screen.getByRole("tab", { name: "Dictation" }));
    fireEvent.change(screen.getByRole("combobox", { name: "ASR profile" }), {
      target: { value: "snappy" }
    });
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await userEvent.click(screen.getByRole("tab", { name: "Status" }));

    await waitFor(() => expect(getStatus).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(getDiagnostics).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(warmRuntime).toHaveBeenCalledTimes(2));
    expect(screen.getByText("snappy")).toBeInTheDocument();
    expect(screen.getByText(/Runtime: profile=snappy/)).toBeInTheDocument();
    expect(screen.queryByText(/Runtime: profile=low-impact model=small\.en/)).not.toBeInTheDocument();
  });

  it("polls for a new pending correction, focuses the desktop window, and confirms it", async () => {
    vi.useFakeTimers();
    const pendingCorrection = {
      id: "42",
      original: "local flow",
      raw_transcript: "local flow",
      app_name: "Notes",
      window_title: "Draft",
      detected_at: "2026-05-10T09:30:00Z"
    };
    const getPendingCorrections = vi
      .fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([pendingCorrection])
      .mockResolvedValueOnce([]);
    const confirmPendingCorrection = vi.fn(async () => []);
    const getLearningSuggestions = vi
      .fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ kind: "vocabulary" as const, phrase: "LocalFlow", count: 3 }]);
    render(
      <App
        client={fakeClient({
          getPendingCorrections,
          confirmPendingCorrection,
          getLearningSuggestions
        })}
      />
    );

    expect(screen.getByText("WezaFlow")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(2000);

    expect(screen.getByText("Did this edit fix dictation?")).toBeInTheDocument();
    expect(screen.getByLabelText("Original dictated phrase")).toHaveValue("local flow");
    expect(bringLocalFlowWindowForward).toHaveBeenCalledTimes(1);
    vi.useRealTimers();

    fireEvent.change(screen.getByLabelText("Corrected phrase for pending edit"), {
      target: { value: "LocalFlow" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm correction" }));

    await waitFor(() =>
      expect(confirmPendingCorrection).toHaveBeenCalledWith("42", "local flow", "LocalFlow")
    );
    expect(await screen.findByText("Suggested vocabulary")).toBeInTheDocument();
    expect(screen.getByText("LocalFlow (3)")).toBeInTheDocument();
  });

  it("dismisses the current pending correction", async () => {
    const pendingCorrection = {
      id: "43",
      original: "open male",
      raw_transcript: "open male",
      app_name: "Mail",
      window_title: "Inbox",
      detected_at: "2026-05-10T09:31:00Z"
    };
    const dismissPendingCorrection = vi.fn(async () => undefined);
    render(
      <App
        client={fakeClient({
          getPendingCorrections: vi.fn(async () => [pendingCorrection]),
          dismissPendingCorrection
        })}
      />
    );

    expect(await screen.findByText("Did this edit fix dictation?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss correction" }));

    await waitFor(() => expect(dismissPendingCorrection).toHaveBeenCalledWith("43"));
    expect(screen.queryByText("Did this edit fix dictation?")).not.toBeInTheDocument();
  });
});
