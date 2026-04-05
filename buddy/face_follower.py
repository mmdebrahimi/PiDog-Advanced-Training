#!/usr/bin/env python3
"""Face detection, head tracking, and person following for PiDog.

Two-stage detection pipeline:
  1. PersonDetector (TFLite SSD) finds people in frame
  2. FaceDetector (Haar cascade) finds faces within person ROIs
  3. HeadEstimator infers head position when face not visible

Falls back to Haar-only if TFLite is unavailable.

Standalone:
    python3 -m buddy.face_follower              # With dog + video
    python3 -m buddy.face_follower --video-only  # Video only, no dog
"""

import threading
import csv
import os
import cv2
import numpy as np
from time import sleep, time
from picamera2 import Picamera2
from .servo_controller import ServoController
from .tracker import SORTTracker
from .face_id import FaceIDWorker

# Try to import TFLite-based detectors; fall back to Haar-only
try:
    from .detectors import PersonDetector, FaceDetector, HeadEstimator
    _TFLITE_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    _TFLITE_AVAILABLE = False
    print(f"TFLite detectors unavailable ({e}), using Haar cascade only.")

CASCADE_PATHS = [
    "/opt/vilib/haarcascade_frontalface_default.xml",
    "/home/pidog/pidog_lab/vilib/workspace/haarcascade_frontalface_default.xml",
]

FRAME_W, FRAME_H = 640, 480


class FaceFollower:
    """Detects faces, shows live video, tracks with head servos."""

    # Head servo limits (yaw narrowed from ±80 to ±55 to protect CSI ribbon cable)
    YAW_MIN, YAW_MAX = -55, 55
    PITCH_MIN, PITCH_MAX = -30, 30
    PITCH_COMP = -25  # Less negative = head looks more upward

    # Body following thresholds
    FACE_FAR = 120
    FACE_CLOSE = 280
    YAW_TURN_THRESHOLD = 30

    # Timing
    LOOP_HZ = 20
    FACE_LOST_TIMEOUT = 2.0
    TRACK_COAST_FRAMES = 5  # Keep tracking via Kalman prediction when detection drops

    # Sound direction
    DEFAULT_PITCH = 30  # Look up toward humans by default (max pitch)

    # Sweep fallback (narrower than yaw limits to stay safe)
    SWEEP_MIN, SWEEP_MAX = -45, 45
    SWEEP_SPEED = 10  # degrees per second
    SWEEP_TIMEOUT = 3.0  # seconds with no face/sound before sweeping

    def __init__(self, dog_behavior=None, show_video=True, detector='auto',
                 log=False):
        """
        Args:
            dog_behavior: DogBehavior instance (None = video only, no head tracking)
            show_video: Show live video window on HDMI monitor
            detector: 'auto' (TFLite if available), 'tflite', or 'haar'
            log: Write per-frame CSV log to ~/pidog_lab/logs/
        """
        self.dog = dog_behavior
        self.show_video = show_video
        self.follow_mode = False
        self._running = False
        self._thread = None

        # Logging
        self._log_file = None
        self._log_writer = None
        if log:
            self._init_log()

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
        self._coast_count = 0  # Frames without detection while coasting on Kalman
        self._sweep_direction = 1  # 1 = moving right, -1 = moving left
        self._face_info = {"x": 0, "y": 0, "w": 0, "n": 0}

        # Camera + detectors
        self._camera = None
        self._latest_frame = None
        self._frame_lock = threading.Lock()

        # Initialize detection pipeline
        use_tflite = (detector == 'tflite' or
                      (detector == 'auto' and _TFLITE_AVAILABLE))
        if use_tflite and _TFLITE_AVAILABLE:
            self._person_detector = PersonDetector()
            self._face_detector = FaceDetector()
            self._use_tflite = True
            print("Detection: TFLite person + Haar face (two-stage)")
        else:
            self._person_detector = None
            self._face_detector = None
            self._use_tflite = False
            print("Detection: Haar cascade only")

        # Haar cascade fallback (used when TFLite unavailable or as face detector)
        self._cascade = None
        for path in CASCADE_PATHS:
            self._cascade = cv2.CascadeClassifier(path)
            if not self._cascade.empty():
                break
        else:
            if not self._use_tflite:
                raise RuntimeError("Haar cascade model not found.")

        # SORT tracker for persistent person IDs
        self._tracker = SORTTracker(max_age=15, min_hits=1, iou_threshold=0.3)
        self._primary_track_id = None  # Track ID of the person we're following

        # Face ID (async background thread)
        self._face_id = FaceIDWorker()
        self._face_id.start()

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
            # Let auto white balance and exposure settle
            sleep(1.0)
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
        self._face_id.stop()
        if self.show_video:
            cv2.destroyAllWindows()
        if self._camera:
            self._camera.stop()
            self._camera.close()
            self._camera = None
        if self._log_file:
            self._log_file.close()
            print(f"Log saved: {self._log_path}")

    def _init_log(self):
        log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._log_path = os.path.join(log_dir, f'track_{ts}.csv')
        self._log_file = open(self._log_path, 'w', newline='')
        self._log_writer = csv.writer(self._log_file)
        self._log_writer.writerow([
            'time', 'frame_ms', 'detect_ms',
            'n_persons', 'n_faces', 'target_src',
            'target_x', 'target_y', 'target_w',
            'yaw', 'pitch', 'yaw_delta', 'pitch_delta',
            'state', 'sound_dir',
        ])
        self._log_start = time()
        self._prev_yaw = 0.0
        self._prev_pitch = 0.0
        print(f"Logging to {self._log_path}")

    def _log_frame(self, frame_ms, detect_ms, target, faces, persons, state,
                   sound_dir=-1):
        if not self._log_writer:
            return
        t = time() - self._log_start
        yaw_d = self.yaw - self._prev_yaw
        pitch_d = self.pitch - self._prev_pitch
        self._prev_yaw = self.yaw
        self._prev_pitch = self.pitch
        self._log_writer.writerow([
            f'{t:.3f}', f'{frame_ms:.1f}', f'{detect_ms:.1f}',
            len(persons), len(faces),
            target[3] if target else '',
            f'{target[0]:.0f}' if target else '',
            f'{target[1]:.0f}' if target else '',
            f'{target[2]:.0f}' if target else '',
            f'{self.yaw:.2f}', f'{self.pitch:.2f}',
            f'{yaw_d:.2f}', f'{pitch_d:.2f}',
            state, sound_dir,
        ])
        self._log_file.flush()

    def set_follow_mode(self, enabled):
        self.follow_mode = enabled

    def is_tracking(self):
        return self._tracking

    def get_face_info(self):
        return self._face_info.copy()

    def get_tracked_people(self):
        """Get list of tracked people with IDs and names."""
        return [{"id": t.id, "name": t.name, "bbox": t.bbox,
                 "has_face": t.face_bbox is not None}
                for t in self._tracker.tracks if t.time_since_update == 0]

    def enroll_face(self, name):
        """Enroll the currently tracked face under a name. Returns True on success."""
        for t in self._tracker.tracks:
            if t.face_bbox and t.time_since_update == 0:
                try:
                    frame = self._camera.capture_array()
                    return self._face_id.enroll(frame, t.face_bbox, name)
                except Exception:
                    return False
        return False

    @property
    def face_id(self):
        """Access the FaceIDWorker for database operations."""
        return self._face_id

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
            cv2.imshow("PiDog Camera", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:  # q or ESC
            return False
        return True

    def _detect(self, frame):
        """Run detection pipeline. Returns (target, faces, persons).

        target: (cx, cy, w, source) or None — what to track.
            source is 'face' or 'body' (for overlay info).
        faces: list of (x, y, w, h) face bounding boxes.
        persons: list of (x, y, w, h, conf) person bounding boxes (empty if Haar-only).
        """
        if self._use_tflite:
            return self._detect_tflite(frame)
        return self._detect_haar(frame)

    def _detect_tflite(self, frame):
        """Two-stage: PersonDetector → FaceDetector on each person ROI → HeadEstimator.

        Face detection (Haar) only runs every 3rd frame to improve FPS.
        Person detection + head estimation runs every frame.
        """
        persons = self._person_detector.detect(frame)
        all_faces = []
        target = None

        # Run face detection less often (it's slow on top of TFLite)
        self._tflite_frame_count = getattr(self, '_tflite_frame_count', 0) + 1
        run_face = (self._tflite_frame_count % 3 == 0)

        for person in persons:
            px, py, pw, ph = person[:4]
            roi = (px, py, pw, ph)
            faces = self._face_detector.detect(frame, roi=roi) if run_face else []
            all_faces.extend(faces)

            if faces:
                # Pick largest face in this person's ROI
                largest = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = largest
                cx, cy = fx + fw // 2, fy + fh // 2
                # Keep the best (largest face) across all persons
                if target is None or fw * fh > target[2] ** 2:
                    target = (cx, cy, fw, 'face')
            elif target is None:
                # No face in this person — estimate head position
                hx, hy = HeadEstimator.estimate(person)
                target = (hx, hy, pw, 'body')

        # If no persons detected by TFLite, try Haar on full frame as fallback
        if not persons and self._cascade is not None:
            _, faces_fallback, _ = self._detect_haar(frame)
            if faces_fallback:
                all_faces = faces_fallback
                largest = max(faces_fallback, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = largest
                target = (fx + fw // 2, fy + fh // 2, fw, 'face')

        return target, all_faces, persons

    def _detect_haar(self, frame):
        """Haar cascade on full frame (fallback mode)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (320, 240))
        faces_raw = self._cascade.detectMultiScale(
            small, scaleFactor=1.2, minNeighbors=5, minSize=(30, 30)
        )
        faces = [(x * 2, y * 2, w * 2, h * 2) for (x, y, w, h) in faces_raw]

        target = None
        if faces:
            largest = max(faces, key=lambda f: f[2] * f[3])
            fx, fy, fw, fh = largest
            target = (fx + fw // 2, fy + fh // 2, fw, 'face')

        return target, faces, []

    def _draw_overlay(self, frame, faces, persons=None, target=None,
                      tracks=None):
        """Draw detection rectangles and tracking info on frame."""
        # Tracked persons with IDs and names (replaces raw person boxes)
        if tracks:
            for t in tracks:
                tx, ty, tw, th = t.bbox
                color = (255, 180, 0)  # orange for tracked
                cv2.rectangle(frame, (tx, ty), (tx + tw, ty + th), color, 2)
                label = f"#{t.id}"
                if t.name:
                    label += f" {t.name}"
                cv2.putText(frame, label, (tx, ty - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        elif persons:
            for p in persons:
                px, py, pw, ph = p[:4]
                conf = p[4] if len(p) > 4 else 0
                cv2.rectangle(frame, (px, py), (px + pw, py + ph), (255, 128, 0), 1)
                cv2.putText(frame, f"Person {conf:.0%}", (px, py - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 128, 0), 1)

        # Face bounding boxes (green)
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, f"Face {w}x{h}", (x, y - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # Tracking target marker (yellow circle)
        if target:
            tcx, tcy = int(target[0]), int(target[1])
            color = (0, 255, 255) if target[3] == 'face' else (0, 165, 255)
            cv2.circle(frame, (tcx, tcy), 8, color, 2)
            cv2.putText(frame, target[3], (tcx + 12, tcy + 4),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        # Status bar
        mode = "TFLite" if self._use_tflite else "Haar"
        status = f"{mode} | Faces: {len(faces)} | Yaw: {self.yaw:+.0f} | Pitch: {self.pitch:+.0f}"
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

            t_detect = time()
            target, faces, persons = self._detect(frame)
            detect_ms = (time() - t_detect) * 1000

            # Update SORT tracker with all person detections
            tracks = self._tracker.update(persons) if persons else self._tracker.update([])

            # Match faces to tracks by center distance (robust to bbox timing mismatch)
            for track in tracks:
                tid = track.id
                tcx_t, tcy_t = track.center
                best_face = None
                best_dist = float('inf')
                for fx, fy, fw, fh in faces:
                    fcx, fcy = fx + fw / 2, fy + fh / 2
                    dist = ((fcx - tcx_t) ** 2 + (fcy - tcy_t) ** 2) ** 0.5
                    # Match if face center within half the track bbox diagonal
                    tx, ty, tw_t, th_t = track.bbox
                    max_dist = ((tw_t ** 2 + th_t ** 2) ** 0.5) / 2
                    if dist < max_dist and dist < best_dist:
                        best_dist = dist
                        best_face = (fx, fy, fw, fh)
                if best_face:
                    track.face_bbox = best_face
                    self._face_id.submit(frame, best_face, tid)
                # Update track name from face ID results
                result = self._face_id.get_result(tid)
                if result and result[0]:
                    track.name = result[0]

            state = 'idle'
            if target:
                tcx, tcy, tw = target[0], target[1], target[2]
                self._coast_count = 0

                self._face_info = {"x": tcx, "y": tcy, "w": tw, "n": len(faces)}
                if not self._tracking:
                    self._servo.set_mode('lockon')
                    state = 'lockon'
                else:
                    state = 'tracking'
                self._tracking = True
                self._last_face_time = time()

                # Remember which track we're following for coasting
                if tracks:
                    self._last_track_id = tracks[0].id

                if self.dog:
                    self._track_head(tcx, tcy)
                if self.follow_mode and self.dog and target[3] == 'face':
                    self._follow_body(tw)

            elif self._tracking and self._coast_count < self.TRACK_COAST_FRAMES:
                # No detection this frame — coast on SORT track's Kalman prediction
                self._coast_count += 1
                track = self._tracker.get_track(
                    getattr(self, '_last_track_id', None))
                if track and self.dog:
                    cx, cy = track.center
                    self._track_head(cx, cy)
                state = 'coast'

            else:
                self._face_info = {"x": 0, "y": 0, "w": 0, "n": 0}
                now = time()

                # Sound direction: only use when truly idle (no recent detection)
                if (self.dog and not self._tracking
                        and now - self._last_face_time > self.SWEEP_TIMEOUT
                        and self._try_sound_direction()):
                    self._last_sound_time = now
                    state = 'sound'
                elif self._tracking and now - self._last_face_time > self.FACE_LOST_TIMEOUT:
                    self._tracking = False
                    self._coast_count = 0
                    state = 'lost'
                elif (self.dog and not self._tracking
                      and now - max(self._last_face_time, self._last_sound_time) > self.SWEEP_TIMEOUT):
                    self._sweep_step(interval)
                    state = 'sweep'

            frame_ms = (time() - t_start) * 1000

            # Draw overlay and store for video display
            if self.show_video:
                annotated = self._draw_overlay(frame.copy(), faces, persons, target,
                                               tracks)
                # Show FPS on overlay
                fps = 1000.0 / frame_ms if frame_ms > 0 else 0
                cv2.putText(annotated, f"{fps:.0f} FPS | det {detect_ms:.0f}ms",
                           (FRAME_W - 200, 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
                with self._frame_lock:
                    self._latest_frame = annotated

            # Log frame data
            self._log_frame(frame_ms, detect_ms, target, faces, persons, state)

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
    parser.add_argument("--detector", choices=["auto", "tflite", "haar"],
                        default="auto",
                        help="Detection mode: auto (TFLite if available), tflite, haar")
    parser.add_argument("--log", action="store_true",
                        help="Write per-frame CSV log to ~/pidog_lab/logs/")
    args = parser.parse_args()

    dog = None
    if not args.video_only:
        sys.path.insert(0, "/home/pidog/pidog_lab")
        from buddy.dog_behavior import DogBehavior
        print("Initializing dog...")
        dog = DogBehavior(safe_mode=True)
        dog.sit()
        sleep(1)

    tracker = FaceFollower(dog_behavior=dog, show_video=not args.no_video,
                           detector=args.detector, log=args.log)

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
