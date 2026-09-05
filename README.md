# Self-Whisper

**Real-Time Windows Speech-to-Text Dictation powered by Gemini Live & Google AI Studio API.**

Self-Whisper is a background speech-to-text dictation application for Windows that types live into any active application:
- **Chat apps**: WhatsApp Desktop & Web, Discord, Messenger, Telegram, Slack
- **Productivity & Office**: Microsoft Word, Excel, PowerPoint, OneNote, Notepad, VS Code
- **Browsers & Anywhere**: Chrome, Edge, Firefox, Brave, text fields, and web forms

Only one copy runs at a time: launching it again just brings the running app forward.

---

## Key Features

1. **Powered by Gemini Live**:
   - Streams 16 kHz 16-bit linear PCM audio in real-time to Google AI Studio's Gemini Live API (`gemini-3.5-transcribe-live` / `gemini-2.0-flash`).
   - Seamless low-latency live transcription and fallback resilience.

2. **Specialized for Bangla (বাংলা) & English**:
   - Primary focus on **Bangla (বাংলা লিপি)** phonetics and vocabulary.
   - Flawless **code-switching ("Banglish")**: comfortably speak sentences mixing Bangla and English (e.g., *"আমি কালকে Discord-এ মিটিং করব"* or *"WhatsApp-এ লিঙ্কটা পাঠাও"*).
   - Pick the language from the floating bar, the tray menu, or Settings (`BN · EN`, `বাংলা`, `EN`, `AUTO`). Hindi/Devanagari output is explicitly forbidden in every mode.

3. **Built-in Auto-Correction & Punctuation Refinement**:
   - Cleans up stutters, false starts, and filler sounds (*"uh"*, *"um"*, *"মানে"*).
   - Fixes minor grammar slips and phonetics.
   - Automatically inserts punctuation: Bengali daari (`।`), commas, question marks, and English capitalization.

4. **Bengali Unicode Injection**:
   - **Live typing** writes into the textbox as you speak and corrects words in place.
   - **Block paste** pastes once when you stop (best for complex যুক্তবর্ণ like ক্ষ, জ্ঞ, ঙ্ক in Electron/Office apps).

5. **Modern Windows 11 UI**:
   - **Floating bar**: draggable dark-mode pill with animated equalizer, vector mic icon, and language badge.
   - **System tray**: background icon with full menu (toggle, language, settings, exit).
   - **Settings**: tabbed dialog (Connection / Language & Voice / Microphone / Shortcuts / Logs) — no scrolling.
   - **Logs tab**: dictation history plus the full application log, so no console window is needed.

6. **Global Hotkeys (both always active — no mode to pick)**:
   - **Toggle**: press `Ctrl + Shift + Space` to start, press again to stop.
   - **Push-to-talk**: hold `F8` while speaking, release to stop. Releasing it can never cut off a toggle dictation.
   - Shortcuts are customizable with press-to-record buttons in Settings → Shortcuts.

7. **Auto-stop on silence (optional)**:
   - Settings → Microphone → "Auto-stop on silence" ends toggle dictations automatically after 1–3.5 s of silence (your choice). Off by default; never applies to push-to-talk.

8. **Secure API key storage**:
   - The key is kept in **Windows Credential Manager** (never in plain text). Falls back to the local config file only if no vault backend exists.

---

## Quick Start

### Option A — EXE (no Python needed)
1. Double-click `build_exe.bat` (builds `dist\Self-Whisper\Self-Whisper.exe`).
2. Copy the `dist\Self-Whisper` folder anywhere and run `Self-Whisper.exe`.

### Option B — From source
Requirements: Windows 10/11 (64-bit), Python 3.10+, a Google AI Studio API key ([get one free](https://aistudio.google.com/app/apikey)).

```powershell
pip install -r requirements.txt
```

Double-click `run.bat` (windowless) or `run_debug.bat` (with console for troubleshooting).

### Setting up your API Key
1. Click the gear on the floating bar, or right-click the tray icon → **Settings...**.
2. Paste your key (`AIzaSy...`) → **Test Connection** → **Save Settings**.
3. Speak: click any text field, press `Ctrl + Shift + Space`, talk, press again.

### Quitting
- Right-click the tray icon (in the taskbar corner or the `^` hidden-icons overflow) → **Exit / Quit Self-Whisper**, or
- Settings → **Quit App** (bottom-left, with confirmation).

---

## Dictation Flow

1. Click into any text field (WhatsApp, Discord, Word, Notepad...).
2. Press **`Ctrl + Shift + Space`** (or hold **`F8`**).
   - The bar glows red: listening.
3. Speak naturally in Bangla, English, or a mix.
4. Press the toggle again, release `F8`, or just go silent (if auto-stop is on).
   - The text is finalized into your active window, and saved in Settings → Logs.

---

## Configuration Reference

General settings live in `~/.self_whisper/config.json`. The API key lives in Windows Credential Manager.

| Setting | Default | Description |
| :--- | :--- | :--- |
| `model` | `gemini-3.5-transcribe-live` | Target Gemini model |
| `language_mode` | `bn_primary` | `bn_primary`, `bn_only`, `en_only`, `auto` |
| `correction_level` | `high` | `high`, `normal`, `verbatim` |
| `hotkey_toggle` | `<ctrl>+<shift>+<space>` | Press to start/stop |
| `hotkey_push_to_talk` | `<f8>` | Hold to talk |
| `injection_mode` | `typewriter` | `typewriter` or `smart_paste` |
| `input_device_index` | `None` | Microphone index (`None` = Windows default) |
| `vad_enabled` | `false` | Auto-stop on silence |
| `vad_silence_ms` | `1800` | Silence duration for auto-stop |

---

## Project Structure

```
Self-Whisper/
├── main.py                # App coordinator (tray, hotkeys, streaming, injection)
├── config.py              # Settings persistence (~/.self_whisper/config.json)
├── secure_store.py        # API key in Windows Credential Manager (+ fallback)
├── audio_capture.py       # 16kHz PCM engine with real-time level metering
├── vad.py                 # Auto-stop-on-silence detector
├── gemini_live.py         # Gemini Live WebSocket + REST fallback client
├── text_injector.py       # Live in-place typing + smart-paste injector
├── hotkey_manager.py      # Global listener (toggle chord + push-to-talk)
├── hotkey_recorder.py     # Press-to-capture shortcut recorder
├── log_store.py           # In-memory logs + dictation history (Logs tab)
├── single_instance.py     # One-copy-only guard
├── ui/
│   ├── floating_hud.py    # Floating pill: EQ visualizer, mic icon, language menu
│   ├── settings_dialog.py # Tabbed settings incl. mic test + Logs viewer
│   └── tray_icon.py       # Tray icon with full context menu
├── test_verification.py   # Automated test suite (11 tests)
├── requirements.txt       # Runtime dependencies
├── SelfWhisper.spec       # PyInstaller recipe (windowless EXE)
├── build_exe.bat          # One-click EXE build
├── run.bat                # Windowless launcher
└── run_debug.bat          # Console launcher for troubleshooting
```

CI runs the compile check + test suite on every push/PR (`.github/workflows/ci.yml`).

---

## License
MIT License
