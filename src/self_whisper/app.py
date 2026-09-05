"""
Self-Whisper: Real-Time Windows Speech-to-Text via Gemini Live API
Main Application Orchestrator

Connects:
- Audio Capture Engine (sounddevice 16kHz PCM)
- Gemini Live Streaming Client & Fallback (Google AI Studio)
- Text Injector (Smart Clipboard paste into WhatsApp/Discord/Office)
- Global Hotkey Manager (Toggle & Push-to-Talk)
- Floating HUD & System Tray UI
"""

import sys
import os
import threading
import time
from typing import Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from self_whisper.core.config import config
from self_whisper.core.log_store import install as install_log_store, log, log_dictation
from self_whisper.platform_win.single_instance import SingleInstanceGuard
from self_whisper.audio.vad import SilenceDetector
from self_whisper.audio.capture import AudioCaptureEngine
from self_whisper.transcription.gemini_live import (
    GeminiLiveSession,
    GeminiRewrite,
    GeminiTranscribeFallback,
    resolve_translate_target,
)
from self_whisper.input.injector import injector
from self_whisper.input.hotkey_manager import GlobalHotkeyManager
from self_whisper.ui.floating_hud import FloatingHUD
from self_whisper.ui.settings_dialog import SettingsDialog
from self_whisper.ui.tray_icon import SelfWhisperTray
from self_whisper.audio.sound_effects import play_start_sound, play_stop_sound, play_error_sound


class AppSignals(QObject):
    """Thread-safe signal bridge between background workers and Qt GUI."""
    status_changed = pyqtSignal(str, str)     # (status, message)
    audio_level_updated = pyqtSignal(float)   # 0.0 - 1.0
    preview_updated = pyqtSignal(str)         # live transcript text
    inject_requested = pyqtSignal(str)        # final text to inject
    request_settings = pyqtSignal()           # open settings dialog
    # Hotkey thread -> GUI thread marshalling (pyqtSignal.emit is thread-safe,
    # direct method calls from pynput listener thread are NOT safe for Qt UI).
    toggle_requested = pyqtSignal()
    push_start_requested = pyqtSignal()
    push_stop_requested = pyqtSignal()
    auto_stop_requested = pyqtSignal()  # VAD silence detected (worker -> GUI)
    rewrite_ready = pyqtSignal(str, str)  # (rewritten_text, original_text)


class SelfWhisperApp:
    @staticmethod
    def _get_api_key() -> str:
        """Vault (Credential Manager) first, legacy config file second."""
        try:
            from self_whisper.platform_win import secure_store
            vault_key = secure_store.get_api_key()
            if vault_key:
                return vault_key
        except Exception:
            pass
        return (config.get("api_key", "") or "").strip()

    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.signals = AppSignals()

        # State tracking
        self.is_recording = False
        self._turn_finalized = True
        self.active_session: Optional[GeminiLiveSession] = None
        self.accumulated_pcm = bytearray()
        self.stream_thread: Optional[threading.Thread] = None
        self._stop_stream_flag = False
        self.target_hwnd: Optional[int] = None
        self.last_external_hwnd: Optional[int] = None
        # Debounce for toggle (hotkey auto-repeat / double-fire guard).
        # Without this, one physical press can fire toggle twice (start->stop),
        # which looks like "need to press 2 times".
        self._last_toggle_time = 0.0
        self._toggle_debounce_s = 0.6
        # Tracks whether the current recording was started by holding the
        # push-to-talk key. PTT release only stops a PTT-owned session, so
        # releasing PTT can never kill a toggle-started dictation.
        self._ptt_owner = False
        # Voice Activity Detection state (auto-stop on silence).
        self._vad = None
        self._vad_active = False
        self._last_audio_level = 0.0
        # Which post-dictation pass is in flight ("rewriting"/"translating").
        self._post_pass_kind = "rewriting"

        # Continuous background focus tracker: always remembers target application
        self.focus_poll_timer = QTimer()
        self.focus_poll_timer.timeout.connect(self._track_foreground_window)
        self.focus_poll_timer.start(100)

        # Initialize UI Components
        saved_x = config.get("hud_x")
        saved_y = config.get("hud_y")
        self.hud = FloatingHUD(initial_x=saved_x, initial_y=saved_y)
        self.hud.update_language_badge(config.get("language_mode", "bn_primary"))

        self.tray = SelfWhisperTray()
        self.tray.show()
        # Point users at the tray Exit entry (also visible in the hidden-icons overflow).
        self.tray.show_running_notice()

        self.settings_dialog: Optional[SettingsDialog] = None

        # Initialize Audio Capture
        dev_idx = config.get("input_device_index")
        self.audio_engine = AudioCaptureEngine(
            sample_rate=config.get("sample_rate", 16000),
            chunk_ms=config.get("chunk_duration_ms", 100),
            device_index=dev_idx,
            level_callback=self._on_audio_level,
        )

        # Initialize Text Injector
        injector.set_mode(config.get("injection_mode", "typewriter"))

        # Initialize Hotkey Manager
        # NOTE: callbacks only emit thread-safe Qt signals. The actual
        # start/stop/toggle logic always runs on the GUI thread.
        self.hotkey_mgr = GlobalHotkeyManager(
            toggle_hotkey=config.get("hotkey_toggle", "<ctrl>+<shift>+<space>"),
            push_to_talk_key=config.get("hotkey_push_to_talk", "<f8>"),
            mode=config.get("hotkey_mode", "toggle"),
            on_toggle_callback=lambda: self.signals.toggle_requested.emit(),
            on_push_start_callback=lambda: self.signals.push_start_requested.emit(),
            on_push_stop_callback=lambda: self.signals.push_stop_requested.emit(),
        )

        self._connect_signals()
        self.hotkey_mgr.start()

        # Respect Auto-Hide setting on launch
        if config.get("auto_hide_hud", False):
            self.hud.hide()
        else:
            self.hud.show()

    def _track_foreground_window(self):
        """Continuously records the active window so typing always reaches the right app."""
        try:
            import ctypes
            fg = ctypes.windll.user32.GetForegroundWindow()
            if not fg:
                return
            hud_hwnd = int(self.hud.winId()) if self.hud else 0
            settings_hwnd = int(self.settings_dialog.winId()) if (self.settings_dialog and self.settings_dialog.isVisible()) else 0
            if fg != hud_hwnd and fg != settings_hwnd:
                self.last_external_hwnd = fg
        except Exception:
            pass

    def _connect_signals(self):
        # Bridge signals to UI slots. Connected EXACTLY ONCE here.
        # (Previously HUD/tray connections lived inside _on_preview_updated,
        # so every transcript delta added another connection -> N clicks fired
        # N times. Even N = net no-op, which made the mouse button look dead.)
        self.signals.status_changed.connect(self.hud.set_status)
        self.signals.audio_level_updated.connect(self.hud.update_audio_level)
        self.signals.preview_updated.connect(self._on_preview_updated)
        self.signals.inject_requested.connect(self._handle_injection)
        self.signals.request_settings.connect(self.open_settings)
        # Hotkey marshalling: listener thread -> GUI thread.
        # Both shortcuts are always active: toggle chord flips state,
        # PTT key records while held (and only stops its own session).
        self.signals.toggle_requested.connect(self.toggle_recording)
        self.signals.push_start_requested.connect(self._on_push_start)
        self.signals.push_stop_requested.connect(self._on_push_stop)
        self.signals.auto_stop_requested.connect(self._on_vad_stop)
        self.signals.rewrite_ready.connect(self._finish_rewrite_injection)

        # HUD button events (connect once)
        try:
            self.hud.toggle_clicked.disconnect()
        except Exception:
            pass
        try:
            self.hud.settings_clicked.disconnect()
        except Exception:
            pass
        try:
            self.hud.language_cycle_clicked.disconnect()
        except Exception:
            pass
        try:
            self.hud.language_picked.disconnect()
        except Exception:
            pass
        # Explicit picker menu (no blind cycling: the mode only changes when
        # the user ticks an entry, a tray item, or the Settings combo).
        self.hud.language_picked.connect(self._set_language)
        self.hud.toggle_clicked.connect(self.toggle_recording)
        self.hud.settings_clicked.connect(self.open_settings)

        # Tray actions (connect once)
        try:
            self.tray.toggle_requested.disconnect()
        except Exception:
            pass
        try:
            self.tray.toggle_hud_requested.disconnect()
        except Exception:
            pass
        try:
            self.tray.settings_requested.disconnect()
        except Exception:
            pass
        try:
            self.tray.language_changed.disconnect()
        except Exception:
            pass
        try:
            self.tray.exit_requested.disconnect()
        except Exception:
            pass
        self.tray.toggle_requested.connect(self.toggle_recording)
        self.tray.toggle_hud_requested.connect(self._toggle_hud_visibility)
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.language_changed.connect(self._set_language)
        self.tray.exit_requested.connect(self.exit_app)
        try:
            self.tray.messageClicked.connect(self._on_tray_message_clicked)
        except Exception:
            pass
        self._tray_msg_opens_settings = False

    def _on_preview_updated(self, text: str):
        """Updates HUD and types live in the active application's textbox as you speak."""
        self.hud.set_preview_text(text)
        if self.is_recording:
            injector.stream_update(text, target_hwnd=self.target_hwnd)

    def _on_audio_level(self, level: float):
        # Runs on the audio thread: only store + re-emit (both thread-safe).
        try:
            self._last_audio_level = float(level)
        except Exception:
            pass
        self.signals.audio_level_updated.emit(level)

    def _toggle_hud_visibility(self):
        if self.hud.isVisible():
            self.hud.hide()
        else:
            self.hud.show()

    def _on_secondary_launch(self):
        """Another launch attempt: come forward instead of duplicating."""
        try:
            self.hud.show()
            self.hud.raise_()
            self.hud.activateWindow()
        except Exception:
            pass
        try:
            self.tray.showMessage(
                "Self-Whisper is already running",
                "There can only be one copy — this window was brought forward.",
            )
        except Exception:
            pass
        log("Second launch blocked: primary instance brought forward.")

    @staticmethod
    def _post_translate_target(lang_mode: str = None) -> Optional[str]:
        """Target when the Rewrite model translates post-dictation, else None."""
        mode = lang_mode if lang_mode is not None else config.get("language_mode", "bn_primary")
        return resolve_translate_target(config.get("translator_enabled", False), mode)

    def _set_language(self, lang_mode: str):
        config.set("language_mode", lang_mode, auto_save=True)
        self.hud.update_language_badge(lang_mode)
        # Session config (prompt + language hints) is fixed at setup and the
        # docs forbid changing it mid-connection — so reconnect immediately.
        # Otherwise the switch would silently keep transcribing with the stale
        # language until the next app restart. Safe mid-recording: the stream
        # worker keeps running into the fresh session; buffered PCM is kept
        # for the fallback path.
        try:
            if self.active_session is not None:
                self.active_session.stop()
                self.active_session = None
                self._ensure_live_session()
        except Exception:
            pass
        mode_names = {
            "bn_primary": "Bangla (Primary) + English",
            "bn_only": "Bangla Only",
            "en_only": "English Only",
            "auto": "Auto Detect",
        }
        self.hud.set_status("idle", f"Language: {mode_names.get(lang_mode, lang_mode)}")

    def toggle_recording(self):
        """Toggles between listening and transcribing (debounced, GUI thread only)."""
        now = time.monotonic()
        if now - self._last_toggle_time < self._toggle_debounce_s:
            return
        self._last_toggle_time = now
        # Manual toggle takes over: a pending PTT hold no longer owns the session.
        self._ptt_owner = False
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def _on_push_start(self):
        """Hold-to-talk pressed: start only if idle, and claim ownership."""
        if self.is_recording:
            self._ptt_owner = False
            return
        self._ptt_owner = True
        self.start_recording(use_vad=False)  # holding the key IS the stop signal

    def _on_push_stop(self):
        """Hold-to-talk released: stop only the PTT-owned session."""
        owned = self._ptt_owner
        self._ptt_owner = False
        if owned and self.is_recording:
            self.stop_recording()

    def _on_vad_stop(self):
        """Auto-stop fired after silence (GUI thread, idempotent)."""
        self._vad_active = False
        if self.is_recording:
            log("Auto-stop: silence detected, finalizing.")
            self.stop_recording()

    def start_recording(self, use_vad: bool = True):
        """Initiates microphone capture and real-time streaming."""
        if self.is_recording:
            return

        api_key = self._get_api_key()
        if not api_key:
            if config.get("sound_effects_enabled", True):
                play_error_sound()
            self.signals.status_changed.emit("error", "API Key Missing! Set in Settings.")
            self.signals.request_settings.emit()
            return

        # Start audio recording first
        started = self.audio_engine.start()
        if not started:
            if config.get("sound_effects_enabled", True):
                play_error_sound()
            self.signals.status_changed.emit("error", "Microphone access error! Check Settings.")
            self.tray.set_recording_state(False)
            return

        self.is_recording = True
        self.accumulated_pcm = bytearray()
        self._stop_stream_flag = False
        self._last_audio_level = 0.0

        # Arm voice-activity auto-stop if enabled in Settings (toggle mode only).
        self._vad = None
        self._vad_active = False
        if use_vad and config.get("vad_enabled", False):
            try:
                self._vad = SilenceDetector(
                    threshold=float(config.get("vad_threshold", 0.08)),
                    silence_ms=int(config.get("vad_silence_ms", 1800)),
                )
                self._vad_active = True
            except Exception as e:
                print(f"[SelfWhisper] VAD init failed ({e}); continuing without auto-stop.")

        # Capture current active foreground window so text is injected into it
        try:
            import ctypes
            fg = ctypes.windll.user32.GetForegroundWindow()
            hud_hwnd = int(self.hud.winId()) if self.hud else 0
            settings_hwnd = int(self.settings_dialog.winId()) if (self.settings_dialog and self.settings_dialog.isVisible()) else 0
            if fg and fg != hud_hwnd and fg != settings_hwnd:
                self.target_hwnd = fg
            elif self.last_external_hwnd and ctypes.windll.user32.IsWindow(self.last_external_hwnd):
                self.target_hwnd = self.last_external_hwnd

            if self.target_hwnd:
                print(f"[SelfWhisper] Target window captured: {hex(self.target_hwnd)}")
        except Exception:
            pass

        # Prepare live stream session in injector for real-time in-place typing
        self._turn_finalized = False
        injector.start_live_session(target_hwnd=self.target_hwnd)

        # Visual feedback: update HUD and ensure it's visible on screen
        self.hud.show()
        self.signals.status_changed.emit("listening", "Listening... Speak now")
        self.tray.set_recording_state(True)

        # Audio chime feedback: instant audible cue that recording has started
        if config.get("sound_effects_enabled", True):
            play_start_sound()

        # Ensure Live WebSocket session is connected
        self._ensure_live_session()

        # Start background streaming worker
        self.stream_thread = threading.Thread(target=self._stream_pipeline, daemon=True)
        self.stream_thread.start()

    def _ensure_live_session(self):
        """Maintains persistent WebSocket session with Gemini Live."""
        api_key = self._get_api_key()
        model = config.get("model", "gemini-3.5-transcribe-live")
        fallback_model = config.get("fallback_model", "gemini-2.0-flash")
        corr_level = config.get("correction_level", "high")
        lang_mode = config.get("language_mode", "bn_primary")

        if self.active_session is None or not self.active_session._is_connected:
            self.active_session = GeminiLiveSession(
                api_key=api_key,
                model=model,
                fallback_model=fallback_model,
                correction_level=corr_level,
                language_mode=lang_mode,
                on_text_delta=lambda t: self.signals.preview_updated.emit(t),
                on_turn_complete=lambda t: self.signals.inject_requested.emit(t),
                on_status_change=lambda s: print(f"[GeminiLive Status] {s}"),
            )
            self.active_session.start()
        else:
            try:
                self.active_session.set_language_mode(lang_mode)
            except Exception:
                pass
            self.active_session.reset_transcript()

    def _stream_pipeline(self):
        """Pulls chunks from audio engine, streams over WebSocket to Gemini Live."""
        while not self._stop_stream_flag and self.is_recording:
            chunk = self.audio_engine.get_chunk(timeout=0.08)
            if chunk:
                self.accumulated_pcm.extend(chunk)
                if self.active_session:
                    self.active_session.send_pcm_chunk(chunk)
            # Voice-activity auto-stop (checked every loop, ~12x/sec).
            if self._vad_active and self._vad is not None and self.is_recording:
                try:
                    if self._vad.update(self._last_audio_level):
                        self._vad_active = False  # one-shot
                        self.signals.auto_stop_requested.emit()
                        return
                except Exception:
                    pass

    def stop_recording(self):
        """Stops recording, signals turnComplete over WebSocket and triggers single clean injection."""
        if not self.is_recording:
            return

        self.is_recording = False
        self._stop_stream_flag = True
        self._vad_active = False

        self.signals.status_changed.emit("transcribing", "Finalizing...")
        self.tray.set_recording_state(False)

        # Stop audio hardware
        self.audio_engine.stop()

        # Signal turn complete to Gemini Live over WebSocket
        if self.active_session:
            self.active_session.finish_turn()

        # In worker thread, wait for WebSocket response or execute fallback
        threading.Thread(target=self._finalize_transcription, daemon=True).start()

    def _finalize_transcription(self):
        # Wait up to ~4 seconds for Gemini Live WebSocket to deliver transcript.
        # The old 1.5s timeout fired too early on slow networks, forcing an
        # unnecessary REST fallback (which has different language behavior).
        # Poll for a stable, non-empty transcript instead of a fixed short wait.
        last_text = ""
        stable_count = 0
        for _ in range(80):  # 80 x 0.05s = 4.0s
            if self._turn_finalized:
                return
            current = ""
            if self.active_session:
                try:
                    current = (self.active_session._current_transcript or "").strip()
                except Exception:
                    current = ""
            if current:
                if current == last_text:
                    stable_count += 1
                else:
                    stable_count = 0
                    last_text = current
                # Emit once text looks stable (same across ~300ms) or after 1.2s
                # of having *some* text, so we don't cut off long utterances.
                # The turnComplete callback path sets _turn_finalized and returns
                # early; this path covers servers that never send turnComplete.
                if stable_count >= 6:
                    text = current
                    self.signals.inject_requested.emit(text)
                    return
            time.sleep(0.05)

        # One last check: if we have any text at all, use it.
        if self._turn_finalized:
            return
        try:
            tail = (self.active_session._current_transcript.strip()
                    if self.active_session else "")
        except Exception:
            tail = ""
        if tail:
            self.signals.inject_requested.emit(tail)
            return

        if not self.accumulated_pcm:
            self.signals.inject_requested.emit("")
            return

        # If WebSocket didn't return text after 4s, run REST fallback with gemini-2.0-flash
        print("[SelfWhisper] WebSocket timed out; using Gemini fallback engine...")
        api_key = self._get_api_key()
        corr_level = config.get("correction_level", "high")
        lang_mode = config.get("language_mode", "bn_primary")

        try:
            result_text = GeminiTranscribeFallback.transcribe_audio_clip(
                pcm_bytes=bytes(self.accumulated_pcm),
                api_key=api_key,
                model="gemini-2.0-flash",
                correction_level=corr_level,
                language_mode=lang_mode,
            )
            if not self._turn_finalized:
                if result_text:
                    self.signals.inject_requested.emit(result_text)
                else:
                    self.signals.inject_requested.emit("")
                    self.signals.status_changed.emit("idle", "No speech detected.")
        except Exception as e:
            print(f"[SelfWhisper] Transcribe error: {e}")
            if config.get("sound_effects_enabled", True):
                play_error_sound()
            self.signals.status_changed.emit("error", "Transcription failed!")
            if not self._turn_finalized:
                self.signals.inject_requested.emit("")

    def _handle_injection(self, text: str):
        """Called on Qt thread to finalize live dictation in the active application. Guaranteed single execution."""
        if self._turn_finalized:
            return
        self._turn_finalized = True

        clean_text = text.strip()
        if not clean_text:
            injector.finalize_live_session(None, target_hwnd=self.target_hwnd)
            self.signals.status_changed.emit("idle", "")
            if config.get("auto_hide_hud", False):
                QTimer.singleShot(250, self.hud.hide)
            return

        # Optional post-dictation pass over the WHOLE finalized phrase.
        # Translator (Rewrite-model engine) takes precedence: it translates
        # into the selected specific language, which already fixes language
        # issues. Otherwise the plain rewrite pass runs when enabled.
        # Runs off the GUI thread; the actual injection happens in
        # _finish_rewrite_injection once the result arrives.
        post_target = self._post_translate_target()
        if post_target is not None:
            self._post_pass_kind = "translating"
            self.signals.status_changed.emit("transcribing", "Translating...")
            threading.Thread(
                target=self._run_post_pass, args=(clean_text, post_target), daemon=True
            ).start()
            return
        if config.get("rewrite_enabled", False):
            self._post_pass_kind = "rewriting"
            self.signals.status_changed.emit("transcribing", "Rewriting...")
            threading.Thread(
                target=self._run_post_pass, args=(clean_text, None), daemon=True
            ).start()
            return

        self._inject_final_text(clean_text)

    def _run_post_pass(self, original: str, target: Optional[str]):
        """Background worker: translate or rewrite the full phrase, then hand back to Qt."""
        api_key = self._get_api_key()
        lang_mode = config.get("language_mode", "bn_primary")
        corr_level = config.get("correction_level", "high")
        model = config.get("rewrite_model", "gemini-3.5-flash-lite") or "gemini-3.5-flash-lite"
        try:
            if target is not None:
                result = GeminiRewrite.translate_text(
                    text=original,
                    api_key=api_key,
                    model=model,
                    target=target,
                    correction_level=corr_level,
                )
            else:
                result = GeminiRewrite.rewrite_text(
                    text=original,
                    api_key=api_key,
                    model=model,
                    language_mode=lang_mode,
                    correction_level=corr_level,
                )
        except Exception as e:
            print(f"[SelfWhisper] Post-pass error: {e}")
            result = ""
        self.signals.rewrite_ready.emit(result or "", original)

    def _finish_rewrite_injection(self, rewritten: str, original: str):
        """Qt-thread slot: inject the post-pass phrase (or original on failure)."""
        final = rewritten.strip() if rewritten and rewritten.strip() else original
        kind = getattr(self, "_post_pass_kind", "rewriting")
        if rewritten and rewritten.strip() and rewritten.strip() != original:
            print(f"[SelfWhisper] {kind.capitalize()} applied to finalized phrase.")
        self._inject_final_text(final)

    def _inject_final_text(self, clean_text: str):
        """Logs, announces, and types the finalized phrase into the target app."""
        try:
            print(f"[SelfWhisper] Finalizing live dictation: {clean_text}")
        except UnicodeEncodeError:
            print(f"[SelfWhisper] Finalizing live dictation (Unicode len={len(clean_text)})")
        log_dictation(clean_text)
        self.hud.set_status("done", clean_text)

        # Single subtle sound cue
        if config.get("sound_effects_enabled", True):
            play_stop_sound()

        # Finalize live dictation in-place:
        # types final diff/punctuation, appends space, saves clipboard backup, resets for next turn
        injector.finalize_live_session(clean_text, target_hwnd=self.target_hwnd)

        # If Auto-Hide HUD enabled, hide floating bar after brief visual feedback
        if config.get("auto_hide_hud", False):
            QTimer.singleShot(450, self.hud.hide)

    def open_settings(self):
        """Opens the settings dialog, restoring it if already open/minimized."""
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self._raise_settings()
            return
        self.settings_dialog = SettingsDialog()
        self.settings_dialog.settings_saved.connect(self._on_settings_saved)
        self.settings_dialog.hud_reset_requested.connect(self.hud.position_bottom_right)
        self.settings_dialog.quit_requested.connect(self.exit_app)
        self.settings_dialog.show()
        self._raise_settings()

    def _raise_settings(self):
        """Brings the settings window to the front, un-minimizing if needed.

        Settings is usually opened from a hotkey/tray click while another app
        owns the foreground, and Windows actively blocks background apps from
        stealing focus — without countermeasures the dialog ends up minimized
        or hidden behind everything with no visible trace.
        """
        dlg = self.settings_dialog
        if dlg is None:
            return
        log("Opening Settings window...")
        # 1) Qt-level restore + raise (twice: immediately and after the
        #    foreground lock has had a chance to clear).
        for _ in range(2):
            try:
                st = dlg.windowState()
                st &= ~Qt.WindowState.WindowMinimized
                st |= Qt.WindowState.WindowActive
                dlg.setWindowState(st)
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
            except Exception:
                pass
        # 2) Win32-level restore + foreground assist.
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = int(dlg.winId())
            user32.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL: restore + activate
            fg = user32.GetForegroundWindow()
            if fg and fg != hwnd:
                cur = kernel32.GetCurrentThreadId()
                try:
                    fg_thread = user32.GetWindowThreadProcessId(fg, None)
                except Exception:
                    fg_thread = 0
                if fg_thread:
                    user32.AttachThreadInput(cur, fg_thread, True)
                    user32.SetForegroundWindow(hwnd)
                    user32.AttachThreadInput(cur, fg_thread, False)
                else:
                    user32.SetForegroundWindow(hwnd)
            dlg.activateWindow()
        except Exception as e:
            print(f"[SelfWhisper] Foreground assist failed: {e}")
        # 3) Delayed second attempt (foreground lock often eats the first).
        try:
            QTimer.singleShot(150, self._reresise_settings)
        except Exception:
            pass
        # 4) If it STILL is not the active window, make it findable: flash
        #    the taskbar button and post a tray balloon that raises it.
        try:
            QTimer.singleShot(700, self._ensure_settings_visible)
        except Exception:
            pass

    def _reresise_settings(self):
        try:
            dlg = self.settings_dialog
            if dlg is not None and dlg.isVisible():
                dlg.raise_()
                dlg.activateWindow()
        except Exception:
            pass

    def _ensure_settings_visible(self):
        """Last resort: flash taskbar + balloon so the window can't hide."""
        try:
            dlg = self.settings_dialog
            if dlg is None or not dlg.isVisible():
                return
            import ctypes
            user32 = ctypes.windll.user32
            if user32.GetForegroundWindow() == int(dlg.winId()):
                return  # success, nothing to do
            # Flash the taskbar button until it gets focus.
            try:
                class FLASHWINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_uint),
                                ("hwnd", ctypes.c_void_p),
                                ("dwFlags", ctypes.c_uint),
                                ("uCount", ctypes.c_uint),
                                ("dwTimeout", ctypes.c_uint)]
                info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), int(dlg.winId()), 3, 5, 0)
                user32.FlashWindowEx(ctypes.byref(info))
            except Exception:
                pass
            self._tray_msg_opens_settings = True
            self.tray.showMessage(
                "Settings is open",
                "Click here to bring the Settings window forward.",
            )
            log("Settings opened in background; posted tray balloon to find it.")
        except Exception:
            pass

    def _on_tray_message_clicked(self):
        try:
            if getattr(self, "_tray_msg_opens_settings", False):
                self._tray_msg_opens_settings = False
                self._raise_settings()
        except Exception:
            pass

    def _on_settings_saved(self):
        """Reloads settings into active components."""
        # Update text injector mode
        injector.set_mode(config.get("injection_mode", "typewriter"))

        # Update audio device
        dev_idx = config.get("input_device_index")
        self.audio_engine.set_device_index(dev_idx)

        # Update hotkeys (both shortcuts are always active; no mode switch)
        self.hotkey_mgr.update_keys(
            config.get("hotkey_toggle", "<ctrl>+<shift>+<space>"),
            config.get("hotkey_push_to_talk", "<f8>"),
        )

        # Reset live session so new API key or model takes effect
        if self.active_session:
            self.active_session.stop()
            self.active_session = None

        # Update language badge
        self.hud.update_language_badge(config.get("language_mode", "bn_primary"))

        # Check Auto-Hide state
        if config.get("auto_hide_hud", False):
            if not self.is_recording:
                self.hud.hide()
        else:
            self.hud.show()

        self.hud.set_status("idle", "Settings updated!")

    def exit_app(self):
        """Clean shutdown of background threads and app."""
        # Save HUD coordinates
        pos = self.hud.pos()
        config.set("hud_x", pos.x(), auto_save=False)
        config.set("hud_y", pos.y(), auto_save=True)

        self.hotkey_mgr.stop()
        self.audio_engine.stop()
        if self.active_session:
            self.active_session.stop()

        self.hud.close()
        self.qapp.quit()


def main():
    # Capture all logs/prints into the in-app Logs tab so the app can run
    # without a console window (see run.bat -> pythonw).
    install_log_store()

    # Enable High DPI scaling
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running in system tray
    app.setApplicationName("Self-Whisper")

    # Single instance: a second launch just nudges the running app and quits.
    instance_guard = SingleInstanceGuard()
    if not instance_guard.try_acquire():
        sys.exit(0)

    try:
        from self_whisper.core.version import __version__ as _app_version
    except Exception:
        _app_version = ""
    log(f"Self-Whisper v{_app_version} starting..." if _app_version else "Self-Whisper starting...")
    whisper_app = SelfWhisperApp(app)
    instance_guard.show_requested.connect(whisper_app._on_secondary_launch)
    log("Self-Whisper ready. Press Ctrl+Shift+Space or hold F8 to dictate.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
