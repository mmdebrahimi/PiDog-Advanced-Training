#!/usr/bin/env python3
"""One-shot hardware checkup: P0/P3 verdicts + brownout headroom.
Run with HAT powered (green LED). Answers y/n prompts; prints verdict summary.
Single-servo wiggles are safe; the multi-servo stage asks before each step."""
from time import sleep


def ask(q):
    while True:
        a = input(f"{q} (y/n): ").strip().lower()
        if a in ("y", "n"):
            return a == "y"


def wiggle(port, amp=45):
    from robot_hat import Servo
    sv = Servo(f"P{port}")
    for a in (0, amp, -amp, 0):
        sv.angle(a)
        sleep(1.0)


def batt():
    from robot_hat import utils
    return utils.get_battery_voltage()


def main():
    v = batt()
    print(f"Battery: {v:.2f} V")
    if v < 6.0:
        print("ABORT: no servo power — HAT off or battery dead/unplugged.")
        return
    if not ask("Is the dog placed safely (not near a table edge)?"):
        print("Place it safely, rerun.")
        return

    swapped = ask("Is the PWM0<->PWM9 cable swap still in place (back-left shin on P9, tail on P0)?")
    results = {}

    print("\n--- Wiggling P9 now, watch:", "BACK-LEFT SHIN" if swapped else "TAIL")
    wiggle(9)
    results["p9"] = ask("Did it move?")

    print("\n--- Wiggling P0 now, watch:", "TAIL" if swapped else "BACK-LEFT SHIN")
    wiggle(0)
    results["p0"] = ask("Did it move?")

    print("\n--- Wiggling P3 now, watch: FRONT-LEFT SHIN")
    wiggle(3)
    results["p3"] = ask("Did it move?")

    print("\n===== VERDICTS =====")
    if swapped:
        print("Back-left shin SERVO:", "ALIVE (so P0 channel was the fault)" if results["p9"] else "DEAD — needs replacement")
        print("P0 HAT channel:", "GOOD" if results["p0"] else "DEAD (tail servo is known-good)")
    else:
        print("P9/tail:", "ok" if results["p9"] else "UNEXPECTED FAIL")
        print("Back-left shin on P0:", "moves now!" if results["p0"] else "still dead (servo or channel — do the swap test)")
    print("Front-left shin (P3):", "ALIVE — was a seating issue" if results["p3"] else "still dead — next: swap its cable onto a good port")

    # ---- brownout headroom (known-good servos only) ----
    if not ask("\nRun brownout headroom test (moves several legs a little, Pi may reboot)?"):
        print("Skipped. Done.")
        return
    groups = [["2", "7"], ["2", "7", "10", "1"], ["2", "7", "10", "1", "8", "11"]]
    from robot_hat import Servo
    for g in groups:
        v = batt()
        print(f"\nBattery {v:.2f} V — moving {len(g)} servos simultaneously (P{', P'.join(g)}), ±10")
        if not ask("Proceed?"):
            break
        svs = [Servo(f"P{p}") for p in g]
        for a in (10, -10, 0):
            for sv in svs:
                sv.angle(a)
            sleep(0.8)
        print(f"Survived {len(g)} simultaneous servos.")
    print(f"\nFinal battery: {batt():.2f} V. Done — report results back to Claude.")


if __name__ == "__main__":
    main()
