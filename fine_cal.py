#!/usr/bin/env python3
"""Camera-based fine calibration capture.

Init with current pidog.conf offsets, command zero, hold, capture a
full-res frame, exit. Claude analyzes joint plumb/level per iteration.

Usage: python3 fine_cal.py <label>
"""

import sys
import cv2
from pidog import Pidog
from time import sleep

label = sys.argv[1] if len(sys.argv) > 1 else 'cal'

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
for _ in range(10):
    cap.read()

dog = Pidog()
sleep(1.0)
try:
    print('offsets:', [round(o, 2) for o in dog.legs.offset])
    dog.legs_move([[0] * 8], immediately=True, speed=40)
    dog.wait_all_done()
    print('HANDS CLEAR — capturing in:')
    for i in range(8, 0, -1):
        print(f'  {i}...')
        sleep(1)
    for _ in range(5):
        cap.read()
    ok, frame = cap.read()
    if ok:
        cv2.imwrite(f'captures/{label}.jpg', frame)
        print(f'captured {label}.jpg {frame.shape}')
    else:
        print('CAPTURE FAILED')
finally:
    cap.release()
    dog.close()
