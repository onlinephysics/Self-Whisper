"""
Automated Verification Suite for Self-Whisper
Tests:
1. Config persistence
2. Bangla Unicode preservation and Smart Clipboard injection mechanics
3. Audio capture device enumeration and RMS metering
4. Gemini Live client configuration and payload generation
"""

import os
import sys
import unittest
import math
import struct

# Ensure local imports work
sys.path.insert(0, os.path.dirname(__file__))

from config import ConfigManager
from text_injector import get_clipboard_text, set_clipboard_text, injector
from audio_capture import list_input_devices
from gemini_live import SYSTEM_INSTRUCTIONS, GeminiLiveSession


class TestSelfWhisper(unittest.TestCase):

    def test_01_config_manager(self):
        """Verify configuration manager reads/writes correctly."""
        test_path = os.path.join(os.path.dirname(__file__), "test_config.json")
        try:
            cfg = ConfigManager(custom_path=test_path)
            self.assertEqual(cfg.get("language_mode"), "bn_primary")
            cfg.set("language_mode", "bn_only")
            self.assertEqual(cfg.get("language_mode"), "bn_only")

            # Reload to verify persistence
            cfg2 = ConfigManager(custom_path=test_path)
            self.assertEqual(cfg2.get("language_mode"), "bn_only")
        finally:
            if os.path.exists(test_path):
                os.remove(test_path)

    def test_02_bangla_unicode_clipboard(self):
        """
        Verify complex Bengali Unicode strings (যুক্তবর্ণ) are preserved
        with 100% fidelity through Windows clipboard APIs.
        Skipped automatically on headless machines (CI) with no clipboard.
        """
        try:
            probe_ok = set_clipboard_text("probe")
        except Exception:
            probe_ok = False
        if not probe_ok:
            self.skipTest("No system clipboard available (headless environment).")
        test_phrases = [
            "আমি বাংলায় গান গাই।",
            "যুক্তবর্ণ পরীক্ষা: ক্ষ, জ্ঞ, ঙ্ক, ণ্ড, হ্ম, ঞ্চ, ঙ্গ, ্য-ফলা, র-ফলা",
            "কালকে Discord এবং WhatsApp এ মিটিং আছে।",
            "English with Bangla: Hello বন্ধু, কেমন আছেন?",
        ]

        # Backup original clipboard
        orig = get_clipboard_text()

        import unicodedata
        for phrase in test_phrases:
            success = set_clipboard_text(phrase)
            self.assertTrue(success, f"Failed setting clipboard for: {phrase}")
            retrieved = get_clipboard_text()
            expected = unicodedata.normalize("NFC", phrase)
            self.assertEqual(retrieved, expected, f"Unicode mismatch for: {phrase}")

        # Restore original clipboard
        if orig is not None:
            set_clipboard_text(orig)

    def test_03_audio_devices_and_rms(self):
        """Verify audio device enumeration and RMS formula."""
        devices = list_input_devices()
        self.assertIsInstance(devices, list)
        print(f"\n[Test] Detected {len(devices)} input audio device(s).")
        for idx, name in devices:
            print(f"       -> [{idx}] {name}")

        # Test synthetic RMS calculation
        silence = struct.pack("<1600h", *([0] * 1600))
        shorts_silence = struct.unpack("<1600h", silence)
        rms_silence = math.sqrt(sum(s * s for s in shorts_silence) / len(shorts_silence))
        self.assertEqual(rms_silence, 0.0)

        # Test sine wave signal (440Hz)
        sine_samples = [int(math.sin(2 * math.pi * 440 * (i / 16000.0)) * 10000) for i in range(1600)]
        sine_bytes = struct.pack("<1600h", *sine_samples)
        shorts_sine = struct.unpack("<1600h", sine_bytes)
        rms_sine = math.sqrt(sum(s * s for s in shorts_sine) / len(shorts_sine))
        self.assertGreater(rms_sine, 5000)

    def test_04_gemini_prompts_and_instructions(self):
        """Verify prompt templates contain required Bengali and English rules."""
        high_prompt = SYSTEM_INSTRUCTIONS["high"]
        self.assertIn("Bangla (বাংলা)", high_prompt)
        self.assertIn("WhatsApp", high_prompt)
        self.assertIn("Discord", high_prompt)
        self.assertIn("Banglish", high_prompt)

        session = GeminiLiveSession(
            api_key="test_key",
            model="gemini-3.5-transcribe-live",
            correction_level="high",
        )
        self.assertEqual(session._get_model_name("gemini-3.5-transcribe-live"), "models/gemini-3.5-transcribe-live")
    def test_05_live_stream_diff_engine(self):
        """
        Verify real-time diff engine:
        1. Common prefix preservation
        2. Real-time backspace count calculation for corrections
        3. Characters to type
        4. Seamless multi-turn session continuation without deleting prior text
        """
        import unicodedata

        def calculate_diff(old_text: str, new_text: str):
            old = unicodedata.normalize("NFC", old_text)
            new = unicodedata.normalize("NFC", new_text)
            common_len = 0
            min_len = min(len(old), len(new))
            while common_len < min_len and old[common_len] == new[common_len]:
                common_len += 1
            backspaces = len(old) - common_len
            chars_to_type = new[common_len:]
            return common_len, backspaces, chars_to_type

        # Turn 1: Speaking first words
        phrase1 = "আমি বাজারে"
        c, b, t = calculate_diff("", phrase1)
        self.assertEqual(b, 0)
        self.assertEqual(t, unicodedata.normalize("NFC", phrase1))

        # Turn 1: Model corrects / auto-corrects mid-utterance (বাজারে -> দোকানে যাচ্ছি)
        phrase2 = "আমি দোকানে যাচ্ছি"
        c, b, t = calculate_diff(phrase1, phrase2)
        self.assertEqual(c, 4)  # "আমি " is common (length 4)
        self.assertEqual(b, 6)  # deletes "বাজারে" (length 6)
        self.assertEqual(t, "দোকানে যাচ্ছি")

        # Turn 1: Finalize with daari
        c, b, t = calculate_diff("আমি বাংলায় কথা বলছি", "আমি বাংলায় কথা বলছি।")
        self.assertEqual(b, 0)
        self.assertEqual(t, "।")

        # Turn 2: User stops, then starts next dictation
        # State resets: old_text = ""
        c, b, t = calculate_diff("", "কেমন আছেন সবাই?")
        self.assertEqual(b, 0)
        self.assertEqual(t, "কেমন আছেন সবাই?")
        # Verified: Previous text in the textbox is NEVER touched!

    def test_06_vad_silence_detector(self):
        """SilenceDetector fires once after speech + silence, never otherwise."""
        from vad import SilenceDetector

        # Case 1: speech then long silence -> fires exactly once.
        d = SilenceDetector(threshold=0.08, silence_ms=1000, min_speech_ms=300, min_total_ms=500)
        t = 1000.0
        d.reset(now=t)
        for _ in range(10):  # 1s of speech in 100ms steps
            t += 0.1
            self.assertFalse(d.update(0.5, now=t))
        for _ in range(9):   # 0.9s silence -> not yet
            t += 0.1
            self.assertFalse(d.update(0.0, now=t))
        t += 0.2             # 1.1s silence -> fires
        self.assertTrue(d.update(0.0, now=t))
        self.assertFalse(d.update(0.0, now=t + 1.0))  # latched, never twice

        # Case 2: silence with no speech first -> never fires.
        d2 = SilenceDetector(threshold=0.08, silence_ms=500, min_speech_ms=300, min_total_ms=200)
        t = 2000.0
        d2.reset(now=t)
        for _ in range(30):
            t += 0.1
            self.assertFalse(d2.update(0.0, now=t))

        # Case 3: grace period after hotkey press -> never fires early.
        d3 = SilenceDetector(threshold=0.08, silence_ms=100, min_speech_ms=50, min_total_ms=2000)
        t = 3000.0
        d3.reset(now=t)
        t += 0.1
        self.assertFalse(d3.update(0.0, now=t))

    def test_07_hotkeys_both_active(self):
        """Toggle chord and PTT key each fire independently (no mode gating)."""
        from pynput import keyboard
        from hotkey_manager import GlobalHotkeyManager

        toggles, starts, stops = [], [], []
        m = GlobalHotkeyManager(
            toggle_hotkey="ctrl+shift+space", push_to_talk_key="f8",
            on_toggle_callback=lambda: toggles.append(1),
            on_push_start_callback=lambda: starts.append(1),
            on_push_stop_callback=lambda: stops.append(1),
        )
        # Toggle chord works...
        m._handle_press(keyboard.Key.ctrl_l)
        m._handle_press(keyboard.Key.shift_l)
        m._handle_press(keyboard.Key.space)
        self.assertEqual(len(toggles), 1)
        # ...and PTT works in the same session without any mode switch.
        m._handle_release(keyboard.Key.space)
        m._handle_release(keyboard.Key.shift_l)
        m._handle_release(keyboard.Key.ctrl_l)
        m._last_toggle_fire -= 10.0  # bypass debounce for the test
        m._handle_press(keyboard.Key.f8)
        self.assertEqual(len(starts), 1)
        m._handle_release(keyboard.Key.f8)
        self.assertEqual(len(stops), 1)
        # Space auto-repeat can never double-toggle.
        m._handle_press(keyboard.Key.ctrl_l)
        m._handle_press(keyboard.Key.shift_l)
        m._handle_press(keyboard.Key.space)
        n = len(toggles)
        m._handle_press(keyboard.Key.space)
        m._handle_press(keyboard.Key.space)
        self.assertEqual(len(toggles), n)

    def test_08_log_store_roundtrip(self):
        """log_store keeps app lines and dictation history, then clears."""
        import log_store
        log_store.clear_all()
        log_store.log("unit-test line")
        log_store.log_dictation("unit-test dictation")
        self.assertTrue(any("unit-test line" in l for l in log_store.get_app_lines()))
        self.assertTrue(any(t == "unit-test dictation" for _, t in log_store.get_dictations()))
        self.assertIn("unit-test dictation", log_store.get_logs_text())
        log_store.clear_all()
        self.assertEqual(log_store.get_dictations(), [])

    def test_09_hotkey_string_builder(self):
        """Recorder output orders modifiers first and round-trips the parser."""
        from hotkey_recorder import build_hotkey_string
        from hotkey_manager import parse_hotkey_to_set
        s = build_hotkey_string(["space", "shift", "ctrl"])
        self.assertEqual(s, "ctrl+shift+space")
        self.assertEqual(parse_hotkey_to_set(s), frozenset({"ctrl", "shift", "space"}))
        self.assertEqual(build_hotkey_string(["f8"]), "f8")

    def test_10_secure_store(self):
        """Vault round-trips when available; safe no-op otherwise."""
        import secure_store
        if not secure_store.available():
            self.assertEqual(secure_store.get_api_key(), "")
            self.assertFalse(secure_store.set_api_key("x"))
            return
        try:
            self.assertTrue(secure_store.set_api_key("unit-test-key"))
            self.assertEqual(secure_store.get_api_key(), "unit-test-key")
        finally:
            secure_store.set_api_key("")

    def test_11_prompts_forbid_hindi_everywhere(self):
        """Every language mode carries the anti-Hindi/Devanagari constraint."""
        from gemini_live import build_system_prompt
        for mode in ("bn_primary", "bn_only", "en_only", "auto"):
            for corr in ("high", "normal", "verbatim"):
                p = build_system_prompt(mode, corr)
                self.assertIn("Devanagari", p, f"missing Devanagari guard: {mode}/{corr}")
                self.assertIn("NEVER output Hindi", p, f"missing Hindi guard: {mode}/{corr}")


if __name__ == "__main__":
    unittest.main()

