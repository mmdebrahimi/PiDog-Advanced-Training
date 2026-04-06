"""Microphone recording with energy-based voice activity detection."""

import pyaudio
import struct
import math
import io
import wave
from time import time

from . import config


class AudioCapture:
    """Records audio from microphone, returns WAV bytes when speech ends."""

    def __init__(self, device_index=None, on_voice_start=None, on_voice_end=None):
        self.sample_rate = config.SAMPLE_RATE
        self.channels = config.CHANNELS
        self.chunk_size = config.CHUNK_SIZE
        self.silence_threshold = config.SILENCE_THRESHOLD
        self.silence_duration = config.SILENCE_DURATION
        self.max_seconds = config.MAX_RECORD_SECONDS
        self.min_seconds = config.MIN_RECORD_SECONDS

        # Callbacks for UI feedback
        self.on_voice_start = on_voice_start
        self.on_voice_end = on_voice_end

        self._pa = pyaudio.PyAudio()
        self.device_index = device_index or self._find_usb_mic()

    def _find_usb_mic(self):
        """Find the USB microphone's PyAudio device index."""
        for i in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0 and "USB" in info.get("name", ""):
                print(f"Found mic: index {i} — {info['name']}")
                return i
        # Fallback to default
        print("No USB mic found, using default input")
        return None

    def _get_energy(self, data):
        """Calculate RMS energy of audio chunk."""
        count = len(data) // 2
        shorts = struct.unpack(f"{count}h", data)
        sum_sq = sum(s * s for s in shorts)
        return math.sqrt(sum_sq / count) if count > 0 else 0

    def _to_wav_bytes(self, frames):
        """Convert raw audio frames to WAV format bytes."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"".join(frames))
        return buf.getvalue()

    def calibrate(self, seconds=3):
        """Record ambient noise and set threshold to 3x the floor energy."""
        print(f"Calibrating mic for {seconds}s — stay quiet...")
        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk_size,
        )

        energies = []
        chunks = int(self.sample_rate / self.chunk_size * seconds)
        for _ in range(chunks):
            data = stream.read(self.chunk_size, exception_on_overflow=False)
            energies.append(self._get_energy(data))

        stream.stop_stream()
        stream.close()

        ambient = sum(energies) / len(energies) if energies else 300
        self.silence_threshold = max(int(ambient * 3), 300)
        print(f"Ambient energy: {ambient:.0f}, threshold set to: {self.silence_threshold}")
        return self.silence_threshold

    def record_utterance(self):
        """Block until voice is detected, record until silence, return WAV bytes.

        Returns None if no speech detected within max_seconds.
        """
        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk_size,
        )

        frames = []
        recording = False
        silence_start = None
        record_start = None

        try:
            while True:
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                energy = self._get_energy(data)

                if not recording:
                    if energy > self.silence_threshold:
                        # Voice detected — start recording
                        recording = True
                        record_start = time()
                        silence_start = None
                        frames = [data]
                        if self.on_voice_start:
                            self.on_voice_start()
                else:
                    frames.append(data)
                    duration = time() - record_start

                    if energy < self.silence_threshold:
                        if silence_start is None:
                            silence_start = time()
                        elif time() - silence_start >= self.silence_duration:
                            # Silence long enough — end recording
                            if duration >= self.min_seconds:
                                if self.on_voice_end:
                                    self.on_voice_end()
                                return self._to_wav_bytes(frames)
                            else:
                                # Too short, probably noise — reset
                                recording = False
                                frames = []
                    else:
                        silence_start = None

                    if duration >= self.max_seconds:
                        if self.on_voice_end:
                            self.on_voice_end()
                        return self._to_wav_bytes(frames)

        finally:
            stream.stop_stream()
            stream.close()

    def close(self):
        self._pa.terminate()
