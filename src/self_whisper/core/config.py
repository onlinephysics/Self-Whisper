"""
Self-Whisper Configuration Manager
Handles persistence and retrieval of application settings, API keys, hotkeys, and preferences.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    # Google AI Studio API Settings
    "api_key": os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", "")),
    "model": "gemini-3.5-transcribe-live",
    "fallback_model": "gemini-2.0-flash",

    # Language & Auto-Correction
    # Options: "bn_primary" (Bangla primary + English), "bn_only", "en_only", "auto"
    "language_mode": "bn_primary",
    # Options: "high" (Fix grammar, stutters, and punctuate), "normal" (Clean & punctuate), "verbatim"
    "correction_level": "high",
    # Post-dictation full-phrase rewrite (second AI pass over the finalized
    # text to fix language/script issues across the whole sentence).
    "rewrite_enabled": False,
    "rewrite_model": "gemini-3.5-flash-lite",

    # Translator: input speech is always treated as Bangla+English mixed, and
    # the finalized text is translated into the selected SPECIFIC language
    # via the Rewrite model (text REST after dictation ends).
    # Only single-language targets work ("bn_only" -> Bangla, "en_only" ->
    # English); mixed modes ("bn_primary", "auto") skip translation.
    "translator_enabled": False,

    # Hotkeys
    # Modes: "toggle" or "push_to_talk"
    "hotkey_mode": "toggle",
    "hotkey_toggle": "<ctrl>+<shift>+<space>",
    "hotkey_push_to_talk": "<f8>",
    "sound_effects_enabled": True,

    # Text Injection
    # Options: "typewriter" (Real-time live typing with in-place diff editing), "smart_paste"
    "injection_mode": "typewriter",
    "restore_clipboard_delay_ms": 100,

    # Audio Settings
    "input_device_index": None,  # None means system default
    "sample_rate": 16000,
    "chunk_duration_ms": 100,    # 100ms chunks for real-time streaming

    # Voice Activity Detection (auto-stop on silence)
    "vad_enabled": False,        # When True, dictation ends automatically after silence
    "vad_silence_ms": 1800,      # Silence duration that triggers auto-stop
    "vad_threshold": 0.08,       # Normalized mic level (0-1) counted as speech

    # UI Preferences
    "hud_always_on_top": True,
    "hud_opacity": 0.96,
    "hud_x": None,
    "hud_y": None,
    "auto_hide_hud": False,      # If True, HUD only shows while recording, hides when stopped
    "show_preview_text": False,
    "auto_hide_delay_s": 5.0,
}


class ConfigManager:
    def __init__(self, custom_path: str = None):
        if custom_path:
            self.config_file = Path(custom_path)
        else:
            # Store in user's home .self_whisper directory for persistent settings
            app_dir = Path(os.path.expanduser("~")) / ".self_whisper"
            app_dir.mkdir(parents=True, exist_ok=True)
            self.config_file = app_dir / "config.json"

        self.config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> Dict[str, Any]:
        """Loads configuration from JSON file if present."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.config.update(saved)
                    # Sanitize any legacy hotkey string
                    if self.config.get("hotkey_toggle") == "<ctrl>+<shift>+space":
                        self.config["hotkey_toggle"] = "<ctrl>+<shift>+<space>"
                    # Drop removed Translator Model switches (live engine retired;
                    # translation is Rewrite-model only now).
                    self.config.pop("translator_engine", None)
                    self.config.pop("translator_use_live", None)
            except Exception as e:
                print(f"[ConfigManager] Warning: Error loading config file: {e}")
        return self.config

    def save(self) -> bool:
        """Saves current configuration to JSON file."""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ConfigManager] Error saving config file: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any, auto_save: bool = True) -> None:
        self.config[key] = value
        if auto_save:
            self.save()

    def update(self, updates: Dict[str, Any], auto_save: bool = True) -> None:
        self.config.update(updates)
        if auto_save:
            self.save()


# Global config singleton
config = ConfigManager()
