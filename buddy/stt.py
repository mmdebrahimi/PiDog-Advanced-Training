"""Speech-to-text via OpenAI Whisper API."""

import io
from openai import OpenAI

from . import config


class STT:
    """Transcribes audio bytes to text using OpenAI Whisper."""

    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key)

    # Known Whisper hallucinations on silence/noise
    HALLUCINATIONS = {
        "thanks for watching", "thank you for watching", "subscribe",
        "like and subscribe", "please subscribe", "bye", "you",
        "the end", "thank you", "thanks for listening",
    }

    def transcribe(self, wav_bytes):
        """Transcribe WAV audio bytes to text.

        Returns transcript string, or empty string on failure.
        Filters known Whisper hallucinations on silence.
        """
        try:
            audio_file = io.BytesIO(wav_bytes)
            audio_file.name = "speech.wav"

            response = self.client.audio.transcriptions.create(
                model=config.STT_MODEL,
                file=audio_file,
                language="en",
            )
            transcript = response.text.strip()

            # Filter Whisper hallucinations
            if transcript.lower().rstrip(".!?,") in self.HALLUCINATIONS:
                print(f"Filtered hallucination: {transcript}")
                return ""

            return transcript
        except Exception as e:
            print(f"STT error: {e}")
            return ""

    def contains_wake_word(self, transcript):
        """Check if transcript contains any wake word.

        Uses fuzzy matching — Whisper may transcribe 'Nounou' as
        'Nunu', 'no no', 'new new', etc.
        """
        text_lower = transcript.lower().strip(".,!?")

        # Check exact wake words first
        for wake_word in config.WAKE_WORDS:
            if wake_word in text_lower:
                cleaned = text_lower
                for w in config.WAKE_WORDS:
                    cleaned = cleaned.replace(w, "").strip()
                return True, cleaned if cleaned else transcript

        # Fuzzy: check if starts with "hi"/"hey"/"hello" + something close to the dog name
        dog_name = config.DOG_NAME.lower()
        words = text_lower.replace(",", "").replace("!", "").replace(".", "").split()
        if len(words) >= 2 and words[0] in ("hi", "hey", "hello"):
            second = words[1].strip(".,!?")
            # Known Whisper transcription variants of the dog name
            variants = {dog_name}
            # Add common mishearings: remove vowels, double letters, etc.
            variants.add(dog_name.replace("ou", "u"))  # nounou -> nunu
            variants.add(dog_name.replace("oo", "u"))   # noonoo -> nunu
            variants.add(dog_name.replace("u", "ou"))   # nunu -> nounou
            # Also try first 3 chars match
            for v in list(variants):
                variants.add(v[:3])

            if second in variants or any(second.startswith(v) for v in variants if len(v) >= 3):
                cleaned = " ".join(words[2:]).strip()
                print(f"Wake word matched: '{text_lower}' (heard '{second}' as {dog_name})")
                return True, cleaned if cleaned else transcript

        print(f"No wake word in: '{text_lower}'")
        return False, transcript
