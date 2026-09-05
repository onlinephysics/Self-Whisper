# Self-Whisper 🎙️

**Real-Time Windows Speech-to-Text Dictation powered by Gemini 3.5 Transcribe Live & Google AI Studio API.**

Self-Whisper is a background speech-to-text dictation application for Windows that types live into any active application:
- **Chat apps**: WhatsApp Desktop & Web, Discord, Messenger, Telegram, Slack
- **Productivity & Office**: Microsoft Word, Excel, PowerPoint, OneNote, Notepad, VS Code
- **Browsers & Anywhere**: Chrome, Edge, Firefox, Brave, text fields, and web forms

---

## Key Features

1. **Powered by Gemini Live**:
   - Streams 16 kHz 16-bit linear PCM audio in real-time to Google AI Studio's Gemini Live API (`gemini-3.5-transcribe-live` / `gemini-2.0-flash`).
   - Seamless low-latency live transcription and fallback resilience.

2. **Specialized for Bangla (বাংলা) & English**:
   - Primary focus on **Bangla (বাংলা লিপি)** phonetics and vocabulary.
   - Flawless **code-switching ("Banglish")**: comfortably speak sentences mixing Bangla and English (e.g., *"আমি কালকে Discord-এ মিটিং করব"* or *"WhatsApp-এ লিঙ্কটা পাঠাও"*).
   - Fast language cycling (`🇧🇩 BN+EN`, `🇧🇩 BN`, `🇬🇧 EN`, `🌐 AUTO`) directly from the floating HUD or system tray.

3. **Built-in Auto-Correction & Punctuation Refinement**:
   - Cleans up stutters, false starts, and filler sounds (*"uh"*, *"um"*, *"মানে"*).
   - Fixes minor grammar slips and phonetics.
   - Automatically inserts punctuation: Bengali daari (`।`), commas, question marks, and English capitalization.

4. **100% Accurate Bengali Unicode Injection**:
   - Uses **Smart Clipboard Injection** by default to paste complex Bengali conjuncts (যুক্তবর্ণ যেমন ক্ষ, জ্ঞ, ঙ্ক, ণ্ড, হ্ম, ্য, ্র) into Electron apps (Discord, WhatsApp) and Office apps with zero character corruption, preserving your original clipboard in milliseconds.
   - Optional **Typewriter Mode** (direct SendInput Unicode keystrokes).

5. **Modern Windows 11 UI**:
   - **Floating HUD**: Draggable, translucent dark-mode pill with dynamic real-time audio waveform equalizer, live transcript ticker, and quick controls.
   - **System Tray**: Unobtrusive background icon with a full context menu.
   - **Settings Window**: Configure your Google AI Studio API key, test connection, choose models, select microphone devices, and customize hotkeys.

6. **Global Hotkeys**:
   - **Toggle Mode (Default)**: Press `Ctrl + Shift + Space` once to start speaking, press again to stop and inject.
   - **Push-to-Talk Mode**: Hold `F8` (or custom key) while speaking; release to finish and inject.

---

## Quick Start

### 1. Requirements
- Windows 10 or Windows 11 (64-bit)
- Python 3.10+ (Python 3.10 - 3.14 supported)
- Google AI Studio API Key ([Get one free from Google AI Studio](https://aistudio.google.com/app/apikey))

### 2. Installation
Dependencies are listed in `requirements.txt`:
```powershell
pip install -r requirements.txt
```

### 3. Launching
Double-click `run.bat` or run:
```powershell
python main.py
```

### 4. Setting up your API Key
1. On first launch, click the gear icon `⚙️` on the floating HUD or right-click the system tray icon and select **Settings...**.
2. Paste your Google AI Studio API Key (`AIzaSy...`).
3. Click **Test API** to verify connection.
4. Click **Save Settings**.

---

## Hotkey Usage & Dictation Flow

1. Click into any text field (WhatsApp message box, Discord chat, Microsoft Word, Notepad).
2. Press **`Ctrl + Shift + Space`** (or your configured Push-to-Talk key).
   - The HUD pill will glow red with animated equalizer bars: `Listening... (কথা বলুন)`.
3. Speak naturally in Bangla, English, or a mix.
4. Press **`Ctrl + Shift + Space`** again (or release the key).
   - The text is auto-corrected and typed instantly into your active window!

---

## Configuration Reference

Configuration is stored in `~/.self_whisper/config.json`:

| Setting | Default | Description |
| :--- | :--- | :--- |
| `api_key` | `""` | Google AI Studio API Key |
| `model` | `gemini-3.5-transcribe-live` | Target Gemini model |
| `language_mode` | `bn_primary` | `bn_primary`, `bn_only`, `en_only`, `auto` |
| `correction_level` | `high` | `high` (full auto-correction), `normal`, `verbatim` |
| `hotkey_mode` | `toggle` | `toggle` or `push_to_talk` |
| `hotkey_toggle` | `<ctrl>+<shift>+space` | Shortcut chord for toggle mode |
| `hotkey_push_to_talk` | `<f8>` | Key for hold-to-speak mode |
| `injection_mode` | `smart_paste` | `smart_paste` or `typewriter` |
| `input_device_index` | `None` | Microphone index (`None` = Windows default) |

---

## Project Structure

```
Self-Whisper/
├── config.py              # Configuration manager and persistence (~/.self_whisper/config.json)
├── audio_capture.py       # 16kHz PCM audio engine with real-time RMS metering
├── gemini_live.py         # Google AI Studio Gemini Live WebSocket & REST fallback client
├── text_injector.py       # Windows Smart Clipboard Paste & Typewriter Unicode Injector
├── hotkey_manager.py      # Global hotkey listener (Toggle & Push-to-Talk)
├── ui/
│   ├── floating_hud.py    # Windows 11 frameless floating pill overlay with waveform
│   ├── settings_dialog.py # Settings UI with API tester, mic selector, model options
│   └── tray_icon.py       # System tray icon with context menu
├── main.py                # Main application coordinator
├── test_verification.py   # Automated test suite
├── requirements.txt       # Dependencies
└── run.bat                # 1-click Windows launcher
```

---

## License
MIT License
