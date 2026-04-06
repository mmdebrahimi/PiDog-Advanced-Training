#!/usr/bin/env python3
"""Background state logger for PiDog.

Records joint angles, IMU data, and sensor readings at a fixed rate to CSV.
Designed to run alongside any control code.

Usage as module:
    from state_logger import StateLogger
    logger = StateLogger(dog, hz=50)
    logger.start()
    # ... do control stuff ...
    logger.stop()  # returns filepath

Usage standalone (records for N seconds):
    python3 state_logger.py [--seconds=10] [--hz=50] [--output=logs/]
"""

import csv
import os
import threading
from time import sleep, time
from datetime import datetime


class StateLogger:
    """Logs PiDog state to CSV at a fixed rate in a background thread."""

    FIELDS = [
        "timestamp",
        # Leg joint angles (commanded positions from Pidog internals)
        "leg_0", "leg_1", "leg_2", "leg_3",
        "leg_4", "leg_5", "leg_6", "leg_7",
        # Head joint angles
        "head_yaw", "head_roll", "head_pitch",
        # Tail
        "tail",
        # IMU accelerometer (raw)
        "acc_x", "acc_y", "acc_z",
        # IMU gyroscope (raw)
        "gyro_x", "gyro_y", "gyro_z",
        # Fused orientation
        "pitch", "roll",
        # Ultrasonic
        "distance_cm",
    ]

    def __init__(self, dog, hz=50, output_dir="logs"):
        self.dog = dog
        self.hz = hz
        self.interval = 1.0 / hz
        self.output_dir = output_dir
        self._stop_event = threading.Event()
        self._thread = None
        self._filepath = None
        self._sample_count = 0
        self._drop_count = 0

    def start(self):
        """Start logging in a background thread. Returns the output filepath."""
        os.makedirs(self.output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._filepath = os.path.join(self.output_dir, f"state_{ts}.csv")
        self._stop_event.clear()
        self._sample_count = 0
        self._drop_count = 0

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"Logging started: {self._filepath} @ {self.hz}Hz")
        return self._filepath

    def stop(self):
        """Stop logging and return the filepath."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        duration = self._sample_count * self.interval
        actual_hz = self._sample_count / duration if duration > 0 else 0
        print(f"Logging stopped: {self._sample_count} samples in {duration:.1f}s "
              f"({actual_hz:.1f}Hz actual, {self._drop_count} drops)")
        return self._filepath

    @property
    def filepath(self):
        return self._filepath

    @property
    def sample_count(self):
        return self._sample_count

    def _read_state(self):
        """Read current robot state. Returns a dict matching FIELDS."""
        dog = self.dog
        t = time()

        legs = dog.leg_current_angles if dog.leg_current_angles else [0] * 8
        head = dog.head_current_angles if dog.head_current_angles else [0] * 3
        tail = dog.tail_current_angles if dog.tail_current_angles else [0]

        acc = dog.accData if dog.accData else [0, 0, 0]
        gyro = dog.gyroData if dog.gyroData else [0, 0, 0]

        return {
            "timestamp": f"{t:.4f}",
            "leg_0": legs[0], "leg_1": legs[1], "leg_2": legs[2], "leg_3": legs[3],
            "leg_4": legs[4], "leg_5": legs[5], "leg_6": legs[6], "leg_7": legs[7],
            "head_yaw": head[0], "head_roll": head[1], "head_pitch": head[2],
            "tail": tail[0],
            "acc_x": acc[0], "acc_y": acc[1], "acc_z": acc[2],
            "gyro_x": gyro[0], "gyro_y": gyro[1], "gyro_z": gyro[2],
            "pitch": dog.pitch, "roll": dog.roll,
            "distance_cm": dog.read_distance(),
        }

    def _run(self):
        """Background logging loop."""
        with open(self._filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDS)
            writer.writeheader()

            while not self._stop_event.is_set():
                t_start = time()

                state = self._read_state()
                writer.writerow(state)
                self._sample_count += 1

                # Flush every 100 samples (~2s at 50Hz)
                if self._sample_count % 100 == 0:
                    f.flush()

                # Sleep for remaining interval
                elapsed = time() - t_start
                remaining = self.interval - elapsed
                if remaining > 0:
                    sleep(remaining)
                else:
                    self._drop_count += 1

            f.flush()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="PiDog state logger")
    parser.add_argument("--seconds", type=float, default=10,
                        help="Duration to log (default: 10)")
    parser.add_argument("--hz", type=int, default=50,
                        help="Sample rate (default: 50)")
    parser.add_argument("--output", default="logs",
                        help="Output directory (default: logs/)")
    args = parser.parse_args()

    print("Initializing Pidog...")
    from pidog import Pidog
    dog = Pidog()
    sleep(1.5)

    logger = StateLogger(dog, hz=args.hz, output_dir=args.output)

    try:
        filepath = logger.start()
        print(f"Recording for {args.seconds}s...")
        sleep(args.seconds)
        logger.stop()

        # Print summary
        print(f"\nFile: {filepath}")
        print(f"Samples: {logger.sample_count}")

        # Show first and last few lines
        with open(filepath) as f:
            lines = f.readlines()
        print(f"Columns: {lines[0].strip()}")
        if len(lines) > 2:
            print(f"First:   {lines[1].strip()}")
            print(f"Last:    {lines[-1].strip()}")

    finally:
        dog.close()


if __name__ == "__main__":
    main()
