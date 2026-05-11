import { describe, expect, it } from "vitest";

import {
  canonicalizeShortcut,
  canonicalizeShortcutList,
  validateHotkeySettings
} from "./shortcuts";

describe("shortcut helpers", () => {
  it("canonicalizes common Windows hotkey names", () => {
    expect(canonicalizeShortcut("Control + Alt + Space")).toBe("Ctrl+Alt+Space");
    expect(canonicalizeShortcut("ctrl+shift+e")).toBe("Ctrl+Shift+E");
    expect(canonicalizeShortcut("Escape")).toBe("Esc");
    expect(canonicalizeShortcut("mouse 4")).toBe("MouseX1");
  });

  it("normalizes single legacy hotkeys into a list", () => {
    expect(canonicalizeShortcutList("control + alt + space")).toEqual(["Ctrl+Alt+Space"]);
    expect(canonicalizeShortcutList(["Mouse 5", "ctrl+alt+e"])).toEqual([
      "MouseX2",
      "Ctrl+Alt+E"
    ]);
  });

  it("requires one non-modifier key", () => {
    const result = validateHotkeySettings({
      dictation: ["Ctrl+Alt"],
      command_mode: ["Ctrl+Alt+E"]
    });

    expect(result.valid).toBe(false);
    expect(result.errors.dictation).toContain("one non-modifier key");
  });

  it("rejects duplicate dictation and command shortcuts", () => {
    const result = validateHotkeySettings({
      dictation: ["Control+Alt+Space", "MouseX1"],
      command_mode: ["Ctrl+Alt+E", "mouse 4"]
    });

    expect(result.valid).toBe(false);
    expect(result.errors.command_mode).toContain("must be different");
  });

  it("accepts multiple keyboard and mouse bindings per action", () => {
    const result = validateHotkeySettings({
      dictation: ["Control+Alt+Space", "MouseX1"],
      command_mode: ["Ctrl+Alt+E", "MouseX2"]
    });

    expect(result.valid).toBe(true);
  });
});
