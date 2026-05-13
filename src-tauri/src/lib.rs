use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    net::TcpStream,
    path::PathBuf,
    process::{Child, Command, Stdio},
    str::FromStr,
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use serde::{de::Error as DeError, Deserialize, Deserializer, Serialize};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    App, AppHandle, Emitter, Manager, PhysicalPosition, WebviewWindow, Window, WindowEvent,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

const RUNTIME_BASE_URL: &str = "http://127.0.0.1:8765";
const RUNTIME_SOCKET_ADDR: &str = "127.0.0.1:8765";
const RECORDING_BAR_LABEL: &str = "recording-bar";
const RECORDING_BAR_EVENT: &str = "recording-bar-state";
const RECORDING_BAR_WIDTH: i32 = 300;
const RECORDING_BAR_HEIGHT: i32 = 72;
const RECORDING_BAR_BOTTOM_MARGIN: i32 = 72;
const RECORDING_BAR_HIDE_DELAY: Duration = Duration::from_millis(700);
const RECORDING_STATE_LISTENING: &str = "listening";
const RECORDING_STATE_COMMAND: &str = "command";
const RECORDING_STATE_ERROR: &str = "error";

#[cfg(windows)]
use std::{
    os::windows::process::CommandExt,
    sync::{Once, OnceLock},
};
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[cfg(windows)]
use windows_sys::Win32::{
    Foundation::{LPARAM, LRESULT, WPARAM},
    UI::WindowsAndMessaging::{
        CallNextHookEx, DispatchMessageW, GetMessageW, SetWindowsHookExW, TranslateMessage, MSG,
        MSLLHOOKSTRUCT, WH_MOUSE_LL, WM_XBUTTONDOWN, WM_XBUTTONUP, XBUTTON1, XBUTTON2,
    },
};

#[cfg(windows)]
use windows::Win32::{
    Media::Audio::{
        eConsole, eRender, Endpoints::IAudioEndpointVolume, IMMDeviceEnumerator, MMDeviceEnumerator,
    },
    System::Com::{CoCreateInstance, CoInitializeEx, CLSCTX_ALL, COINIT_MULTITHREADED},
};

#[cfg(windows)]
static START_MOUSE_HOOK: Once = Once::new();
#[cfg(windows)]
static MOUSE_HOOK_APP: OnceLock<AppHandle> = OnceLock::new();

#[derive(Default)]
struct DesktopState {
    runtime_process: Mutex<Option<Child>>,
    hotkeys: Mutex<RegisteredHotkeys>,
    audio_ducking: Mutex<AudioDuckingState>,
    audio_ducking_settings: Mutex<AudioDuckingSettings>,
    recording_mode: Mutex<Option<String>>,
}

#[derive(Clone, Debug, Default)]
struct RegisteredHotkeys {
    dictation: HotkeyBindings,
    command_mode: HotkeyBindings,
}

#[derive(Clone, Debug, Default)]
struct HotkeyBindings {
    keyboard: Vec<Shortcut>,
    mouse: Vec<MouseButtonBinding>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum MouseButtonBinding {
    X1,
    X2,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct HotkeySettings {
    #[serde(deserialize_with = "deserialize_hotkey_list")]
    pub dictation: Vec<String>,
    #[serde(deserialize_with = "deserialize_hotkey_list")]
    pub command_mode: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
struct RuntimeStartRequest<'a> {
    mode: &'a str,
    language: Option<&'a str>,
}

#[derive(Clone, Debug, Serialize)]
struct RuntimeStopRequest<'a> {
    language: Option<&'a str>,
}

#[derive(Clone, Debug, Serialize)]
struct RecordingBarStatePayload {
    state: String,
    mode: String,
    message: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize)]
struct AudioDuckingSettings {
    enabled: bool,
    target_volume: f32,
}

impl Default for AudioDuckingSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            target_volume: 0.08,
        }
    }
}

impl AudioDuckingSettings {
    fn from_runtime_settings(runtime: DesktopRuntimeSettings) -> Self {
        Self {
            enabled: runtime.system_audio_ducking.unwrap_or(true),
            target_volume: duck_volume_percent_to_scalar(runtime.system_audio_duck_volume),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct VolumeSnapshot {
    volume: f32,
    muted: bool,
}

#[derive(Clone, Debug, Default)]
struct AudioDuckingState {
    snapshot: Option<VolumeSnapshot>,
}

#[derive(Clone, Debug, Deserialize)]
struct DesktopSettings {
    hotkeys: HotkeySettings,
    runtime: Option<DesktopRuntimeSettings>,
}

#[derive(Clone, Debug, Deserialize)]
struct DesktopRuntimeSettings {
    system_audio_ducking: Option<bool>,
    system_audio_duck_volume: Option<u8>,
}

trait VolumeEndpoint {
    fn get_volume(&mut self) -> Result<f32, String>;
    fn set_volume(&mut self, volume: f32) -> Result<(), String>;
    fn get_muted(&mut self) -> Result<bool, String>;
    fn set_muted(&mut self, muted: bool) -> Result<(), String>;
}

#[tauri::command]
fn start_runtime_process(app: AppHandle) -> Result<(), String> {
    spawn_runtime_api(&app)
}

#[tauri::command]
fn stop_runtime_process(app: AppHandle) -> Result<(), String> {
    restore_system_audio(&app);
    let state = app.state::<DesktopState>();
    if let Some(mut child) = state
        .runtime_process
        .lock()
        .map_err(|err| err.to_string())?
        .take()
    {
        let _ = child.kill();
    }
    Ok(())
}

#[tauri::command]
async fn runtime_status() -> Result<serde_json::Value, String> {
    get_json("/status").await
}

#[tauri::command]
async fn runtime_check() -> Result<serde_json::Value, String> {
    get_json("/runtime/check").await
}

#[tauri::command]
async fn runtime_diagnostics() -> Result<serde_json::Value, String> {
    get_json("/runtime/diagnostics").await
}

#[tauri::command]
fn show_settings_window(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        window.show().map_err(|err| err.to_string())?;
        window.set_focus().map_err(|err| err.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn register_hotkeys(app: AppHandle, hotkeys: HotkeySettings) -> Result<(), String> {
    register_hotkeys_inner(&app, hotkeys)
}

#[tauri::command]
fn configure_desktop_settings(app: AppHandle, settings: DesktopSettings) -> Result<(), String> {
    configure_desktop_settings_inner(&app, settings)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(DesktopState::default())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(handle_shortcut)
                .build(),
        )
        .setup(|app| {
            create_tray(app)?;
            if let Err(err) = spawn_runtime_api(&app.handle()) {
                eprintln!("WezaFlow could not start the Python runtime API: {err}");
            }
            start_mouse_button_listener(app.handle().clone());
            register_hotkeys_inner(
                &app.handle(),
                HotkeySettings {
                    dictation: vec!["Ctrl+Alt+Space".to_string()],
                    command_mode: vec!["Ctrl+Alt+E".to_string()],
                },
            )?;
            Ok(())
        })
        .on_window_event(handle_window_event)
        .invoke_handler(tauri::generate_handler![
            configure_desktop_settings,
            register_hotkeys,
            runtime_check,
            runtime_diagnostics,
            runtime_status,
            show_settings_window,
            start_runtime_process,
            stop_runtime_process
        ])
        .run(tauri::generate_context!())
        .expect("error while running WezaFlow");
}

fn create_tray(app: &mut App) -> tauri::Result<()> {
    let open_settings =
        MenuItem::with_id(app, "open_settings", "Open Settings", true, None::<&str>)?;
    let start_runtime =
        MenuItem::with_id(app, "start_runtime", "Start Engine", true, None::<&str>)?;
    let stop_runtime = MenuItem::with_id(app, "stop_runtime", "Stop Engine", true, None::<&str>)?;
    let diagnostics = MenuItem::with_id(app, "diagnostics", "Diagnostics", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit WezaFlow", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &open_settings,
            &start_runtime,
            &stop_runtime,
            &diagnostics,
            &quit,
        ],
    )?;

    TrayIconBuilder::with_id("main-tray")
        .menu(&menu)
        .tooltip("WezaFlow")
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open_settings" | "diagnostics" => {
                let _ = show_settings_window(app.clone());
            }
            "start_runtime" => {
                let _ = start_runtime_process(app.clone());
            }
            "stop_runtime" => {
                let _ = stop_runtime_process(app.clone());
            }
            "quit" => {
                let _ = stop_runtime_process(app.clone());
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;

    Ok(())
}

fn handle_window_event(window: &Window, event: &WindowEvent) {
    if let WindowEvent::CloseRequested { api, .. } = event {
        api.prevent_close();
        let _ = window.hide();
    }
}

fn register_hotkeys_inner(app: &AppHandle, hotkeys: HotkeySettings) -> Result<(), String> {
    let registered = parse_registered_hotkeys(hotkeys)?;

    app.global_shortcut()
        .unregister_all()
        .map_err(|err| err.to_string())?;
    for shortcut in registered
        .dictation
        .keyboard
        .iter()
        .chain(registered.command_mode.keyboard.iter())
    {
        app.global_shortcut()
            .register(shortcut.clone())
            .map_err(|err| err.to_string())?;
    }

    let state = app.state::<DesktopState>();
    *state.hotkeys.lock().map_err(|err| err.to_string())? = registered;
    Ok(())
}

fn configure_desktop_settings_inner(
    app: &AppHandle,
    settings: DesktopSettings,
) -> Result<(), String> {
    update_audio_ducking_settings(app, settings.runtime);
    register_hotkeys_inner(app, settings.hotkeys)
}

fn update_audio_ducking_settings(app: &AppHandle, runtime: Option<DesktopRuntimeSettings>) {
    let settings = runtime
        .map(AudioDuckingSettings::from_runtime_settings)
        .unwrap_or_default();
    if let Ok(mut current) = app.state::<DesktopState>().audio_ducking_settings.lock() {
        *current = settings;
    }
}

fn handle_shortcut(
    app: &AppHandle,
    shortcut: &Shortcut,
    event: tauri_plugin_global_shortcut::ShortcutEvent,
) {
    let state = app.state::<DesktopState>();
    let hotkeys = match state.hotkeys.lock() {
        Ok(hotkeys) => hotkeys.clone(),
        Err(_) => return,
    };
    let mode = if hotkeys
        .dictation
        .keyboard
        .iter()
        .any(|registered| registered == shortcut)
    {
        Some("dictation")
    } else if hotkeys
        .command_mode
        .keyboard
        .iter()
        .any(|registered| registered == shortcut)
    {
        Some("command")
    } else {
        None
    };

    let Some(mode) = mode else {
        return;
    };
    match event.state() {
        ShortcutState::Pressed => start_runtime_mode(app, mode),
        ShortcutState::Released => stop_runtime_mode(app),
    }
}

fn parse_registered_hotkeys(hotkeys: HotkeySettings) -> Result<RegisteredHotkeys, String> {
    let registered = RegisteredHotkeys {
        dictation: parse_hotkey_bindings(&hotkeys.dictation)?,
        command_mode: parse_hotkey_bindings(&hotkeys.command_mode)?,
    };
    ensure_unique_bindings(&registered)?;
    Ok(registered)
}

fn parse_hotkey_bindings(values: &[String]) -> Result<HotkeyBindings, String> {
    if values.is_empty() {
        return Err("At least one hotkey is required.".to_string());
    }
    let mut bindings = HotkeyBindings::default();
    for value in values {
        let trimmed = value.trim();
        if trimmed.is_empty() {
            return Err("Hotkey cannot be empty.".to_string());
        }
        if let Some(button) = parse_mouse_button(trimmed) {
            bindings.mouse.push(button);
        } else {
            bindings.keyboard.push(parse_shortcut(trimmed)?);
        }
    }
    Ok(bindings)
}

fn ensure_unique_bindings(hotkeys: &RegisteredHotkeys) -> Result<(), String> {
    let keyboard_bindings: Vec<(&str, &Shortcut)> = hotkeys
        .dictation
        .keyboard
        .iter()
        .map(|shortcut| ("dictation", shortcut))
        .chain(
            hotkeys
                .command_mode
                .keyboard
                .iter()
                .map(|shortcut| ("command mode", shortcut)),
        )
        .collect();
    for left in 0..keyboard_bindings.len() {
        for right in (left + 1)..keyboard_bindings.len() {
            if keyboard_bindings[left].1 == keyboard_bindings[right].1 {
                return duplicate_hotkey_error(
                    keyboard_bindings[left].0,
                    keyboard_bindings[right].0,
                );
            }
        }
    }

    let mouse_bindings: Vec<(&str, MouseButtonBinding)> = hotkeys
        .dictation
        .mouse
        .iter()
        .copied()
        .map(|button| ("dictation", button))
        .chain(
            hotkeys
                .command_mode
                .mouse
                .iter()
                .copied()
                .map(|button| ("command mode", button)),
        )
        .collect();
    for left in 0..mouse_bindings.len() {
        for right in (left + 1)..mouse_bindings.len() {
            if mouse_bindings[left].1 == mouse_bindings[right].1 {
                return duplicate_hotkey_error(mouse_bindings[left].0, mouse_bindings[right].0);
            }
        }
    }
    Ok(())
}

fn duplicate_hotkey_error(left: &str, right: &str) -> Result<(), String> {
    if left == right {
        Err("Hotkeys must be unique.".to_string())
    } else {
        Err("Dictation and command mode hotkeys must be different.".to_string())
    }
}

fn duck_volume_percent_to_scalar(value: Option<u8>) -> f32 {
    f32::from(value.unwrap_or(8).min(30)) / 100.0
}

fn apply_audio_ducking<E: VolumeEndpoint>(
    endpoint: &mut E,
    settings: AudioDuckingSettings,
    state: &mut AudioDuckingState,
) -> Result<(), String> {
    if !settings.enabled || state.snapshot.is_some() {
        return Ok(());
    }

    let current_muted = endpoint.get_muted()?;
    let current_volume = endpoint.get_volume()?.clamp(0.0, 1.0);
    let target = settings.target_volume.clamp(0.0, 0.30);
    if current_muted || current_volume <= target {
        return Ok(());
    }

    state.snapshot = Some(VolumeSnapshot {
        volume: current_volume,
        muted: current_muted,
    });
    endpoint.set_volume(target)?;
    Ok(())
}

fn restore_audio_ducking<E: VolumeEndpoint>(
    endpoint: &mut E,
    state: &mut AudioDuckingState,
) -> Result<(), String> {
    let Some(snapshot) = state.snapshot.take() else {
        return Ok(());
    };
    endpoint.set_volume(snapshot.volume.clamp(0.0, 1.0))?;
    endpoint.set_muted(snapshot.muted)?;
    Ok(())
}

fn duck_system_audio(app: &AppHandle) {
    let settings = app
        .state::<DesktopState>()
        .audio_ducking_settings
        .lock()
        .map(|settings| *settings)
        .unwrap_or_default();
    if !settings.enabled {
        return;
    }
    let Err(err) = with_system_volume_endpoint(|endpoint| {
        let desktop_state = app.state::<DesktopState>();
        let mut state = desktop_state
            .audio_ducking
            .lock()
            .map_err(|err| err.to_string())?;
        apply_audio_ducking(endpoint, settings, &mut state)
    }) else {
        return;
    };
    eprintln!("WezaFlow could not duck system audio: {err}");
}

fn restore_system_audio(app: &AppHandle) {
    let Err(err) = with_system_volume_endpoint(|endpoint| {
        let desktop_state = app.state::<DesktopState>();
        let mut state = desktop_state
            .audio_ducking
            .lock()
            .map_err(|err| err.to_string())?;
        restore_audio_ducking(endpoint, &mut state)
    }) else {
        return;
    };
    eprintln!("WezaFlow could not restore system audio: {err}");
}

#[cfg(windows)]
struct WindowsVolumeEndpoint {
    endpoint: IAudioEndpointVolume,
}

#[cfg(windows)]
impl VolumeEndpoint for WindowsVolumeEndpoint {
    fn get_volume(&mut self) -> Result<f32, String> {
        unsafe {
            self.endpoint
                .GetMasterVolumeLevelScalar()
                .map_err(|err| err.to_string())
        }
    }

    fn set_volume(&mut self, volume: f32) -> Result<(), String> {
        unsafe {
            self.endpoint
                .SetMasterVolumeLevelScalar(volume.clamp(0.0, 1.0), std::ptr::null())
                .map_err(|err| err.to_string())
        }
    }

    fn get_muted(&mut self) -> Result<bool, String> {
        unsafe {
            self.endpoint
                .GetMute()
                .map(|muted| muted.as_bool())
                .map_err(|err| err.to_string())
        }
    }

    fn set_muted(&mut self, muted: bool) -> Result<(), String> {
        unsafe {
            self.endpoint
                .SetMute(muted.into(), std::ptr::null())
                .map_err(|err| err.to_string())
        }
    }
}

#[cfg(windows)]
fn with_system_volume_endpoint<F>(operation: F) -> Result<(), String>
where
    F: FnOnce(&mut WindowsVolumeEndpoint) -> Result<(), String>,
{
    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        let enumerator: IMMDeviceEnumerator =
            CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
                .map_err(|err| err.to_string())?;
        let device = enumerator
            .GetDefaultAudioEndpoint(eRender, eConsole)
            .map_err(|err| err.to_string())?;
        let endpoint = device
            .Activate(CLSCTX_ALL, None)
            .map_err(|err| err.to_string())?;
        operation(&mut WindowsVolumeEndpoint { endpoint })
    }
}

#[cfg(not(windows))]
fn with_system_volume_endpoint<F>(_operation: F) -> Result<(), String>
where
    F: FnOnce(&mut NoopVolumeEndpoint) -> Result<(), String>,
{
    Ok(())
}

#[cfg(not(windows))]
struct NoopVolumeEndpoint;

#[cfg(not(windows))]
impl VolumeEndpoint for NoopVolumeEndpoint {
    fn get_volume(&mut self) -> Result<f32, String> {
        Ok(1.0)
    }

    fn set_volume(&mut self, _volume: f32) -> Result<(), String> {
        Ok(())
    }

    fn get_muted(&mut self) -> Result<bool, String> {
        Ok(false)
    }

    fn set_muted(&mut self, _muted: bool) -> Result<(), String> {
        Ok(())
    }
}

pub fn parse_shortcut(value: &str) -> Result<Shortcut, String> {
    let mut modifiers = Modifiers::empty();
    let mut key: Option<Code> = None;

    for raw_part in value.split('+') {
        let part = raw_part.trim();
        if part.is_empty() {
            continue;
        }
        match part.to_ascii_lowercase().as_str() {
            "ctrl" | "control" => modifiers.insert(Modifiers::CONTROL),
            "alt" | "option" => modifiers.insert(Modifiers::ALT),
            "shift" => modifiers.insert(Modifiers::SHIFT),
            "meta" | "super" | "win" | "windows" | "cmd" | "command" => {
                modifiers.insert(Modifiers::SUPER)
            }
            _ => {
                if key.is_some() {
                    return Err("Shortcut must contain exactly one non-modifier key.".to_string());
                }
                key = Some(parse_code(part)?);
            }
        }
    }

    let Some(key) = key else {
        return Err("Shortcut must contain exactly one non-modifier key.".to_string());
    };
    let modifiers = if modifiers.is_empty() {
        None
    } else {
        Some(modifiers)
    };
    Ok(Shortcut::new(modifiers, key))
}

fn parse_code(part: &str) -> Result<Code, String> {
    let normalized = part.trim();
    match normalized.to_ascii_lowercase().as_str() {
        "space" | "spacebar" => return Ok(Code::Space),
        "esc" | "escape" => return Ok(Code::Escape),
        "enter" | "return" => return Ok(Code::Enter),
        "tab" => return Ok(Code::Tab),
        "backspace" => return Ok(Code::Backspace),
        "delete" | "del" => return Ok(Code::Delete),
        _ => {}
    }

    if normalized.len() == 1 {
        let character = normalized.chars().next().unwrap();
        if character.is_ascii_alphabetic() {
            return Code::from_str(&format!("Key{}", character.to_ascii_uppercase()))
                .map_err(|_| format!("Unsupported shortcut key: {part}"));
        }
        if character.is_ascii_digit() {
            return Code::from_str(&format!("Digit{character}"))
                .map_err(|_| format!("Unsupported shortcut key: {part}"));
        }
    }

    Code::from_str(normalized).map_err(|_| format!("Unsupported shortcut key: {part}"))
}

fn parse_mouse_button(part: &str) -> Option<MouseButtonBinding> {
    match part
        .trim()
        .to_ascii_lowercase()
        .replace([' ', '_', '-'], "")
        .as_str()
    {
        "mousex1" | "mouse4" | "button4" | "xbutton1" | "back" => Some(MouseButtonBinding::X1),
        "mousex2" | "mouse5" | "button5" | "xbutton2" | "forward" => Some(MouseButtonBinding::X2),
        _ => None,
    }
}

fn deserialize_hotkey_list<'de, D>(deserializer: D) -> Result<Vec<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = serde_json::Value::deserialize(deserializer)?;
    match value {
        serde_json::Value::String(shortcut) => Ok(vec![shortcut]),
        serde_json::Value::Array(items) => items
            .into_iter()
            .map(|item| match item {
                serde_json::Value::String(shortcut) => Ok(shortcut),
                _ => Err(D::Error::custom("hotkey entries must be strings")),
            })
            .collect(),
        _ => Err(D::Error::custom(
            "hotkey must be a string or list of strings",
        )),
    }
}

fn recording_bar_payload(
    state: &str,
    mode: &str,
    message: Option<&str>,
) -> RecordingBarStatePayload {
    RecordingBarStatePayload {
        state: state.to_string(),
        mode: mode.to_string(),
        message: message.map(|value| value.to_string()),
    }
}

fn recording_bar_window(app: &AppHandle) -> Option<WebviewWindow> {
    app.get_webview_window(RECORDING_BAR_LABEL)
}

fn position_recording_bar(window: &WebviewWindow) {
    let Ok(Some(monitor)) = window.primary_monitor() else {
        return;
    };
    let work_area = monitor.work_area();
    let x = work_area.position.x + ((work_area.size.width as i32 - RECORDING_BAR_WIDTH) / 2);
    let y = work_area.position.y + work_area.size.height as i32
        - RECORDING_BAR_HEIGHT
        - RECORDING_BAR_BOTTOM_MARGIN;
    if let Err(err) = window.set_position(PhysicalPosition::new(
        x.max(work_area.position.x),
        y.max(work_area.position.y),
    )) {
        eprintln!("WezaFlow could not position recording bar: {err}");
    }
}

fn show_recording_bar(app: &AppHandle, state: &str, mode: &str, message: Option<&str>) {
    let Some(window) = recording_bar_window(app) else {
        return;
    };
    position_recording_bar(&window);
    if let Err(err) = window.emit(
        RECORDING_BAR_EVENT,
        recording_bar_payload(state, mode, message),
    ) {
        eprintln!("WezaFlow could not emit recording bar state: {err}");
    }
    if let Err(err) = window.show() {
        eprintln!("WezaFlow could not show recording bar: {err}");
    }
}

fn hide_recording_bar(app: &AppHandle) {
    let Some(window) = recording_bar_window(app) else {
        return;
    };
    if let Err(err) = window.hide() {
        eprintln!("WezaFlow could not hide recording bar: {err}");
    }
}

fn hide_recording_bar_after(app: AppHandle) {
    thread::spawn(move || {
        thread::sleep(RECORDING_BAR_HIDE_DELAY);
        hide_recording_bar(&app);
    });
}

fn set_active_recording_mode(app: &AppHandle, mode: &str) {
    if let Ok(mut recording_mode) = app.state::<DesktopState>().recording_mode.lock() {
        *recording_mode = Some(mode.to_string());
    }
}

fn take_active_recording_mode(app: &AppHandle) -> String {
    app.state::<DesktopState>()
        .recording_mode
        .lock()
        .ok()
        .and_then(|mut mode| mode.take())
        .unwrap_or_else(|| "dictation".to_string())
}

fn is_active_recording_mode(app: &AppHandle, expected_mode: &str) -> bool {
    app.state::<DesktopState>()
        .recording_mode
        .lock()
        .map(|mode| mode.as_deref() == Some(expected_mode))
        .unwrap_or(false)
}

fn start_runtime_mode(app: &AppHandle, mode: &str) {
    if mode == "dictation" {
        duck_system_audio(app);
    }
    set_active_recording_mode(app, mode);
    let recording_state = if mode == "command" {
        RECORDING_STATE_COMMAND
    } else {
        RECORDING_STATE_LISTENING
    };
    show_recording_bar(app, recording_state, mode, None);
    let app = app.clone();
    let mode = mode.to_string();
    tauri::async_runtime::spawn(async move {
        if let Err(err) = post_json(
            "/runtime/start",
            &RuntimeStartRequest {
                mode: &mode,
                language: Some("en"),
            },
        )
        .await
        {
            if !is_active_recording_mode(&app, &mode) {
                return;
            }
            show_recording_bar(&app, RECORDING_STATE_ERROR, &mode, Some(&err));
            hide_recording_bar_after(app);
        }
    });
}

fn stop_runtime_mode(app: &AppHandle) {
    let _ = take_active_recording_mode(app);
    hide_recording_bar(app);
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(err) = post_json(
            "/runtime/stop",
            &RuntimeStopRequest {
                language: Some("en"),
            },
        )
        .await
        {
            eprintln!("WezaFlow could not stop recording cleanly: {err}");
        }
        restore_system_audio(&app);
    });
}

fn handle_mouse_button(app: &AppHandle, button: MouseButtonBinding, pressed: bool) {
    let state = app.state::<DesktopState>();
    let hotkeys = match state.hotkeys.lock() {
        Ok(hotkeys) => hotkeys.clone(),
        Err(_) => return,
    };
    let mode = if hotkeys.dictation.mouse.contains(&button) {
        Some("dictation")
    } else if hotkeys.command_mode.mouse.contains(&button) {
        Some("command")
    } else {
        None
    };

    let Some(mode) = mode else {
        return;
    };
    if pressed {
        start_runtime_mode(app, mode);
    } else {
        stop_runtime_mode(app);
    }
}

#[cfg(windows)]
fn start_mouse_button_listener(app: AppHandle) {
    START_MOUSE_HOOK.call_once(move || {
        let _ = MOUSE_HOOK_APP.set(app);
        thread::spawn(|| unsafe {
            let hook =
                SetWindowsHookExW(WH_MOUSE_LL, Some(mouse_hook_proc), std::ptr::null_mut(), 0);
            if hook.is_null() {
                return;
            }
            let mut message: MSG = std::mem::zeroed();
            while GetMessageW(&mut message, std::ptr::null_mut(), 0, 0) > 0 {
                let _ = TranslateMessage(&message);
                DispatchMessageW(&message);
            }
        });
    });
}

#[cfg(not(windows))]
fn start_mouse_button_listener(_app: AppHandle) {}

#[cfg(windows)]
unsafe extern "system" fn mouse_hook_proc(code: i32, w_param: WPARAM, l_param: LPARAM) -> LRESULT {
    if code >= 0 && (w_param as u32 == WM_XBUTTONDOWN || w_param as u32 == WM_XBUTTONUP) {
        let info = *(l_param as *const MSLLHOOKSTRUCT);
        let x_button = ((info.mouseData >> 16) & 0xffff) as u16;
        let button = match x_button {
            XBUTTON1 => Some(MouseButtonBinding::X1),
            XBUTTON2 => Some(MouseButtonBinding::X2),
            _ => None,
        };
        if let (Some(app), Some(button)) = (MOUSE_HOOK_APP.get(), button) {
            handle_mouse_button(app, button, w_param as u32 == WM_XBUTTONDOWN);
        }
    }
    CallNextHookEx(std::ptr::null_mut(), code, w_param, l_param)
}

async fn get_json(path: &str) -> Result<serde_json::Value, String> {
    reqwest::Client::new()
        .get(format!("{RUNTIME_BASE_URL}{path}"))
        .send()
        .await
        .map_err(|err| err.to_string())?
        .error_for_status()
        .map_err(|err| err.to_string())?
        .json::<serde_json::Value>()
        .await
        .map_err(|err| err.to_string())
}

async fn post_json<T: Serialize + ?Sized>(
    path: &str,
    payload: &T,
) -> Result<serde_json::Value, String> {
    reqwest::Client::new()
        .post(format!("{RUNTIME_BASE_URL}{path}"))
        .json(payload)
        .send()
        .await
        .map_err(|err| err.to_string())?
        .error_for_status()
        .map_err(|err| err.to_string())?
        .json::<serde_json::Value>()
        .await
        .map_err(|err| err.to_string())
}

fn spawn_runtime_api(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<DesktopState>();
    let mut runtime = state
        .runtime_process
        .lock()
        .map_err(|err| err.to_string())?;

    if runtime_api_is_compatible() {
        return Ok(());
    }

    if let Some(child) = runtime.as_mut() {
        if child.try_wait().map_err(|err| err.to_string())?.is_none() {
            wait_for_runtime_api(child, Duration::from_secs(3))?;
            return Ok(());
        }
        *runtime = None;
    }

    let root = project_root();
    if runtime_api_is_listening() {
        terminate_recorded_runtime_process(&root);
        wait_for_runtime_api_port_to_close(Duration::from_secs(2));
        if runtime_api_is_listening() {
            return Err(
                "an incompatible LocalFlow runtime API is already using 127.0.0.1:8765".to_string(),
            );
        }
    }

    if !is_project_root(&root) {
        return Err(format!(
            "could not find project root containing services/runtime/api.py from {}",
            root.display()
        ));
    }
    let python = python_executable(&root);
    let mut command = Command::new(python);
    command
        .args(["-m", "services.runtime.api"])
        .current_dir(&root);

    if let Ok(log_file) = runtime_log_file(&root) {
        if let Ok(stderr) = log_file.try_clone() {
            command.stdout(Stdio::from(log_file));
            command.stderr(Stdio::from(stderr));
        }
    }

    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    let mut child = command.spawn().map_err(|err| err.to_string())?;
    wait_for_runtime_api(&mut child, Duration::from_secs(30))?;
    record_runtime_pid(&root, child.id());
    *runtime = Some(child);
    Ok(())
}

fn project_root() -> PathBuf {
    find_project_root_from_candidates(project_root_candidates())
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
}

fn project_root_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(root) = std::env::var("LOCALFLOW_PROJECT_ROOT") {
        candidates.push(PathBuf::from(root));
    }
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        candidates.push(exe);
    }
    candidates
}

fn find_project_root_from_candidates<I>(candidates: I) -> Option<PathBuf>
where
    I: IntoIterator<Item = PathBuf>,
{
    for candidate in candidates {
        let start = if candidate.is_file() || candidate.extension().is_some() {
            candidate.parent().map(PathBuf::from)
        } else {
            Some(candidate)
        };
        let Some(start) = start else {
            continue;
        };
        for ancestor in start.ancestors() {
            if is_project_root(ancestor) {
                return Some(ancestor.to_path_buf());
            }
        }
    }
    None
}

fn is_project_root(path: &std::path::Path) -> bool {
    path.join("pyproject.toml").exists()
        && path
            .join("services")
            .join("runtime")
            .join("api.py")
            .exists()
}

fn runtime_log_file(root: &std::path::Path) -> Result<File, String> {
    let log_dir = root.join("artifacts").join("logs");
    fs::create_dir_all(&log_dir).map_err(|err| err.to_string())?;
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("desktop-python-api.log"))
        .map_err(|err| err.to_string())
}

fn runtime_pid_file(root: &std::path::Path) -> PathBuf {
    root.join("artifacts")
        .join("logs")
        .join("desktop-python-api.pid")
}

fn record_runtime_pid(root: &std::path::Path, pid: u32) {
    let path = runtime_pid_file(root);
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(path, pid.to_string());
}

fn terminate_recorded_runtime_process(root: &std::path::Path) {
    let Ok(pid_text) = fs::read_to_string(runtime_pid_file(root)) else {
        return;
    };
    let Ok(pid) = pid_text.trim().parse::<u32>() else {
        return;
    };
    terminate_process(pid);
}

fn terminate_process(pid: u32) {
    #[cfg(windows)]
    {
        let mut command = Command::new("taskkill");
        command.args(["/PID", &pid.to_string(), "/T", "/F"]);
        command.creation_flags(CREATE_NO_WINDOW);
        let _ = command.status();
    }

    #[cfg(not(windows))]
    {
        let _ = Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status();
    }
}

fn runtime_api_is_listening() -> bool {
    let Ok(addr) = RUNTIME_SOCKET_ADDR.parse() else {
        return false;
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(250)).is_ok()
}

fn runtime_api_is_compatible() -> bool {
    runtime_api_is_compatible_with(|path| runtime_api_path_is_ok(path, Duration::from_millis(600)))
}

fn runtime_api_is_compatible_with<F>(mut probe: F) -> bool
where
    F: FnMut(&str) -> bool,
{
    ["/health", "/runtime/capabilities"]
        .into_iter()
        .all(|path| probe(path))
}

fn runtime_api_path_is_ok(path: &str, timeout: Duration) -> bool {
    let Ok(addr) = RUNTIME_SOCKET_ADDR.parse() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, timeout) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(timeout));
    let _ = stream.set_write_timeout(Some(timeout));
    let request = format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    runtime_api_response_is_ok(path, &response)
}

fn runtime_api_response_is_ok(path: &str, response: &str) -> bool {
    let status_ok = response
        .lines()
        .next()
        .map(|line| line.contains(" 200 "))
        .unwrap_or(false);
    if !status_ok {
        return false;
    }
    if path == "/runtime/capabilities" {
        return response.contains("\"runtime-warmup\"");
    }
    true
}

fn wait_for_runtime_api_port_to_close(timeout: Duration) {
    let started = Instant::now();
    while started.elapsed() < timeout {
        if !runtime_api_is_listening() {
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }
}

fn wait_for_runtime_api(child: &mut Child, timeout: Duration) -> Result<(), String> {
    let started = Instant::now();
    while started.elapsed() < timeout {
        if runtime_api_is_compatible() {
            return Ok(());
        }
        if let Some(status) = child.try_wait().map_err(|err| err.to_string())? {
            return Err(format!(
                "Python runtime API exited during startup with status {status}. Check artifacts/logs/desktop-python-api.log."
            ));
        }
        thread::sleep(Duration::from_millis(150));
    }
    Err("Python runtime API did not become ready before the startup timeout.".to_string())
}

fn python_executable(root: &PathBuf) -> PathBuf {
    let venv_python = if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    };
    if venv_python.exists() {
        venv_python
    } else {
        PathBuf::from("python")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ctrl_alt_space() {
        let shortcut = parse_shortcut("Ctrl+Alt+Space").unwrap();

        assert!(shortcut.mods.contains(Modifiers::CONTROL));
        assert!(shortcut.mods.contains(Modifiers::ALT));
        assert_eq!(shortcut.key, Code::Space);
    }

    #[test]
    fn parses_single_letter_command_shortcut() {
        let shortcut = parse_shortcut("control + alt + e").unwrap();

        assert!(shortcut.mods.contains(Modifiers::CONTROL));
        assert!(shortcut.mods.contains(Modifiers::ALT));
        assert_eq!(shortcut.key, Code::KeyE);
    }

    #[test]
    fn rejects_shortcuts_without_non_modifier_key() {
        let error = parse_shortcut("Ctrl+Alt").unwrap_err();

        assert!(error.contains("one non-modifier key"));
    }

    #[test]
    fn parses_keyboard_and_mouse_bindings() {
        let bindings =
            parse_hotkey_bindings(&["Ctrl+Alt+Space".to_string(), "MouseX1".to_string()]).unwrap();

        assert_eq!(bindings.keyboard.len(), 1);
        assert_eq!(bindings.mouse, vec![MouseButtonBinding::X1]);
    }

    #[test]
    fn rejects_duplicate_bindings_across_modes() {
        let error = parse_registered_hotkeys(HotkeySettings {
            dictation: vec!["Ctrl+Alt+Space".to_string(), "MouseX1".to_string()],
            command_mode: vec!["Ctrl+Alt+E".to_string(), "Mouse 4".to_string()],
        })
        .unwrap_err();

        assert!(error.contains("must be different"));
    }

    #[test]
    fn finds_project_root_from_release_executable_path() {
        let root = std::env::temp_dir().join(format!(
            "localflow-root-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let release_dir = root.join("src-tauri").join("target").join("release");
        let runtime_dir = root.join("services").join("runtime");
        std::fs::create_dir_all(&release_dir).unwrap();
        std::fs::create_dir_all(&runtime_dir).unwrap();
        std::fs::write(root.join("pyproject.toml"), "").unwrap();
        std::fs::write(runtime_dir.join("api.py"), "").unwrap();

        let found = find_project_root_from_candidates([release_dir.join("localflow.exe")]).unwrap();

        assert_eq!(found, root);
        std::fs::remove_dir_all(found).unwrap();
    }

    #[derive(Debug)]
    struct FakeVolumeEndpoint {
        volume: f32,
        muted: bool,
        changes: Vec<String>,
    }

    impl VolumeEndpoint for FakeVolumeEndpoint {
        fn get_volume(&mut self) -> Result<f32, String> {
            Ok(self.volume)
        }

        fn set_volume(&mut self, volume: f32) -> Result<(), String> {
            self.volume = volume;
            self.changes.push(format!("volume:{volume:.2}"));
            Ok(())
        }

        fn get_muted(&mut self) -> Result<bool, String> {
            Ok(self.muted)
        }

        fn set_muted(&mut self, muted: bool) -> Result<(), String> {
            self.muted = muted;
            self.changes.push(format!("muted:{muted}"));
            Ok(())
        }
    }

    #[test]
    fn ducks_and_restores_volume_once_per_dictation_hold() {
        let mut endpoint = FakeVolumeEndpoint {
            volume: 0.75,
            muted: false,
            changes: Vec::new(),
        };
        let mut state = AudioDuckingState::default();
        let settings = AudioDuckingSettings {
            enabled: true,
            target_volume: 0.08,
        };

        apply_audio_ducking(&mut endpoint, settings, &mut state).unwrap();
        apply_audio_ducking(&mut endpoint, settings, &mut state).unwrap();
        restore_audio_ducking(&mut endpoint, &mut state).unwrap();

        assert_eq!(endpoint.volume, 0.75);
        assert_eq!(
            endpoint.changes,
            vec![
                "volume:0.08".to_string(),
                "volume:0.75".to_string(),
                "muted:false".to_string()
            ]
        );
    }

    #[test]
    fn skips_ducking_when_disabled_or_already_quieter_than_target() {
        let mut endpoint = FakeVolumeEndpoint {
            volume: 0.05,
            muted: false,
            changes: Vec::new(),
        };
        let mut state = AudioDuckingState::default();

        apply_audio_ducking(
            &mut endpoint,
            AudioDuckingSettings {
                enabled: true,
                target_volume: 0.08,
            },
            &mut state,
        )
        .unwrap();
        apply_audio_ducking(
            &mut endpoint,
            AudioDuckingSettings {
                enabled: false,
                target_volume: 0.08,
            },
            &mut state,
        )
        .unwrap();

        assert!(endpoint.changes.is_empty());
    }

    #[test]
    fn runtime_compatibility_requires_current_api_surface() {
        let mut probed_paths = Vec::new();

        let compatible = runtime_api_is_compatible_with(|path| {
            probed_paths.push(path.to_string());
            path != "/runtime/capabilities"
        });

        assert!(!compatible);
        assert!(probed_paths.contains(&"/runtime/capabilities".to_string()));
        assert!(!probed_paths.contains(&"/corrections/pending".to_string()));
        assert!(!probed_paths.contains(&"/learning/suggestions".to_string()));
    }

    #[test]
    fn runtime_compatibility_accepts_all_required_paths() {
        assert!(runtime_api_is_compatible_with(|_| true));
    }

    #[test]
    fn runtime_capability_response_requires_warmup_capability() {
        assert!(runtime_api_response_is_ok(
            "/runtime/capabilities",
            "HTTP/1.1 200 OK\r\n\r\n{\"capabilities\":[\"runtime-warmup\"]}"
        ));
        assert!(!runtime_api_response_is_ok(
            "/runtime/capabilities",
            "HTTP/1.1 200 OK\r\n\r\n{\"capabilities\":[\"profile-session-refresh\"]}"
        ));
    }
}
