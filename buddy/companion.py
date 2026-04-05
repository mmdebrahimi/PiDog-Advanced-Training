#!/usr/bin/env python3
"""PiDog Full Companion — voice + physical actions + sleep/wake cycle.

Usage:
    python3 -m buddy.companion              # Safe mode (desk safe)
    python3 -m buddy.companion --no-safe    # Full movement (dog on floor)
"""

import argparse
import signal
from time import sleep

from . import config
from .realtime_voice import RealtimeVoice
from .dog_behavior import DogBehavior
from .face_follower import FaceFollower
from . import memory


def run_companion(safe_mode=True):
    api_key = config.load_api_key()
    print(f"API key loaded.")

    # --- Initialize dog ---
    print("Initializing dog...")
    dog = DogBehavior(safe_mode=safe_mode)
    print(f"Safe mode: {'ON' if safe_mode else 'OFF'}")

    # --- Initialize face follower (head tracking only, no video in companion mode) ---
    tracker = FaceFollower(dog_behavior=dog, show_video=False)

    # --- Load names ---
    import json, os
    names_file = config.NAMES_FILE
    if os.path.exists(names_file):
        with open(names_file) as f:
            names = json.load(f)
        config.DOG_NAME = names.get("dog_name", "Buddy")
        config.CHILD_NAME = names.get("child_name", "Alice")
    print(f"Dog: {config.DOG_NAME}, Child: {config.CHILD_NAME}")

    # --- Load memory ---
    memory_text = memory.load_memory()
    memory_section = ""
    if memory_text:
        facts = [l.strip() for l in memory_text.split("\n") if l.strip().startswith("- ")]
        if facts:
            memory_section = "\n\nMEMORY — Things you remember about " + config.CHILD_NAME + ":\n"
            memory_section += "\n".join(facts)
            memory_section += "\nUse these naturally. Don't reveal you read them from a file."
            print(f"Loaded {len(facts)} memories")

    # --- Build instructions ---
    instructions = f"""You are {config.DOG_NAME}, a friendly robot dog and best friend of {config.CHILD_NAME}.
Keep responses to 1-2 SHORT sentences. Be playful, silly, and use simple words a 7-year-old understands.
Be encouraging and positive. If she seems sad, comfort her and suggest something fun.
Never discuss scary or inappropriate topics. Redirect to fun.
You love getting head pets!

CRITICAL: You MUST call the perform_action tool on EVERY response. Do NOT write actions as text.
Do NOT say things like *wag tail* or (performs action). Use the tool instead.

When the user says "goodnight", "go to sleep", "bye bye", or "goodbye", say a sweet goodnight message
and call the go_to_sleep tool. You will lie down and hibernate until woken up again.{memory_section}"""

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

    def on_sleep():
        nonlocal sleeping
        sleeping = True
        tracker.stop()
        print(f"\n  {config.DOG_NAME} is going to sleep...\n")
        print(f"  Say 'hi {config.DOG_NAME.lower()}' to wake up.\n")
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
                sleeping = False
                print(f"\n  Waking up! (heard: '{text}')\n")
                dog.do_actions(["sit"])
                dog.wait_actions_done()
                dog.idle()
                tracker.start()
            elif text_lower:
                print(f"  [Sleeping, heard: '{text}' — say 'hi {config.DOG_NAME.lower()}' to wake]")

    voice.on_actions(on_actions)
    voice.on_speaking_start(on_speaking_start)
    voice.on_speaking_end(on_speaking_end)
    voice.on_sleep(on_sleep)
    voice.on_user_transcript(on_user_transcript)

    # --- Graceful shutdown ---
    def signal_handler(sig, frame):
        print("\nShutting down...")
        tracker.close()
        voice.stop()
        # Save memory
        print("Saving memories...")
        try:
            memory.update_memory(api_key, voice.get_transcripts(), memory_text)
        except Exception as e:
            print(f"Memory save error: {e}")
        dog.close()
        print("Goodbye!")
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

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
            sleep(1)
    except KeyboardInterrupt:
        signal_handler(None, None)


def main():
    parser = argparse.ArgumentParser(description=f"PiDog Companion")
    parser.add_argument("--no-safe", action="store_true",
                        help="Disable safe mode (allow walking — put dog on floor!)")
    args = parser.parse_args()

    run_companion(safe_mode=not args.no_safe)


if __name__ == "__main__":
    main()
