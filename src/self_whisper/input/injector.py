"""
Self-Whisper Real-Time In-Place Text Injector
Enables true live dictation:
1. Types in real time into the active application's textbox as you speak.
2. Edits/corrects words live via intelligent diffing (backspacing revised portions and typing replacements).
3. Finalizes with clean punctuation and trailing space when you stop.
4. Seamlessly starts the next dictation from the cursor without touching prior sentences.
"""

import ctypes
import time
import unicodedata
import threading
from typing import Optional
from pynput.keyboard import Controller, Key

# Win32 Virtual Key Codes and Flags
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12    # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def release_modifier_keys():
    """Ensures Ctrl, Shift, Alt, and Win keys are released logically."""
    for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def force_foreground_window(hwnd: int):
    """
    Robustly restores focus to the target application window using Win32 AttachThreadInput.
    Works even if called from a background thread or a tool window.
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return
    cur_fg = user32.GetForegroundWindow()
    if cur_fg == hwnd:
        return

    try:
        cur_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(cur_fg, None)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        if fg_thread and fg_thread != cur_thread:
            user32.AttachThreadInput(cur_thread, fg_thread, True)
        if target_thread and target_thread != cur_thread:
            user32.AttachThreadInput(cur_thread, target_thread, True)

        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)

        if fg_thread and fg_thread != cur_thread:
            user32.AttachThreadInput(cur_thread, fg_thread, False)
        if target_thread and target_thread != cur_thread:
            user32.AttachThreadInput(cur_thread, target_thread, False)
    except Exception as e:
        print(f"[TextInjector] Error focusing window {hex(hwnd)}: {e}")


def get_clipboard_text() -> Optional[str]:
    """Retrieves current Unicode text from Windows clipboard."""
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception as e:
        print(f"[TextInjector] Error getting clipboard: {e}")
        return None


def set_clipboard_text(text: str) -> bool:
    """Sets Unicode text onto the Windows clipboard."""
    try:
        import pyperclip
        normalized = unicodedata.normalize("NFC", text)
        pyperclip.copy(normalized)
        return True
    except Exception as e:
        print(f"[TextInjector] Error setting clipboard: {e}")
        return False


def send_paste_keys():
    """
    Synthesizes clean Ctrl+V key combination to paste into the active window.
    Releases Shift/Alt/Win modifiers first so they don't combine into Ctrl+Shift+V.
    """
    release_modifier_keys()
    time.sleep(0.04)

    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    time.sleep(0.02)

    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.02)

    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.03)


class TextInjector:
    def __init__(self, mode: str = "typewriter"):
        self.mode = mode
        self.current_streamed = ""
        self.target_hwnd: Optional[int] = None
        self._session_active = False
        self._lock = threading.Lock()
        self.kb = Controller()

    def set_mode(self, mode: str):
        self.mode = mode

    def start_live_session(self, target_hwnd: Optional[int] = None):
        """Prepares state for a fresh live dictation turn."""
        with self._lock:
            self.current_streamed = ""
            self.target_hwnd = target_hwnd
            self._session_active = True
            release_modifier_keys()
            if target_hwnd and user32.IsWindow(target_hwnd):
                force_foreground_window(target_hwnd)

    def _stream_diff_locked(self, new_text: str, active_hwnd: Optional[int] = None):
        """Internal worker to calculate diff and type into active window."""
        old = self.current_streamed
        new = unicodedata.normalize("NFC", new_text)

        if old == new:
            return

        release_modifier_keys()

        # Compute common prefix length
        common_len = 0
        min_len = min(len(old), len(new))
        while common_len < min_len and old[common_len] == new[common_len]:
            common_len += 1

        backspaces_needed = len(old) - common_len
        chars_to_type = new[common_len:]

        # 1. Backspace revised/corrected characters in real-time
        if backspaces_needed > 0:
            for _ in range(backspaces_needed):
                self.kb.tap(Key.backspace)
                time.sleep(0.003)

        # 2. Type newly added/revised characters in real-time
        if chars_to_type:
            for ch in chars_to_type:
                self.kb.type(ch)
                time.sleep(0.002)

        self.current_streamed = new

    def stream_update(self, new_text: str, target_hwnd: Optional[int] = None):
        """
        Real-time live typing and in-place correction:
        Calculates diff with previously streamed text.
        If the model corrected earlier words, backspaces the revised part.
        Then types newly spoken characters directly into the application's textbox.
        """
        if not new_text or not self._session_active:
            return

        with self._lock:
            if not self._session_active:
                return

            active_hwnd = target_hwnd or self.target_hwnd
            if active_hwnd and user32.IsWindow(active_hwnd):
                cur_fg = user32.GetForegroundWindow()
                if cur_fg != active_hwnd:
                    force_foreground_window(active_hwnd)
                    time.sleep(0.015)

            self._stream_diff_locked(new_text, active_hwnd)

    def finalize_live_session(self, final_text: Optional[str] = None, target_hwnd: Optional[int] = None):
        """
        Finalizes current dictation turn:
        Updates text with final punctuation, appends trailing space,
        copies to clipboard, and resets session so next dictation starts from cursor.
        Guarded so it can NEVER type duplicate text even if called multiple times.
        """
        with self._lock:
            if not self._session_active:
                # Session was already finalized; strictly ignore duplicate calls
                return
            self._session_active = False

            active_hwnd = target_hwnd or self.target_hwnd
            if active_hwnd and user32.IsWindow(active_hwnd):
                cur_fg = user32.GetForegroundWindow()
                if cur_fg != active_hwnd:
                    force_foreground_window(active_hwnd)
                    time.sleep(0.015)

            if final_text:
                clean_final = unicodedata.normalize("NFC", final_text.strip())
                # If nothing was streamed live yet, type it directly
                if not self.current_streamed:
                    release_modifier_keys()
                    for ch in clean_final:
                        self.kb.type(ch)
                        time.sleep(0.002)
                    self.current_streamed = clean_final
                else:
                    # Apply final diff (e.g. adding punctuation)
                    self._stream_diff_locked(clean_final, active_hwnd)

                # Keep a copy on clipboard for user convenience
                set_clipboard_text(clean_final)

            # Add trailing space so next session starts cleanly from next position
            if self.current_streamed and not self.current_streamed.endswith((" ", "\n")):
                release_modifier_keys()
                self.kb.tap(Key.space)

            # Reset session state: next dictation starts cleanly from current cursor!
            self.current_streamed = ""
            self.target_hwnd = None

    def inject_text(self, text: str, append_space: bool = False, target_hwnd: Optional[int] = None):
        """Fallback complete block injection via Smart Paste or Typewriter."""
        if not text:
            return

        text = unicodedata.normalize("NFC", text)
        if append_space and not text.endswith((" ", "\n", "।", ".")):
            text += " "

        if target_hwnd and user32.IsWindow(target_hwnd):
            cur_fg = user32.GetForegroundWindow()
            if cur_fg != target_hwnd:
                user32.SetForegroundWindow(target_hwnd)
                time.sleep(0.06)

        if self.mode == "typewriter":
            try:
                self.kb.type(text)
            except Exception:
                self._inject_smart_paste(text)
        else:
            self._inject_smart_paste(text)

    def _inject_smart_paste(self, text: str):
        with self._lock:
            set_clipboard_text(text)
            time.sleep(0.03)
            send_paste_keys()


# Singleton instance
injector = TextInjector()
