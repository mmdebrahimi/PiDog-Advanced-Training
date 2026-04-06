#!/usr/bin/env python3
"""Verify all PiDog sensors are functional."""

from time import sleep, time

print("=== PiDog Sensor Check ===\n")

print("Initializing Pidog...")
from pidog import Pidog
dog = Pidog()
sleep(1.5)
print("Ready.\n")

results = {}

try:
    # IMU
    print("--- IMU (SH3001) ---")
    samples = []
    for i in range(10):
        ax, ay, az = dog.accData
        gx, gy, gz = dog.gyroData
        samples.append((ax, ay, az, gx, gy, gz))
        sleep(0.1)

    last = samples[-1]
    has_gravity = any(abs(v) > 10000 for v in last[:3])
    print(f"  Acc:  [{last[0]:.0f}, {last[1]:.0f}, {last[2]:.0f}]")
    print(f"  Gyro: [{last[3]:.0f}, {last[4]:.0f}, {last[5]:.0f}]")
    print(f"  Pitch: {dog.pitch:.1f}°  Roll: {dog.roll:.1f}°")
    print(f"  Gravity detected: {'YES' if has_gravity else 'NO'}")
    results["IMU"] = "OK" if has_gravity else "FAIL"

    # Ultrasonic
    print("\n--- Ultrasonic Distance ---")
    distances = []
    for i in range(5):
        d = dog.read_distance()
        distances.append(d)
        sleep(0.2)
    valid = [d for d in distances if d > 0]
    if valid:
        print(f"  Readings: {[f'{d:.1f}cm' for d in distances]}")
        print(f"  Average: {sum(valid)/len(valid):.1f} cm")
        results["Ultrasonic"] = "OK"
    else:
        print(f"  No valid readings (all <= 0)")
        results["Ultrasonic"] = "FAIL"

    # RGB LEDs
    print("\n--- RGB LED Strip ---")
    try:
        dog.rgb_strip.set_mode("monochromatic", "green", brightness=0.5)
        sleep(1.5)
        dog.rgb_strip.set_mode("breath", "black")
        sleep(0.5)
        print("  Set green briefly — check if LEDs flashed")
        results["RGB"] = "OK"
    except Exception as e:
        print(f"  Error: {e}")
        results["RGB"] = "FAIL"

    # Dual Touch
    print("\n--- Dual Touch Sensors ---")
    try:
        touch = dog.dual_touch.read()
        print(f"  Current state: '{touch}' (N=none, L=rear, R=front)")
        results["Touch"] = "OK"
    except Exception as e:
        print(f"  Error: {e}")
        results["Touch"] = "FAIL"

    # Sound Direction
    print("\n--- Sound Direction ---")
    try:
        direction = dog.ears.read()
        detected = dog.ears.isdetected()
        print(f"  Direction: {direction}° (detected: {detected})")
        results["Sound Direction"] = "OK"
    except Exception as e:
        print(f"  Error: {e}")
        results["Sound Direction"] = "FAIL"

    # Summary
    print("\n=== Sensor Summary ===\n")
    for name, status in results.items():
        marker = "OK" if status == "OK" else "FAIL"
        print(f"  {name:20s} [{marker}]")

finally:
    dog.close()

print("\nSensor check complete.")
