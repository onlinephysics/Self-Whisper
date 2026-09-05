"""
Self-Whisper Global Hotkey Manager
Listens for global keyboard shortcuts across all Windows applications.

Both shortcuts are ALWAYS active at the same time (no mode selector):
- Toggle chord (default Ctrl+Shift+Space): press once to start, press again to stop.
- Push-to-Talk key (default F8): hold to talk, release to stop.

Reliability notes (fixes "press 2 times" bug):
- Uses a single raw `pynput.keyboard.Listener` with an explicit pressed-key set
  instead of `GlobalHotKeys`. GlobalHotKeys is flaky for Ctrl+Shift+Space on
  Windows (space canonicalization + key auto-repeat causes double-fire:
  start->stop in one physical press, looking like "nothing happened").
- Edge-triggered: fires ONCE per physical chord press (transition from
  "not all keys down" -> "all keys down"), then disarms until at least one
  chord key is released. Auto-repeat of Space can never double-toggle.
- Time debounced (default 0.6s) as a second guard against OS-level repeats.
- Callbacks are invoked on the listener thread; callers MUST marshal to the
  Qt GUI thread (e.g. via pyqtSignal.emit) instead of touching widgets directly.
"""

import threading
import time
from typing import Callable, FrozenSet, Optional, Set

from pynput import keyboard


TOGGLE_DEBOUNCE_S = 0.6


def normalize_hotkey_string(hotkey_str: str) -> str:
    """
    Converts friendly strings like 'ctrl+shift+space' or '<ctrl>+<shift>+space'
    into strict pynput format like '<ctrl>+<shift>+<space>'.
    """
    if not hotkey_str:
        return "<ctrl>+<shift>+<space>"

    # Split by '+'
    parts = [p.strip().lower() for p in hotkey_str.split('+') if p.strip()]
    normalized_parts = []
    special_keys = {
        'ctrl', 'ctrl_l', 'ctrl_r',
        'shift', 'shift_l', 'shift_r',
        'alt', 'alt_l', 'alt_r', 'alt_gr',
        'cmd', 'cmd_l', 'cmd_r',
        'space', 'enter', 'tab', 'esc', 'backspace', 'delete',
        'up', 'down', 'left', 'right', 'home', 'end',
        'page_up', 'page_down', 'caps_lock', 'insert'
    }

    for p in parts:
        clean = p.replace('<', '').replace('>', '').strip()
        if clean in special_keys or (clean.startswith('f') and clean[1:].isdigit()):
            normalized_parts.append(f'<{clean}>')
        else:
            normalized_parts.append(clean)

    return '+'.join(normalized_parts)


def _base_key_name(name: str) -> str:
    """ctrl_l / ctrl_r -> ctrl, shift_l -> shift, etc."""
    name = name.lower()
    for base in ("ctrl", "shift", "alt", "cmd"):
        if name == base or name.startswith(base + "_") or name.startswith(base + "-"):
            return base
    return name


def parse_hotkey_to_set(hotkey_str: str) -> FrozenSet[str]:
    """'ctrl+shift+space' / '<ctrl>+<shift>+<space>' -> frozenset({'ctrl','shift','space'})."""
    if not hotkey_str:
        return frozenset({"ctrl", "shift", "space"})
    parts = [p.strip().lower() for p in hotkey_str.split('+') if p.strip()]
    out: Set[str] = set()
    for p in parts:
        clean = p.replace('<', '').replace('>', '').strip()
        if not clean:
            continue
        out.add(_base_key_name(clean))
    if not out:
        return frozenset({"ctrl", "shift", "space"})
    return frozenset(out)


def canonical_key_token(key) -> Optional[str]:
    """
    Map a pynput key event to a canonical token comparable with
    parse_hotkey_to_set() output.
    Returns None if the key cannot be identified.
    """
    try:
        # Special keys: keyboard.Key.space, Key.ctrl_l, Key.f8, ...
        if isinstance(key, keyboard.Key):
            name = getattr(key, "name", None) or str(key).replace("Key.", "")
            return _base_key_name(str(name).lower())
        # Character keys: keyboard.KeyCode
        if isinstance(key, keyboard.KeyCode):
            ch = getattr(key, "char", None)
            vk = getattr(key, "vk", None)
            if ch is not None:
                if ch == ' ' or ch == '\x20':
                    return "space"
                # '\r'/'\n' from numpad enter etc.
                if ch in ('\r', '\n'):
                    return "enter"
                if ch == '\t':
                    return "tab"
                if len(ch) == 1:
                    return ch.lower()
            # Fallback via virtual-key code (Windows)
            if vk is not None:
                try:
                    vk_int = int(vk)
                except Exception:
                    vk_int = None
                if vk_int == 32:
                    return "space"
                if vk_int == 13:
                    return "enter"
                if vk_int == 9:
                    return "tab"
                if vk_int == 27:
                    return "esc"
                if 112 <= vk_int <= 135:  # F1..F24
                    return f"f{vk_int - 111}"
            return None
        # Unknown object with .name / .char attributes
        if hasattr(key, "name") and getattr(key, "name"):
            return _base_key_name(str(key.name).lower())
        if hasattr(key, "char") and getattr(key, "char"):
            ch = key.char
            if ch == ' ':
                return "space"
            return str(ch).lower()
    except Exception:
        return None
    return None


class GlobalHotkeyManager:
    def __init__(
        self,
        toggle_hotkey: str = "<ctrl>+<shift>+<space>",
        push_to_talk_key: str = "<f8>",
        mode: str = "toggle",
        on_toggle_callback: Optional[Callable[[], None]] = None,
        on_push_start_callback: Optional[Callable[[], None]] = None,
        on_push_stop_callback: Optional[Callable[[], None]] = None,
    ):
        self.toggle_hotkey = normalize_hotkey_string(toggle_hotkey)
        self._toggle_set: FrozenSet[str] = parse_hotkey_to_set(toggle_hotkey)
        self.push_to_talk_key = push_to_talk_key.replace('<', '').replace('>', '').lower().strip()
        self._ptt_token: str = _base_key_name(self.push_to_talk_key or "f8")
        # `mode` is kept for backward compatibility but ignored: both the
        # toggle chord and the push-to-talk key are always active.
        self.mode = "both"

        self.on_toggle_callback = on_toggle_callback
        self.on_push_start_callback = on_push_start_callback
        self.on_push_stop_callback = on_push_stop_callback

        self._listener: Optional[keyboard.Listener] = None
        self._pressed: Set[str] = set()
        self._toggle_armed = True   # require release of a chord key before next fire
        self._last_toggle_fire = 0.0
        self._is_holding_ptt = False
        self._lock = threading.Lock()

    def set_mode(self, mode: str):
        # No-op (kept for backward compatibility): both shortcuts are
        # always active, there is no mode to switch.
        with self._lock:
            self._pressed.clear()
            self._toggle_armed = True
            self._is_holding_ptt = False

    def update_keys(self, toggle_hotkey: str, push_to_talk_key: str):
        with self._lock:
            self.toggle_hotkey = normalize_hotkey_string(toggle_hotkey)
            self._toggle_set = parse_hotkey_to_set(toggle_hotkey)
            self.push_to_talk_key = push_to_talk_key.replace('<', '').replace('>', '').lower().strip()
            self._ptt_token = _base_key_name(self.push_to_talk_key or "f8")
            self._pressed.clear()
            self._toggle_armed = True
            self._is_holding_ptt = False
        self.restart()

    def start(self):
        """Starts the single raw listener (both shortcuts always active)."""
        with self._lock:
            self.stop_locked()
            try:
                self._pressed.clear()
                self._toggle_armed = True
                self._is_holding_ptt = False
                self._listener = keyboard.Listener(
                    on_press=self._handle_press,
                    on_release=self._handle_release,
                )
                self._listener.daemon = True
                self._listener.start()
                print(f"[HotkeyManager] Listening (both active) "
                      f"toggle={self.toggle_hotkey} ptt=<{self._ptt_token}>")
            except Exception as e:
                print(f"[HotkeyManager] Error starting listener: {e}")
                self._listener = None

    def stop_locked(self):
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        self._pressed.clear()
        self._toggle_armed = True
        self._is_holding_ptt = False

    def stop(self):
        """Stops any active hotkey listeners."""
        with self._lock:
            self.stop_locked()
        # Back-compat: old code referenced these; keep as no-op aliases.
        self._hotkey_listener = None
        self._raw_listener = None

    # Provide attributes for older external references (avoid AttributeError)
    _hotkey_listener = None
    _raw_listener = None

    def restart(self):
        self.stop()
        self.start()

    # -- internal --

    def _safe_fire(self, cb: Optional[Callable[[], None]]):
        if cb is None:
            return
        try:
            cb()
        except Exception as e:
            print(f"[HotkeyManager] Callback error: {e}")

    def _handle_press(self, key):
        token = canonical_key_token(key)
        if token is None:
            return
        toggle_cb = None
        ptt_cb = None
        with self._lock:
            # Track pressed (set semantics => auto-repeat adds nothing new)
            is_repeat = token in self._pressed
            self._pressed.add(token)

            # Both shortcuts are evaluated on every press (no mode gating).
            # 1) Toggle chord: edge-triggered + debounced.
            if self._toggle_set.issubset(self._pressed):
                if self._toggle_armed and not is_repeat:
                    now = time.monotonic()
                    if now - self._last_toggle_fire >= TOGGLE_DEBOUNCE_S:
                        self._last_toggle_fire = now
                        self._toggle_armed = False
                        toggle_cb = self.on_toggle_callback
                    else:
                        self._toggle_armed = False
            # 2) Push-to-talk: hold to talk (repeat-safe via _is_holding_ptt).
            if token == self._ptt_token and not self._is_holding_ptt:
                self._is_holding_ptt = True
                ptt_cb = self.on_push_start_callback
        # Fire outside the lock so a slow GUI marshal can't block the listener.
        if toggle_cb is not None:
            self._safe_fire(toggle_cb)
        if ptt_cb is not None:
            self._safe_fire(ptt_cb)

    def _handle_toggle_fire(self, cb):
        self._safe_fire(cb)

    def _handle_release(self, key):
        token = canonical_key_token(key)
        if token is None:
            return
        ptt_cb = None
        with self._lock:
            self._pressed.discard(token)
            # Re-arm toggle once any chord key is released -> next physical
            # press can fire exactly once.
            if not self._toggle_set.issubset(self._pressed):
                self._toggle_armed = True
            if token == self._ptt_token and self._is_holding_ptt:
                self._is_holding_ptt = False
                ptt_cb = self.on_push_stop_callback
        if ptt_cb is not None:
            self._safe_fire(ptt_cb)

    # -- legacy entry points (kept so older code paths still work) --

    def _handle_toggle(self):
        self._safe_fire(self.on_toggle_callback)

    def _matches_ptt_key(self, key) -> bool:
        return canonical_key_token(key) == self._ptt_token

    def _handle_raw_press(self, key):
        self._handle_press(key)

    def _handle_raw_release(self, key):
        self._handle_release(key)
