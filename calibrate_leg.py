#!/usr/bin/env python3
"""Calibrate a single leg servo interactively.

Usage: source .venv/bin/activate && python3 calibrate_leg.py
"""

from pidog import Pidog
from time import sleep
import sys

print("Initializing PiDog (hold the dog steady)...")
dog = Pidog()
sleep(2)

# Current offsets from the Robot objects
offsets = list(dog.legs.offset)
NAMES = [
    "LF_upper (0)", "LF_lower (1)",
    "RF_upper (2)", "RF_lower (3)",
    "LH_upper (4)", "LH_lower (5)",
    "RH_upper (6)", "RH_lower (7)",
]

print("\nCurrent leg servo offsets:")
for i, name in enumerate(NAMES):
    marker = " <<<" if i in (4, 5) else ""
    print(f"  [{i}] {name}: {offsets[i]:+.1f}{marker}")

# Default to LH_lower (the problem leg)
idx = 5
print(f"\nAdjusting: {NAMES[idx]} (current offset: {offsets[idx]:+.1f})")
print("Commands: +5, -5, +1, -1, 'sit', 'stand', 's' to switch servo, 'show', 'q' to save & quit\n")

try:
    while True:
        cmd = input(f"[{NAMES[idx]} = {offsets[idx]:+.1f}] > ").strip().lower()

        if cmd == 'q':
            break
        elif cmd == 's':
            try:
                new_idx = int(input("Servo index (0-7): "))
                if 0 <= new_idx <= 7:
                    idx = new_idx
                    print(f"Now adjusting: {NAMES[idx]} = {offsets[idx]:+.1f}")
            except ValueError:
                print("Enter 0-7")
            continue
        elif cmd == 'sit':
            dog.do_action("sit", speed=50)
            sleep(1)
            continue
        elif cmd == 'stand':
            dog.do_action("stand", speed=50)
            sleep(1)
            continue
        elif cmd == 'show':
            for i, name in enumerate(NAMES):
                marker = " <<<" if i == idx else ""
                print(f"  [{i}] {name}: {offsets[i]:+.1f}{marker}")
            continue

        try:
            delta = float(cmd)
        except ValueError:
            print("Enter a number (+5, -5, +1, -1, etc.), 'sit', 'stand', 's', 'show', or 'q'")
            continue

        offsets[idx] += delta
        offsets[idx] = max(-30, min(30, offsets[idx]))

        # Apply offset and move to sit
        dog.legs.set_offset(offsets)
        dog.do_action("sit", speed=50)
        sleep(0.5)
        print(f"  {NAMES[idx]} = {offsets[idx]:+.1f}")

except KeyboardInterrupt:
    print("\nCancelled (not saved)")
    dog.close()
    sys.exit(0)

# Save
print(f"\nFinal offsets: {offsets}")
save = input("Save to pidog.conf? (y/n): ").strip().lower()
if save == 'y':
    dog.legs.set_offset(offsets)
    print("Saved!")
else:
    print("Not saved.")

dog.close()
