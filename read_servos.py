#!/usr/bin/env python3
"""Read current servo positions directly from MCU I2C registers.

Does NOT reset the MCU or move any servos. Safe to run while the dog is active.

Usage:
    python3 read_servos.py          # Print current positions
    python3 read_servos.py --save   # Save to ~/.config/pidog/saved_pose.json
"""

import json
import os
import sys
from smbus2 import SMBus

MCU_ADDRS = [0x14, 0x15, 0x16]
REG_CHN = 0x20
PERIOD = 4095
MIN_PW = 500
MAX_PW = 2500

SERVO_NAMES = {
    0: 'RL_upper', 1: 'RL_lower', 2: 'FL_upper', 3: 'FL_lower',
    4: 'head_yaw', 5: 'head_pitch', 6: 'head_roll',
    7: 'FR_upper', 8: 'FR_lower', 9: 'tail',
    10: 'RR_upper', 11: 'RR_lower',
}

# ActionFlow leg order
LEG_ORDER = [2, 3, 7, 8, 0, 1, 10, 11]
LEG_NAMES = ['FL_upper', 'FL_lower', 'FR_upper', 'FR_lower',
             'RL_upper', 'RL_lower', 'RR_upper', 'RR_lower']


def read_servo_angles():
    """Read all 12 servo angles from MCU without reset."""
    bus = SMBus(1)

    mcu_addr = None
    for addr in MCU_ADDRS:
        try:
            bus.read_byte(addr)
            mcu_addr = addr
            break
        except OSError:
            continue

    if not mcu_addr:
        bus.close()
        raise RuntimeError('MCU not found on I2C bus')

    angles = {}
    for ch in range(12):
        reg = REG_CHN + ch
        try:
            data = bus.read_i2c_block_data(mcu_addr, reg, 2)
            raw = (data[0] << 8) | data[1]
            if raw == 0:
                angles[ch] = None  # No PWM set (MCU was reset)
            else:
                pw_time = raw / PERIOD * 20000
                angle = (pw_time - MIN_PW) / (MAX_PW - MIN_PW) * 180 - 90
                angles[ch] = round(angle, 1)
        except Exception:
            angles[ch] = None

    bus.close()
    return angles


def main():
    save = '--save' in sys.argv

    angles = read_servo_angles()

    # Check if any servos are active
    active = any(v is not None for v in angles.values())
    if not active:
        print("All servos read 0 — MCU was reset or no PWM active.")
        print("Run this while the companion is active to capture live positions.")
        return

    print("=== Current Servo Positions ===\n")
    for ch in range(12):
        name = SERVO_NAMES.get(ch, f'ch{ch}')
        val = angles[ch]
        if val is not None:
            print(f"  {ch:2d}  {name:15s}  {val:+7.1f}°")
        else:
            print(f"  {ch:2d}  {name:15s}  (inactive)")

    leg_angles = [angles.get(p) for p in LEG_ORDER]
    head_angles = [angles.get(4), angles.get(6), angles.get(5)]  # yaw, roll, pitch
    tail_angle = angles.get(9)

    print(f"\nLegs (ActionFlow order): {leg_angles}")
    print(f"Head [yaw, roll, pitch]: {head_angles}")
    print(f"Tail: {tail_angle}")

    if save:
        pose = {
            "legs": leg_angles,
            "head": head_angles,
            "tail": tail_angle,
            "raw": {SERVO_NAMES[k]: v for k, v in angles.items()},
        }
        save_path = os.path.expanduser("~/.config/pidog/saved_pose.json")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'w') as f:
            json.dump(pose, f, indent=2)
        print(f"\nSaved to {save_path}")


if __name__ == '__main__':
    main()
