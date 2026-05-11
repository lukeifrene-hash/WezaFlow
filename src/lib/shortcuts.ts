export type HotkeySettings = {
  dictation: HotkeyValue;
  command_mode: HotkeyValue;
};

export type HotkeyValue = string | string[];

export type HotkeyValidation = {
  valid: boolean;
  errors: Partial<Record<keyof HotkeySettings, string>>;
};

const MODIFIER_ORDER = ["Ctrl", "Alt", "Shift", "Meta"] as const;
const MODIFIER_ALIASES = new Map<string, string>([
  ["ctrl", "Ctrl"],
  ["control", "Ctrl"],
  ["cmd", "Meta"],
  ["command", "Meta"],
  ["win", "Meta"],
  ["windows", "Meta"],
  ["super", "Meta"],
  ["meta", "Meta"],
  ["alt", "Alt"],
  ["option", "Alt"],
  ["shift", "Shift"]
]);
const KEY_ALIASES = new Map<string, string>([
  [" ", "Space"],
  ["space", "Space"],
  ["spacebar", "Space"],
  ["escape", "Esc"],
  ["esc", "Esc"],
  ["enter", "Enter"],
  ["return", "Enter"],
  ["delete", "Delete"],
  ["backspace", "Backspace"],
  ["tab", "Tab"]
]);
const MOUSE_ALIASES = new Map<string, string>([
  ["mousex1", "MouseX1"],
  ["mouse x1", "MouseX1"],
  ["mouse4", "MouseX1"],
  ["mouse 4", "MouseX1"],
  ["button4", "MouseX1"],
  ["button 4", "MouseX1"],
  ["xbutton1", "MouseX1"],
  ["x button 1", "MouseX1"],
  ["back", "MouseX1"],
  ["mousex2", "MouseX2"],
  ["mouse x2", "MouseX2"],
  ["mouse5", "MouseX2"],
  ["mouse 5", "MouseX2"],
  ["button5", "MouseX2"],
  ["button 5", "MouseX2"],
  ["xbutton2", "MouseX2"],
  ["x button 2", "MouseX2"],
  ["forward", "MouseX2"]
]);

export function canonicalizeShortcut(value: string): string {
  const mouse = MOUSE_ALIASES.get(value.trim().toLowerCase());
  if (mouse) {
    return mouse;
  }

  const parts = value
    .split("+")
    .map((part) => part.trim())
    .filter(Boolean);
  const modifiers = new Set<string>();
  const keys: string[] = [];

  for (const part of parts) {
    const normalized = part.toLowerCase();
    const modifier = MODIFIER_ALIASES.get(normalized);
    if (modifier) {
      modifiers.add(modifier);
      continue;
    }
    keys.push(KEY_ALIASES.get(normalized) ?? normalizeKey(part));
  }

  return [
    ...MODIFIER_ORDER.filter((modifier) => modifiers.has(modifier)),
    ...keys
  ].join("+");
}

export function canonicalizeShortcutList(value: HotkeyValue): string[] {
  const values = Array.isArray(value) ? value : [value];
  const result: string[] = [];
  for (const item of values) {
    const canonical = canonicalizeShortcut(item);
    if (!canonical) {
      continue;
    }
    result.push(canonical);
  }
  return result;
}

export function shortcutListForEditing(value: HotkeyValue): string[] {
  const values = Array.isArray(value) ? value : [value];
  return values.length ? values.map((item) => (item.trim() ? canonicalizeShortcut(item) : "")) : [""];
}

export function canonicalizeHotkeySettings(settings: HotkeySettings): {
  dictation: string[];
  command_mode: string[];
} {
  return {
    dictation: canonicalizeShortcutList(settings.dictation),
    command_mode: canonicalizeShortcutList(settings.command_mode)
  };
}

export function validateHotkeySettings(settings: HotkeySettings): HotkeyValidation {
  const errors: HotkeyValidation["errors"] = {};
  const dictation = canonicalizeShortcutList(settings.dictation);
  const commandMode = canonicalizeShortcutList(settings.command_mode);

  const dictationError = validateHotkeyList(dictation);
  if (dictationError) {
    errors.dictation = dictationError;
  }
  const commandError = validateHotkeyList(commandMode);
  if (commandError) {
    errors.command_mode = commandError;
  }
  if (!errors.dictation && !errors.command_mode) {
    const dictationSet = new Set(dictation);
    if (commandMode.some((shortcut) => dictationSet.has(shortcut))) {
      errors.command_mode = "Command mode shortcuts must be different from dictation.";
    }
  }

  return { valid: Object.keys(errors).length === 0, errors };
}

export function shortcutFromKeyboardEvent(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "altKey" | "shiftKey" | "metaKey">): string | null {
  if (["Control", "Alt", "Shift", "Meta"].includes(event.key)) {
    return null;
  }
  const parts = [
    event.ctrlKey ? "Ctrl" : "",
    event.altKey ? "Alt" : "",
    event.shiftKey ? "Shift" : "",
    event.metaKey ? "Meta" : "",
    keyFromEvent(event.key)
  ].filter(Boolean);
  return canonicalizeShortcut(parts.join("+"));
}

export function shortcutFromMouseButton(button: number): string | null {
  if (button === 3) {
    return "MouseX1";
  }
  if (button === 4) {
    return "MouseX2";
  }
  return null;
}

function validateHotkeyList(shortcuts: string[]): string | null {
  if (shortcuts.length < 1) {
    return "At least one hotkey is required.";
  }
  const seen = new Set<string>();
  for (const shortcut of shortcuts) {
    if (seen.has(shortcut)) {
      return "Hotkeys must be unique.";
    }
    seen.add(shortcut);
    const error = validateSingleHotkey(shortcut);
    if (error) {
      return error;
    }
  }
  return null;
}

function validateSingleHotkey(shortcut: string): string | null {
  if (shortcut === "MouseX1" || shortcut === "MouseX2") {
    return null;
  }
  const parts = shortcut.split("+").filter(Boolean);
  if (parts.some((part) => part === "MouseX1" || part === "MouseX2")) {
    return "Mouse hotkeys cannot include keyboard modifiers.";
  }
  const keyCount = parts.filter((part) => !MODIFIER_ORDER.includes(part as never)).length;
  if (keyCount !== 1) {
    return "Hotkey must contain exactly one non-modifier key.";
  }
  return null;
}

function keyFromEvent(key: string): string {
  if (key === " ") {
    return "Space";
  }
  return KEY_ALIASES.get(key.toLowerCase()) ?? key;
}

function normalizeKey(value: string): string {
  if (value.length === 1) {
    return value.toUpperCase();
  }
  return value.slice(0, 1).toUpperCase() + value.slice(1);
}
