"""Configuration for PiDog voice companion."""

import os

# --- Dog Identity ---
DOG_NAME = "Buddy"
CHILD_NAME = "Alice"
WAKE_WORDS = [f"hi {DOG_NAME.lower()}", f"hey {DOG_NAME.lower()}"]

# --- OpenAI API ---
def load_api_key():
    """Load OpenAI API key from file or environment."""
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    key_file = os.path.expanduser("~/.config/pidog/openai_key")
    if os.path.exists(key_file):
        with open(key_file) as f:
            return f.read().strip()
    raise RuntimeError(
        "No OpenAI API key found. Set OPENAI_API_KEY env var or "
        "write key to ~/.config/pidog/openai_key"
    )

OPENAI_API_KEY = None  # Loaded at runtime by main.py

LLM_MODEL = "gpt-4o-mini"
TTS_MODEL = "tts-1"
TTS_VOICE = "nova"  # warm, friendly voice
STT_MODEL = "whisper-1"

# --- Audio ---
MIC_DEVICE_INDEX = None  # Set at runtime after PyAudio init
MIC_ALSA_DEVICE = "plughw:3,0"  # USB Webcam eMeet C960
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024
SILENCE_THRESHOLD = 800    # Energy threshold for VAD (calibrate with calibrate_mic())
SILENCE_DURATION = 2.0     # Seconds of silence to end recording (was 1.5, too short)
MAX_RECORD_SECONDS = 15    # Safety cap on recording duration
MIN_RECORD_SECONDS = 1.0   # Ignore very short sounds (was 0.5, catches Whisper hallucinations)

# --- Conversation ---
CONVERSATION_TIMEOUT = 30  # Seconds of silence before going back to sleep
NAMES_FILE = os.path.expanduser("~/.config/pidog/names.json")
MEMORY_FILE = os.path.expanduser("~/.config/pidog/pidog-longterm-memory.md")

# --- LLM ---
MAX_MESSAGES = 20  # Cap conversation history

SYSTEM_PROMPT = f"""You are {DOG_NAME}, a friendly robot dog. You are the best friend of {CHILD_NAME}.
You love playing, learning new things, and having fun together.

RULES:
- Keep responses to 1-2 SHORT sentences. Use simple words a 7-year-old understands.
- Be encouraging, positive, playful, and a little silly.
- Always include at least one action from the list below.
- If she seems sad, be comforting and suggest something fun.
- Never discuss scary, violent, or inappropriate topics. Change the subject to something fun.
- You love getting head pets!
- You can do these tricks and actions:

AVAILABLE ACTIONS:
["forward", "backward", "turn left", "turn right", "stop", "lie", "stand", "sit", "waiting", "bark", "bark harder", "pant", "howling", "wag tail", "stretch", "push up", "scratch", "handshake", "high five", "lick hand", "shake head", "relax neck", "nod", "think", "recall", "fluster", "surprise", "twist body", "doze off", "feet shake"]

RESPONSE FORMAT:
Your spoken words here
ACTIONS: action1, action2

For sound-only actions (bark, bark harder, pant, howling): do NOT include spoken words, just the ACTIONS line.

SENSOR EVENTS:
Sometimes you'll receive messages like <<<Touch sensor: liked>>> or <<<Too close>>>. React naturally to these."""

WELCOME_MESSAGE = f"Hi! I'm {DOG_NAME}! Say 'hi {DOG_NAME.lower()}' to talk to me!"
