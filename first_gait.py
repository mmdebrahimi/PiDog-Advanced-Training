#!/usr/bin/env python3
"""First manual walking gait for PiDog.

A simple diagonal (trot) pattern:
  Phase A: Lift LF + RH, swing forward, plant
  Phase B: Lift RF + LH, swing forward, plant

Leg index mapping:
  0: LF_upper  1: LF_lower
  2: RF_upper  3: RF_lower
  4: LH_upper  5: LH_lower
  6: RH_upper  7: RH_lower

Sign conventions (from joint mapping):
  Upper joints: positive = shoulder/hip forward
  Lower joints: positive = knee extend
  Left/right are mirrored (opposite signs for same motion)
"""

import argparse
from time import sleep
from pidog import Pidog
from state_logger import StateLogger

# Standing pose — legs roughly under the body, moderate height
# Derived from the sit pose but more upright
STAND = [25, 35, -25, -35, 35, 35, -35, -35]

# Gait parameters
LIFT_ANGLE = 15      # How much to lift the upper joint (degrees)
SWING_ANGLE = 15     # How far forward/back each step swings
STANCE_SPEED = 60    # Speed for ground-contact phase
SWING_SPEED = 80     # Speed for leg-in-air phase


def make_gait_frames(stand, lift, swing):
    """Generate the 4 keyframes of a diagonal trot cycle.

    Returns a list of [8-angle] frames:
      1. Lift diagonal A (LF+RH up)
      2. Swing diagonal A forward, B backward (weight shift)
      3. Lift diagonal B (RF+LH up)
      4. Swing diagonal B forward, A backward (weight shift)
    """
    s = stand.copy()

    # Frame 1: Lift LF + RH (raise upper joints)
    f1 = s.copy()
    f1[0] = s[0] - lift    # LF upper: lift
    f1[1] = s[1] - lift    # LF lower: fold up
    f1[6] = s[6] + lift    # RH upper: lift (mirrored sign)
    f1[7] = s[7] + lift    # RH lower: fold up (mirrored sign)

    # Frame 2: Swing LF+RH forward, RF+LH backward (in air → on ground)
    f2 = s.copy()
    f2[0] = s[0] + swing   # LF upper: forward
    f2[6] = s[6] - swing   # RH upper: forward (mirrored)
    f2[2] = s[2] - swing   # RF upper: backward (mirrored, pushes body forward)
    f2[4] = s[4] - swing   # LH upper: backward (pushes body forward)

    # Frame 3: Lift RF + LH
    f3 = s.copy()
    f3[2] = s[2] + lift    # RF upper: lift (mirrored sign)
    f3[3] = s[3] + lift    # RF lower: fold up (mirrored sign)
    f3[4] = s[4] - lift    # LH upper: lift
    f3[5] = s[5] - lift    # LH lower: fold up

    # Frame 4: Swing RF+LH forward, LF+RH backward
    f4 = s.copy()
    f4[2] = s[2] - swing   # RF upper: forward (mirrored)
    f4[4] = s[4] + swing   # LH upper: forward
    f4[0] = s[0] - swing   # LF upper: backward (pushes body forward)
    f4[6] = s[6] + swing   # RH upper: backward (mirrored)

    return [f1, f2, f3, f4]


def main():
    parser = argparse.ArgumentParser(description="PiDog first walking gait")
    parser.add_argument("--cycles", type=int, default=4,
                        help="Number of gait cycles (default: 4)")
    parser.add_argument("--lift", type=int, default=LIFT_ANGLE,
                        help=f"Lift angle in degrees (default: {LIFT_ANGLE})")
    parser.add_argument("--swing", type=int, default=SWING_ANGLE,
                        help=f"Swing angle in degrees (default: {SWING_ANGLE})")
    parser.add_argument("--speed", type=int, default=STANCE_SPEED,
                        help=f"Movement speed 0-100 (default: {STANCE_SPEED})")
    parser.add_argument("--no-log", action="store_true",
                        help="Disable state logging")
    args = parser.parse_args()

    print("Initializing Pidog...")
    dog = Pidog()
    sleep(1.5)

    logger = None
    if not args.no_log:
        logger = StateLogger(dog, hz=50)

    try:
        # Stand up first
        print("Standing up...")
        dog.legs_move([STAND], immediately=True, speed=40)
        dog.wait_legs_done()
        sleep(1)

        # Generate gait frames
        frames = make_gait_frames(STAND, args.lift, args.swing)

        print(f"\nGait parameters:")
        print(f"  Stand:  {STAND}")
        print(f"  Lift:   {args.lift}°")
        print(f"  Swing:  {args.swing}°")
        print(f"  Speed:  {args.speed}")
        print(f"  Cycles: {args.cycles}")
        print(f"\nKeyframes:")
        for i, f in enumerate(frames):
            print(f"  F{i+1}: {f}")

        print(f"\nStarting gait in 2 seconds...")
        sleep(2)

        if logger:
            logger.start()

        print("Walking!")
        for cycle in range(args.cycles):
            for i, frame in enumerate(frames):
                dog.legs_move([frame], immediately=True, speed=args.speed)
                dog.wait_legs_done()
                sleep(0.05)  # Brief pause between frames

            print(f"  Cycle {cycle + 1}/{args.cycles}")

        # Return to stand
        print("\nReturning to stand...")
        dog.legs_move([STAND], immediately=True, speed=40)
        dog.wait_legs_done()
        sleep(0.5)

        if logger:
            filepath = logger.stop()
            print(f"\nLog saved: {filepath}")

        print("Done.")

    finally:
        dog.close()


if __name__ == "__main__":
    main()
