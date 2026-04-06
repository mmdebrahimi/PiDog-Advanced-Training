#!/usr/bin/env python3
"""CLI tool for testing individual servo joints on the PiDog.

Usage:
    python3 joint_test.py legs <index> [--range=-45,45] [--step=10] [--speed=30]
    python3 joint_test.py head <index> [--range=-45,45] [--step=10] [--speed=30]
    python3 joint_test.py tail [--range=-45,45] [--step=10] [--speed=30]
    python3 joint_test.py sweep              # Sweep all joints sequentially

Leg indices 0-7:  LF_upper, LF_lower, RF_upper, RF_lower,
                  LH_upper, LH_lower, RH_upper, RH_lower
Head indices 0-2: yaw, roll, pitch
Tail: single servo (index ignored)
"""

import argparse
import csv
import os
import sys
from time import sleep

JOINT_NAMES = {
    "legs": [
        "LF_upper (pin2)", "LF_lower (pin3)",
        "RF_upper (pin7)", "RF_lower (pin8)",
        "LH_upper (pin0)", "LH_lower (pin1)",
        "RH_upper (pin10)", "RH_lower (pin11)",
    ],
    "head": ["yaw (pin4)", "roll (pin6)", "pitch (pin5)"],
    "tail": ["tail (pin9)"],
}

LIE_ANGLES = [45, -45, -45, 45, 45, -45, -45, 45]
ZERO_ANGLES = [0, 0, 0, 0, 0, 0, 0, 0]
HEAD_NEUTRAL = [0, 0, 0]
TAIL_NEUTRAL = [0]

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "joint_mapping.csv")
CSV_HEADER = ["body_part", "index", "pin", "joint_name", "neutral_angle",
              "direction_positive", "min_safe", "max_safe", "notes"]

PIN_MAP = {
    "legs": [2, 3, 7, 8, 0, 1, 10, 11],
    "head": [4, 6, 5],
    "tail": [9],
}


def parse_range(range_str):
    parts = range_str.split(",")
    return int(parts[0]), int(parts[1])


def init_pidog():
    print("Initializing Pidog (wait 1.5s for MCU reset + IMU calibration)...")
    from pidog import Pidog
    dog = Pidog()
    sleep(1.5)
    print("Ready.\n")
    return dog


def test_legs(dog, index, angle_range, step, speed):
    lo, hi = angle_range
    name = JOINT_NAMES["legs"][index]
    print(f"=== Testing LEG joint {index}: {name} ===")
    print(f"Range: {lo}° to {hi}°, step: {step}°, speed: {speed}\n")

    # Start from all-zeros baseline
    print("Moving to all-zeros baseline...")
    dog.legs_move([ZERO_ANGLES], immediately=True, speed=50)
    dog.wait_legs_done()
    sleep(0.5)

    print(f"Sweeping joint {index} from {lo}° to {hi}°:\n")
    angles_list = list(range(lo, hi + 1, step))
    if hi not in angles_list:
        angles_list.append(hi)

    for angle in angles_list:
        target = ZERO_ANGLES.copy()
        target[index] = angle
        dog.legs_move([target], immediately=True, speed=speed)
        dog.wait_legs_done()
        print(f"  {angle:+4d}°", flush=True)
        sleep(0.5)

    # Return to zero
    print(f"\nReturning to zero...")
    dog.legs_move([ZERO_ANGLES], immediately=True, speed=50)
    dog.wait_legs_done()

    # Now test from lie position
    print(f"\nMoving to lie position...")
    dog.legs_move([LIE_ANGLES], immediately=True, speed=50)
    dog.wait_legs_done()
    sleep(0.5)

    lie_val = LIE_ANGLES[index]
    print(f"Lie position for joint {index}: {lie_val}°")
    print(f"Sweeping from lie baseline:\n")

    for delta in [-20, -10, 0, 10, 20]:
        target = LIE_ANGLES.copy()
        target[index] = lie_val + delta
        dog.legs_move([target], immediately=True, speed=speed)
        dog.wait_legs_done()
        print(f"  {lie_val + delta:+4d}° (lie {delta:+d}°)", flush=True)
        sleep(0.5)

    # Return to lie
    dog.legs_move([LIE_ANGLES], immediately=True, speed=50)
    dog.wait_legs_done()
    print(f"\nDone testing joint {index}: {name}")


def test_head(dog, index, angle_range, step, speed):
    lo, hi = angle_range
    name = JOINT_NAMES["head"][index]
    print(f"=== Testing HEAD joint {index}: {name} ===")
    print(f"Range: {lo}° to {hi}°, step: {step}°, speed: {speed}\n")

    # Start from neutral
    print("Moving to head neutral [0, 0, 0]...")
    dog.head_move_raw([HEAD_NEUTRAL], immediately=True, speed=50)
    dog.wait_head_done()
    sleep(0.5)

    print(f"Sweeping joint {index} from {lo}° to {hi}°:\n")
    angles_list = list(range(lo, hi + 1, step))
    if hi not in angles_list:
        angles_list.append(hi)

    for angle in angles_list:
        target = HEAD_NEUTRAL.copy()
        target[index] = angle
        dog.head_move_raw([target], immediately=True, speed=speed)
        dog.wait_head_done()
        print(f"  {angle:+4d}°", flush=True)
        sleep(0.5)

    # Return to neutral
    dog.head_move_raw([HEAD_NEUTRAL], immediately=True, speed=50)
    dog.wait_head_done()
    print(f"\nDone testing head joint {index}: {name}")


def test_tail(dog, angle_range, step, speed):
    lo, hi = angle_range
    print(f"=== Testing TAIL ===")
    print(f"Range: {lo}° to {hi}°, step: {step}°, speed: {speed}\n")

    print("Moving to tail neutral [0]...")
    dog.tail_move([TAIL_NEUTRAL], immediately=True, speed=50)
    dog.wait_tail_done()
    sleep(0.5)

    angles_list = list(range(lo, hi + 1, step))
    if hi not in angles_list:
        angles_list.append(hi)

    for angle in angles_list:
        dog.tail_move([[angle]], immediately=True, speed=speed)
        dog.wait_tail_done()
        print(f"  {angle:+4d}°", flush=True)
        sleep(0.5)

    dog.tail_move([TAIL_NEUTRAL], immediately=True, speed=50)
    dog.wait_tail_done()
    print(f"\nDone testing tail.")


def sweep_all(dog, speed):
    """Sweep all 12 joints sequentially with a small test range."""
    print("=== SWEEP ALL JOINTS ===\n")
    print("Testing each joint: 0° → +15° → -15° → 0°\n")

    # Legs
    print("--- Legs (from zero baseline) ---")
    dog.legs_move([ZERO_ANGLES], immediately=True, speed=50)
    dog.wait_legs_done()
    sleep(0.5)

    for i in range(8):
        name = JOINT_NAMES["legs"][i]
        print(f"  Joint {i}: {name} ... ", end="", flush=True)

        for angle in [15, -15, 0]:
            target = ZERO_ANGLES.copy()
            target[i] = angle
            dog.legs_move([target], immediately=True, speed=speed)
            dog.wait_legs_done()
            sleep(0.3)
        print("ok")

    # Head
    print("\n--- Head (from zero baseline) ---")
    dog.head_move_raw([HEAD_NEUTRAL], immediately=True, speed=50)
    dog.wait_head_done()
    sleep(0.5)

    for i in range(3):
        name = JOINT_NAMES["head"][i]
        print(f"  Joint {i}: {name} ... ", end="", flush=True)

        for angle in [15, -15, 0]:
            target = HEAD_NEUTRAL.copy()
            target[i] = angle
            dog.head_move_raw([target], immediately=True, speed=speed)
            dog.wait_head_done()
            sleep(0.3)
        print("ok")

    # Tail
    print("\n--- Tail ---")
    dog.tail_move([TAIL_NEUTRAL], immediately=True, speed=50)
    dog.wait_tail_done()
    sleep(0.5)

    print(f"  Tail ... ", end="", flush=True)
    for angle in [30, -30, 0]:
        dog.tail_move([[angle]], immediately=True, speed=speed)
        dog.wait_tail_done()
        sleep(0.3)
    print("ok")

    print("\n=== All 12 joints tested ===")


def main():
    parser = argparse.ArgumentParser(description="PiDog joint testing tool")
    parser.add_argument("part", choices=["legs", "head", "tail", "sweep"],
                        help="Body part to test, or 'sweep' for all")
    parser.add_argument("index", nargs="?", type=int, default=0,
                        help="Joint index (legs: 0-7, head: 0-2)")
    parser.add_argument("--range", dest="angle_range", default="-45,45",
                        help="Angle range as min,max (default: -45,45)")
    parser.add_argument("--step", type=int, default=10,
                        help="Angle step size (default: 10)")
    parser.add_argument("--speed", type=int, default=30,
                        help="Movement speed 0-100 (default: 30)")

    args = parser.parse_args()
    angle_range = parse_range(args.angle_range)

    dog = init_pidog()
    try:
        if args.part == "sweep":
            sweep_all(dog, args.speed)
        elif args.part == "legs":
            if args.index < 0 or args.index > 7:
                print("Leg index must be 0-7")
                sys.exit(1)
            test_legs(dog, args.index, angle_range, args.step, args.speed)
        elif args.part == "head":
            if args.index < 0 or args.index > 2:
                print("Head index must be 0-2")
                sys.exit(1)
            test_head(dog, args.index, angle_range, args.step, args.speed)
        elif args.part == "tail":
            test_tail(dog, angle_range, args.step, args.speed)
    finally:
        dog.close()


if __name__ == "__main__":
    main()
