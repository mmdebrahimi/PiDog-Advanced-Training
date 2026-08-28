#!/usr/bin/env python3
"""Test user hypothesis: back-left HIP (idx 4) command sign is inverted.

Sequence: zero -> normal sit BUT with idx4 flipped (-80 instead of +80).
Optional: pass 'knee' as arg to ALSO flip idx5 (-45 -> +45).

Usage: python3 sit_flip_test.py [knee]
"""

import sys
from pidog import Pidog
from time import sleep

flip_knee = len(sys.argv) > 1 and sys.argv[1] == 'knee'

# stock sit: [30, 60, -30, -60, 80, -45, -80, 45]
sit = [30, 60, -30, -60, -80, -45, -80, 45]  # idx4 flipped
if flip_knee:
    sit[5] = 45

dog = Pidog()
sleep(1.5)
try:
    print('-> zero')
    dog.legs_move([[0] * 8], immediately=True, speed=40)
    dog.wait_all_done()
    sleep(2)

    print(f'-> sit with LH hip FLIPPED (idx4=-80{", idx5=+45" if flip_knee else ""})')
    print('   WATCH THE BACK-LEFT THIGH: should now rotate BACKWARD like the right one')
    dog.legs_move([sit], immediately=True, speed=25)
    dog.wait_all_done()
    sleep(4)

    print('-> back to zero')
    dog.legs_move([[0] * 8], immediately=True, speed=30)
    dog.wait_all_done()
finally:
    dog.close()
print('DONE')
