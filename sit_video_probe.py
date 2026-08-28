#!/usr/bin/env python3
"""Video-mode sit probe: record continuously at ~30fps during the whole
zero->sit->hold sequence, timestamping every frame and every action marker
so frames can be correlated with commanded motion.

Usage: python3 sit_video_probe.py <run-label> [dLH] [dLK] [dRH] [dRK]
  deltas: left-hip(idx4) left-knee(idx5) right-hip(idx6) right-knee(idx7)
"""

import os
import sys
import threading
import cv2
from pidog import Pidog
from time import sleep, time

label = sys.argv[1] if len(sys.argv) > 1 else 'v1'
dLH = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
dLK = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
dRH = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
dRK = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0

OUT = f'captures/video_{label}'
os.makedirs(OUT, exist_ok=True)

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)
for _ in range(10):
    cap.read()

recording = True
t0 = time()
frame_count = 0


def recorder():
    global frame_count
    while recording:
        ok, frame = cap.read()
        if ok:
            ms = int((time() - t0) * 1000)
            cv2.imwrite(f'{OUT}/f{ms:06d}.jpg', frame,
                        [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_count += 1


def mark(msg):
    ms = int((time() - t0) * 1000)
    print(f'MARK {ms:06d}ms {msg}')


rec_thread = threading.Thread(target=recorder, daemon=True)
rec_thread.start()

dog = Pidog()
sleep(1.0)
try:
    dog.legs.offset[4] += dLH
    dog.legs.offset[5] += dLK
    dog.legs.offset[6] += dRH
    dog.legs.offset[7] += dRK
    mark(f'init done, deltas LH={dLH} LK={dLK} RH={dRH} RK={dRK}')

    mark('-> zero')
    dog.legs_move([[0] * 8], immediately=True, speed=40)
    dog.wait_all_done()
    mark('zero reached')
    sleep(1.5)

    mark('-> sit')
    dog.do_action('sit', speed=25)
    dog.wait_all_done()
    mark('sit reached')
    sleep(2)
    mark('hold done')
finally:
    recording = False
    rec_thread.join(timeout=2)
    cap.release()
    dog.close()

print(f'RECORDED {frame_count} frames to {OUT}/')
