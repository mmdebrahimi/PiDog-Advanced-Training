#!/usr/bin/env python3
"""Auto-level the standing pose using IMU feedback.

The calibration tool caps offsets at +/-20, but three servos need more.
This script perturbs each capped servo, measures tilt response via IMU,
solves least-squares for the offset deltas that level the torso, applies
them, and prints the corrected offset list for pidog.conf.
"""

import math
import numpy as np
from pidog import Pidog
from time import sleep

CAPPED = [0, 2, 5]  # indexes in legs offset list pinned at +/-20
PROBE = 8.0         # degrees to perturb per servo for jacobian
MAX_ITER = 2


def measure_tilt(dog, samples=15):
    ax = ay = az = 0.0
    for _ in range(samples):
        acc = dog.accData
        ax += acc[0] / samples
        ay += acc[1] / samples
        az += acc[2] / samples
        sleep(0.05)
    roll = math.degrees(math.atan2(ay, -ax))
    pitch = math.degrees(math.atan2(az, -ax))
    return roll, pitch


def stand_and_measure(dog):
    dog.do_action('stand', speed=70)
    dog.wait_all_done()
    sleep(1.5)
    return measure_tilt(dog)


def main():
    dog = Pidog()
    sleep(1.5)
    try:
        base_offsets = list(dog.legs.offset)
        print(f'Current offsets: {[round(o, 1) for o in base_offsets]}')

        r0, p0 = stand_and_measure(dog)
        print(f'Baseline tilt: roll={r0:.1f} pitch={p0:.1f}')

        for it in range(MAX_ITER):
            # Build jacobian: tilt response per servo perturbation
            J = np.zeros((2, len(CAPPED)))
            for k, idx in enumerate(CAPPED):
                saved = dog.legs.offset[idx]
                dog.legs.offset[idx] = saved + PROBE
                r, p = stand_and_measure(dog)
                J[0, k] = (r - r0) / PROBE
                J[1, k] = (p - p0) / PROBE
                print(f'  probe servo[{idx}]: droll={r-r0:+.1f} dpitch={p-p0:+.1f}')
                dog.legs.offset[idx] = saved

            # Solve J @ delta = -[r0, p0]
            delta, *_ = np.linalg.lstsq(J, -np.array([r0, p0]), rcond=None)
            # Clamp step to avoid overshoot
            delta = np.clip(delta, -15, 15)
            print(f'Iteration {it+1} deltas: {[round(d, 1) for d in delta]}')

            for k, idx in enumerate(CAPPED):
                dog.legs.offset[idx] += float(delta[k])

            r0, p0 = stand_and_measure(dog)
            print(f'After iteration {it+1}: roll={r0:.1f} pitch={p0:.1f}')
            if abs(r0) < 3 and abs(p0) < 3:
                break

        final = [round(o, 2) for o in dog.legs.offset]
        print(f'FINAL offsets: {final}')
        print(f'FINAL tilt: roll={r0:.1f} pitch={p0:.1f}')

        sleep(2)
        dog.do_action('sit', speed=50)
        dog.wait_all_done()
    finally:
        dog.close()


if __name__ == '__main__':
    main()
