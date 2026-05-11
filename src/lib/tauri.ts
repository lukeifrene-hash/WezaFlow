import type { Settings } from "./api";
import type { HotkeySettings } from "./shortcuts";

export type RecordingBarState = "listening" | "command" | "processing" | "done" | "error";
export type RecordingBarMode = "dictation" | "command";

export type RecordingBarStatePayload = {
  state: RecordingBarState;
  mode: RecordingBarMode;
  message?: string | null;
};

type TauriInternals = {
  metadata?: {
    currentWindow?: {
      label?: string;
    };
  };
};

function tauriInternals(): TauriInternals | undefined {
  return (window as Window & { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__;
}

export function getDesktopWindowLabel(): string {
  return tauriInternals()?.metadata?.currentWindow?.label ?? "main";
}

export async function registerDesktopHotkeys(hotkeys: HotkeySettings): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) {
    return;
  }
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("register_hotkeys", { hotkeys });
}

export async function configureDesktopSettings(settings: Settings): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) {
    return;
  }
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("configure_desktop_settings", { settings });
}

export async function bringLocalFlowWindowForward(): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) {
    return;
  }
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  const appWindow = getCurrentWindow();
  await appWindow.unminimize();
  await appWindow.show();
  await appWindow.setFocus();
}

export async function listenToRecordingBarState(
  onState: (payload: RecordingBarStatePayload) => void
): Promise<() => void> {
  if (!("__TAURI_INTERNALS__" in window)) {
    return () => undefined;
  }
  const { listen } = await import("@tauri-apps/api/event");
  return listen<RecordingBarStatePayload>("recording-bar-state", (event) => {
    onState(event.payload);
  });
}
