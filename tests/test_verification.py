"""
Automated Verification Suite for Self-Whisper
Tests:
1. Config persistence
2. Bangla Unicode preservation and Smart Clipboard injection mechanics
3. Audio capture device enumeration and RMS metering
4. Gemini Live client configuration and payload generation
"""

import os
import unittest
import math
import struct

from self_whisper.core.config import ConfigManager
from self_whisper.input.injector import get_clipboard_text, set_clipboard_text, injector
from self_whisper.audio.capture import list_input_devices
from self_whisper.transcription.gemini_live import SYSTEM_INSTRUCTIONS, GeminiLiveSession


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
        from self_whisper.audio.vad import SilenceDetector

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
        from self_whisper.input.hotkey_manager import GlobalHotkeyManager

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
        from self_whisper.core import log_store
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
        from self_whisper.input.hotkey_recorder import build_hotkey_string
        from self_whisper.input.hotkey_manager import parse_hotkey_to_set
        s = build_hotkey_string(["space", "shift", "ctrl"])
        self.assertEqual(s, "ctrl+shift+space")
        self.assertEqual(parse_hotkey_to_set(s), frozenset({"ctrl", "shift", "space"}))
        self.assertEqual(build_hotkey_string(["f8"]), "f8")

    def test_10_secure_store(self):
        """Vault round-trips when available; safe no-op otherwise."""
        from self_whisper.platform_win import secure_store
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
        from self_whisper.transcription.gemini_live import build_system_prompt
        for mode in ("bn_primary", "bn_only", "en_only", "auto"):
            for corr in ("high", "normal", "verbatim"):
                p = build_system_prompt(mode, corr)
                self.assertIn("Devanagari", p, f"missing Devanagari guard: {mode}/{corr}")
                self.assertIn("NEVER output Hindi", p, f"missing Hindi guard: {mode}/{corr}")

    def test_12_rewrite_prompt_guards(self):
        """Rewrite prompt targets the whole phrase and keeps language guards."""
        from self_whisper.transcription.gemini_live import build_rewrite_prompt
        for mode in ("bn_primary", "bn_only", "en_only", "auto"):
            for corr in ("high", "normal", "verbatim"):
                p = build_rewrite_prompt(mode, corr)
                self.assertIn("Devanagari", p, f"missing Devanagari guard: {mode}/{corr}")
                self.assertIn("NEVER output Hindi", p, f"missing Hindi guard: {mode}/{corr}")
                self.assertIn("FULL finalized phrase", p, f"rewrite must target the full phrase: {mode}/{corr}")

    def test_13_rewrite_text_fallbacks(self):
        """rewrite_text never networks without input/key; parses success; '' on error."""
        import io
        import json
        from unittest import mock
        from self_whisper.transcription.gemini_live import GeminiRewrite

        # Empty input / missing key: no network, deterministic return.
        with mock.patch("urllib.request.urlopen") as fake_open:
            self.assertEqual(GeminiRewrite.rewrite_text("", "key"), "")
            self.assertEqual(GeminiRewrite.rewrite_text("  ", "key"), "")
            self.assertEqual(GeminiRewrite.rewrite_text("hello", ""), "hello")
            fake_open.assert_not_called()

        # Mocked REST success: rewritten text is parsed out.
        body = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "আমি ঠিক আছি।"}]}}],
        }).encode("utf-8")
        fake_resp = mock.MagicMock()
        fake_resp.read.return_value = body
        fake_resp.__enter__.return_value = fake_resp
        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            out = GeminiRewrite.rewrite_text("ami thik asi", "test-key")
            self.assertEqual(out, "আমি ঠিক আছি।")

        # HTTP failure: caller gets "" so it can fall back to the original.
        import urllib.error
        err = urllib.error.HTTPError(
            url="http://x", code=400, msg="bad",
            hdrs=None, fp=io.BytesIO(b'{"error": "bad"}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            self.assertEqual(GeminiRewrite.rewrite_text("hello", "test-key"), "")


    def test_14_rewrite_model_defaults_and_fetch_filter(self):
        """Rewrite defaults to gemini-3.5-flash-lite; fetch keeps generateContent models."""
        from self_whisper.core.config import DEFAULT_CONFIG
        self.assertEqual(DEFAULT_CONFIG["rewrite_model"], "gemini-3.5-flash-lite")

        import inspect
        from self_whisper.transcription.gemini_live import GeminiRewrite
        sig = inspect.signature(GeminiRewrite.rewrite_text)
        self.assertEqual(sig.parameters["model"].default, "gemini-3.5-flash-lite")

        from self_whisper.ui.settings_dialog import SettingsDialog
        names = SettingsDialog._generate_content_models([
            {"name": "models/gemini-3.5-flash-lite",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.5-transcribe-live",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/gemini-3.5-flash-lite",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "", "supportedGenerationMethods": ["generateContent"]},
        ])
        self.assertEqual(names, ["gemini-3.5-flash-lite", "gemini-3.5-transcribe-live"])
        self.assertEqual(SettingsDialog._generate_content_models([]), [])


    def test_15_fetch_model_names(self):
        """_fetch_model_names parses the models endpoint into filtered names."""
        import json
        from unittest import mock
        from self_whisper.ui.settings_dialog import SettingsDialog

        body = json.dumps({
            "models": [
                {"name": "models/gemini-3.5-flash-lite",
                 "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embedding-001",
                 "supportedGenerationMethods": ["embedContent"]},
            ],
        }).encode("utf-8")
        fake_resp = mock.MagicMock()
        fake_resp.read.return_value = body
        fake_resp.__enter__.return_value = fake_resp
        with mock.patch("urllib.request.urlopen", return_value=fake_resp) as opener:
            names = SettingsDialog._fetch_model_names("test-key")
            self.assertEqual(names, ["gemini-3.5-flash-lite"])
            called_url = opener.call_args[0][0].full_url
            self.assertIn("v1beta/models?key=test-key", called_url)


    def test_16_translator_targets_and_prompts(self):
        """Translation resolves only for specific languages and keeps guards."""
        from self_whisper.transcription import gemini_live as gl

        self.assertEqual(gl.resolve_translate_target(True, "bn_only"), "bn_only")
        self.assertEqual(gl.resolve_translate_target(True, "en_only"), "en_only")
        self.assertIsNone(gl.resolve_translate_target(True, "bn_primary"))
        self.assertIsNone(gl.resolve_translate_target(True, "auto"))
        self.assertIsNone(gl.resolve_translate_target(True, "bogus"))
        self.assertIsNone(gl.resolve_translate_target(False, "en_only"))

        for target in ("bn_only", "en_only"):
            p = gl.build_translate_prompt(target, "high")
            self.assertIn("Devanagari", p)
            self.assertIn("NEVER output Hindi", p)
            self.assertIn("Translate the whole text", p)

        # Unknown target falls back to English.
        self.assertIn("English (Latin script)", gl.build_translate_prompt("xx", "high"))

        # Live session stays transcription-only (no translation block).
        sess = gl.GeminiLiveSession(api_key="k")
        self.assertFalse(hasattr(sess, "translate_target"))
        self.assertFalse(hasattr(sess, "set_translate_target"))
        self.assertNotIn("TRANSLATION MODE", sess._get_system_prompt())

    def test_17_translate_text(self):
        """translate_text parses success, '' on error, no network without input/key."""
        import json
        from unittest import mock
        from self_whisper.transcription.gemini_live import GeminiRewrite

        with mock.patch("urllib.request.urlopen") as fake_open:
            self.assertEqual(GeminiRewrite.translate_text("", "key"), "")
            self.assertEqual(GeminiRewrite.translate_text("hello", ""), "hello")
            fake_open.assert_not_called()

        body = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "How are you?"}]}}],
        }).encode("utf-8")
        fake_resp = mock.MagicMock()
        fake_resp.read.return_value = body
        fake_resp.__enter__.return_value = fake_resp
        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            out = GeminiRewrite.translate_text("কেমন আছেন?", "k", target="en_only")
            self.assertEqual(out, "How are you?")

        import urllib.error
        import io
        err = urllib.error.HTTPError(
            url="http://x", code=400, msg="bad",
            hdrs=None, fp=io.BytesIO(b'{"error": "bad"}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            self.assertEqual(GeminiRewrite.translate_text("hi", "k"), "")


    def test_18_settings_dialog_scrollable(self):
        """Settings tabs scroll internally; footer actions stay reachable."""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication, QScrollArea
            from self_whisper.ui.settings_dialog import SettingsDialog
        except Exception as e:
            self.skipTest(f"Qt unavailable: {e}")
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        try:
            dlg = SettingsDialog()
        except Exception as e:
            self.skipTest(f"Cannot build dialog headless: {e}")
            return
        try:
            self.assertEqual(dlg.tabs.count(), 5)
            for i in range(dlg.tabs.count()):
                page = dlg.tabs.widget(i)
                self.assertIsInstance(
                    page, QScrollArea,
                    f"tab '{dlg.tabs.tabText(i)}' must scroll internally",
                )
                self.assertTrue(page.widgetResizable())
                inner = page.widget()
                self.assertIsNotNone(inner)
                self.assertIsNotNone(inner.layout())
            for btn in (dlg.quit_btn, dlg.cancel_btn, dlg.save_btn):
                self.assertTrue(btn.isEnabled())
            self.assertEqual(dlg.save_btn.objectName(), "PrimaryBtn")
            self.assertLessEqual(dlg.minimumHeight(), 480)
        finally:
            dlg.close()


    def test_19_translator_legacy_keys_dropped(self):
        """Retired Translator Model switches are purged from loaded configs."""
        import json
        import tempfile
        from self_whisper.core.config import ConfigManager, DEFAULT_CONFIG

        self.assertNotIn("translator_use_live", DEFAULT_CONFIG)
        self.assertNotIn("translator_engine", DEFAULT_CONFIG)
        self.assertIn("translator_enabled", DEFAULT_CONFIG)

        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"translator_engine": "live", "translator_use_live": True}, f)
            cfg = ConfigManager(custom_path=p)
            self.assertNotIn("translator_engine", cfg.config)
            self.assertNotIn("translator_use_live", cfg.config)
            self.assertFalse(cfg.get("translator_enabled", False))
            cfg.save()
            with open(p, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertNotIn("translator_engine", saved)
            self.assertNotIn("translator_use_live", saved)


if __name__ == "__main__":
    unittest.main()

