#!/usr/bin/env python3
"""PiDog Full Companion — voice + physical actions + sleep/wake cycle.

Usage:
    python3 -m buddy.companion              # Safe mode (desk safe)
    python3 -m buddy.companion --no-safe    # Full movement (dog on floor)
"""

import argparse
import signal
import subprocess
from time import sleep, time

from . import config
from .realtime_voice import RealtimeVoice
from .dog_behavior import DogBehavior
from .face_follower import FaceFollower
from .room_awareness import RoomState
from .memory_compiler import MemoryCompiler
from .personality import PersonalityState
from .social_graph import SocialGraph
from . import memory

try:
    from pidog.dual_touch import TouchStyle
except ImportError:
    TouchStyle = None


def run_companion(safe_mode=True, show_video=False):
    api_key = config.load_api_key()
    print(f"API key loaded.")

    # --- Initialize dog ---
    print("Initializing dog...")
    dog = DogBehavior(safe_mode=safe_mode)
    print(f"Safe mode: {'ON' if safe_mode else 'OFF'}")

    # --- Initialize face follower (social_graph linked after load) ---
    tracker = None  # Created after social_graph is initialized

    # --- Initialize room awareness ---
    room = RoomState()

    # --- Load names ---
    import json, os
    names_file = config.NAMES_FILE
    if os.path.exists(names_file):
        with open(names_file) as f:
            names = json.load(f)
        config.DOG_NAME = names.get("dog_name", "Buddy")
        config.CHILD_NAME = names.get("child_name", "Alice")
    print(f"Dog: {config.DOG_NAME}, Child: {config.CHILD_NAME}")

    # --- Initialize personality + social graph + memory compiler ---
    social_graph = SocialGraph()
    personality = PersonalityState()
    compiler = MemoryCompiler(social_graph=social_graph, personality=personality)
    personality.on_session_start()
    memory_text = memory.load_memory()
    print(f"Personality: {personality.mood['current']} | People: {len(social_graph.people)}")

    # --- Create face follower with social graph linkage ---
    tracker = FaceFollower(dog_behavior=dog, show_video=show_video,
                           social_graph=social_graph)

    # --- Build instructions ---
    BEHAVIOR_RULES = f"""You are {config.DOG_NAME}, a friendly robot dog and best friend of {config.CHILD_NAME}.
Keep responses to 1-2 SHORT sentences. Be playful, silly, and use simple words a 7-year-old understands.
Be encouraging and positive. If she seems sad, comfort her and suggest something fun.
Never discuss scary or inappropriate topics. Redirect to fun.

CRITICAL: You MUST call the perform_action tool on EVERY response. Do NOT write actions as text.
Do NOT say things like *wag tail* or (performs action). Use the tool instead.

When the user says "goodnight", "go to sleep", "bye bye", or "goodbye", say a sweet goodnight message
and call the go_to_sleep tool. You will lie down and hibernate until woken up again."""

    def build_instructions(room_summary=""):
        compiled_context = compiler.compile(room_summary)
        return f"{BEHAVIOR_RULES}\n\n{compiled_context}"

    def build_instructions_update(room_summary=""):
        """Lightweight update for mid-session room state changes."""
        update_context = compiler.compile_update(room_summary)
        return f"{BEHAVIOR_RULES}\n\n{update_context}" if update_context else None

    instructions = build_instructions()

    # --- Initialize voice ---
    voice = RealtimeVoice(api_key, instructions, voice="shimmer")

    # --- State ---
    sleeping = False

    # --- Wire callbacks ---
    def on_actions(actions):
        print(f"  Actions: {actions}")
        dog.do_actions(actions)

    def on_speaking_start():
        dog.speaking()

    def on_speaking_end():
        if not sleeping:
            dog.idle()

    def wake_up(source="unknown"):
        nonlocal sleeping
        if not sleeping:
            return
        sleeping = False
        print(f"\n  Waking up! (source: {source})\n")
        dog.do_actions(["sit"])
        dog.wait_actions_done()
        dog.idle()
        tracker.start()
        sleep(1.5)
        yaw, pitch = tracker.get_yaw_pitch()
        room.update(tracker.get_tracked_people(), yaw, pitch)
        greeted = room.get_greeting()
        if greeted:
            print(f"  Recognized: {greeted}!")
            voice.update_instructions(
                build_instructions(f"{greeted} just woke you up! Greet them by name.")
            )
        else:
            voice.update_instructions(build_instructions("Someone just woke you up!"))

    def on_sleep():
        nonlocal sleeping
        sleeping = True
        tracker.stop()
        print(f"\n  {config.DOG_NAME} is going to sleep...\n")
        print(f"  Pat my head or say 'hi {config.DOG_NAME.lower()}' to wake up.\n")
        sleep(3)  # Let the goodbye audio finish playing
        dog.do_actions(["lie"])
        dog.wait_actions_done()
        dog.dog.rgb_strip.set_mode("breath", "blue", bps=0.3)  # Dim blue = sleeping

    def on_user_transcript(text):
        nonlocal sleeping
        if sleeping:
            text_lower = text.lower().strip(".,!?")
            dog_name_lower = config.DOG_NAME.lower()
            # Broad wake word matching — any greeting + dog name variant
            greetings = ["hi", "hey", "hello", "wake up", "good morning"]
            name_variants = [dog_name_lower, dog_name_lower.replace("ou", "u"),
                           "buddy", "nunu", "nounou", "nono", "lulu"]

            # Match: any greeting + any name variant anywhere in text
            has_greeting = any(g in text_lower for g in greetings)
            has_name = any(n in text_lower for n in name_variants)

            if has_greeting and has_name:
                wake_up(source=f"voice: '{text}'")
            elif text_lower:
                print(f"  [Sleeping, heard: '{text}' — say 'hi {config.DOG_NAME.lower()}' to wake]")

    def on_who_is_here():
        return room.get_summary()

    def on_remember_face(name):
        success = tracker.enroll_face(name)
        if success:
            print(f"  Enrolled face: {name}")
            return f"Got it! I'll remember {name}'s face."
        return "I can't see a face right now. Look at me and try again."

    voice.on_actions(on_actions)
    voice.on_speaking_start(on_speaking_start)
    voice.on_speaking_end(on_speaking_end)
    voice.on_sleep(on_sleep)
    voice.on_user_transcript(on_user_transcript)
    voice.on_who_is_here(on_who_is_here)
    voice.on_remember_face(on_remember_face)

    # --- Graceful shutdown ---
    def signal_handler(sig, frame):
        print("\nShutting down...")
        tracker.close()
        voice.stop()
        # Save memory + social graph + personality
        print("Saving memories...")
        transcripts = voice.get_transcripts()
        try:
            memory.update_memory(api_key, transcripts, memory_text)
        except Exception as e:
            print(f"Memory save error: {e}")
        try:
            memory.update_social_graph(api_key, transcripts, social_graph)
        except Exception as e:
            print(f"Social graph update error: {e}")
        try:
            personality.on_session_end()
            print("Personality state saved.")
        except Exception as e:
            print(f"Personality save error: {e}")
        dog.close()
        print("Goodbye!")
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # --- Set volume to max ---
    try:
        subprocess.run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', '100%'],
                      capture_output=True, timeout=5)
        print("Volume: 100%")
    except Exception:
        pass

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

    # --- Main loop: update room awareness ---
    last_room_summary = ""
    last_instruction_time = 0
    last_who_printed = []
    last_room_update = 0
    INSTRUCTION_INTERVAL = 10.0  # Min seconds between LLM instruction updates
    ROOM_UPDATE_INTERVAL = 2.0
    try:
        while True:
            # Pump video window if enabled (needs ~30Hz for responsive display)
            if show_video:
                if not tracker.update_video():
                    break
                sleep(0.03)
            else:
                sleep(0.5)

            now = time()

            # During sleep: poll touch sensor for head pat wake
            if sleeping:
                if TouchStyle is not None:
                    try:
                        touch = dog.dog.dual_touch.read()
                        if touch == TouchStyle.FRONT_TO_REAR:
                            wake_up(source="head pat")
                    except Exception:
                        pass
                continue

            if now - last_room_update < ROOM_UPDATE_INTERVAL:
                continue
            last_room_update = now

            if not sleeping:
                yaw, pitch = tracker.get_yaw_pitch()
                room.update(tracker.get_tracked_people(), yaw, pitch)
                who = room.who_is_here()

                # Print room changes (arrivals/departures only)
                if sorted(who) != sorted(last_who_printed):
                    if who:
                        print(f"  Room: {', '.join(who)}")
                    else:
                        print("  Room: empty")
                    last_who_printed = list(who)

                # Rate-limit LLM instruction updates
                summary = room.get_summary()
                now = time()
                if (summary != last_room_summary
                        and now - last_instruction_time >= INSTRUCTION_INTERVAL):
                    # Check for new person arrival → personality reaction
                    new_arrivals = set(who) - set(last_who_printed)
                    for name in new_arrivals:
                        person = social_graph.get_person(name)
                        role = person.get("role", "") if person else ""
                        personality.on_person_seen(name, role)

                    last_room_summary = summary
                    last_instruction_time = now
                    update = build_instructions_update(summary)
                    if update:
                        voice.update_instructions(update)
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
