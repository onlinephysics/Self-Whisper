"""
Self-Whisper Gemini Live Client
Manages real-time bidirectional streaming over WebSockets to Google AI Studio Live API
(supporting gemini-3.5-transcribe-live, gemini-2.0-flash, and REST fallback).
Enforces Bangla-first multilingual transcription, auto-correction, and intelligent punctuation.
"""

import asyncio
import base64
import json
import threading
import time
import urllib.request
import urllib.error
import wave
import io
from typing import Callable, Optional, Union

# Language-specific instruction blocks. The critical fix for "Hindi leak":
# Bengali and Hindi phonetics overlap, so without an explicit negative
# constraint the model often emits Devanagari for Bangla speech (especially on
# short/noisy clips). Every mode below therefore FORBIDS Devanagari.
LANGUAGE_INSTRUCTIONS = {
    "bn_primary": (
        "LANGUAGE & SCRIPT RULES (Bangla primary + English):\n"
        "1. Primary language is Bangla (বাংলা), with frequent English code-switching ('Banglish').\n"
        "2. Transcribe Bangla speech ONLY in Bengali script (Unicode U+0980–U+09FF, বাংলা লিপি).\n"
        "3. Transcribe English speech and common loanwords (e.g. WhatsApp, Discord, Meeting, Office, Link, File) ONLY in Latin letters (A-Z).\n"
        "4. Seamlessly blend Bangla and English in mixed sentences (e.g. 'আমি কালকে Discord এ কথা বলব।').\n"
        "5. CRITICAL — NEVER output Hindi. NEVER output Devanagari script (Unicode U+0900–U+097F, e.g. ह म न क र आ ई उ ए ओ). "
        "Bengali and Hindi sound similar: when in doubt, ALWAYS choose Bengali script, never Devanagari. "
        "If the audio is ambiguous, prefer Bangla. NEVER transliterate Bangla words into Devanagari.\n"
        "6. NEVER output Urdu/Arabic script either. Allowed scripts: Bengali + Latin ONLY."
    ),
    "bn_only": (
        "LANGUAGE & SCRIPT RULES (Bangla ONLY):\n"
        "1. Output ONLY Bangla in Bengali script (Unicode U+0980–U+09FF, বাংলা লিপি).\n"
        "2. Transliterate any English loanwords into Bengali phonetics (e.g. 'Discord' -> 'ডিসকর্ড').\n"
        "3. CRITICAL — NEVER output Hindi. NEVER output Devanagari script (U+0900–U+097F). "
        "Bengali and Hindi sound similar: when in doubt, ALWAYS choose Bengali script. "
        "NEVER output Latin/English sentences and NEVER output Urdu/Arabic script."
    ),
    "en_only": (
        "LANGUAGE & SCRIPT RULES (English ONLY):\n"
        "1. Output ONLY English in Latin letters (A-Z, a-z).\n"
        "2. If the speaker uses a Bangla word, write its English transliteration/translation in Latin letters.\n"
        "3. CRITICAL — NEVER output Bengali script (U+0980–U+09FF) and NEVER output Hindi/Devanagari script (U+0900–U+097F). "
        "Latin script ONLY."
    ),
    "auto": (
        "LANGUAGE & SCRIPT RULES (Auto-detect Bangla vs English):\n"
        "1. Detect the spoken language per utterance: Bangla -> Bengali script (U+0980–U+09FF), English -> Latin letters.\n"
        "2. For mixed Bangla+English sentences, blend scripts word-by-word like 'আমি কালকে Discord এ কথা বলব।'.\n"
        "3. CRITICAL — NEVER output Hindi. NEVER output Devanagari script (U+0900–U+097F). "
        "Bengali and Hindi sound similar: when in doubt between Bengali and Hindi, ALWAYS choose Bengali. "
        "Allowed scripts: Bengali + Latin ONLY. NEVER Urdu/Arabic script."
    ),
}

CORRECTION_INSTRUCTIONS = {
    "high": (
        "AUTO-CORRECTION & FORMATTING:\n"
        "1. Fix minor speech stutters, false starts, and filler sounds (uh, um, মানে, ইত্যাদি).\n"
        "2. Fix minor grammatical slips while preserving the speaker's true intent.\n"
        "3. Apply natural punctuation: Bangla daari '।' for Bengali sentences, periods '.' for English sentences, and commas or question marks '?' where appropriate."
    ),
    "normal": (
        "AUTO-CORRECTION & FORMATTING:\n"
        "Transcribe in Bangla (বাংলা) and English per the language rules above. "
        "Apply correct punctuation (Bangla '।', English periods, commas, and question marks). "
        "Light cleanup only; do not rephrase."
    ),
    "verbatim": (
        "AUTO-CORRECTION & FORMATTING:\n"
        "Transcribe every spoken word exactly as uttered, following the language/script rules above. "
        "Do not alter words, do not rephrase, do not add punctuation beyond what was spoken."
    ),
}

STRICT_OUTPUT_SUFFIX = (
    "STRICT OUTPUT CONSTRAINT:\n"
    "Output ONLY the finalized transcribed text. Never add assistant chatter, conversational replies, or markdown blocks."
)


def build_system_prompt(language_mode: str = "bn_primary", correction_level: str = "high") -> str:
    """Combines language/script rules (incl. anti-Hindi) with correction rules."""
    lang_block = LANGUAGE_INSTRUCTIONS.get(language_mode, LANGUAGE_INSTRUCTIONS["bn_primary"])
    corr_block = CORRECTION_INSTRUCTIONS.get(correction_level, CORRECTION_INSTRUCTIONS["high"])
    return (
        "You are an ultra-precise, real-time speech-to-text dictation engine for Windows.\n"
        "Your task is to transcribe spoken audio directly into written text for apps like WhatsApp, Discord, Messenger, and Microsoft Office.\n\n"
        f"{lang_block}\n\n{corr_block}\n\n{STRICT_OUTPUT_SUFFIX}"
    )


def contains_devanagari(text: str) -> bool:
    """True if text contains any Devanagari codepoint (U+0900–U+097F). Used for leak warnings."""
    for ch in text or "":
        if '\u0900' <= ch <= '\u097f':
            return True
    return False


# Back-compat: old code imported SYSTEM_INSTRUCTIONS["high"|"normal"|"verbatim"].
# Keep the same keys working, now built with the default bn_primary language block.
SYSTEM_INSTRUCTIONS = {
    "high": build_system_prompt("bn_primary", "high"),
    "normal": build_system_prompt("bn_primary", "normal"),
    "verbatim": build_system_prompt("bn_primary", "verbatim"),
}


class GeminiLiveSession:
    """
    Manages persistent Live WebSocket session with Google AI Studio.
    Streams 16kHz PCM audio via realtimeInput, sends turnComplete via clientContent,
    and captures real-time transcript deltas (interimInputTranscription, inputTranscription, modelTurn).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-transcribe-live",
        fallback_model: str = "gemini-2.0-flash",
        correction_level: str = "high",
        language_mode: str = "bn_primary",
        on_text_delta: Optional[Callable[[str], None]] = None,
        on_turn_complete: Optional[Callable[[str], None]] = None,
        on_status_change: Optional[Callable[[str], None]] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.fallback_model = fallback_model
        self.correction_level = correction_level
        self.language_mode = language_mode or "bn_primary"
        self.on_text_delta = on_text_delta
        self.on_turn_complete = on_turn_complete
        self.on_status_change = on_status_change

        self.ws = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._is_running = False
        self._is_connected = False
        self._current_transcript = ""
        self.committed_text = ""
        self.interim_text = ""
        self._send_queue: Optional[asyncio.Queue[Union[bytes, dict, None]]] = None
        # Chunks arriving before the WebSocket is ready were previously DROPPED,
        # truncating the start of every utterance (short clips mis-detect as
        # Hindi). Buffer them and flush in order once the send loop starts.
        self._pending_chunks: list = []
        self._pending_lock = threading.Lock()

    def _get_model_name(self, model: str) -> str:
        if not model.startswith("models/"):
            return f"models/{model}"
        return model

    def _get_system_prompt(self) -> str:
        return build_system_prompt(self.language_mode, self.correction_level)

    def set_language_mode(self, language_mode: str):
        """Updates language live (takes effect on next turn; no reconnect needed)."""
        if language_mode in LANGUAGE_INSTRUCTIONS:
            self.language_mode = language_mode

    def set_correction_level(self, correction_level: str):
        if correction_level in CORRECTION_INSTRUCTIONS:
            self.correction_level = correction_level

    def start(self):
        """Starts the asynchronous WebSocket loop in a background thread."""
        if self._is_running:
            return
        self._is_running = True
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()

    def _run_event_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._send_queue = asyncio.Queue()
        try:
            self.loop.run_until_complete(self._connect_and_stream())
        except Exception as e:
            print(f"[GeminiLive] Event loop ended: {e}")
        finally:
            self._is_running = False
            self._is_connected = False

    async def _connect_and_stream(self):
        import websockets

        target_model = self.model
        url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={self.api_key}"

        if self.on_status_change:
            self.on_status_change("connecting")

        try:
            async with websockets.connect(url, max_size=10 * 1024 * 1024) as ws:
                self.ws = ws
                self._is_connected = True
                print(f"[GeminiLive] WebSocket connected for model: {target_model}")
                if self.on_status_change:
                    self.on_status_change("ready")

                # Step 1: Send setup handshake
                setup_msg = {
                    "setup": {
                        "model": self._get_model_name(target_model),
                        "generationConfig": {
                            "responseModalities": ["TEXT"],
                            "temperature": 0.1,
                        },
                        "systemInstruction": {
                            "parts": [
                                {
                                    "text": self._get_system_prompt()
                                }
                            ]
                        },
                    }
                }
                await ws.send(json.dumps(setup_msg))

                # Step 2: Concurrently receive messages and send audio/control messages
                receive_task = asyncio.create_task(self._receive_loop(ws))
                send_task = asyncio.create_task(self._send_loop(ws))

                done, pending = await asyncio.wait(
                    [receive_task, send_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

        except Exception as e:
            print(f"[GeminiLive] Connection error: {e}")
            if self.on_status_change:
                self.on_status_change("error")
        finally:
            self._is_connected = False
            self.ws = None

    async def _receive_loop(self, ws):
        """Processes real-time server messages and handles all Gemini Live formats."""
        try:
            async for message in ws:
                data = json.loads(message)

                # 1. Setup response
                if "setupComplete" in data:
                    print("[GeminiLive] Setup completed by server.")
                    continue

                server_content = data.get("serverContent", {})

                # 2. Interim Real-Time Transcription (gemini-3.5-transcribe-live)
                interim = server_content.get("interimInputTranscription")
                if interim and "text" in interim:
                    txt = interim["text"]
                    if txt:
                        self.interim_text = txt
                        full = (self.committed_text + " " + txt).strip() if self.committed_text else txt
                        self._current_transcript = full
                        if self.on_text_delta:
                            self.on_text_delta(full)

                # 3. Final Input Transcription (gemini-3.5-transcribe-live)
                final_inp = server_content.get("inputTranscription")
                if final_inp and "text" in final_inp:
                    txt = final_inp["text"].strip()
                    if txt:
                        if self.committed_text:
                            self.committed_text = self.committed_text.rstrip() + " " + txt
                        else:
                            self.committed_text = txt
                        self.interim_text = ""
                        self._current_transcript = self.committed_text
                        if self.on_text_delta:
                            self.on_text_delta(self.committed_text)

                # 4. Model Turn (gemini-2.0-flash / conversational live model)
                model_turn = server_content.get("modelTurn")
                if model_turn:
                    parts = model_turn.get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            self._current_transcript += text
                            if self.on_text_delta:
                                self.on_text_delta(self._current_transcript)

                # 5. Turn Complete notification
                if server_content.get("turnComplete"):
                    final_text = self._current_transcript.strip()
                    print(f"[GeminiLive] Turn complete received with text: {final_text}")
                    if contains_devanagari(final_text):
                        print("[GeminiLive] WARNING: transcript contains Devanagari "
                              f"(mode={self.language_mode}); prompt forbids Hindi.")
                    if final_text and self.on_turn_complete:
                        self.on_turn_complete(final_text)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[GeminiLive] Receive loop error: {e}")

    async def _send_loop(self, ws):
        """Pulls audio chunks or control messages from queue and sends to WebSocket."""
        # Flush anything buffered while connecting, in original order.
        try:
            with self._pending_lock:
                pending = list(self._pending_chunks)
                self._pending_chunks.clear()
            for chunk in pending:
                b64_audio = base64.b64encode(chunk).decode("utf-8")
                media_msg = {
                    "realtimeInput": {
                        "mediaChunks": [
                            {
                                "mimeType": "audio/pcm;rate=16000",
                                "data": b64_audio,
                            }
                        ]
                    }
                }
                await ws.send(json.dumps(media_msg))
            if pending:
                print(f"[GeminiLive] Flushed {len(pending)} buffered audio chunk(s).")
        except Exception as e:
            print(f"[GeminiLive] Flush error: {e}")
        try:
            while self._is_running:
                item = await self._send_queue.get()
                if item is None:
                    break

                if isinstance(item, bytes):
                    # Audio chunk -> realtimeInput
                    b64_audio = base64.b64encode(item).decode("utf-8")
                    media_msg = {
                        "realtimeInput": {
                            "mediaChunks": [
                                {
                                    "mimeType": "audio/pcm;rate=16000",
                                    "data": b64_audio,
                                }
                            ]
                        }
                    }
                    await ws.send(json.dumps(media_msg))

                elif isinstance(item, dict):
                    # Control message (e.g. clientContent: turnComplete)
                    await ws.send(json.dumps(item))

                self._send_queue.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[GeminiLive] Send loop error: {e}")

    def send_pcm_chunk(self, chunk: bytes):
        """Thread-safe submission of a PCM chunk (buffers if socket not ready yet)."""
        if not chunk or not self._is_running:
            return
        try:
            if self.loop and self._send_queue:
                self.loop.call_soon_threadsafe(self._send_queue.put_nowait, chunk)
                return
        except Exception:
            pass
        # Event loop / queue not ready yet (connecting) -> buffer, don't drop.
        try:
            with self._pending_lock:
                if len(self._pending_chunks) < 200:  # ~20s cap
                    self._pending_chunks.append(chunk)
        except Exception:
            pass

    def finish_turn(self):
        """
        Signals the model that speech is finished so it finalizes transcription.
        Sends clientContent with turnComplete: true.
        """
        finish_msg = {
            "clientContent": {
                "turns": [{"role": "user", "parts": []}],
                "turnComplete": True,
            }
        }
        if self.loop and self._send_queue and self._is_running:
            self.loop.call_soon_threadsafe(self._send_queue.put_nowait, finish_msg)

    def reset_transcript(self):
        self._current_transcript = ""
        self.committed_text = ""
        self.interim_text = ""

    def stop(self):
        """Gracefully closes the WebSocket session."""
        self._is_running = False
        if self.loop and self._send_queue:
            self.loop.call_soon_threadsafe(self._send_queue.put_nowait, None)


class GeminiTranscribeFallback:
    """
    High-reliability REST fallback client.
    Note: If model is gemini-3.5-transcribe-live, it automatically routes to gemini-2.0-flash
    because transcribe-live is an exclusive WebSocket (BidiGenerateContent) model.
    """

    @staticmethod
    def transcribe_audio_clip(
        pcm_bytes: bytes,
        api_key: str,
        model: str = "gemini-2.0-flash",
        sample_rate: int = 16000,
        correction_level: str = "high",
        language_mode: str = "bn_primary",
    ) -> str:
        if not pcm_bytes:
            return ""

        # Ensure we use a model that supports REST generateContent
        clean_model = model.replace("models/", "").strip()
        if "transcribe-live" in clean_model:
            clean_model = "gemini-2.0-flash"

        # Build WAV in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        wav_data = wav_buffer.getvalue()

        b64_wav = base64.b64encode(wav_data).decode("utf-8")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={api_key}"

        prompt = build_system_prompt(language_mode, correction_level)

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt + "\n\nTranscribe the following spoken audio accurately:"},
                        {
                            "inlineData": {
                                "mimeType": "audio/wav",
                                "data": b64_wav,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                res_json = json.loads(response.read().decode("utf-8"))
                candidates = res_json.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        text = parts[0].get("text", "").strip()
                        if contains_devanagari(text):
                            print("[GeminiFallback] WARNING: fallback output contains "
                                  f"Devanagari (mode={language_mode}); prompt forbids Hindi.")
                        return text
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            print(f"[GeminiFallback] HTTP Error: {e.code} - {err_msg}")
        except Exception as e:
            print(f"[GeminiFallback] Request Error: {e}")

        return ""
