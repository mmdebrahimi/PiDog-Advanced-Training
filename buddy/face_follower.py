#!/usr/bin/env python3
"""Face detection, head tracking, and person following for PiDog.

Uses picamera2 + OpenCV Haar cascade for face detection.
Shows live video with face detection overlay on the HDMI monitor.
Head servos track the detected face. Optional body following.

Standalone:
    python3 -m buddy.face_follower              # With dog + video
    python3 -m buddy.face_follower --video-only  # Video only, no dog
"""

import threading
import cv2
import numpy as np
from time import sleep, time
from picamera2 import Picamera2
from .servo_controller import ServoController

CASCADE_PATHS = [
    "/opt/vilib/haarcascade_frontalface_default.xml",
    "/home/pidog/pidog_lab/vilib/workspace/haarcascade_frontalface_default.xml",
]

FRAME_W, FRAME_H = 640, 480


class FaceFollower:
    """Detects faces, shows live video, tracks with head servos."""

    # Head servo limits
    YAW_MIN, YAW_MAX = -80, 80
    PITCH_MIN, PITCH_MAX = -30, 30
    PITCH_COMP = -40

    # Body following thresholds
    FACE_FAR = 120
    FACE_CLOSE = 280
    YAW_TURN_THRESHOLD = 30

    # Timing
    LOOP_HZ = 20
    FACE_LOST_TIMEOUT = 2.0

    # Sound direction
    DEFAULT_PITCH = 20  # Look up toward humans by default

    # Sweep fallback
    SWEEP_MIN, SWEEP_MAX = -60, 60
    SWEEP_SPEED = 10  # degrees per second
    SWEEP_TIMEOUT = 3.0  # seconds with no face/sound before sweeping

    def __init__(self, dog_behavior=None, show_video=True):
        """
        Args:
            dog_behavior: DogBehavior instance (None = video only, no head tracking)
            show_video: Show live video window on HDMI monitor
        """
        self.dog = dog_behavior
        self.show_video = show_video
        self.follow_mode = False
        self._running = False
        self._thread = None

        # Servo controller (Kalman + PID + EMA)
        self._servo = ServoController(
            FRAME_W, FRAME_H,
            yaw_limits=(self.YAW_MIN, self.YAW_MAX),
            pitch_limits=(self.PITCH_MIN, self.PITCH_MAX),
        )
        self._servo.reset(yaw=0.0, pitch=self.DEFAULT_PITCH)

        # Head state (kept in sync with servo controller for external access)
        self.yaw = 0.0
        self.pitch = float(self.DEFAULT_PITCH)

        # Tracking state
        self._tracking = False
        self._last_face_time = 0
        self._last_sound_time = 0
        self._sweep_direction = 1  # 1 = moving right, -1 = moving left
        self._face_info = {"x": 0, "y": 0, "w": 0, "n": 0}

        # Camera + detector
        self._camera = None
        self._cascade = None
        self._latest_frame = None
        self._frame_lock = threading.Lock()

        # Load Haar cascade
        for path in CASCADE_PATHS:
            self._cascade = cv2.CascadeClassifier(path)
            if not self._cascade.empty():
                break
        else:
            raise RuntimeError("Haar cascade model not found.")

    def start(self):
        """Start camera, face detection, and video display."""
        if self._running:
            return

        if self._camera is None:
            print("Starting camera...")
            self._camera = Picamera2(0)
            cam_config = self._camera.create_preview_configuration(
                main={"size": (FRAME_W, FRAME_H), "format": "RGB888"}
            )
            self._camera.configure(cam_config)
            self._camera.start()
            sleep(0.5)
            print("Camera started.")

        self._running = True
        self._thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self._thread.start()

        if self.show_video:
            print("Video window opening on monitor...")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._tracking = False

    def close(self):
        self.stop()
        if self.show_video:
            cv2.destroyAllWindows()
        if self._camera:
            self._camera.stop()
            self._camera.close()
            self._camera = None

    def set_follow_mode(self, enabled):
        self.follow_mode = enabled

    def is_tracking(self):
        return self._tracking

    def get_face_info(self):
        return self._face_info.copy()

    def center_head(self):
        self.yaw = 0.0
        self.pitch = float(self.DEFAULT_PITCH)
        self._servo.reset(yaw=0.0, pitch=float(self.DEFAULT_PITCH))
        if self.dog:
            self.dog.dog.head_move(
                [[0, 0, self.DEFAULT_PITCH]], pitch_comp=self.PITCH_COMP,
                immediately=True, speed=60
            )

    def update_video(self):
        """Call this from the main thread to update the video window.
        OpenCV imshow must run in the main thread on most platforms.
        Returns False if window was closed."""
        if not self.show_video:
            return True

        with self._frame_lock:
            frame = self._latest_frame

        if frame is not None:
            # Convert RGB to BGR for OpenCV display
            display = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            cv2.imshow("PiDog Camera", display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:  # q or ESC
            return False
        return True

    def _detect_faces(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        small = cv2.resize(gray, (320, 240))
        faces = self._cascade.detectMultiScale(
            small, scaleFactor=1.2, minNeighbors=5, minSize=(30, 30)
        )
        return [(x * 2, y * 2, w * 2, h * 2) for (x, y, w, h) in faces]

    def _draw_overlay(self, frame, faces):
        """Draw face rectangles and tracking info on frame."""
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, f"Face {w}x{h}", (x, y - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # Status bar
        status = f"Faces: {len(faces)} | Yaw: {self.yaw:+.0f} | Pitch: {self.pitch:+.0f}"
        if self._tracking:
            status += " | TRACKING"
        if self.follow_mode:
            status += " | FOLLOW"
        cv2.putText(frame, status, (10, FRAME_H - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        # Crosshair at center
        cx, cy = FRAME_W // 2, FRAME_H // 2
        cv2.line(frame, (cx - 15, cy), (cx + 15, cy), (0, 0, 255), 1)
        cv2.line(frame, (cx, cy - 15), (cx, cy + 15), (0, 0, 255), 1)

        return frame

    def _tracking_loop(self):
        interval = 1.0 / self.LOOP_HZ

        while self._running:
            t_start = time()

            try:
                frame = self._camera.capture_array()
            except Exception:
                sleep(0.1)
                continue

            faces = self._detect_faces(frame)

            if faces:
                largest = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = largest
                face_cx = fx + fw // 2
                face_cy = fy + fh // 2

                self._face_info = {"x": face_cx, "y": face_cy, "w": fw, "n": len(faces)}
                if not self._tracking:
                    self._servo.set_mode('lockon')
                self._tracking = True
                self._last_face_time = time()

                if self.dog:
                    self._track_head(face_cx, face_cy)
                if self.follow_mode and self.dog:
                    self._follow_body(fw)
            else:
                self._face_info = {"x": 0, "y": 0, "w": 0, "n": 0}
                now = time()

                if self.dog and self._try_sound_direction():
                    # Sound detected — head snapped toward voice
                    self._last_sound_time = now
                elif self._tracking and now - self._last_face_time > self.FACE_LOST_TIMEOUT:
                    self._tracking = False
                elif (self.dog and not self._tracking
                      and now - max(self._last_face_time, self._last_sound_time) > self.SWEEP_TIMEOUT):
                    self._sweep_step(interval)

            # Draw overlay and store for video display
            if self.show_video:
                annotated = self._draw_overlay(frame.copy(), faces)
                with self._frame_lock:
                    self._latest_frame = annotated

            elapsed = time() - t_start
            remaining = interval - elapsed
            if remaining > 0:
                sleep(remaining)

    def _track_head(self, face_x, face_y):
        self.yaw, self.pitch = self._servo.update(face_x, face_y)
        self.dog.dog.head_move(
            [[self.yaw, 0, self.pitch]], pitch_comp=self.PITCH_COMP,
            immediately=True, speed=80
        )

    def _follow_body(self, face_w):
        if face_w < self.FACE_FAR:
            if self.yaw > self.YAW_TURN_THRESHOLD:
                self.dog.dog.do_action("turn_right", speed=98)
            elif self.yaw < -self.YAW_TURN_THRESHOLD:
                self.dog.dog.do_action("turn_left", speed=98)
            else:
                self.dog.dog.do_action("forward", speed=98)


    def _sweep_step(self, dt):
        """Advance one step of the slow yaw sweep while looking up."""
        self._servo.set_mode('sweep')
        self.yaw += self._sweep_direction * self.SWEEP_SPEED * dt
        if self.yaw >= self.SWEEP_MAX:
            self.yaw = self.SWEEP_MAX
            self._sweep_direction = -1
        elif self.yaw <= self.SWEEP_MIN:
            self.yaw = self.SWEEP_MIN
            self._sweep_direction = 1

        self.pitch = self.DEFAULT_PITCH
        self.dog.dog.head_move(
            [[self.yaw, 0, self.pitch]], pitch_comp=self.PITCH_COMP,
            immediately=True, speed=60
        )

    def _try_sound_direction(self):
        """Snap head toward detected sound. Returns True if sound was detected."""
        ears = self.dog.dog.ears
        if not ears.isdetected():
            return False

        direction = ears.read()
        if direction < 0:
            return False

        # Convert 360° sensor angle to yaw:
        # 0° = front, 0-180° = right side (negative yaw), 180-360° = left side (positive yaw)
        if direction <= 180:
            yaw = -direction
        else:
            yaw = 360 - direction

        self.yaw = max(self.YAW_MIN, min(self.YAW_MAX, yaw))
        self.pitch = float(self.DEFAULT_PITCH)
        self._servo.reset(yaw=self.yaw, pitch=self.pitch)

        self.dog.dog.head_move(
            [[self.yaw, 0, self.pitch]], pitch_comp=self.PITCH_COMP,
            immediately=True, speed=80
        )
        return True


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="PiDog Face Tracker")
    parser.add_argument("--video-only", action="store_true",
                        help="Video + face detection only, no dog hardware")
    parser.add_argument("--no-video", action="store_true",
                        help="No video window (headless)")
    args = parser.parse_args()

    dog = None
    if not args.video_only:
        sys.path.insert(0, "/home/pidog/pidog_lab")
        from buddy.dog_behavior import DogBehavior
        print("Initializing dog...")
        dog = DogBehavior(safe_mode=True)
        dog.sit()
        sleep(1)

    tracker = FaceFollower(dog_behavior=dog, show_video=not args.no_video)

    try:
        tracker.start()
        print("\nFace tracking active!")
        print("  Move your face in front of the camera.")
        print("  Press 'q' in the video window or Ctrl+C to stop.\n")

        while True:
            if tracker.show_video:
                if not tracker.update_video():
                    break  # Window closed
            else:
                info = tracker.get_face_info()
                if info["n"] > 0:
                    print(f"Face: x={info['x']:3d} y={info['y']:3d} "
                          f"w={info['w']:3d} | yaw={tracker.yaw:+6.1f} "
                          f"pitch={tracker.pitch:+6.1f}    ", end="\r")
                sleep(0.05)

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        tracker.close()
        if dog:
            dog.close()
