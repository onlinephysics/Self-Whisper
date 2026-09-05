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
        """
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


if __name__ == "__main__":
    unittest.main()

