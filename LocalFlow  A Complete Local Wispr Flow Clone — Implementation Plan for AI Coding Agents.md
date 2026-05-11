# LocalFlow: A Complete Local Wispr Flow Clone
## Implementation Plan for AI Coding Agents

***

## Executive Summary

Wispr Flow is a cloud-first AI dictation tool that routes audio through Baseten for ASR and OpenAI/Anthropic/Cerebras for LLM post-processing. Its edge comes from four pillars: (1) a low-latency pipeline with a sub-700ms total budget, (2) LLM post-processing that interprets intent rather than just transcribing words, (3) context-aware formatting that reads the active app via accessibility APIs, and (4) continuous vocabulary adaptation over time. This plan replicates and exceeds all four pillars locally, at zero recurring cost, on the Minisforum UM890 Pro (AMD Ryzen 9 8945HS, Radeon 780M, 64 GB DDR5).[^1][^2][^3][^4][^5][^6]

The hardware has no dedicated NPU. On Windows, the stable baseline is CPU inference with CTranslate2 int8 quantization; the Radeon 780M iGPU can be evaluated later through Vulkan-backed `whisper.cpp` / `llama.cpp`, or through ROCm/HIP only after the exact Windows Ryzen APU stack is validated. With `faster-whisper` on CPU using CTranslate2 int8 quantization, a large-v3-turbo model runs well within the latency budget on modern AMD Zen 4 hardware.[^7][^8][^9][^10][^11][^12]

***

## Part 1: Dissecting Wispr Flow — What Gives It the Edge

### 1.1 The Core Pipeline

Wispr Flow's full pipeline operates as follows: the user holds a hotkey → local mic captures PCM audio → audio is encrypted and sent to Baseten (cloud ASR) → raw transcript returned → LLM (OpenAI/Anthropic/Cerebras) reformats, cleans filler words, and adjusts tone → final polished text is injected into the active text field. The total time budget is 700ms: ≤200ms for ASR inference, ≤200ms for LLM formatting, and ≤200ms for network round-trip.[^13][^3][^4]

### 1.2 What Makes It Better Than Basic Dictation

| Feature | Basic Dictation (OS built-in) | Wispr Flow | LocalFlow Target |
|---|---|---|---|
| Filler word removal | ❌ | ✅ Automatic | ✅ LLM post-process |
| Self-correction handling | ❌ | ✅ ("actually make that 75K") | ✅ LLM post-process |
| Context-aware tone | ❌ | ✅ Email vs Slack vs Code | ✅ App-profile system |
| Personal dictionary | ❌ | ✅ Auto-learns corrections | ✅ SQLite + prompt injection |
| Command Mode (edit highlighted) | ❌ | ✅ | ✅ Clipboard-based edit |
| Whisper mode (quiet speech) | ❌ | ✅ | ✅ No-threshold VAD |
| Snippets / voice shortcuts | ❌ | ✅ | ✅ YAML-based triggers |
| 100+ languages | ❌ | ✅ | ✅ Whisper multilingual |
| Privacy | Cloud-only, data leaves device | Cloud-only by design[^14] | ✅ 100% local |

### 1.3 Context Awareness — The Killer Feature

Wispr Flow reads the active application using macOS Accessibility APIs and Windows UI Automation. It identifies app categories (Email, Work Messaging, Personal Messaging, Code, Other) and pre-selects a matching LLM system prompt for formatting style. For browsers, it reads the URL to differentiate Gmail from Slack even if both are in Chrome. This is the feature that most basic Whisper clones lack and what makes dictated text feel "already edited."[^6]

### 1.4 The LLM Post-Processing Layer

Flow does not just transcribe — it runs text through an LLM to (a) remove filler words, (b) handle self-corrections like "wait, no, I mean…", (c) add punctuation and capitalization, (d) adjust tone to match app context, and (e) recognize proper nouns from screen context. This step is what turns raw ASR output into publication-ready text. The LLM receives: the raw transcript + active app category + screen-visible text snippets (for proper nouns) + user's custom vocabulary.[^15][^1]

***

## Part 2: Hardware & Runtime Analysis

### 2.1 Minisforum UM890 Pro Capabilities

- **CPU**: AMD Ryzen 9 8945HS — Zen 4, 8C/16T, up to 5.2 GHz[^5]
- **iGPU**: AMD Radeon 780M — RDNA 3, gfx1103, 12 CUs, 2800 MHz[^16]
- **RAM**: 64 GB DDR5-5600 (shared with iGPU)[^17]
- **NPU**: None — Ryzen 9 8945HS uses CPU/GPU for AI workloads[^9]
- **Windows GPU path**: treat CPU int8 as the supported baseline; evaluate AMD ROCm/HIP only after verifying the current Windows Ryzen APU support matrix on the target machine[^31]
- **Vulkan**: llama.cpp and whisper.cpp both support Vulkan compute — viable optional acceleration path on Windows[^11]

### 2.2 Recommended Inference Strategy

| Component | Primary Backend | Fallback |
|---|---|---|
| Whisper ASR (STT) | `faster-whisper` large-v3-turbo, int8, CPU | whisper.cpp Vulkan |
| LLM Post-Processor | Ollama + Qwen3.5:4b, CPU offload | `llama.cpp` Vulkan, iGPU |
| VAD | Silero VAD (ONNX, CPU, <1ms per chunk) | webrtcvad |
| Context Engine | `win32gui` + `win32process` + `psutil` for active app/window | UI Automation title-only fallback |
| Browser URL Context | `pywinauto` UI Automation value extraction | Browser extension or title-only classification |
| Text Injection | Clipboard paste via `pyperclip` + `pyautogui.hotkey("ctrl", "v")` | `keyboard.send("ctrl+v")`; direct `pyautogui.write()` for simple ASCII |

**Why `faster-whisper` over `whisper.cpp` for primary ASR**: CTranslate2 int8 CPU inference is extremely well-optimized for x86-64 AVX2/AVX-512 and achieves sub-1-second latency on short utterances without requiring ROCm setup. The large-v3-turbo model (4 decoder layers vs 32 in large-v3) provides a 5.4x speedup over large-v3 with minimal quality loss. Whisper large-v3-turbo has an RTFx of 216x, making real-time transcription feasible.[^8][^18][^19][^20]

**Why Qwen3.5:4b for LLM**: Small Qwen3 models are broadly recommended for local use in 2026. For a filler-word-removal + tone-formatting task with 20-50 word inputs, the LLM step at 4B parameters adds ~200-400ms on CPU, keeping total latency under 1 second. Ollama handles model management and exposes a local REST API compatible with the OpenAI client.[^21][^22][^23]

### 2.3 Cloud Resources (Colab Pro + Linode)

- **Colab Pro**: Use for Whisper fine-tuning on user-specific vocabulary (runs once; produces an adapter or a smaller fine-tuned model)[^24]
- **Linode**: Optional remote Whisper API endpoint (faster-whisper served via FastAPI) for when the local machine is under heavy CPU load; the client falls back to local automatically

***

## Part 3: Full System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    LOCALFLOW DESKTOP APP                     │
│              (Tauri 2.0 — Rust backend + React UI)          │
├─────────────────────────────────────────────────────────────┤
│  Global Hotkey Manager (tauri-plugin-global-shortcut)        │
│    Hold → Start Recording    Release → Stop + Process        │
├──────────────┬──────────────────────────────────────────────┤
│              │                                               │
│  Audio       │  Context Engine                              │
│  Capture     │  (Active app/window → Win32 + UI Automation)  │
│  (cpal /     │  → App Category Resolver                     │
│  sounddevice)│  → System Prompt Selector                    │
│              │  → Proper Noun Extractor                     │
├──────────────┴──────────────────────────────────────────────┤
│  Silero VAD (ONNX) — filters silence before ASR             │
├─────────────────────────────────────────────────────────────┤
│  ASR Engine                                                  │
│  faster-whisper large-v3-turbo (int8 CPU; Vulkan optional)  │
│  → Raw transcript                                            │
├─────────────────────────────────────────────────────────────┤
│  LLM Post-Processor (Ollama REST API → Qwen3.5:4b)          │
│  Prompt: raw_transcript + app_context + vocab_hints          │
│  → Polished text                                             │
├─────────────────────────────────────────────────────────────┤
│  Text Injection Engine                                       │
│  Clipboard paste (pyperclip + pyautogui/keyboard Ctrl+V)    │
├─────────────────────────────────────────────────────────────┤
│  Persistence Layer (SQLite via rusqlite)                     │
│  • Personal vocabulary + correction log                      │
│  • App profiles (custom prompts per app)                     │
│  • Snippets / voice shortcuts                                │
│  • Transcription history (local)                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 Windows-First Adaptation Summary

The implementation plan below is Windows-primary. Linux names remain only when they are useful background or optional future portability.

| Module | Linux assumption in original plan | Windows implementation |
|---|---|---|
| Text injection | `xdotool`, `ydotool`, `xclip` | Clipboard paste via `pyperclip` + `pyautogui.hotkey("ctrl", "v")`; fallback to `keyboard.send("ctrl+v")`; direct typing only for short ASCII strings |
| Active app detection | `xprop`, `xdotool getactivewindow` | `win32gui.GetForegroundWindow()` + `win32process.GetWindowThreadProcessId()` + `psutil.Process(pid).name()` |
| Browser URL extraction | AT-SPI | Windows UI Automation through `pywinauto` or `uiautomation`; fall back to title/process classification if URL is inaccessible |
| Selected text for Command Mode | `xclip -o`, `xdotool getselection` | Copy current selection with `Ctrl+C`, read `pyperclip`, restore previous clipboard, then paste replacement text with `Ctrl+V` |
| System tray + hotkey | Tauri global shortcut | Tauri global shortcut and tray still work on Windows; configure Tauri v2 plugin permissions/capabilities |
| Startup service | `systemd --user` | Windows Task Scheduler at user logon; use NSSM only for non-interactive background services, not desktop text injection |
| Setup scripts | Bash, `apt`, `Makefile` | PowerShell scripts, `winget`, `py -3`, `.venv\Scripts`, and a root `tasks.ps1` helper |
| SQLite initialization | `sqlite3` CLI | Python `scripts/init_db.py` or bundled `sqlite3.exe`; avoid requiring a separate CLI |
| GPU acceleration | Linux ROCm env vars | CPU int8 baseline; optional `whisper.cpp`/`llama.cpp` Vulkan; ROCm/HIP only after exact Windows hardware support is verified |
| Permissions | Linux input/accessibility packages | Windows microphone privacy permission, non-elevated/elevated app integrity matching, UI Automation availability |

***

## Part 4: Module-by-Module Implementation Plan

Each module is a discrete, testable unit. Agents should implement and validate one module before moving to the next. Dependencies are listed per module.

***

### MODULE 0: Repository & Project Scaffold

**Goal**: Create the project skeleton that all other modules plug into.

**Tasks**:
1. Initialize a Tauri 2.0 project: `cargo create-tauri-app localflow --template react-ts`
2. Configure `src-tauri/Cargo.toml` with dependencies: `tauri`, `tauri-plugin-global-shortcut`, `tauri-plugin-notification`, `tauri-plugin-store`, `rusqlite`, `cpal`, `serde`, `tokio`, `reqwest`
3. Create Python service directories: `services/asr/`, `services/llm/`, `services/context/`, `services/injection/`
4. Initialize `services/asr/requirements.txt`: `faster-whisper`, `silero-vad`, `sounddevice`, `numpy`, `fastapi`, `uvicorn`
5. Initialize `services/llm/requirements.txt`: `ollama`, `httpx`, `fastapi`, `uvicorn`
6. Initialize `services/context/requirements.txt`: `pywin32`, `pywinauto`, `uiautomation`, `psutil`
7. Initialize `services/injection/requirements.txt`: `pyperclip`, `pyautogui`, `keyboard`
8. Create a `config/` directory with YAML schemas: `app_profiles.yaml`, `snippets.yaml`, `settings.yaml`
9. Create a `scripts/` directory for Windows setup automation: `setup.ps1`, `start_services.ps1`, `test_pipeline.ps1`, `install_startup_task.ps1`, `init_db.py`
10. Set up SQLite DB schema file: `db/schema.sql`
11. Create a root `tasks.ps1` with commands: `Install`, `Dev`, `Build`, `Test`, `StartServices`

**DB Schema**:
```sql
CREATE TABLE vocabulary (
  id INTEGER PRIMARY KEY,
  word TEXT NOT NULL UNIQUE,
  frequency INTEGER DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE app_profiles (
  id INTEGER PRIMARY KEY,
  app_name TEXT NOT NULL,
  app_category TEXT NOT NULL, -- email | work_chat | personal_chat | code | other
  custom_system_prompt TEXT,
  tone TEXT DEFAULT 'formal' -- formal | casual | very_casual | code
);

CREATE TABLE snippets (
  id INTEGER PRIMARY KEY,
  trigger_phrase TEXT NOT NULL UNIQUE,
  expansion TEXT NOT NULL
);

CREATE TABLE transcription_history (
  id INTEGER PRIMARY KEY,
  raw_transcript TEXT,
  polished_text TEXT,
  app_context TEXT,
  duration_ms INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE corrections (
  id INTEGER PRIMARY KEY,
  original TEXT NOT NULL,
  corrected TEXT NOT NULL,
  count INTEGER DEFAULT 1
);
```

***

### MODULE 1: Audio Capture Service

**Goal**: Capture microphone audio during hotkey hold, return a WAV buffer for ASR.

**Dependencies**: Module 0

**Implementation** (`services/asr/audio_capture.py`):

```python
import sounddevice as sd
import numpy as np
import io
import wave
import threading

class AudioRecorder:
    SAMPLE_RATE = 16000
    CHANNELS = 1
    DTYPE = np.float32

    def __init__(self):
        self._frames = []
        self._lock = threading.Lock()
        self._stream = None
        self.is_recording = False

    def _callback(self, indata, frames, time, status):
        with self._lock:
            self._frames.append(indata.copy())

    def start(self):
        self._frames = []
        self.is_recording = True
        self._stream = sd.InputStream(
            samplerate=self.SAMPLE_RATE,
            channels=self.CHANNELS,
            dtype=self.DTYPE,
            callback=self._callback,
            blocksize=1024
        )
        self._stream.start()

    def stop(self) -> bytes:
        if self._stream:
            self._stream.stop()
            self._stream.close()
        self.is_recording = False
        with self._lock:
            audio = np.concatenate(self._frames, axis=0).flatten()
        return self._to_wav_bytes(audio)

    def _to_wav_bytes(self, audio: np.ndarray) -> bytes:
        pcm = (audio * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()
```

**Validation**: Record 5 seconds, write to `artifacts\test.wav` or `%TEMP%\localflow-test.wav`, verify playback.

***

### MODULE 2: VAD (Voice Activity Detection)

**Goal**: Strip silent frames before passing audio to ASR, reducing hallucinations and compute waste.

**Dependencies**: Module 1

**Implementation** (`services/asr/vad.py`):

```python
import numpy as np
import torch
from silero_vad import load_silero_vad, get_speech_timestamps

class VADFilter:
    def __init__(self, threshold=0.5, min_speech_duration_ms=250):
        self.model = load_silero_vad()
        self.threshold = threshold
        self.min_speech_ms = min_speech_duration_ms
        self.sample_rate = 16000

    def filter(self, audio_float32: np.ndarray) -> np.ndarray:
        """Returns audio with silence removed. Returns None if no speech detected."""
        wav = torch.from_numpy(audio_float32)
        timestamps = get_speech_timestamps(
            wav,
            self.model,
            threshold=self.threshold,
            min_speech_duration_ms=self.min_speech_ms,
            sampling_rate=self.sample_rate,
            return_seconds=False
        )
        if not timestamps:
            return None
        # Concatenate speech segments
        segments = [audio_float32[t['start']:t['end']] for t in timestamps]
        return np.concatenate(segments)
```

Silero VAD processes one 30ms chunk in under 1ms on CPU, making it zero-cost in the pipeline.[^25]

**Validation**: Pass a silent 3-second buffer, assert `None` returned. Pass audio with speech, assert non-empty array returned.

***

### MODULE 3: ASR Engine

**Goal**: Transcribe speech to raw text using `faster-whisper` large-v3-turbo.

**Dependencies**: Module 2

**Implementation** (`services/asr/transcriber.py`):

```python
from faster_whisper import WhisperModel
import numpy as np
import time

class Transcriber:
    def __init__(self, model_size="large-v3-turbo", device="cpu", compute_type="int8"):
        # Windows AMD baseline: CPU int8. Do not probe CUDA on machines
        # that do not have NVIDIA drivers; it adds startup noise and delay.
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.device = device
        self.model_size = model_size

    def transcribe(
        self,
        audio: np.ndarray,
        language: str = None,
        initial_prompt: str = None
    ) -> dict:
        start = time.perf_counter()
        segments, info = self.model.transcribe(
            audio,
            language=language,
            initial_prompt=initial_prompt,
            vad_filter=False,  # VAD handled upstream
            beam_size=1,
            best_of=1,
            temperature=0.0,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            condition_on_previous_text=False,
            word_timestamps=False,
        )
        text = " ".join(seg.text.strip() for seg in segments)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "text": text.strip(),
            "language": info.language,
            "latency_ms": elapsed_ms
        }
```

**Windows acceleration notes**: Do not depend on Linux ROCm environment variables such as `HSA_OVERRIDE_GFX_VERSION`. Start with `faster-whisper` on CPU using `compute_type="int8"`, because it is the most predictable Windows path. If benchmarks require GPU acceleration, add a pluggable ASR backend and test `whisper.cpp` Vulkan first. Treat ROCm/HIP on Windows as optional until the exact Radeon 780M / Ryzen APU stack and Python framework support are confirmed on the target machine.[^11][^12][^31]

**Whisper Initial Prompt for Vocabulary Injection**: Pass the user's top vocabulary words as an `initial_prompt` string to Whisper's decoder. This biases the model toward correct spelling of proper nouns and technical terms without retraining.[^26]

```python
# vocab_prompt.py
import sqlite3

def build_initial_prompt(db_path: str, max_words: int = 30) -> str:
    """Inject top vocabulary words into Whisper's initial prompt."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT word FROM vocabulary ORDER BY frequency DESC LIMIT ?", (max_words,)
    ).fetchall()
    conn.close()
    words = [r for r in rows]
    return ", ".join(words) + "." if words else ""
```

**Validation**: Transcribe a 10-second English audio clip, assert WER < 10%, assert latency < 2000ms.

***

### MODULE 4: Context Engine

**Goal**: Detect the active application and extract context for LLM formatting.

**Dependencies**: Module 0

This is the feature that separates LocalFlow from simple Whisper clones. The Windows implementation uses Win32 APIs for the active foreground window and UI Automation for best-effort browser URL and visible-text extraction. Context detection should start when recording starts so UI Automation latency is hidden behind the user's speech.

**Implementation** (`services/context/app_detector.py`):

```python
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import psutil
import win32gui
import win32process
from pywinauto import Application

@dataclass
class AppContext:
    app_name: str           # e.g. "chrome", "msedge", "code", "slack"
    window_title: str       # Full window title
    category: str           # email | work_chat | personal_chat | code | other
    url: Optional[str]      # For browsers
    visible_text: Optional[str]  # Nearest text (for proper noun extraction)

APP_CATEGORY_MAP = {
    # Code editors
    "code": "code", "cursor": "code", "windsurf": "code", "devenv": "code",
    "pycharm64": "code", "idea64": "code", "webstorm64": "code",
    "notepad++": "code", "windowsterminal": "code",
    # Work chat
    "slack": "work_chat", "teams": "work_chat", "ms-teams": "work_chat",
    "discord": "work_chat", "zoom": "work_chat", "telegram": "work_chat",
    # Email (app-level)
    "outlook": "email", "olk": "email", "thunderbird": "email",
    # Personal chat
    "whatsapp": "personal_chat", "signal": "personal_chat",
}

BROWSER_URL_CATEGORY_MAP = {
    "mail.google.com": "email",
    "outlook.office.com": "email",
    "outlook.live.com": "email",
    "app.slack.com": "work_chat",
    "teams.microsoft.com": "work_chat",
    "discord.com": "work_chat",
    "notion.so": "other",
    "docs.google.com": "other",
    "github.com": "code",
    "chat.openai.com": "other",
    "claude.ai": "other",
}

BROWSER_APPS = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi"}
ADDRESS_BAR_HINTS = ("address", "search", "omnibox", "url")

def get_active_app_context() -> AppContext:
    """Windows foreground-window implementation."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        window_title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe_name = psutil.Process(pid).name().lower()
        app_name = Path(exe_name).stem

        # Determine category
        category = _classify_app(app_name, window_title)

        # For browsers, try to extract URL through Windows UI Automation.
        url = _extract_browser_url(hwnd, app_name)
        if url:
            for domain, cat in BROWSER_URL_CATEGORY_MAP.items():
                if domain in url:
                    category = cat
                    break

        visible_text = _extract_visible_text(hwnd, max_items=40)
        return AppContext(
            app_name=app_name,
            window_title=window_title,
            category=category,
            url=url,
            visible_text=visible_text
        )
    except Exception:
        return AppContext("unknown", "", "other", None, None)

def _classify_app(app_name: str, title: str) -> str:
    for key, cat in APP_CATEGORY_MAP.items():
        if key in app_name:
            return cat
    return "other"

def _extract_browser_url(hwnd: int, app_name: str) -> Optional[str]:
    if app_name not in BROWSER_APPS:
        return None

    try:
        app = Application(backend="uia").connect(handle=hwnd, timeout=0.3)
        window = app.window(handle=hwnd)
        edits = window.descendants(control_type="Edit")
        for edit in edits:
            name = (edit.element_info.name or "").lower()
            if not any(hint in name for hint in ADDRESS_BAR_HINTS):
                continue
            value = _safe_value(edit)
            if value and _looks_like_url(value):
                return _normalize_url(value)
    except Exception:
        pass
    return None

def _extract_visible_text(hwnd: int, max_items: int = 40) -> Optional[str]:
    """Best-effort visible text for proper-noun hints. Keep this bounded."""
    try:
        app = Application(backend="uia").connect(handle=hwnd, timeout=0.3)
        window = app.window(handle=hwnd)
        texts = []
        for ctrl in window.descendants(control_type="Text")[:max_items]:
            text = ctrl.window_text().strip()
            if text and len(text) <= 120:
                texts.append(text)
        return "\n".join(dict.fromkeys(texts)) if texts else None
    except Exception:
        return None

def _safe_value(control) -> Optional[str]:
    try:
        return control.iface_value.CurrentValue.strip()
    except Exception:
        try:
            return control.window_text().strip()
        except Exception:
            return None

def _looks_like_url(value: str) -> bool:
    value = value.strip().lower()
    return value.startswith(("http://", "https://")) or "." in value

def _normalize_url(value: str) -> str:
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value
```

**App Profile Loader** (`services/context/profile_loader.py`):

```python
import sqlite3
import yaml

SYSTEM_PROMPTS = {
    "email": (
        "You are a professional email writing assistant. "
        "Rewrite the following raw speech transcription into a polished, professional email body. "
        "Remove all filler words (um, uh, like, you know), handle self-corrections "
        "(if the speaker says 'actually', 'wait no', 'I mean', keep only the final version), "
        "add proper punctuation, capitalization, and paragraph breaks where natural."
    ),
    "work_chat": (
        "You are a concise work messaging assistant. "
        "Clean up the following speech transcription for a Slack or Teams message: "
        "remove filler words, handle self-corrections, keep the tone professional but conversational, "
        "add punctuation. Keep it brief."
    ),
    "personal_chat": (
        "You are a casual messaging assistant. "
        "Clean the following speech transcription for a personal chat message: "
        "remove filler words, handle self-corrections, keep the tone casual and natural. "
        "Do not over-formalize."
    ),
    "code": (
        "You are a code comment and technical documentation assistant. "
        "Clean the following speech transcription for use in a code editor: "
        "remove filler words, preserve technical terms, variable names, "
        "and code syntax exactly. Return only the cleaned text."
    ),
    "other": (
        "You are a general-purpose dictation assistant. "
        "Clean the following speech transcription: remove filler words (um, uh, like), "
        "handle self-corrections (keep only the final intent), add proper punctuation and capitalization."
    ),
}

def get_system_prompt(category: str, custom_prompt: str = None) -> str:
    if custom_prompt:
        return custom_prompt
    return SYSTEM_PROMPTS.get(category, SYSTEM_PROMPTS["other"])
```

**Validation**: Open Chrome or Edge to Gmail, call `get_active_app_context()`, assert `category == "email"` and `url` contains `mail.google.com` when UI Automation exposes the address bar. Open VS Code, assert `category == "code"`. If UI Automation URL extraction fails for a browser, assert the app/title fallback still returns a useful `AppContext`.

***

### MODULE 5: LLM Post-Processor

**Goal**: Transform raw ASR transcript into polished text using a local LLM via Ollama.

**Dependencies**: Modules 3, 4; Ollama installed with `qwen3.5:4b` or `qwen3:4b` pulled.

**Setup**:
```powershell
# Install Ollama manually from https://ollama.com/download/windows or:
winget install --id Ollama.Ollama -e

# Pull model
ollama pull qwen3.5:4b   # ~2.5GB, fast on Zen 4 CPU
```

**Implementation** (`services/llm/formatter.py`):

```python
import httpx
import sqlite3
import time
from typing import Optional

OLLAMA_BASE = "http://localhost:11434"

class LLMFormatter:
    def __init__(self, model: str = "qwen3.5:4b", db_path: str = "db/localflow.db"):
        self.model = model
        self.db_path = db_path
        self.client = httpx.Client(timeout=10.0)

    def _build_vocab_hint(self) -> str:
        try:
            conn = sqlite3.connect(self.db_path)
            words = conn.execute(
                "SELECT word FROM vocabulary ORDER BY frequency DESC LIMIT 20"
            ).fetchall()
            corrections = conn.execute(
                "SELECT original, corrected FROM corrections ORDER BY count DESC LIMIT 10"
            ).fetchall()
            conn.close()
            hints = []
            if words:
                hints.append("Known terms: " + ", ".join(r for r in words))
            if corrections:
                hints.append("Always correct: " + "; ".join(f'"{r}" → "{r[^1]}"' for r in corrections))
            return "\n".join(hints)
        except Exception:
            return ""

    def format(
        self,
        raw_text: str,
        system_prompt: str,
        app_context: Optional[str] = None
    ) -> dict:
        vocab_hint = self._build_vocab_hint()
        user_message = f"Raw transcription:\n{raw_text}"
        if app_context:
            user_message = f"Active app: {app_context}\n\n{user_message}"
        if vocab_hint:
            user_message = f"{vocab_hint}\n\n{user_message}"

        start = time.perf_counter()
        resp = self.client.post(
            f"{OLLAMA_BASE}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 512,
                    "num_ctx": 1024,
                }
            }
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        text = resp.json()["message"]["content"].strip()
        # Strip thinking tags if model has CoT output
        if "<think>" in text:
            text = text.split("</think>")[-1].strip()
        return {"text": text, "latency_ms": elapsed_ms}
```

**Command Mode** (voice editing of highlighted text):

```python
def command_edit(self, selected_text: str, command: str) -> dict:
    """Apply a voice command to selected text. E.g. 'make this more concise'."""
    system = (
        "You are a text editing assistant. Apply the user's instruction to the provided text. "
        "Return ONLY the edited text, no explanation."
    )
    user = f"Text to edit:\n{selected_text}\n\nInstruction: {command}"
    resp = self.client.post(
        f"{OLLAMA_BASE}/api/chat",
        json={
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 1024}
        }
    )
    text = resp.json()["message"]["content"].strip()
    if "<think>" in text:
        text = text.split("</think>")[-1].strip()
    return {"text": text}
```

**Validation**: Pass `"um so I was thinking uh let's go with the second option, wait no the first one"` → assert output is `"Let's go with the first option."` (or similar clean version).

***

### MODULE 6: Text Injection Engine

**Goal**: Type or paste the final text into whatever application is currently focused.

**Dependencies**: Module 0

```python
# services/injection/text_injector.py
import pyperclip
import time
import platform
import pyautogui

try:
    import keyboard
except Exception:
    keyboard = None

class TextInjector:
    def __init__(self, paste_delay: float = 0.08, restore_clipboard: bool = True):
        self.os = platform.system()
        self.paste_delay = paste_delay
        self.restore_clipboard = restore_clipboard

    def inject(self, text: str, method: str = "auto"):
        """Inject text into the active text field."""
        if method == "auto":
            method = self._best_method()

        if method == "clipboard":
            self._inject_clipboard(text)
        elif method == "typewrite":
            self._inject_typewrite(text)
        else:
            raise ValueError(f"Unknown injection method: {method}")

    def _best_method(self) -> str:
        # Clipboard paste is fastest and handles Unicode/newlines reliably.
        return "clipboard"

    def _inject_clipboard(self, text: str):
        previous = pyperclip.paste() if self.restore_clipboard else None
        pyperclip.copy(text)
        time.sleep(self.paste_delay)
        self._send_paste()
        if previous is not None:
            time.sleep(0.15)
            pyperclip.copy(previous)

    def _send_paste(self):
        try:
            pyautogui.hotkey("ctrl", "v")
        except Exception:
            if keyboard is None:
                raise
            keyboard.send("ctrl+v")

    def _inject_typewrite(self, text: str):
        # Use only for short ASCII strings; clipboard paste is better for Unicode.
        pyautogui.write(text, interval=0)

    def press_enter(self):
        """For 'send message' command."""
        pyautogui.press("enter")
```

**Windows notes**: Clipboard injection is the default because it is faster than key-by-key typing and handles punctuation, newlines, Arabic, emoji, and technical symbols. Windows can block synthetic input across integrity levels, so LocalFlow should run at the same privilege level as the target app; if the target app is elevated, either run LocalFlow elevated too or do not inject into that app.

**Validation**: Open Notepad, run `inject("Hello World")`, verify text appears in the editor. Repeat with multiline Unicode text. Then run against VS Code, Chrome, Slack/Teams, and an elevated app to document privilege-boundary behavior.

***

### MODULE 7: Snippet Engine

**Goal**: Expand voice-triggered text shortcuts.

**Dependencies**: Module 0

```python
# services/snippets/snippet_engine.py
import sqlite3
import re

class SnippetEngine:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def check_and_expand(self, text: str) -> tuple[str, bool]:
        """
        Check if text matches a snippet trigger.
        Returns (expanded_text, was_expanded).
        """
        conn = sqlite3.connect(self.db_path)
        snippets = conn.execute("SELECT trigger_phrase, expansion FROM snippets").fetchall()
        conn.close()

        text_lower = text.lower().strip()
        for trigger, expansion in snippets:
            if text_lower == trigger.lower().strip():
                return expansion, True
        return text, False

    def add_snippet(self, trigger: str, expansion: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO snippets (trigger_phrase, expansion) VALUES (?, ?)",
            (trigger, expansion)
        )
        conn.commit()
        conn.close()
```

***

### MODULE 8: Vocabulary Learning System

**Goal**: Automatically learn corrections the user makes, improving future transcriptions.

**Dependencies**: Module 0

```python
# services/vocab/vocab_learner.py
import sqlite3
from difflib import SequenceMatcher

class VocabLearner:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def record_correction(self, original: str, corrected: str):
        """
        Call when user edits transcribed text.
        Detects changed words and records them.
        """
        orig_words = original.split()
        corr_words = corrected.split()
        matcher = SequenceMatcher(None, orig_words, corr_words)
        conn = sqlite3.connect(self.db_path)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "replace":
                orig_phrase = " ".join(orig_words[i1:i2])
                corr_phrase = " ".join(corr_words[j1:j2])
                conn.execute(
                    """INSERT INTO corrections (original, corrected, count)
                       VALUES (?, ?, 1)
                       ON CONFLICT(original) DO UPDATE SET
                       corrected=excluded.corrected, count=count+1""",
                    (orig_phrase, corr_phrase)
                )
                # Add corrected form to vocabulary
                for word in corr_phrase.split():
                    conn.execute(
                        """INSERT INTO vocabulary (word, frequency) VALUES (?, 1)
                           ON CONFLICT(word) DO UPDATE SET frequency=frequency+1""",
                        (word,)
                    )
        conn.commit()
        conn.close()
```

***

### MODULE 9: Pipeline Orchestrator

**Goal**: Wire all modules together into the full push-to-talk pipeline.

**Dependencies**: All previous modules

```python
# services/pipeline.py
from audio_capture import AudioRecorder
from vad import VADFilter
from transcriber import Transcriber
from vocab_prompt import build_initial_prompt
from context.app_detector import get_active_app_context
from context.profile_loader import get_system_prompt
from llm.formatter import LLMFormatter
from snippets.snippet_engine import SnippetEngine
from injection.text_injector import TextInjector
import numpy as np
import io, wave, time

DB_PATH = "db/localflow.db"

class LocalFlowPipeline:
    def __init__(self):
        self.recorder = AudioRecorder()
        self.vad = VADFilter()
        self.transcriber = Transcriber()
        self.formatter = LLMFormatter(db_path=DB_PATH)
        self.snippets = SnippetEngine(db_path=DB_PATH)
        self.injector = TextInjector()
        self.recording = False

    def start_recording(self):
        # Capture context BEFORE recording (while user is still on the target app)
        self.current_context = get_active_app_context()
        self.recorder.start()
        self.recording = True

    def stop_and_process(self) -> dict:
        if not self.recording:
            return {"error": "Not recording"}
        self.recording = False

        t0 = time.perf_counter()
        # 1. Stop recording, get WAV bytes
        wav_bytes = self.recorder.stop()

        # 2. Convert WAV to float32 numpy array
        audio = self._wav_to_float32(wav_bytes)

        # 3. VAD filter
        audio_filtered = self.vad.filter(audio)
        if audio_filtered is None:
            return {"error": "No speech detected"}

        # 4. Build initial prompt from vocabulary
        initial_prompt = build_initial_prompt(DB_PATH)

        # 5. Transcribe
        asr_result = self.transcriber.transcribe(
            audio_filtered,
            initial_prompt=initial_prompt
        )
        raw_text = asr_result["text"]
        if not raw_text:
            return {"error": "Empty transcription"}

        # 6. Check snippets
        expanded, was_snippet = self.snippets.check_and_expand(raw_text)
        if was_snippet:
            self.injector.inject(expanded)
            return {"text": expanded, "snippet": True}

        # 7. LLM post-processing
        system_prompt = get_system_prompt(self.current_context.category)
        fmt_result = self.formatter.format(
            raw_text,
            system_prompt,
            app_context=self.current_context.app_name
        )
        polished = fmt_result["text"]

        # 8. Check for "press enter" command
        send_enter = polished.lower().endswith("press enter")
        if send_enter:
            polished = polished[:-len("press enter")].strip().rstrip(",.")

        # 9. Inject text
        self.injector.inject(polished)
        if send_enter:
            self.injector.press_enter()

        total_ms = (time.perf_counter() - t0) * 1000
        return {
            "raw": raw_text,
            "polished": polished,
            "context": self.current_context.category,
            "total_ms": total_ms,
            "asr_ms": asr_result["latency_ms"],
            "llm_ms": fmt_result["latency_ms"],
        }

    def _wav_to_float32(self, wav_bytes: bytes) -> np.ndarray:
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf) as wf:
            raw = wf.readframes(wf.getnframes())
        pcm = np.frombuffer(raw, dtype=np.int16)
        return pcm.astype(np.float32) / 32768.0
```

***

### MODULE 10: Tauri Desktop App (Frontend + Global Hotkey)

**Goal**: Build the system tray app with global hotkey, settings UI, and pipeline integration.

**Dependencies**: Module 9

The Tauri 2.0 Rust backend manages the global hotkey and spawns/communicates with the Python pipeline via a local socket or child process.[^27][^28] On Windows, keep the hotkey in Tauri rather than Python keyboard hooks; Tauri owns the desktop integration while Python owns audio, context, ASR, LLM formatting, and text injection. Configure the Tauri v2 global-shortcut plugin permissions/capabilities during setup.[^32]

**Rust backend** (`src-tauri/src/main.rs`):

```rust
use tauri::{Manager, SystemTray, SystemTrayMenu, CustomMenuItem};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use std::process::{Command, Child};
use std::sync::Mutex;

struct AppState {
    pipeline_process: Mutex<Option<Child>>,
    is_recording: Mutex<bool>,
}

#[tauri::command]
async fn start_recording() -> Result<(), String> {
    // Send HTTP POST to Python pipeline service
    reqwest::Client::new()
        .post("http://127.0.0.1:8765/start")
        .send().await
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
async fn stop_recording() -> Result<serde_json::Value, String> {
    let resp = reqwest::Client::new()
        .post("http://127.0.0.1:8765/stop")
        .send().await
        .map_err(|e| e.to_string())?
        .json::<serde_json::Value>().await
        .map_err(|e| e.to_string())?;
    Ok(resp)
}

fn main() {
    let tray_menu = SystemTrayMenu::new()
        .add_item(CustomMenuItem::new("settings", "Settings"))
        .add_item(CustomMenuItem::new("quit", "Quit LocalFlow"));

    tauri::Builder::default()
        .system_tray(SystemTray::new().with_menu(tray_menu))
        .setup(|app| {
            let handle = app.handle();
            let ctrl_space = Shortcut::new(
                Some(Modifiers::CONTROL | Modifiers::ALT),
                Code::Space
            );
            handle.plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_handler(move |_app, shortcut, event| {
                        if shortcut == &ctrl_space {
                            match event.state() {
                                ShortcutState::Pressed => {
                                    tauri::async_runtime::spawn(start_recording());
                                },
                                ShortcutState::Released => {
                                    tauri::async_runtime::spawn(async {
                                        let _ = stop_recording().await;
                                    });
                                }
                            }
                        }
                    })
                    .build()
            )?;
            handle.global_shortcut().register(ctrl_space)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![start_recording, stop_recording])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

**Python Pipeline HTTP Server** (`services/pipeline_server.py`):

```python
from fastapi import FastAPI
from pipeline import LocalFlowPipeline
import uvicorn

app = FastAPI()
pipeline = LocalFlowPipeline()

@app.post("/start")
async def start():
    pipeline.start_recording()
    return {"status": "recording"}

@app.post("/stop")
async def stop():
    result = pipeline.stop_and_process()
    return result

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
```

**Visual Overlay** (React UI): A small floating indicator (green dot while recording, brief "✓ done" flash on success) rendered as a transparent always-on-top Tauri window. The settings panel exposes: hotkey config, model selection, app profiles, snippets manager, transcription history, vocabulary viewer.

***

### MODULE 11: Command Mode (Voice Edit)

**Goal**: Highlight text → hold hotkey → speak edit instruction → text replaced.

**Dependencies**: Modules 6, 9

This mode is activated by a secondary hotkey (e.g. `Ctrl+Alt+E`). The flow:
1. User highlights text in any app
2. Presses Command Mode hotkey; LocalFlow copies the selected text with `Ctrl+C` and stores it before recording
3. Speaks instruction ("make this more concise")
4. Pipeline captures audio → ASR → LLM `command_edit()` → clipboard paste replacement

```python
# In pipeline.py, add:
def command_mode_process(self, selected_text: str) -> dict:
    """Process a command against selected text."""
    wav_bytes = self.recorder.stop()
    audio = self._wav_to_float32(wav_bytes)
    audio_filtered = self.vad.filter(audio)
    if audio_filtered is None:
        return {"error": "No speech detected"}
    asr_result = self.transcriber.transcribe(audio_filtered)
    command_text = asr_result["text"]
    result = self.formatter.command_edit(selected_text, command_text)
    self.injector.inject(result["text"], method="clipboard")
    return result
```

The `selected_text` is obtained before recording starts by copying the current selection, reading the clipboard, and restoring the previous clipboard value. This should run while the original target app still has focus; the Tauri overlay must not steal focus.

```python
# services/injection/selection_reader.py
import time
import pyautogui
import pyperclip

def read_selected_text(copy_delay: float = 0.08) -> str:
    previous = pyperclip.paste()
    sentinel = f"__LOCALFLOW_NO_SELECTION_{time.time_ns()}__"
    pyperclip.copy(sentinel)
    pyautogui.hotkey("ctrl", "c")
    time.sleep(copy_delay)
    selected = pyperclip.paste()
    pyperclip.copy(previous)
    return "" if selected == sentinel else selected
```

For apps that block clipboard copy, add a later UI Automation path using `TextPattern` / `ValuePattern`; keep the clipboard path as the universal first pass.

***

### MODULE 12: Settings UI & Persistence

**Goal**: Full settings panel for the app, using Tauri's plugin-store for frontend state and SQLite for vocabulary/profiles.

**Key Settings Components**:
- **Hotkey picker**: Live-captures key combos, validates no conflicts, saves to `plugin-store`
- **App Profile Manager**: Table of app_name → category → custom prompt; add/edit/delete rows
- **Snippets Manager**: Trigger phrase → expansion text; import/export as YAML
- **Vocabulary Viewer**: Sortable list of learned words + corrections; bulk delete
- **Model Selector**: Dropdown of available Ollama models; test button runs a quick pipeline test
- **Transcription History**: Searchable log of past dictations with raw + polished text
- **Language Selector**: Passthrough to `faster-whisper` `language` param; `None` = auto-detect

***

### MODULE 13: Whisper Fine-Tuning on Colab Pro (Optional Enhancement)

**Goal**: Improve ASR accuracy for your specific voice, accent, and domain vocabulary.

**Dependencies**: Google Colab Pro, ~7k+ voice samples

This step runs once on Colab Pro and produces a GGUF/ct2 model artifact for local use.

```python
# colab/finetune_whisper.py
# Run on Colab Pro T4/A100
from transformers import WhisperForConditionalGeneration, WhisperProcessor, Seq2SeqTrainer, Seq2SeqTrainingArguments
from datasets import load_dataset, Audio
import torch

model_name = "openai/whisper-large-v3-turbo"
model = WhisperForConditionalGeneration.from_pretrained(model_name)
processor = WhisperProcessor.from_pretrained(model_name)

# Load your personal voice dataset
# Format: HuggingFace Dataset with 'audio' and 'sentence' columns
# Minimum viable: 500 samples of your voice + domain vocabulary

training_args = Seq2SeqTrainingArguments(
    output_dir="./whisper-localflow-ft",
    num_train_epochs=3,
    per_device_train_batch_size=8,
    learning_rate=1e-5,          # ~40x smaller than pre-training LR
    warmup_steps=100,
    gradient_accumulation_steps=2,
    fp16=True,
    evaluation_strategy="epoch",
    save_strategy="epoch",
    predict_with_generate=True,
    generation_max_length=225,
    report_to=["tensorboard"],
)
```

After fine-tuning, convert to CTranslate2 format for `faster-whisper`:
```bash
ct2-opus-converter --model openai/whisper-large-v3-turbo \
  --output_dir models/whisper-localflow-ft \
  --quantization int8
```

***

### MODULE 14: Linode Remote ASR Fallback

**Goal**: When local CPU is saturated, transparently route to a self-hosted Whisper API on Linode.

**Dependencies**: Module 3

Deploy on Linode (GPU instance or CPU Dedicated):

```python
# linode/server.py
from fastapi import FastAPI, UploadFile
from faster_whisper import WhisperModel
import numpy as np, io, wave

app = FastAPI()
model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")

@app.post("/transcribe")
async def transcribe(file: UploadFile, language: str = None, prompt: str = None):
    wav_bytes = await file.read()
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf) as wf:
        raw = wf.readframes(wf.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    segments, info = model.transcribe(audio, language=language, initial_prompt=prompt, beam_size=1)
    text = " ".join(seg.text.strip() for seg in segments)
    return {"text": text, "language": info.language}
```

In the local `Transcriber` class, add:
```python
def transcribe_with_fallback(self, audio, ...):
    cpu_load = psutil.cpu_percent(interval=0.1)
    if cpu_load > 85 and self.remote_url:
        return self._remote_transcribe(audio, ...)
    return self.transcribe(audio, ...)
```

***

## Part 5: Features That Exceed Wispr Flow

| Feature | Wispr Flow | LocalFlow |
|---|---|---|
| Privacy | Cloud-only, 11+ subprocessors[^4] | 100% local, zero network requests |
| Cost | $15/month[^29] | Free forever |
| Offline support | None — requires internet[^14] | ✅ Full offline |
| Custom LLM system prompts | Not user-configurable | ✅ Full per-app customization |
| Voice fine-tuning | No user fine-tuning | ✅ Colab fine-tune workflow |
| Vocabulary learning | Auto from corrections[^30] | ✅ + explicit add + initial prompt injection |
| Open source | No | ✅ Full source |
| Windows support | ✅ Supported[^2] | ✅ Primary platform |
| Linux support | No[^2] | Optional future portability |
| Remote fallback | N/A | ✅ Self-hosted Linode fallback |
| Command Mode | ✅ | ✅ |
| Context awareness | ✅ (cloud-based) | ✅ (local accessibility API) |
| Snippets | ✅ | ✅ |
| Transcription history | Limited | ✅ Full local SQLite log |

***

## Part 6: Installation & Startup Scripts

**`scripts/setup.ps1`** (run once):
```powershell
$ErrorActionPreference = "Stop"

# Python environment
py -3 -m venv .venv
$python = Join-Path $PWD ".venv\Scripts\python.exe"
$pip = Join-Path $PWD ".venv\Scripts\pip.exe"
& $python -m pip install --upgrade pip
& $pip install -r services\asr\requirements.txt
& $pip install -r services\llm\requirements.txt
& $pip install -r services\context\requirements.txt
& $pip install -r services\injection\requirements.txt

# Ollama. If missing, install manually or with winget:
# winget install --id Ollama.Ollama -e
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama is not installed. Install it from https://ollama.com/download/windows or winget."
}
$env:OLLAMA_KEEP_ALIVE = "-1"
Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 3
ollama pull qwen3.5:4b

# Whisper model (auto-downloaded by faster-whisper on first run)
# Pre-download to avoid first-run delay:
& $python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')"

# Init SQLite DB without requiring sqlite3.exe
& $python scripts\init_db.py

# Build Tauri app
Push-Location src-tauri
cargo build --release
Pop-Location
```

**`scripts/init_db.py`**:
```python
from pathlib import Path
import sqlite3

root = Path(__file__).resolve().parents[1]
db_path = root / "db" / "localflow.db"
schema_path = root / "db" / "schema.sql"
db_path.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(db_path) as conn:
    conn.executescript(schema_path.read_text(encoding="utf-8"))
```

**`scripts/start_services.ps1`** (launch on user logon):
```powershell
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
    $env:OLLAMA_KEEP_ALIVE = "-1"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
}

Start-Process -FilePath $python `
    -ArgumentList (Join-Path $root "services\pipeline_server.py") `
    -WorkingDirectory $root `
    -WindowStyle Hidden

Start-Process -FilePath (Join-Path $root "src-tauri\target\release\localflow.exe") `
    -WorkingDirectory $root
```

**`scripts/install_startup_task.ps1`**:
```powershell
$ErrorActionPreference = "Stop"
$script = Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\start_services.ps1"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -ExecutionTimeLimit 0
Register-ScheduledTask `
    -TaskName "LocalFlow" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Start LocalFlow dictation services at Windows logon" `
    -Force
```

Use Windows Task Scheduler for startup because LocalFlow needs access to the interactive desktop session for hotkeys, clipboard, UI Automation, and text injection. NSSM is only appropriate for a non-interactive helper service; a Windows service running in Session 0 should not own desktop text injection.

***

## Part 7: Testing & Validation Checklist

Each module has validation criteria above. Full integration tests:

1. **Latency test**: Record 5-second utterance, assert total pipeline time < 2000ms (acceptable for local; Wispr targets 700ms with cloud)[^3]
2. **Filler word test**: Input "Um so I was thinking uh we should uh go with option two" → assert output contains no "um" or "uh"
3. **Self-correction test**: Input "Let's budget 50k, actually make that 75k" → assert output is "Let's budget 75k"
4. **Context test**: Run in code editor → assert tone is code-friendly; run in email app → assert tone is professional
5. **Snippet test**: Say trigger phrase → assert expansion text is injected verbatim
6. **Command Mode test**: Highlight paragraph, say "make this a bullet list" → assert clipboard contains bullet-formatted text
7. **Vocabulary test**: Add "Haaga-Helia" to vocabulary → transcribe "I study at Haaga-Helia" → assert correct spelling
8. **No-speech test**: Record 3 seconds of silence → assert VAD returns None and no injection occurs
9. **Windows active-app test**: Open VS Code, Notepad, Outlook, Chrome/Edge Gmail, and Slack/Teams; assert `get_active_app_context()` returns stable app names and categories
10. **Windows injection test**: Paste into Notepad, VS Code, Chrome text fields, Slack/Teams, and an elevated app; document any integrity-level failures
11. **Startup test**: Install the scheduled task, log out/in, and assert Ollama, the Python pipeline, and the Tauri tray app are running in the user session
12. **GPU test** (optional): Benchmark CPU int8 against `whisper.cpp` Vulkan. Only add a ROCm/HIP test after the target Windows hardware support matrix confirms the Radeon 780M path.

***

## Part 8: Latency Optimization Strategies

1. **Model warm-up**: Load `WhisperModel` and run a dummy transcription at startup (before first use). First inference is always slower due to JIT compilation.
2. **Ollama keep-alive**: Set `OLLAMA_KEEP_ALIVE=-1` before launching Ollama, or set it as a Windows user environment variable, to prevent model unloading between requests.
3. **Parallel ASR + context detection**: Start context detection the moment recording begins (not after), so it completes during recording. This hides its latency entirely.
4. **VAD trimming**: Silero VAD removes leading and trailing silence before Whisper processes it, reducing the effective audio duration and therefore inference time.
5. **Beam size = 1**: Use greedy decoding in Whisper (`beam_size=1`, `best_of=1`) to cut ASR latency by 30-50% with minimal accuracy loss for conversational speech.
6. **LLM context size**: Keep `num_ctx=1024` in Ollama — dictation inputs are never longer than ~200 tokens. Smaller context = faster KV cache operations.
7. **Streaming Ollama output**: For Command Mode (longer outputs), use Ollama streaming to start injecting text token-by-token while generation continues.
8. **int8 quantization**: Already used in `faster-whisper` (`compute_type="int8"`). Also use `q4_K_M` GGUF for the Qwen model in Ollama for lower memory footprint.

---

## References

1. [Designing a natural and useful voice interface](https://wisprflow.ai/post/designing-a-natural-and-useful-voice-interface) - Wispr Flow takes a different path. Instead of stacking AI on top of apps, we built it into the core ...

2. [Wispr - Wikipedia](https://en.wikipedia.org/wiki/Wispr) - The company's main product, Wispr Flow, is an AI-powered speech-to-text application available on mac...

3. [Technical challenges and breakthroughs behind Flow](https://wisprflow.ai/post/technical-challenges) - Our users expect full transcription and LLM formatting/interpretation of their speech within 700ms o...

4. [Is Wispr Flow Safe? Privacy, Delve Audit Scandal & Verdict (2026)](https://www.getvoibe.com/resources/is-wispr-flow-safe/) - TL;DR: Wispr Flow is reasonably safe for general cloud dictation in 2026 — it holds SOC 2 Type II an...

5. [Mini PC|MINISFORUM UM890 Pro](https://www.minisforum.com/products/minisforum-um890-pro) - The AMD Ryzen™ 9 8945HS maximum clock reaches5.2GHz. It also integrates the AMD Radeon™ 780M graphic...

6. [Context Awareness](https://docs.wisprflow.ai/articles/4678293671-feature-context-awareness) - Context Awareness reads your active app and adapts transcription accuracy, style, and formatting aut...

7. [Whisper (Whisper.cpp/WhisperKit) for live transcription](https://www.reddit.com/r/LocalLLaMA/comments/1h2kvu2/whisper_whispercppwhisperkit_for_live/) - **subreddit: /r/LocalLLaMA**
author: mark-lord

8. [Whisper dictation on Linux](https://srvr.in/software/2026/03/30/whisper-dictation/) - whisper-dictation is a single Python file (~300 lines). Hold a keyboard shortcut, speak, release — y...

9. [Ryzen 9 8945HS vs Ryzen AI 9 HX 370](https://acemagic.com/blogs/about-ace-mini-pc/ryzen-9-8945hs-vs-ryzen-ai-9-hx-370) - Single-core performance is nearly identical, but the HX 370 consumes ~47% more power. 2. GPU Perform...

10. [Issues with GPU inference for audio models (with Whisper, ...](https://www.reddit.com/r/ROCm/comments/1psytbe/issues_with_gpu_inference_for_audio_models_with/) - There's better support for the 780m than for you 6800xt. You might need to look for gfx1103 patches ...

11. [ROCm Support for AMD Ryzen 9 7940HS with Radeon ...](https://github.com/ROCm/ROCm/issues/3398) - I am writing to request the development of ROCm (Radeon Open Compute) support for the AMD Ryzen 9 79...

12. [jjajjara/rocm-whisper-api - Docker Image](https://hub.docker.com/r/jjajjara/rocm-whisper-api) - A Dockerized API server for OpenAI's Whisper, meticulously optimized for AMD GPUs (ROCm). This proje...

13. [Wispr Flow Review: AI Voice Dictation Tool January 2026](https://willowvoice.com/blog/wispr-flow-review-voice-dictation) - Wispr Flow is an AI voice dictation app for Mac, Windows, and iOS that converts your speech into tex...

14. [Data Controls - Wispr Flow](https://wisprflow.ai/data-controls) - If you choose to disable “Privacy Mode,” your Dictation Data may be used to evaluate, train and impr...

15. [Wispr Flow 101: The Complete Guide to Voice-First ...](https://sidsaladi.substack.com/p/wispr-flow-101-the-complete-guide) - Wispr Flow is an AI-powered voice dictation app that works in every app on your computer and phone. ...

16. [Minisforum UM890Pro Mini PC | AMD Ryzen™ 9 8945HS](https://www.minisforum.uk/products/minisforum-um890pro) - Product name: Minisforum UM890 Pro ; Processor. AMD Ryzen™ 9 8945HS Processor, 8 Cores/16 Threads (1...

17. [MINISFORUM UM890 Pro | AMD Ryzen™ 9 8945HS ...](https://au.minisforum.com/products/minisforum-um890pro) - Unlock elite performance with MINISFORUM UM890 Pro, powered by AMD Ryzen 9 8945HS Processor (8C/16T,...

18. [SoupaWhisper: Free SuperWhisper Alternative for Linux ...](https://www.ksred.com/soupawhisper-how-i-replaced-superwhisper-on-linux/) - SoupaWhisper is a ~250 line Python script that does exactly what SuperWhisper does, powered by OpenA...

19. [unsloth/whisper-large-v3-turbo](https://huggingface.co/unsloth/whisper-large-v3-turbo) - Trained on >5M hours of labeled data, Whisper demonstrates a strong ability to generalise to many da...

20. [The Top Open Source Speech-to-Text (STT) Models in 2025](https://modal.com/blog/open-source-stt) - August 5, 2025•10 minute read

21. [How Groq Makes Tap2Talk the Fastest Dictation App](https://tap2talk.app/blog/groq-fastest-dictation-app/) - — The raw text passes through Groq's LLM (Llama) for grammar, punctuation, and filler word removal ....

22. [keyiiiii/VoxBridge](https://github.com/keyiiiii/VoxBridge) - Ollama is a local LLM server, and Qwen 3 is an AI language model that runs on it. VoxBridge uses Qwe...

23. [[AINews] Top Local Models List - April 2026](https://www.latent.space/p/ainews-top-local-models-list-april) - Qwen 3.5 — most broadly recommended family right now across usecases. Gemma 4 — strong recent buzz f...

24. [Fine-tune Whisper to Improve Transcription on Domain- ...](https://modal.com/docs/examples/fine_tune_asr) - Fine-tune Whisper to Improve Transcription on Domain-Specific Vocab. This example demonstrates how t...

25. [Silero VAD: pre-trained enterprise-grade Voice Activity ...](https://github.com/snakers4/silero-vad) - Silero VAD has excellent results on speech detection tasks. Fast. One audio chunk (30+ ms) takes les...

26. [Final Project Report Whisper: Courtside Edition](https://arxiv.org/html/2602.18966v1) - We introduce Whisper: Courtside Edition, a novel multi-agent large language model (LLM) pipeline tha...

27. [I Built a Local Voice-to-Text App with Rust, Tauri 2.0, ...](https://dev.to/auratech/i-built-a-local-voice-to-text-app-with-rust-tauri-20-whispercpp-and-llamacpp-heres-how-32h5) - The result is MumbleFlow — a local voice-to-text desktop app built with Tauri 2.0, whisper.cpp, and ...

28. [Tauri (8) - Implementing global shortcut key function](https://dev.to/rain9/tauri-8-implementing-global-shortcut-key-function-2336) - This article introduces how to implement global shortcut functionality in Tauri, guiding you step-by...

29. [Typeless vs Wispr Flow: Which AI Dictation App Wins? (2026)](https://www.getvoibe.com/resources/typeless-vs-wispr-flow/) - Context-aware formatting adapts tone for email, Slack, and code editors; + 100+ language support wit...

30. [A complete Wispr Flow overview for 2025: Features, pricing ...](https://www.eesel.ai/blog/wispr-flow-overview) - Our comprehensive Wispr Flow overview covers its key features, pricing, use cases, and significant u...

31. [Use ROCm on Radeon and Ryzen](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/) - AMD's current ROCm guidance for Radeon GPUs and Ryzen APUs across Linux, Windows, and WSL.

32. [Tauri global-shortcut plugin](https://v2.tauri.app/plugin/global-shortcut/) - Official Tauri v2 global shortcut setup, usage, and capability permission guidance.
