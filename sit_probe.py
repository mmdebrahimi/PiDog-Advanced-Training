#!/usr/bin/env python3
"""Sit-pose iteration probe.

Each run: capture zero pose + sit pose photos, with optional runtime
offset deltas applied to the back-left leg for iterative correction.

Usage: python3 sit_probe.py <iteration> [dh] [dk]
  iteration: label number for the photos
  dh: offset delta for back-left HIP (idx 4), default 0
  dk: offset delta for back-left KNEE (idx 5), default 0
"""

import sys
import cv2
from pidog import Pidog
from time import sleep

it = sys.argv[1] if len(sys.argv) > 1 else 'x'
dh = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
dk = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
for _ in range(10):
    cap.read()


def shot(label):
    for _ in range(5):
        cap.read()
    ok, frame = cap.read()
    if ok:
        cv2.imwrite(f'captures/it{it}_{label}.jpg', frame)
        print(f'  [shot] it{it}_{label}')


dog = Pidog()
sleep(1.5)
try:
    # Apply iteration deltas to back-left leg offsets (runtime only)
    dog.legs.offset[4] += dh
    dog.legs.offset[5] += dk
    print(f'deltas: hip={dh} knee={dk} -> offsets {dog.legs.offset}')

    dog.legs_move([[0] * 8], immediately=True, speed=40)
    dog.wait_all_done(); sleep(2)
    shot('zero')

    dog.do_action('sit', speed=25)
    dog.wait_all_done(); sleep(3)
    shot('sit')
    sleep(2)
    shot('sit_hold')
finally:
    cap.release()
    dog.close()
print('SIT PROBE DONE')
