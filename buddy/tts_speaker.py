"""Text-to-speech using OpenAI TTS API with pico2wave fallback."""

import os
import subprocess
import tempfile
from openai import OpenAI

from . import config

# ALSA device for audio output. Use HDMI until I2S speaker is enabled.
# After i2samp.sh + reboot, change to "plughw:2,0" or "default"
APLAY_DEVICE = "plughw:0,0"


class TTSSpeaker:
    """Speaks text aloud. Primary: OpenAI TTS API. Fallback: pico2wave."""

    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key)
        self._use_openai = True

    def speak(self, text):
        """Speak text aloud. Blocks until finished."""
        if not text or not text.strip():
            return

        # Sanitize for safety
        text = text.strip()

        if self._use_openai:
            try:
                self._speak_openai(text)
                return
            except Exception as e:
                print(f"OpenAI TTS failed ({e}), falling back to pico2wave")
                self._use_openai = False

        self._speak_pico2wave(text)

    def _speak_openai(self, text):
        """Speak using OpenAI TTS API — natural, warm voice."""
        response = self.client.audio.speech.create(
            model=config.TTS_MODEL,
            voice=config.TTS_VOICE,
            input=text,
            response_format="wav",
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
            for chunk in response.iter_bytes():
                f.write(chunk)

        try:
            subprocess.run(
                ["aplay", "-q", "-D", APLAY_DEVICE, tmp_path],
                check=True,
                timeout=30,
            )
        finally:
            os.unlink(tmp_path)

    def _speak_pico2wave(self, text):
        """Speak using pico2wave — offline fallback."""
        # Sanitize text for shell safety
        safe_text = text.replace('"', "'").replace('`', "'").replace('$', "")
        safe_text = safe_text[:500]  # Cap length

        tmp_path = "/tmp/buddy_tts.wav"
        try:
            subprocess.run(
                ["pico2wave", "-l", "en-US", "-w", tmp_path, safe_text],
                check=True,
                timeout=10,
            )
            subprocess.run(
                ["aplay", "-q", "-D", APLAY_DEVICE, tmp_path],
                check=True,
                timeout=30,
            )
        except Exception as e:
            print(f"pico2wave TTS failed: {e}")
