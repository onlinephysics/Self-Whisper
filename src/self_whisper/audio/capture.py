"""
Self-Whisper Audio Capture Engine
Captures real-time audio from microphone using sounddevice.RawInputStream (pure CFFI, zero numpy dependency).
Produces 16kHz 16-bit mono linear PCM chunks for Gemini Live streaming.
Computes real-time RMS audio levels to drive the animated HUD visualizer.
Supports live volume test metering for the Settings dialog.
"""

import math
import queue
import struct
import threading
from typing import Callable, List, Optional, Tuple


class AudioCaptureEngine:
    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_ms: int = 100,
        device_index: Optional[int] = None,
        level_callback: Optional[Callable[[float], None]] = None,
    ):
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.chunk_size = int(self.sample_rate * (self.chunk_ms / 1000.0))
        self.device_index = device_index
        self.level_callback = level_callback

        self.audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._is_recording = False
        self._stream = None
        self._lock = threading.Lock()
        self._current_level = 0.0

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def current_level(self) -> float:
        """Normalized 0.0 to 1.0 audio level for UI visualizer."""
        return self._current_level

    def set_device_index(self, device_index: Optional[int]):
        was_recording = self._is_recording
        if was_recording:
            self.stop()
        self.device_index = device_index
        if was_recording:
            self.start()

    def set_level_callback(self, callback: Optional[Callable[[float], None]]):
        self.level_callback = callback

    def _audio_callback(self, indata, frames, time_info, status):
        """sounddevice RawInputStream callback (called in audio thread)."""
        if not self._is_recording:
            return

        # indata is a CFFI buffer for RawInputStream. Convert to pure bytes.
        raw_pcm_bytes = bytes(indata)

        # Compute RMS volume level (normalized 0.0 to 1.0) using built-in struct/math
        try:
            count = len(raw_pcm_bytes) // 2
            if count > 0:
                shorts = struct.unpack(f"<{count}h", raw_pcm_bytes)
                sum_sq = sum(s * s for s in shorts)
                rms = math.sqrt(sum_sq / count)
                # RMS for 16-bit max is 32767. Normalize with dynamic curve
                level = min(1.0, max(0.0, float(rms) / 4000.0))
                # Apply smoothing
                self._current_level = (self._current_level * 0.3) + (level * 0.7)
                if self.level_callback:
                    self.level_callback(self._current_level)
        except Exception:
            pass

        # Push PCM bytes into queue
        try:
            self.audio_queue.put_nowait(raw_pcm_bytes)
        except queue.Full:
            # Drop oldest to prevent latency lag
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                pass
            self.audio_queue.put_nowait(raw_pcm_bytes)

    def start(self) -> bool:
        """Starts capturing audio stream using RawInputStream."""
        import sounddevice as sd

        with self._lock:
            if self._is_recording:
                return True

            # Clear any leftover queue data
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break

            self._current_level = 0.0

            try:
                # Use RawInputStream to bypass any numpy wrapper or dependency issues
                self._stream = sd.RawInputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=self.chunk_size,
                    device=self.device_index,
                    callback=self._audio_callback,
                )
                self._stream.start()
                self._is_recording = True
                dev_desc = self.device_index if self.device_index is not None else "Default"
                print(f"[AudioCaptureEngine] Started recording (Device: {dev_desc}, Rate: {self.sample_rate}Hz)")
                return True
            except Exception as e:
                print(f"[AudioCaptureEngine] Error starting stream: {e}")
                self._is_recording = False
                self._stream = None
                return False

    def stop(self):
        """Stops capturing audio stream."""
        with self._lock:
            if not self._is_recording:
                return

            self._is_recording = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as e:
                    print(f"[AudioCaptureEngine] Error stopping stream: {e}")
                self._stream = None

            self._current_level = 0.0
            if self.level_callback:
                self.level_callback(0.0)
            print("[AudioCaptureEngine] Stopped recording.")

    def get_chunk(self, timeout: float = 0.2) -> Optional[bytes]:
        """Retrieves next 16kHz PCM audio chunk from the queue."""
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None


def list_input_devices() -> List[Tuple[int, str]]:
    """Returns list of (device_index, device_name) for all available microphones."""
    devices = []
    try:
        import sounddevice as sd
        all_devs = sd.query_devices()
        for idx, dev in enumerate(all_devs):
            if dev.get("max_input_channels", 0) > 0:
                name = dev.get("name", f"Device {idx}")
                devices.append((idx, name))
    except Exception as e:
        print(f"[AudioCaptureEngine] Error querying audio devices: {e}")
    return devices
