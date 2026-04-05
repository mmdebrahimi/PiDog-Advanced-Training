#!/usr/bin/env python3
"""OpenAI Realtime API voice session for PiDog companion.

Replaces the 3-call pipeline (Whisper + GPT + TTS) with a single WebSocket
for sub-second voice conversation. Handles audio I/O, VAD, function calling.
"""

import asyncio
import base64
import json
import numpy as np
import sounddevice as sd
import threading
from time import sleep

from . import config

SAMPLE_RATE = 24000  # Realtime API uses 24kHz
CHANNELS = 1
CHUNK_DURATION = 0.1  # 100ms chunks
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION)

# Audio device — find PulseAudio dynamically instead of hardcoding index
def _find_pulse_device():
    """Find the PulseAudio device index (handles device reordering across reboots)."""
    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            name = d['name'].lower() if isinstance(d['name'], str) else ''
            if 'pulse' in name and d['max_input_channels'] > 0 and d['max_output_channels'] > 0:
                return i
    except Exception:
        pass
    return None  # Fall back to sounddevice default

_PULSE_DEV = _find_pulse_device()
INPUT_DEVICE = _PULSE_DEV
OUTPUT_DEVICE = _PULSE_DEV

REALTIME_MODEL = "gpt-4o-realtime-preview"

PERFORM_ACTION_TOOL = {
    "type": "function",
    "name": "perform_action",
    "description": "Execute physical actions on the robot dog. Call this with every response to make the dog move.",
    "parameters": {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "items": {"type": "string", "enum": [
                    "forward", "backward", "lie", "stand", "sit",
                    "bark", "bark harder", "pant", "howling", "wag tail",
                    "stretch", "push up", "scratch", "handshake", "high five",
                    "lick hand", "shake head", "relax neck", "nod", "think",
                    "recall", "head down", "fluster", "surprise"
                ]},
                "description": "List of actions for the dog to perform"
            }
        },
        "required": ["actions"]
    }
}

GO_TO_SLEEP_TOOL = {
    "type": "function",
    "name": "go_to_sleep",
    "description": "Call this when the user says goodnight, goodbye, or tells you to go to sleep. You will lie down and hibernate until woken up again.",
    "parameters": {
        "type": "object",
        "properties": {},
    }
}


class RealtimeVoice:
    """Manages a voice conversation via OpenAI Realtime API."""

    def __init__(self, api_key, instructions, voice="nova"):
        self.api_key = api_key
        self.instructions = instructions
        self.voice = voice

        # Callbacks
        self._on_user_transcript = None
        self._on_assistant_transcript = None
        self._on_actions = None
        self._on_speaking_start = None
        self._on_speaking_end = None
        self._on_sleep = None

        # State
        self._speaking = False  # True while model is outputting audio
        self._running = False
        self._conn = None
        self._loop = None
        self._thread = None
        self._transcripts = []  # Full conversation for memory

    def on_user_transcript(self, callback):
        """Register callback for user speech transcripts: callback(text)"""
        self._on_user_transcript = callback

    def on_assistant_transcript(self, callback):
        """Register callback for assistant speech transcripts: callback(text)"""
        self._on_assistant_transcript = callback

    def on_actions(self, callback):
        """Register callback for action requests: callback(list[str])"""
        self._on_actions = callback

    def on_speaking_start(self, callback):
        """Register callback when model starts speaking."""
        self._on_speaking_start = callback

    def on_speaking_end(self, callback):
        """Register callback when model finishes speaking."""
        self._on_speaking_end = callback

    def on_sleep(self, callback):
        """Register callback when model calls go_to_sleep (goodnight)."""
        self._on_sleep = callback

    def start(self):
        """Start the realtime voice session in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_async, daemon=True)
        self._thread.start()
        print("Realtime voice session starting...")

    def stop(self):
        """Stop the voice session."""
        self._running = False
        try:
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
        except RuntimeError:
            pass  # Event loop already closed
        if self._thread:
            self._thread.join(timeout=5)
        print("Realtime voice session stopped.")

    def get_transcripts(self):
        """Return conversation transcripts for memory summarization."""
        return self._transcripts.copy()

    def update_instructions(self, instructions):
        """Update session instructions (e.g., to inject room state)."""
        self.instructions = instructions
        try:
            if self._conn and self._loop and self._loop.is_running():
                import json as _json
                msg = _json.dumps({
                    "type": "session.update",
                    "session": {"instructions": instructions}
                })
                asyncio.run_coroutine_threadsafe(
                    self._conn.send(msg), self._loop
                )
        except RuntimeError:
            pass  # Event loop closed

    def _run_async(self):
        """Run the async event loop in a thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._session())
        except Exception as e:
            print(f"Realtime session error: {e}")
        finally:
            self._loop.close()

    async def _session(self):
        """Main async session: connect, configure, stream audio."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)

        async with client.realtime.connect(model=REALTIME_MODEL) as conn:
            self._conn = conn

            # Configure session using the newer API schema
            await conn.send({
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": self.instructions,
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "transcription": {"model": "whisper-1", "language": "en"},
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.5,
                                "prefix_padding_ms": 300,
                                "silence_duration_ms": 800,
                            },
                        },
                        "output": {
                            "format": {"type": "audio/pcm", "rate": 24000},
                            "voice": self.voice,
                        },
                    },
                    "tools": [PERFORM_ACTION_TOOL, GO_TO_SLEEP_TOOL],
                    "tool_choice": "auto",
                }
            })

            print("Realtime session connected and configured.")

            # Run send and receive concurrently
            await asyncio.gather(
                self._send_audio(conn),
                self._receive_events(conn),
            )

    async def _send_audio(self, conn):
        """Stream microphone audio to the Realtime API."""
        loop = asyncio.get_event_loop()

        def mic_callback(indata, frames, time_info, status):
            if self._speaking:
                return  # Mute mic while model is speaking (echo cancellation)
            pcm_bytes = indata.tobytes()
            b64 = base64.b64encode(pcm_bytes).decode("utf-8")
            asyncio.run_coroutine_threadsafe(
                conn.input_audio_buffer.append(audio=b64), loop
            )

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SAMPLES,
            device=INPUT_DEVICE,
            callback=mic_callback,
        ):
            print(f"Mic streaming (device {INPUT_DEVICE}).")
            while self._running:
                await asyncio.sleep(0.1)

    async def _receive_events(self, conn):
        """Receive and handle events from the Realtime API."""
        audio_out = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            device=OUTPUT_DEVICE,
        )
        audio_out.start()

        current_user_text = ""
        current_assistant_text = ""

        try:
            async for event in conn:
                if not self._running:
                    break

                # --- Audio output (newer API: response.output_audio.delta) ---
                if event.type in ("response.audio.delta", "response.output_audio.delta"):
                    if not self._speaking:
                        self._speaking = True
                        if self._on_speaking_start:
                            self._on_speaking_start()
                    pcm = base64.b64decode(event.delta)
                    audio_data = np.frombuffer(pcm, dtype=np.int16).reshape(-1, 1)
                    audio_out.write(audio_data)

                elif event.type in ("response.audio.done", "response.output_audio.done"):
                    self._speaking = False
                    if self._on_speaking_end:
                        self._on_speaking_end()

                # --- User transcript ---
                elif event.type == "conversation.item.input_audio_transcription.completed":
                    text = getattr(event, 'transcript', '').strip()
                    if text:
                        print(f"User: {text}")
                        self._transcripts.append({"role": "user", "content": text})
                        if self._on_user_transcript:
                            self._on_user_transcript(text)

                # --- User transcript (delta accumulation) ---
                elif event.type == "conversation.item.input_audio_transcription.delta":
                    text = getattr(event, 'delta', '').strip()
                    if text:
                        print(f"User: {text}")
                        self._transcripts.append({"role": "user", "content": text})
                        if self._on_user_transcript:
                            self._on_user_transcript(text)

                # --- Assistant transcript ---
                elif event.type in ("response.audio_transcript.done", "response.output_audio_transcript.done"):
                    text = getattr(event, 'transcript', '').strip()
                    if text:
                        print(f"Buddy: {text}")
                        self._transcripts.append({"role": "assistant", "content": text})
                        if self._on_assistant_transcript:
                            self._on_assistant_transcript(text)

                # --- Function calls ---
                elif event.type == "response.function_call_arguments.done":
                    func_name = getattr(event, 'name', '') or getattr(event, 'function_name', '')

                    # Check which function was called
                    if func_name == "go_to_sleep":
                        print("Going to sleep...")
                        await conn.conversation.item.create(item={
                            "type": "function_call_output",
                            "call_id": event.call_id,
                            "output": json.dumps({"status": "sleeping"})
                        })
                        if self._on_sleep:
                            self._on_sleep()

                    elif func_name == "perform_action":
                        try:
                            args = json.loads(event.arguments)
                            actions = args.get("actions", [])
                            if actions:
                                print(f"Actions: {actions}")
                                if self._on_actions:
                                    self._on_actions(actions)
                        except json.JSONDecodeError:
                            print(f"Bad function args: {event.arguments}")

                        await conn.conversation.item.create(item={
                            "type": "function_call_output",
                            "call_id": event.call_id,
                            "output": json.dumps({"status": "executed"})
                        })
                        await conn.response.create()

                    else:
                        # Unknown function — just acknowledge
                        print(f"Unknown function: {func_name}")
                        await conn.conversation.item.create(item={
                            "type": "function_call_output",
                            "call_id": event.call_id,
                            "output": json.dumps({"status": "unknown"})
                        })

                # --- Errors ---
                elif event.type == "error":
                    print(f"Realtime API error: {event.error}")

        finally:
            audio_out.stop()
            audio_out.close()


if __name__ == "__main__":
    """Standalone test: voice conversation without the dog."""
    import signal
    import sys

    api_key = config.load_api_key()

    instructions = f"""You are {config.DOG_NAME}, a friendly robot dog and best friend of {config.CHILD_NAME}.
Keep responses to 1-2 SHORT sentences. Be playful, silly, and use simple words a 7-year-old understands.
Be encouraging and positive. If she seems sad, comfort her and suggest something fun.
Never discuss scary or inappropriate topics.

CRITICAL: You MUST call the perform_action tool on EVERY response. Do NOT write actions as text.
Do NOT say things like *wag tail* or (performs action). Use the tool instead.

When the user says "goodnight", "go to sleep", "bye", or "goodbye", say a sweet goodnight message
and call the go_to_sleep tool. You will hibernate until woken up again."""

    voice = RealtimeVoice(api_key, instructions, voice="shimmer")

    state = {"sleeping": False}

    def on_actions(actions):
        print(f"  [Would perform: {actions}]")

    def on_sleep():
        state["sleeping"] = True
        print("\n  [Dog is going to sleep... say 'hi buddy' to wake up]\n")

    def on_user(text):
        if state["sleeping"]:
            text_lower = text.lower().strip(".,!?")
            wake_words = ["hi buddy", "hey buddy", "hi nounou", "hey nounou",
                          config.DOG_NAME.lower()]
            if any(w in text_lower for w in wake_words):
                state["sleeping"] = False
                print(f"\n  [Waking up!]\n")

    voice.on_actions(on_actions)
    voice.on_sleep(on_sleep)
    voice.on_user_transcript(on_user)

    print(f"Starting Realtime Voice (say something! 'goodnight' to sleep, 'hi {config.DOG_NAME.lower()}' to wake)...")
    voice.start()

    try:
        while True:
            sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        voice.stop()
        print("Done.")
