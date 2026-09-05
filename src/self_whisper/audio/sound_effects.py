"""
Self-Whisper Sound Effects
Plays pleasant, soft, non-blocking audio chimes for recording start, stop, and completion.
Uses in-memory synthesized smooth sine waves with fade envelopes played via Windows sound APIs.
Strictly debounced to prevent any overlapping or scary repetitive beeps.
"""

import io
import math
import struct
import sys
import threading
import time
import wave

_last_sound_time = 0.0
_sound_lock = threading.Lock()


def _synthesize_soft_chime(freq: float, duration_ms: int = 50, volume: float = 0.15) -> bytes:
    """Generates an in-memory mono 16-bit PCM WAV with a smooth bell/cosine envelope."""
    sample_rate = 22050
    n_samples = max(1, int(sample_rate * duration_ms / 1000))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        samples = []
        for i in range(n_samples):
            # Smooth bell curve envelope to eliminate any clicks or harshness
            env = math.sin(math.pi * i / n_samples)
            t = i / sample_rate
            val = int(volume * 32767 * env * math.sin(2 * math.pi * freq * t))
            samples.append(max(-32767, min(32767, val)))
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


# Pre-render audio buffers once at module load
_START_WAV = _synthesize_soft_chime(620, duration_ms=55, volume=0.14)
_STOP_WAV = _synthesize_soft_chime(460, duration_ms=50, volume=0.12)
_SUCCESS_WAV = _synthesize_soft_chime(680, duration_ms=45, volume=0.10)
_ERROR_WAV = _synthesize_soft_chime(320, duration_ms=90, volume=0.15)


def _play_wav_buffer(wav_bytes: bytes, min_interval_s: float = 0.35):
    """Plays audio buffer in background thread with debounce guard."""
    global _last_sound_time
    now = time.time()
    with _sound_lock:
        if now - _last_sound_time < min_interval_s:
            return  # Suppress rapid duplicate sound
        _last_sound_time = now

    def _worker():
        try:
            if sys.platform == "win32":
                import winsound
                winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


def play_start_sound():
    """Soft, pleasant warm cue when recording begins."""
    _play_wav_buffer(_START_WAV, min_interval_s=0.3)


def play_stop_sound():
    """Single soft, subtle cue when recording stops."""
    _play_wav_buffer(_STOP_WAV, min_interval_s=0.3)


def play_success_sound():
    """Gentle subtle cue when text completes."""
    _play_wav_buffer(_SUCCESS_WAV, min_interval_s=0.3)


def play_error_sound():
    """Gentle low advisory cue on error."""
    _play_wav_buffer(_ERROR_WAV, min_interval_s=0.3)
