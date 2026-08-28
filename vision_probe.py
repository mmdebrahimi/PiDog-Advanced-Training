#!/usr/bin/env python3
"""Camera-in-the-loop servo probe.

Runs a sequence of poses; captures a labeled photo while each pose is held.
The photos let Claude analyze what each action physically does and
iteratively fix the leg geometry.
"""

import sys
import cv2
from pidog import Pidog
from time import sleep

CAM_INDEX = 0
OUT = 'captures'

cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
for _ in range(10):
    cap.read()


def shot(label):
    for _ in range(5):  # flush stale buffer frames
        cap.read()
    ok, frame = cap.read()
    if ok:
        path = f'{OUT}/{label}.jpg'
        cv2.imwrite(path, frame)
        print(f'  [shot] {label}')
    else:
        print(f'  [shot FAILED] {label}')


Z = [0] * 8

dog = Pidog()
sleep(1.5)
try:
    shot('01_init_lie')

    dog.legs_move([Z], immediately=True, speed=40)
    dog.wait_all_done(); sleep(2)
    shot('02_zero')

    a = Z.copy(); a[4] = 30
    dog.legs_move([a], immediately=True, speed=30)
    dog.wait_all_done(); sleep(2)
    shot('03_LH_hip_plus30')
    dog.legs_move([Z], immediately=True, speed=30)
    dog.wait_all_done(); sleep(1)

    a = Z.copy(); a[5] = 30
    dog.legs_move([a], immediately=True, speed=30)
    dog.wait_all_done(); sleep(2)
    shot('04_LH_knee_plus30')
    dog.legs_move([Z], immediately=True, speed=30)
    dog.wait_all_done(); sleep(1)

    a = Z.copy(); a[5] = -30
    dog.legs_move([a], immediately=True, speed=30)
    dog.wait_all_done(); sleep(2)
    shot('05_LH_knee_minus30')
    dog.legs_move([Z], immediately=True, speed=30)
    dog.wait_all_done(); sleep(1)

    # mirrored rear pose: LH +30/+15, RH -30/-15
    a = Z.copy(); a[4], a[5], a[6], a[7] = 30, 15, -30, -15
    dog.legs_move([a], immediately=True, speed=30)
    dog.wait_all_done(); sleep(2)
    shot('06_rear_mirror_pose')
    dog.legs_move([Z], immediately=True, speed=30)
    dog.wait_all_done(); sleep(1)

    dog.do_action('stand', speed=10)
    dog.wait_all_done(); sleep(2)
    shot('07_stand')
    sleep(2)
    shot('08_stand_hold')

    dog.do_action('lie', speed=15)
    dog.wait_all_done(); sleep(2)
    shot('09_lie')
finally:
    cap.release()
    dog.close()
print('PROBE COMPLETE')
