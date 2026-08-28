#!/usr/bin/env python3
"""IMU-driven stand leveling v2 — all 8 leg servos, small probes.

Hardware prerequisites (all fixed 2026-08-10): healthy knee servo,
factory-correct horn mounting, fully seated PWM connectors.

Probes each servo +/-6 deg at stand, builds a tilt jacobian, solves
least-squares for offsets that level the body, iterates.
"""

import math
import numpy as np
from pidog import Pidog
from time import sleep

PROBE = 6.0
MAX_ITER = 3
TARGET = 3.0  # deg


def tilt(dog, n=15):
    ax = ay = az = 0.0
    for _ in range(n):
        a = dog.accData
        ax += a[0] / n
        ay += a[1] / n
        az += a[2] / n
        sleep(0.04)
    roll = math.degrees(math.atan2(ay, -ax))
    pitch = math.degrees(math.atan2(az, -ax))
    return roll, pitch


def stand_measure(dog):
    dog.do_action('stand', speed=70)
    dog.wait_all_done()
    sleep(1.2)
    return tilt(dog)


def main():
    dog = Pidog()
    sleep(1.0)
    try:
        print('offsets at start:', [round(o, 1) for o in dog.legs.offset])
        r0, p0 = stand_measure(dog)
        print(f'baseline: roll={r0:+.1f} pitch={p0:+.1f}')
        if abs(r0) < TARGET and abs(p0) < TARGET:
            print('ALREADY LEVEL')
            return

        for it in range(MAX_ITER):
            J = np.zeros((2, 8))
            for i in range(8):
                saved = dog.legs.offset[i]
                dog.legs.offset[i] = saved + PROBE
                r, p = stand_measure(dog)
                J[0, i] = (r - r0) / PROBE
                J[1, i] = (p - p0) / PROBE
                dog.legs.offset[i] = saved
                print(f'  probe s{i}: dr={r-r0:+.1f} dp={p-p0:+.1f}')

            delta, *_ = np.linalg.lstsq(J, -np.array([r0, p0]), rcond=None)
            delta = np.clip(delta, -10, 10)
            print(f'iter {it+1} deltas: {[round(float(d),1) for d in delta]}')
            for i in range(8):
                dog.legs.offset[i] += float(delta[i])

            r0, p0 = stand_measure(dog)
            print(f'iter {it+1} result: roll={r0:+.1f} pitch={p0:+.1f}')
            if abs(r0) < TARGET and abs(p0) < TARGET:
                break

        final = [round(o, 2) for o in dog.legs.offset]
        print(f'FINAL offsets: {final}')
        print(f'FINAL tilt: roll={r0:+.1f} pitch={p0:+.1f}')
        print('If good, write these to pidog.conf legs_servo_offset_list')

        sleep(2)
        dog.do_action('sit', speed=50)
        dog.wait_all_done()
    finally:
        dog.close()


if __name__ == '__main__':
    main()
