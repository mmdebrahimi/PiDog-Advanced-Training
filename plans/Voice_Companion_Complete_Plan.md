# PiDog Voice Companion — Complete Build Plan

> Turn the PiDog into an interactive talking companion for a 7-year-old, with ChatGPT conversation, physical dog behaviors, and long-term memory.

---

## Problem Statement

The user's daughter (Alice, age 7) has always wanted a dog, but the parent is allergic. While RL training runs on the laptop, we built the PiDog into a voice-interactive companion that listens, talks, performs tricks, and remembers things about Alice across sessions.

## Design Decisions

### D1: OpenAI TTS API over pico2wave

**Decision:** Use OpenAI TTS API (`tts-1`, `nova` voice) as primary, pico2wave as offline fallback.

**Rationale:** CEO review identified that a warm, natural voice is critical for a child bonding with the dog. Cost difference is $0.02/day. pico2wave sounds robotic.

### D2: Whisper API for STT

**Decision:** Cloud-based OpenAI Whisper API, not local Whisper.

**Rationale:** Local Whisper takes 10-30s on Pi 4 — unusable for a child. Whisper API returns in 1-2s. Cost: ~$0.015/day.

### D3: Wake word via transcript

**Decision:** Send every VAD-detected utterance to Whisper, check transcript for "hi [dog name]".

**Rationale:** Simplest approach, no extra dependencies. Costs ~$0.02/day extra from false positives. Wake word activates conversation mode — subsequent messages don't need the wake word for 30 seconds.

### D4: ActionFlow for physical behaviors

**Decision:** Reuse SunFounder's ActionFlow (24 pre-built dog behaviors) rather than building custom animations.

**Rationale:** ActionFlow handles posture transitions, sound effects, and multi-joint coordination. No reason to reinvent it.

### D5: Safe mode for desk testing

**Decision:** Default to safe_mode=True — only non-movement actions (nod, wag tail, bark, shake head). No walking/standing/lying that could move the robot off a desk.

**Rationale:** Robot is connected to Pi via wires during development. Full movement enabled by setting safe_mode=False.

### D6: Long-term memory via markdown file

**Decision:** Store facts about Alice in `~/.config/pidog/pidog-longterm-memory.md`. Load into system prompt on startup, update via ChatGPT summarization on shutdown.

**Rationale:** Modeled after LESSONS_LEARNED.md pattern. Simple, human-readable, persists across sessions. One extra ChatGPT call per session (~$0.001).

### D7: Audio routing

**Decision:** USB webcam mic (eMeet C960, PyAudio index 2) for input. HDMI (plughw:0,0) for output until I2S speaker is verified after reboot.

**Rationale:** I2S speaker was enabled in config.txt (googlevoicehat-soundcard overlay) but produced white noise before proper setup. HDMI output confirmed working. I2S will be the final output once verified.

## Implementation — What Was Built

### Module structure: `~/pidog_lab/buddy/`

| File | Purpose | Status |
|------|---------|--------|
| `config.py` | Names, prompts, thresholds, API key, file paths | Done |
| `audio_capture.py` | PyAudio mic recording with energy-based VAD, auto-finds USB mic | Done |
| `stt.py` | OpenAI Whisper API wrapper, wake word detection | Done |
| `tts_speaker.py` | OpenAI TTS API primary, pico2wave fallback, HDMI output | Done |
| `llm_chat.py` | ChatGPT conversation (gpt-4o-mini), history management, get_history() | Done |
| `response_parser.py` | Parses "text\nACTIONS: a1, a2" with case-insensitive regex | Done |
| `dog_behavior.py` | Wraps Pidog + ActionFlow, states (idle/listening/thinking/speaking), safe mode, sensor polling | Done |
| `memory.py` | Long-term memory: load/save/update/inject_into_prompt | Done |
| `main.py` | Entry point: name setup, conversation loop, memory integration, graceful shutdown | Done |

### Key features

- **First-run name setup**: Dog asks "What's your name?" and "What would you like to call me?" — saves to `~/.config/pidog/names.json`
- **Wake word**: "hi [dog name]" activates conversation mode
- **Conversation mode**: After wake word, listens for 30 seconds without needing wake word again
- **Goodbye detection**: "bye", "good night", etc. end conversation gracefully
- **Physical feedback**: Head tilt (listening), head up (thinking), wag tail (speaking), cyan/yellow/pink LED states
- **Touch sensor**: Front-to-rear pet = happy reaction + LLM event, rear-to-front = dislike
- **Long-term memory**: Facts learned about Alice persist in `pidog-longterm-memory.md`, loaded into every session
- **Safe mode**: Desk-safe by default (no walking/standing movements)

### Configuration saved at

- API key: `~/.config/pidog/openai_key`
- Names: `~/.config/pidog/names.json`
- Memory: `~/.config/pidog/pidog-longterm-memory.md`

### CLI options

```bash
python3 -m buddy.main                # Full companion
python3 -m buddy.main --test-tts     # Test TTS only
python3 -m buddy.main --test-stt     # Test STT only
python3 -m buddy.main --calibrate    # Calibrate mic only
python3 -m buddy.main --reset-names  # Re-run name setup
python3 -m buddy.main --skip-calibrate  # Skip mic calibration
```

## Hardware Status

| Component | Status |
|-----------|--------|
| USB webcam mic (eMeet C960) | Working (PyAudio index 2, plughw:3,0) |
| HDMI audio output | Working (plughw:0,0) |
| I2S speaker (Robot HAT) | Enabled in config.txt, needs reboot verification |
| I2S MEMS mic (Robot HAT) | Enabled in config.txt, needs reboot verification |
| OpenAI API key | Saved |
| PiDog servos/sensors | Working (HAT switch must be green) |

## Testing completed

- TTS: "Hi Alice! I'm Buddy! Want to play?" plays through HDMI ✓
- STT: USB mic captures speech, Whisper transcribes correctly ✓
- GPIO: MCU reset works, Pidog initializes ✓
- Safe mode: Only non-movement actions execute ✓

## Remaining verification (not yet tested)

- [ ] Full conversation loop end-to-end
- [ ] Memory persistence across sessions
- [ ] I2S speaker after reboot (replace HDMI output)
- [ ] Daughter's first interaction
- [ ] VAD threshold tuning for child's voice

## Cost estimate

~$0.04/day ($1.20/month) at 30 conversations/day:
- Whisper API: $0.015/day
- GPT-4o-mini: $0.002/day
- OpenAI TTS: $0.02/day
- Memory summarization: $0.001/day
