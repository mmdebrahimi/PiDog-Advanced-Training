#!/usr/bin/env python3
"""Type a port number, that ONE servo wiggles, you write down which body part moved.
Only one servo moves at a time — no brownout risk."""
from robot_hat import Servo
from time import sleep

print("Port finder: type 0-11 and press Enter -> that port wiggles (+15, -15, back to 0).")
print("Repeat a number as often as you like. Type q to quit.\n")

while True:
    s = input("Port (0-11, optional amplitude e.g. '3 45', q=quit): ").strip().lower()
    if s == "q":
        break
    parts = s.split()
    if not parts or not parts[0].isdigit() or not (0 <= int(parts[0]) <= 11):
        print("  need a number 0-11")
        continue
    amp = 15
    if len(parts) > 1 and parts[1].lstrip("-").isdigit():
        amp = min(abs(int(parts[1])), 60)
    sv = Servo(f"P{parts[0]}")
    for a in (0, amp, -amp, 0):
        sv.angle(a)
        sleep(1.0)
    print(f"  P{parts[0]} done (±{amp}) — which part moved?")
