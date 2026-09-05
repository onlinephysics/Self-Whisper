"""
Self-Whisper Hotkey Recorder ("press to capture").

Used by the Settings -> Shortcuts tab so users never have to type key names:
click Record, press the chord (e.g. Ctrl+Shift+Space), release — the field
fills itself in.

Emits `captured(str)` with a plain display string like "ctrl+shift+space" or
"f8" (already compatible with hotkey_manager.normalize_hotkey_string), or
`cancelled()` on Esc / timeout / manual stop. Thread-safe via Qt signals.
"""

import threading
from typing import List, Optional

try:
    from PyQt6.QtCore import QObject, pyqtSignal

    class _Base(QObject):
        captured = pyqtSignal(str)
        cancelled = pyqtSignal()
except Exception:  # pragma: no cover
    _Base = object  # type: ignore

from self_whisper.input.hotkey_manager import canonical_key_token

_MODIFIER_ORDER = ("ctrl", "shift", "alt", "cmd")
_TIMEOUT_S = 12.0


def build_hotkey_string(tokens_in_press_order: list) -> str:
    """Orders tokens modifiers-first, de-duplicated, joined with '+'."""
    seen = []
    for t in tokens_in_press_order:
        if t and t not in seen:
            seen.append(t)
    mods = [t for t in _MODIFIER_ORDER if t in seen]
    rest = [t for t in seen if t not in _MODIFIER_ORDER]
    parts = mods + rest
    return "+".join(parts) if parts else ""


class HotkeyCapture(_Base):
    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self._listener = None
        self._tokens: list = []
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._active = False

    def start(self):
        """Begins listening for the next key chord. No-op if already active."""
        from pynput import keyboard

        with self._lock:
            if self._active:
                return
            self._active = True
            self._tokens = []
        try:
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.daemon = True
            self._listener.start()
        except Exception:
            with self._lock:
                self._active = False
            self._emit_cancelled()
            return
        self._timer = threading.Timer(_TIMEOUT_S, self._on_timeout)
        self._timer.daemon = True
        self._timer.start()

    def stop(self, silent: bool = True):
        with self._lock:
            self._active = False
            listener, self._listener = self._listener, None
            timer, self._timer = self._timer, None
        try:
            if timer is not None:
                timer.cancel()
        except Exception:
            pass
        try:
            if listener is not None:
                listener.stop()
        except Exception:
            pass
        if not silent:
            self._emit_cancelled()

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._active

    # -- internals --

    def _emit_captured(self, text: str):
        try:
            self.captured.emit(text)
        except Exception:
            pass

    def _emit_cancelled(self):
        try:
            self.cancelled.emit()
        except Exception:
            pass

    def _finish(self, text: str):
        self.stop(silent=True)
        if text:
            self._emit_captured(text)
        else:
            self._emit_cancelled()

    def _on_timeout(self):
        with self._lock:
            active = self._active
        if active:
            self.stop(silent=True)
            self._emit_cancelled()

    def _on_press(self, key):
        token = canonical_key_token(key)
        with self._lock:
            if not self._active:
                return
            if token is None:
                return
            if token in ("esc", "escape"):
                pass  # handled below (cancel)
            elif token not in self._tokens:
                self._tokens.append(token)
        if token in ("esc", "escape"):
            self.stop(silent=True)
            self._emit_cancelled()

    def _on_release(self, key):
        token = canonical_key_token(key)
        with self._lock:
            if not self._active:
                return False
            # Chord complete when every pressed key is released. pynput does
            # not give us the full pressed set here, so approximate: finish
            # on the first release after 2+ tokens, or on release of a
            # single non-modifier key.
            tokens = list(self._tokens)
            if not tokens:
                return False
            is_modifier = token in _MODIFIER_ORDER
            if len(tokens) >= 2 or not is_modifier:
                text = build_hotkey_string(tokens)
            else:
                return False  # single modifier so far; keep waiting
        self._finish(text)
        try:
            return False  # stop listener
        except Exception:
            return False
