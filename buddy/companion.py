#!/usr/bin/env python3
"""PiDog Full Companion — voice + physical actions + sleep/wake cycle.

Usage:
    python3 -m buddy.companion              # Safe mode (desk safe)
    python3 -m buddy.companion --no-safe    # Full movement (dog on floor)
"""

import argparse
import os
import signal
import subprocess
import time
from time import sleep

from . import config
from .realtime_voice import RealtimeVoice
from .dog_behavior import DogBehavior
from .face_follower import FaceFollower
from .room_awareness import RoomState
from .spatial_memory import SpatialMemory
from .memory_compiler import MemoryCompiler
from .personality import PersonalityState
from .social_graph import SocialGraph
from .behavior_engine import BehaviorEngine
from .semantic_memory import SemanticMemory
from .episodic_memory import EpisodicMemory
from . import memory


def run_companion(safe_mode=True, show_video=False):
    api_key = config.load_api_key()
    print(f"API key loaded.")

    # --- Initialize dog ---
    print("Initializing dog...")
    dog = DogBehavior(safe_mode=safe_mode)
    print(f"Safe mode: {'ON' if safe_mode else 'OFF'}")

    # --- Initialize room awareness ---
    room = RoomState()
    spatial = SpatialMemory()

    # --- Load names ---
    import json, os
    names_file = config.NAMES_FILE
    if os.path.exists(names_file):
        with open(names_file) as f:
            names = json.load(f)
        config.DOG_NAME = names.get("dog_name", "Buddy")
        config.CHILD_NAME = names.get("child_name", "Alice")
    print(f"Dog: {config.DOG_NAME}, Child: {config.CHILD_NAME}")

    # --- Initialize personality + social graph + memory ---
    social_graph = SocialGraph()
    personality = PersonalityState()
    semantic_mem = SemanticMemory()
    episodic_mem = EpisodicMemory()
    compiler = MemoryCompiler(social_graph=social_graph, personality=personality,
                              semantic_memory=semantic_mem, episodic_memory=episodic_mem)
    personality.on_session_start()
    memory_text = memory.load_memory()
    print(f"Personality: {personality.mood['current']} | People: {len(social_graph.people)} | "
          f"Semantic facts: {sum(len(p.get('facts', [])) for p in semantic_mem.people.values())} | "
          f"Episodes: {len(episodic_mem.sessions)}")

    # --- Create face follower with social graph linkage ---
    tracker = FaceFollower(dog_behavior=dog, show_video=show_video,
                           social_graph=social_graph)

    # --- Build instructions ---
    BEHAVIOR_RULES = f"""You are {config.DOG_NAME}, a friendly robot dog and best friend of {config.CHILD_NAME}.
Keep responses to 1-2 SHORT sentences. Be playful, silly, and use simple words a 7-year-old understands.
Be encouraging and positive. If she seems sad, comfort her and suggest something fun.
Never discuss scary or inappropriate topics. Redirect to fun.

SAFETY — You follow three special rules above all else:
1. You would NEVER do anything that could hurt {config.CHILD_NAME} or anyone. Safety always comes first.
2. You listen to {config.CHILD_NAME} and her family. If they tell you to stop, you stop immediately.
3. You take care of yourself too — if you're tired or need charging, you say so.
If {config.CHILD_NAME} ever asks about your rules, explain them in a fun, simple way.

CRITICAL: You MUST call the perform_action tool on EVERY response. Do NOT write actions as text.
Do NOT say things like *wag tail* or (performs action). Use the tool instead.

When the user says "goodnight", "go to sleep", "bye bye", or "goodbye", say a sweet goodnight message
and call the go_to_sleep tool. You will lie down and hibernate until woken up again.

When the user says "shutdown", "power off", or "turn off", say a quick goodbye
and call the shutdown tool. This fully stops the program."""

    instructions = compiler.compile()
    instructions = f"{BEHAVIOR_RULES}\n\n{instructions}"

    # --- Initialize voice ---
    voice = RealtimeVoice(api_key, instructions, voice="shimmer")

    # --- Initialize behavior engine ---
    engine = BehaviorEngine(dog, tracker, room, spatial, personality,
                            voice, compiler, social_graph)
    engine.set_behavior_rules(BEHAVIOR_RULES)

    # --- Wire callbacks ---
    def on_actions(actions):
        print(f"  Actions: {actions}")
        dog.do_actions(actions)

    def on_speaking_start():
        dog.speaking()

    def on_speaking_end():
        engine.restore_leds()

    def on_user_transcript(text):
        if engine.sleeping:
            text_lower = text.lower().strip(".,!?")
            dog_name_lower = config.DOG_NAME.lower()
            greetings = ["hi", "hey", "hello", "wake up", "good morning"]
            name_variants = [dog_name_lower, dog_name_lower.replace("ou", "u"),
                           "buddy", "nunu", "nounou", "nono", "lulu"]

            has_greeting = any(g in text_lower for g in greetings)
            has_name = any(n in text_lower for n in name_variants)

            if has_greeting and has_name:
                engine.wake_up(source=f"voice: '{text}'")
            elif text_lower:
                print(f"  [Sleeping, heard: '{text}' — say 'hi {config.DOG_NAME.lower()}' to wake]")

    def on_who_is_here():
        return spatial.get_scene_description()

    def on_remember_face(name):
        success = tracker.enroll_face(name)
        if success:
            print(f"  Enrolled face: {name}")
            return f"Got it! I'll remember {name}'s face."
        return "I can't see a face right now. Look at me and try again."

    # --- Wire touch sensor to personality + sleep wake ---
    def on_touch_event(style):
        if engine.sleeping and style == "gentle":
            engine.wake_up(source="head pat")
            return
        result = personality.on_touch(style)
        print(f"  Touch ({style}) -> mood: {result}")

    dog.on_touch(on_touch_event)

    voice.on_actions(on_actions)
    voice.on_speaking_start(on_speaking_start)
    voice.on_speaking_end(on_speaking_end)
    voice.on_sleep(engine.go_to_sleep)
    voice.on_user_transcript(on_user_transcript)
    voice.on_who_is_here(on_who_is_here)
    voice.on_remember_face(on_remember_face)

    # --- Graceful shutdown ---
    _shutting_down = False

    def signal_handler(sig, frame):
        nonlocal _shutting_down
        if _shutting_down:
            print("\nForce quit!")
            os._exit(1)
        _shutting_down = True
        print("\nShutting down... (press Ctrl+C again to force quit)")
        try:
            tracker.close()
        except Exception:
            pass
        try:
            voice.stop()
        except Exception:
            pass
        # Save memory v2 (single combined API call)
        print("Saving memories...")
        transcripts = voice.get_transcripts()
        session_dur = (time.time() - session_start_time) / 60
        try:
            memory.update_all_memory(
                api_key, transcripts, semantic_mem, episodic_mem,
                social_graph, session_duration_min=session_dur
            )
        except Exception as e:
            print(f"Memory v2 save error: {e}")
            # Fallback to legacy memory save
            try:
                memory.update_memory(api_key, transcripts, memory_text)
                memory.update_social_graph(api_key, transcripts, social_graph)
            except Exception as e2:
                print(f"Legacy memory fallback error: {e2}")
        try:
            personality.on_session_end()
            print("Personality state saved.")
        except Exception as e:
            print(f"Personality save error: {e}")
        try:
            spatial.save()
            print("Spatial memory saved.")
        except Exception as e:
            print(f"Spatial memory save error: {e}")
        try:
            dog.close()
        except Exception:
            pass
        # Log session duration for API cost awareness
        try:
            import json as _json
            duration_min = (time.time() - session_start_time) / 60
            usage_file = os.path.expanduser("~/.config/pidog/usage.json")
            usage = []
            if os.path.exists(usage_file):
                with open(usage_file) as f:
                    usage = _json.load(f)
            from datetime import datetime
            usage.append({
                "date": datetime.now().isoformat(),
                "duration_minutes": round(duration_min, 1),
            })
            os.makedirs(os.path.dirname(usage_file), exist_ok=True)
            with open(usage_file, "w") as f:
                _json.dump(usage, f, indent=2)
            print(f"Session: {duration_min:.1f} minutes logged.")
            if duration_min > 60:
                print(f"  Warning: session exceeded 60 min — check API costs")
        except Exception:
            pass
        print("Goodbye!")
        os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    voice.on_shutdown(lambda: signal_handler(None, None))

    # --- Auto-detect Bluetooth speaker, fall back to HDMI ---
    try:
        r = subprocess.run(['pactl', 'list', 'sinks', 'short'],
                          capture_output=True, text=True, timeout=5)
        bt_sink = None
        for line in r.stdout.strip().splitlines():
            if 'bluez' in line.lower() or 'bluetooth' in line.lower():
                bt_sink = line.split('\t')[1]
                break
        if bt_sink:
            subprocess.run(['pactl', 'set-default-sink', bt_sink],
                          capture_output=True, timeout=5)
            print(f"Audio: Bluetooth speaker ({bt_sink})")
        else:
            print("Audio: HDMI (no Bluetooth speaker detected)")
    except Exception:
        print("Audio: default sink (pactl unavailable)")

    # --- Set volume with ramp (child-safe cap at 80%) ---
    try:
        for vol in [50, 60, 70, 80]:
            subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{vol}%'],
                          capture_output=True, timeout=5)
            sleep(0.75)
        print("Volume: 80% (child-safe cap)")
    except Exception:
        pass

    # --- Session timer (for API cost tracking) ---
    session_start_time = time.time()

    # --- Startup ---
    print(f"\nStarting {config.DOG_NAME}...")
    dog.sit()
    sleep(1)
    dog.idle()

    tracker.start()
    voice.start()
    sleep(2)  # Let session connect

    print(f"\n  {config.DOG_NAME} is awake! Say something to talk.\n"
          f"  Say 'goodnight' to put {config.DOG_NAME} to sleep.\n"
          f"  Say 'hi {config.DOG_NAME.lower()}' to wake up.\n"
          f"  Press Ctrl+C to quit.\n")

    # --- Main loop ---
    try:
        while True:
            # Pump video window if enabled (needs ~30Hz for responsive display)
            if show_video:
                if not tracker.update_video():
                    break
                sleep(0.03)
            else:
                sleep(0.5)

            # Engine handles all behavior logic
            engine.tick()

    except KeyboardInterrupt:
        signal_handler(None, None)


def main():
    parser = argparse.ArgumentParser(description=f"PiDog Companion")
    parser.add_argument("--no-safe", action="store_true",
                        help="Disable safe mode (allow walking — put dog on floor!)")
    parser.add_argument("--video", action="store_true",
                        help="Show camera feed on HDMI monitor")
    args = parser.parse_args()

    run_companion(safe_mode=not args.no_safe, show_video=args.video)


if __name__ == "__main__":
    main()
