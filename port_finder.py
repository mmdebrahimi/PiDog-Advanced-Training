#!/usr/bin/env python3
"""Type a port number, that ONE servo wiggles, you write down which body part moved.
Only one servo moves at a time — no brownout risk."""
from robot_hat import Servo
from time import sleep

print("Port finder: type 0-11 and press Enter -> that port wiggles (+15, -15, back to 0).")
print("Repeat a number as often as you like. Type q to quit.\n")

while True:
    s = input("Port (0-11, q=quit): ").strip().lower()
    if s == "q":
        break
    if not s.isdigit() or not (0 <= int(s) <= 11):
        print("  need a number 0-11")
        continue
    sv = Servo(f"P{s}")
    for a in (0, 15, -15, 0):
        sv.angle(a)
        sleep(0.6)
    print(f"  P{s} done — which part moved?")
