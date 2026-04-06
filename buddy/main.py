#!/usr/bin/env python3
"""PiDog Voice Companion — main entry point.

Usage:
    python3 -m buddy.main
    python3 -m buddy.main --calibrate   # Calibrate mic first
    python3 -m buddy.main --test-tts    # Test TTS only
    python3 -m buddy.main --test-stt    # Test STT only
    python3 -m buddy.main --reset-names # Re-run name setup
"""

import argparse
import json
import os
import signal
import sys
from time import sleep, time

from . import config
from .audio_capture import AudioCapture
from .stt import STT
from .tts_speaker import TTSSpeaker
from .llm_chat import LLMChat
from .response_parser import parse_response
from .dog_behavior import DogBehavior
from . import memory


def load_names():
    """Load saved names or return None if first run."""
    if os.path.exists(config.NAMES_FILE):
        with open(config.NAMES_FILE) as f:
            return json.load(f)
    return None


def save_names(dog_name, child_name):
    """Save names to file."""
    os.makedirs(os.path.dirname(config.NAMES_FILE), exist_ok=True)
    with open(config.NAMES_FILE, "w") as f:
        json.dump({"dog_name": dog_name, "child_name": child_name}, f)


def setup_names(audio, stt, tts):
    """Interactive name setup on first run."""
    tts.speak("Hi! I'm your new robot dog! What's your name?")
    sleep(0.5)

    # Get child's name
    child_name = ""
    for attempt in range(3):
        wav = audio.record_utterance()
        if wav:
            child_name = stt.transcribe(wav)
            if child_name:
                break
        tts.speak("I didn't catch that. What's your name?")

    if not child_name:
        child_name = "my friend"

    tts.speak(f"Nice to meet you, {child_name}!")
    sleep(0.5)
    tts.speak("What would you like to call me? Pick any name you want!")
    sleep(0.5)

    # Get dog's name
    dog_name = ""
    for attempt in range(3):
        wav = audio.record_utterance()
        if wav:
            dog_name = stt.transcribe(wav)
            if dog_name:
                # Clean up — take first word, capitalize
                dog_name = dog_name.strip().split()[0].strip(".,!?").capitalize()
                break
        tts.speak("Say a name for me! Anything you like!")

    if not dog_name:
        dog_name = "Buddy"

    tts.speak(f"I love it! My name is {dog_name}! Say 'hi {dog_name}' to talk to me anytime!")
    save_names(dog_name, child_name)
    return dog_name, child_name


def apply_names(dog_name, child_name):
    """Update config with the chosen names."""
    config.DOG_NAME = dog_name
    config.CHILD_NAME = child_name
    config.WAKE_WORDS = [f"hi {dog_name.lower()}", f"hey {dog_name.lower()}"]
    config.WELCOME_MESSAGE = f"Hi {child_name}! I'm {dog_name}! Say 'hi {dog_name.lower()}' to talk to me!"
    # Update system prompt with names
    config.SYSTEM_PROMPT = config.SYSTEM_PROMPT.replace("Buddy", dog_name).replace("Alice", child_name)


def test_tts(api_key):
    """Quick TTS test."""
    tts = TTSSpeaker(api_key)
    print("Testing TTS...")
    tts.speak(f"Hi! I'm {config.DOG_NAME}! Want to play?")
    print("Done.")


def test_stt(api_key):
    """Quick STT test."""
    audio = AudioCapture()
    stt = STT(api_key)
    audio.calibrate()
    print("Say something...")
    wav = audio.record_utterance()
    if wav:
        text = stt.transcribe(wav)
        print(f"You said: {text}")
    audio.close()


def run_companion(api_key, skip_calibrate=False, reset_names=False):
    """Main conversation loop with conversation mode."""
    print(f"\n=== PiDog Voice Companion ===\n")

    # Initialize components
    print("Starting up...")
    dog = DogBehavior(safe_mode=True)
    audio = AudioCapture(
        on_voice_start=dog.listening,
        on_voice_end=lambda: None,
    )
    stt = STT(api_key)
    tts = TTSSpeaker(api_key)

    # Graceful shutdown
    shutdown = False

    def signal_handler(sig, frame):
        nonlocal shutdown
        print("\nShutting down...")
        shutdown = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Calibrate mic
        if not skip_calibrate:
            audio.calibrate(seconds=2)

        # Name setup
        names = load_names()
        if names and not reset_names:
            apply_names(names["dog_name"], names["child_name"])
            print(f"Dog: {config.DOG_NAME}, Child: {config.CHILD_NAME}")
        else:
            dog_name, child_name = setup_names(audio, stt, tts)
            apply_names(dog_name, child_name)

        # Load long-term memory and inject into system prompt
        memory_text = memory.load_memory()
        if memory_text:
            config.SYSTEM_PROMPT = memory.inject_into_prompt(config.SYSTEM_PROMPT, memory_text)
            print(f"Loaded {memory_text.count('- ')} memories")
        else:
            print("No memories yet (first run)")

        # Initialize LLM with updated names + memory
        llm = LLMChat(api_key)

        # Welcome
        dog.idle()
        print(f"\nSay 'hi {config.DOG_NAME.lower()}' to start talking!")
        tts.speak(config.WELCOME_MESSAGE)

        # Main loop
        in_conversation = False
        conversation_start = 0

        while not shutdown:
            dog.idle()

            # Check for sensor events
            events = dog.get_sensor_events()
            if events and in_conversation:
                for event in events:
                    reply = llm.chat(event)
                    speech, actions = parse_response(reply)
                    if speech:
                        dog.speaking()
                        tts.speak(speech)
                    dog.do_actions(actions)
                    dog.wait_actions_done()

            # Listen for speech
            wav = audio.record_utterance()
            if wav is None or shutdown:
                # Check conversation timeout
                if in_conversation and time() - conversation_start > config.CONVERSATION_TIMEOUT:
                    in_conversation = False
                    tts.speak(f"I'm going to rest now. Say hi {config.DOG_NAME.lower()} when you want to play again!")
                    dog.idle()
                continue

            # Transcribe
            dog.thinking()
            transcript = stt.transcribe(wav)
            if not transcript:
                dog.idle()
                continue

            print(f"Heard: {transcript}")

            # Check if we're in conversation mode or need wake word
            if not in_conversation:
                is_wake, cleaned = stt.contains_wake_word(transcript)
                if not is_wake:
                    dog.idle()
                    continue
                # Activated!
                in_conversation = True
                conversation_start = time()
                user_input = cleaned if cleaned else f"hi {config.DOG_NAME}"
                print(f"Wake word detected! Entering conversation mode.")
            else:
                # Already in conversation — no wake word needed
                conversation_start = time()  # Reset timeout
                user_input = transcript

            print(f"Processing: {user_input}")

            # Check for goodbye
            goodbye_words = ["bye", "goodbye", "good night", "see you", "go to sleep"]
            if any(g in user_input.lower() for g in goodbye_words):
                reply = llm.chat(user_input)
                speech, actions = parse_response(reply)
                if speech:
                    dog.speaking()
                    tts.speak(speech)
                dog.do_actions(actions)
                dog.wait_actions_done()
                in_conversation = False
                continue

            # Get LLM response
            print(f"Calling ChatGPT...")
            reply = llm.chat(user_input)
            print(f"ChatGPT reply: {reply}")

            # Parse response
            speech, actions = parse_response(reply)
            print(f"Speech: '{speech}', Actions: {actions}")

            # Speak and act
            if speech:
                dog.speaking()
                print(f"Speaking: {speech}")
                tts.speak(speech)
                print("TTS done")

            dog.do_actions(actions)
            dog.wait_actions_done()
            print("Actions done")

    finally:
        # Update long-term memory before shutdown
        print(f"\nSaving memories...")
        try:
            memory_text = memory.update_memory(api_key, llm.get_history(), memory_text)
        except Exception as e:
            print(f"Memory save failed: {e}")

        print(f"{config.DOG_NAME} is going to sleep...")
        try:
            tts.speak("Bye bye! See you next time!")
        except Exception:
            pass
        audio.close()
        dog.close()
        print("Goodbye!")


def main():
    parser = argparse.ArgumentParser(description="PiDog Voice Companion")
    parser.add_argument("--calibrate", action="store_true",
                        help="Run mic calibration only")
    parser.add_argument("--test-tts", action="store_true",
                        help="Test text-to-speech")
    parser.add_argument("--test-stt", action="store_true",
                        help="Test speech-to-text")
    parser.add_argument("--skip-calibrate", action="store_true",
                        help="Skip mic calibration on startup")
    parser.add_argument("--reset-names", action="store_true",
                        help="Re-run name setup (choose new dog/child name)")
    args = parser.parse_args()

    # Load API key
    api_key = config.load_api_key()
    print("API key loaded.")

    if args.calibrate:
        audio = AudioCapture()
        audio.calibrate(seconds=3)
        audio.close()
    elif args.test_tts:
        test_tts(api_key)
    elif args.test_stt:
        test_stt(api_key)
    else:
        run_companion(api_key,
                      skip_calibrate=args.skip_calibrate,
                      reset_names=args.reset_names)


if __name__ == "__main__":
    main()
