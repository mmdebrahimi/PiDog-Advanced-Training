#!/usr/bin/env python3
"""Verify PiDog hardware connectivity after I2C/SPI activation."""

from time import sleep
from robot_hat import I2C
from robot_hat.utils import reset_mcu

EXPECTED_DEVICES = {
    0x14: "Servo MCU (AT32F413)",
    0x36: "IMU (SH3001)",
    0x74: "RGB LED driver (SLED1735)",
}

print("=== PiDog Hardware Check ===\n")

print("Resetting MCU...")
reset_mcu()
sleep(0.5)

print("Scanning I2C bus 1...")
i2c = I2C(bus=1)
devices = i2c.scan()

print(f"Found {len(devices)} device(s):\n")
for addr in sorted(EXPECTED_DEVICES.keys()):
    name = EXPECTED_DEVICES[addr]
    found = addr in devices
    status = "OK" if found else "MISSING"
    print(f"  0x{addr:02x}  {name:40s} [{status}]")

unexpected = [d for d in devices if d not in EXPECTED_DEVICES]
if unexpected:
    print(f"\nUnexpected devices: {[hex(d) for d in unexpected]}")

print("\nInitializing Pidog...")
from pidog import Pidog

dog = Pidog()
sleep(1.5)

print(f"Leg init angles: {dog.leg_current_angles}")
print(f"IMU acc: {dog.accData}")
print(f"IMU gyro: {dog.gyroData}")
print(f"Distance: {dog.read_distance()} cm")

dog.close()
print("\nHardware check complete.")
