#!/usr/bin/env python3
"""Drive all leg servos to true zero (no offsets) and hold for horn re-mounting.

With servos at zero, each leg segment should point straight down per the
assembly manual. Re-seat any segment that sits crooked — that horn is
mounted off by a tooth.
"""

from pidog import Pidog
from time import sleep

dog = Pidog()
sleep(1.5)
try:
    # Kill offsets in memory — we want TRUE servo zero as the reference
    dog.legs.offset = [0.0] * 8
    dog.head.offset = [0.0] * 3
    dog.tail.offset = [0.0] * 1

    print('Moving all servos to TRUE ZERO...')
    dog.legs_move([[0, 0, 0, 0, 0, 0, 0, 0]], immediately=True, speed=30)
    dog.head_move_raw([[0, 0, 0]], immediately=True, speed=30)
    dog.tail_move([[0]], immediately=True, speed=30)
    dog.wait_all_done()
    sleep(1)
    print('HOLDING at zero. Re-mount horns now.')
    print('Every leg segment should point STRAIGHT DOWN.')
    print('Holding for 60 minutes — Ctrl+C or kill when done.')
    for i in range(60):
        sleep(60)
        print(f'  still holding... {59 - i} min left')
finally:
    dog.close()
