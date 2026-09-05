"""Input: global hotkeys, recorder, text injection."""

from self_whisper.input.hotkey_manager import GlobalHotkeyManager, parse_hotkey_to_set
from self_whisper.input.injector import injector

__all__ = ["GlobalHotkeyManager", "parse_hotkey_to_set", "injector"]
