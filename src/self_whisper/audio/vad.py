"""
Self-Whisper Voice Activity Detection (auto-stop on silence).

Pure logic, no audio dependencies: feed it the normalized 0.0-1.0 microphone
level (same scale as AudioCaptureEngine.current_level) and it tells you when
the user has gone silent long enough to end the dictation automatically.

Rules (all tunable via Settings / config):
- Nothing happens during the first `min_total_ms` (lets the user breathe
  after pressing the hotkey).
- Silence only counts AFTER at least `min_speech_ms` of real speech, so
  pressing the hotkey and saying nothing never auto-stops instantly.
- One-shot: once triggered it latches until reset().
"""

import time


class SilenceDetector:
    def __init__(
        self,
        threshold: float = 0.08,
        silence_ms: int = 1800,
        min_speech_ms: int = 700,
        min_total_ms: int = 2000,
    ):
        self.threshold = threshold
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self.min_total_ms = min_total_ms
        self.reset()

    def reset(self, now: float = None):
        now = time.monotonic() if now is None else now
        self._start = now
        self._last = now
        self._speech_ms = 0.0
        self._silent_since = now
        self._fired = False

    def update(self, level: float, now: float = None) -> bool:
        """Returns True exactly once when end-of-speech is detected."""
        now = time.monotonic() if now is None else now
        if self._fired:
            return False
        dt_ms = max(0.0, (now - self._last) * 1000.0)
        self._last = now

        try:
            level = float(level)
        except Exception:
            level = 0.0

        if level >= self.threshold:
            self._speech_ms += dt_ms
            self._silent_since = now
            return False

        # Silent right now.
        if (now - self._start) * 1000.0 < self.min_total_ms:
            return False
        if self._speech_ms < self.min_speech_ms:
            return False
        if (now - self._silent_since) * 1000.0 >= self.silence_ms:
            self._fired = True
            return True
        return False
