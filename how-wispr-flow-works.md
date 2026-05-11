# How Wispr Flow Works — Technical Deep Dive

---

## Overview

Wispr Flow is a **cloud-first AI dictation tool** for macOS and Windows. Despite its name, it has no relation to OpenAI's Whisper model. The name refers to the concept of whispering quietly into your device. Every piece of heavy computation (ASR + LLM) happens on remote cloud servers — the app installed on your machine is essentially a thin hotkey listener + mic recorder + text injector.

---

## The Full Pipeline (Step by Step)

```
User holds hotkey
      ↓
Mic captures raw PCM audio (local)
      ↓
Audio encrypted + sent to Baseten (AWS cloud)
      ↓
Proprietary ASR model → Raw transcript returned
      ↓
Fine-tuned Llama LLM → Polished text (filler removal, tone, corrections)
      ↓
Polished text sent back to the app
      ↓
Text injected into the active text field (local)
```

**Total target latency: ~700ms**
- ASR inference: ≤ 200ms
- LLM formatting: ≤ 250ms (Baseten TensorRT-LLM)
- Network round-trip: ≤ 200ms

---

## Component Breakdown

### 1. Local App (Thin Client)

What runs on your machine:
- **Global hotkey listener** — registers a system-wide shortcut (default: `Option+Space` on macOS)
- **Microphone capture** — records PCM audio while hotkey is held
- **Context detector** — reads the active application using macOS Accessibility APIs or Windows UI Automation
- **Text injector** — types or pastes the final result into whatever app is focused
- **Settings UI** — manages vocabulary, snippets, app profiles

What does NOT run locally:
- ASR (speech recognition)
- LLM (text cleanup/formatting)
- Any AI processing whatsoever

---

### 2. ASR Engine (Cloud — Baseten on AWS)

- **Provider**: Baseten (cloud ML inference platform)
- **Model**: Proprietary — not publicly disclosed, not OpenAI Whisper
- **Infrastructure**: AWS, with TensorRT-LLM optimization
- **What it does**: Converts raw audio bytes into an unpolished raw transcript
- **Output example**: `"um so I was thinking uh we should go with the second option wait no the first one"`

---

### 3. LLM Post-Processor (Cloud — Fine-tuned Llama on Baseten)

This is the core differentiator. Wispr Flow uses **custom fine-tuned Meta Llama models** — not off-the-shelf ChatGPT — trained specifically for dictation cleanup tasks.

**What the LLM does:**

| Task | Input | Output |
|---|---|---|
| Filler word removal | "um so uh like" | "" (removed) |
| Self-correction handling | "let's do 50k, wait no, 75k" | "Let's do 75k" |
| Punctuation + capitalization | "hello world how are you" | "Hello world, how are you?" |
| Tone adjustment | Raw casual speech in Gmail | Professional email prose |
| Proper noun correction | "haaga helia" → context: university | "Haaga-Helia" |

**LLM inputs:**
1. Raw transcript from ASR
2. Active app category (Email / Work Chat / Personal Chat / Code / Other)
3. Screen-visible text snippets (for proper noun context)
4. User's personal vocabulary/corrections

**Additional LLM providers used** (for specific tasks):
- OpenAI — supplementary text processing
- Anthropic — supplementary text processing
- Cerebras — ultra-fast inference fallback
- Fireworks AI — Command Mode (voice editing of selected text)

---

### 4. Context Awareness Engine

This is the second key differentiator. Wispr Flow detects what app you're typing in and automatically adjusts the LLM's formatting instructions.

**How it works on macOS:**
- Uses **macOS Accessibility API** (`AXUIElement`) to read the frontmost application's bundle ID and window title
- For browsers: reads the URL bar text via accessibility tree to distinguish Gmail from Slack even if both are open in Chrome

**How it works on Windows:**
- Uses **Windows UI Automation** API (`IUIAutomation`)
- Same URL extraction logic for browsers

**App categories and their formatting styles:**

| Category | Apps Detected | Formatting Style |
|---|---|---|
| Email | Gmail, Outlook, Thunderbird | Professional, full sentences, paragraphs |
| Work Chat | Slack, Teams, Discord | Concise, professional-casual |
| Personal Chat | WhatsApp, iMessage, Telegram | Casual, natural, informal |
| Code | VS Code, Cursor, Xcode, JetBrains | Preserve technical terms, minimal formatting |
| Other | Everything else | General punctuation + cleanup |

---

### 5. Personal Vocabulary & Learning System

Wispr Flow tracks corrections the user makes after dictation and builds a personal vocabulary:

- Misrecognized words that the user corrects are logged
- These corrections are injected into future prompts as hints to both the ASR (via initial prompt) and the LLM (as vocabulary context)
- Custom words can also be added manually (technical jargon, names, brand names)
- Custom snippets: say a short trigger phrase → expands to a long block of text

---

### 6. Command Mode (Voice Editing)

A secondary mode where the user highlights existing text, presses a Command Mode hotkey, speaks an edit instruction, and the text is replaced.

**Flow:**
```
User highlights text in any app
      ↓
Presses Command Mode hotkey
      ↓
Speaks: "make this more concise" / "translate to French" / "turn into bullet points"
      ↓
Highlighted text + voice command sent to Fireworks AI LLM
      ↓
Edited text replaces selection via clipboard
```

---

### 7. Whisper Mode

Detects when the user is speaking very quietly (whispering) and adjusts VAD (Voice Activity Detection) thresholds accordingly. No processing difference — same pipeline, just more sensitive mic gain.

---

## Privacy & Data Flow

| Data | Where it goes |
|---|---|
| Audio | Encrypted in transit to Baseten (AWS) |
| Raw transcript | Processed on Baseten, not permanently stored by default |
| Polished text | Returned to local app only |
| Personal vocabulary | Stored locally + synced to Wispr Flow servers |
| Screen content | Used briefly for context, not recorded |

**Third-party subprocessors include:** Baseten, AWS, OpenAI, Anthropic, Cerebras, Fireworks AI, Stripe (billing), and several analytics providers.

**Key limitation:** There is no offline mode. Without an internet connection, the app does not work at all.

---

## What Wispr Flow Does NOT Use

- ❌ OpenAI Whisper (the open-source ASR model) — despite the name similarity
- ❌ Any local AI processing
- ❌ On-device inference of any kind
- ❌ Apple's built-in dictation
- ❌ Dragon NaturallySpeaking / any legacy ASR

---

## Why It Feels Better Than Built-in Dictation

Most OS-level dictation (Windows Speech Recognition, macOS Dictation) only does step 1 — raw ASR. They output exactly what you said, filler words and all, with no post-processing.

Wispr Flow's edge is entirely in steps 2–4:
1. **Fine-tuned LLM** that understands dictation-specific cleanup tasks
2. **Context awareness** that selects the right formatting style automatically
3. **Vocabulary learning** that improves over time with your corrections
4. **Sub-700ms total latency** that feels nearly instantaneous

All four of these can be replicated locally using:
- `faster-whisper large-v3-turbo` (ASR)
- `Ollama + Qwen3.5:4b` (LLM post-processor)
- `pywin32` UI Automation (context detection on Windows)
- `pyautogui` / clipboard (text injection)

---

## Summary Diagram

```
┌─────────────────────────────────────────────────────┐
│                YOUR MACHINE (local)                  │
│  Hotkey → Mic → Audio Buffer → Context Detector     │
│                      ↕ encrypted HTTPS               │
├─────────────────────────────────────────────────────┤
│              BASETEN CLOUD (AWS)                     │
│  Proprietary ASR → Raw Transcript                   │
│  Fine-tuned Llama → Polished Text                   │
│  (+ OpenAI / Anthropic / Cerebras / Fireworks AI)   │
├─────────────────────────────────────────────────────┤
│                YOUR MACHINE (local)                  │
│  Text Injector → Active App Text Field              │
└─────────────────────────────────────────────────────┘
```
