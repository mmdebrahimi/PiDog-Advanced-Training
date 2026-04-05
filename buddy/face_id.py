"""Face identification for PiDog.

Uses OpenCV's FaceRecognizerSF (SFace) for face embeddings.
Maintains a JSON database of known faces at ~/.config/pidog/known_faces.json.

Standalone enrollment:
    python3 -m buddy.face_id --enroll "Alice"
    python3 -m buddy.face_id --list
"""

import json
import os
import threading
import cv2
import numpy as np
from pathlib import Path
from time import time, sleep

MODELS_DIR = Path(__file__).parent / "models"
SFACE_MODEL = str(MODELS_DIR / "face_recognition_sface.onnx")
KNOWN_FACES_DB = os.path.expanduser("~/.config/pidog/known_faces.json")

# Match thresholds for cosine similarity (higher = more similar)
MATCH_THRESHOLD = 0.40    # Above this = match
MAYBE_THRESHOLD = 0.30    # Between maybe and match = uncertain


class FaceEmbedder:
    """Generate face embeddings using SFace via OpenCV."""

    def __init__(self, model_path=SFACE_MODEL):
        self._recognizer = cv2.FaceRecognizerSF.create(model_path, "")

    def embed(self, face_crop):
        """Compute embedding for a face crop.

        Args:
            face_crop: BGR image of a face, any size (will be resized to 112x112).

        Returns:
            1D numpy array of shape (128,), L2-normalized.
        """
        aligned = cv2.resize(face_crop, (112, 112))
        embedding = self._recognizer.feature(aligned)
        return embedding.flatten()

    def similarity(self, emb1, emb2):
        """Cosine similarity between two embeddings."""
        emb1_2d = emb1.reshape(1, -1)
        emb2_2d = emb2.reshape(1, -1)
        return self._recognizer.match(emb1_2d, emb2_2d,
                                       cv2.FaceRecognizerSF_FR_COSINE)


class FaceDatabase:
    """Persistent storage for known face embeddings."""

    MAX_EMBEDDINGS = 5  # Per person

    def __init__(self, db_path=KNOWN_FACES_DB):
        self._path = db_path
        self._data = {"version": 1, "people": {}}
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            with open(self._path) as f:
                self._data = json.load(f)

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, self._path)

    def identify(self, embedding, embedder):
        """Match an embedding against all known faces.

        Returns:
            (name, confidence) or (None, 0.0) if no match.
        """
        best_name = None
        best_score = 0.0

        for name, person in self._data["people"].items():
            for stored_emb in person["embeddings"]:
                stored = np.array(stored_emb, dtype=np.float32)
                score = embedder.similarity(embedding, stored)
                if score > best_score:
                    best_score = score
                    best_name = name

        if best_score >= MATCH_THRESHOLD:
            return best_name, best_score
        return None, best_score

    def add_face(self, name, embedding):
        """Add an embedding for a person. Creates person if new."""
        from datetime import datetime

        people = self._data["people"]
        if name not in people:
            people[name] = {
                "embeddings": [],
                "added": datetime.now().isoformat()[:10],
                "last_seen": datetime.now().isoformat(),
            }

        emb_list = people[name]["embeddings"]
        emb_list.append(embedding.tolist())

        # Keep only the most recent MAX_EMBEDDINGS
        if len(emb_list) > self.MAX_EMBEDDINGS:
            emb_list[:] = emb_list[-self.MAX_EMBEDDINGS:]

        people[name]["last_seen"] = datetime.now().isoformat()
        self._save()

    def update_last_seen(self, name):
        """Update last_seen timestamp for a person."""
        from datetime import datetime
        if name in self._data["people"]:
            self._data["people"][name]["last_seen"] = datetime.now().isoformat()
            self._save()

    def remove_face(self, name):
        """Remove a person from the database."""
        if name in self._data["people"]:
            del self._data["people"][name]
            self._save()

    def list_known(self):
        """List all known people with embedding counts."""
        return {name: len(p["embeddings"])
                for name, p in self._data["people"].items()}

    @property
    def people(self):
        return self._data["people"]


class FaceIDWorker:
    """Background thread that identifies faces from tracked persons.

    Runs asynchronously — crops face from frame, computes embedding,
    matches against database. Results are written to track objects.
    """

    COOLDOWN = 1.5  # Seconds between ID attempts per track

    def __init__(self):
        self._embedder = FaceEmbedder()
        self._database = FaceDatabase()
        self._running = False
        self._thread = None
        self._pending = None  # (frame, face_bbox, track_id)
        self._lock = threading.Lock()
        self._last_id_time = {}  # track_id → last attempt timestamp
        self._results = {}  # track_id → (name, confidence)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def submit(self, frame, face_bbox, track_id):
        """Submit a face for identification (non-blocking).

        Only processes if cooldown has elapsed for this track.
        """
        now = time()
        if track_id in self._last_id_time:
            if now - self._last_id_time[track_id] < self.COOLDOWN:
                return

        with self._lock:
            self._pending = (frame.copy(), face_bbox, track_id)
        self._last_id_time[track_id] = now

    def get_result(self, track_id):
        """Get identification result for a track, or None."""
        return self._results.get(track_id)

    def enroll(self, frame, face_bbox, name):
        """Enroll a face under a name (blocking)."""
        x, y, w, h = face_bbox
        crop = frame[y:y+h, x:x+w]
        if crop.size == 0:
            return False
        embedding = self._embedder.embed(crop)
        self._database.add_face(name, embedding)
        return True

    @property
    def database(self):
        return self._database

    def _worker_loop(self):
        while self._running:
            with self._lock:
                job = self._pending
                self._pending = None

            if job is None:
                sleep(0.1)
                continue

            frame, face_bbox, track_id = job
            x, y, w, h = face_bbox
            crop = frame[y:y+h, x:x+w]
            if crop.size == 0:
                continue

            embedding = self._embedder.embed(crop)
            name, confidence = self._database.identify(embedding, self._embedder)
            self._results[track_id] = (name, confidence)


if __name__ == "__main__":
    import argparse
    import sys
    from time import sleep as slp

    parser = argparse.ArgumentParser(description="PiDog Face ID")
    parser.add_argument("--enroll", type=str, help="Enroll a face with this name")
    parser.add_argument("--list", action="store_true", help="List known faces")
    parser.add_argument("--remove", type=str, help="Remove a person")
    args = parser.parse_args()

    if args.list:
        db = FaceDatabase()
        known = db.list_known()
        if known:
            for name, count in known.items():
                print(f"  {name}: {count} embedding(s)")
        else:
            print("  No known faces.")
        sys.exit(0)

    if args.remove:
        db = FaceDatabase()
        db.remove_face(args.remove)
        print(f"Removed '{args.remove}'")
        sys.exit(0)

    if args.enroll:
        from picamera2 import Picamera2

        print(f"Enrolling '{args.enroll}'...")
        print("Look at the camera. Capturing 5 samples over 3 seconds...")

        cam = Picamera2(0)
        config = cam.create_preview_configuration(
            main={"size": (640, 480), "format": "RGB888"})
        cam.configure(config)
        cam.start()
        slp(2.0)  # Let auto exposure + white balance settle
        print("Camera ready. Hold still and face the camera...")

        embedder = FaceEmbedder()
        database = FaceDatabase()

        # Use Haar cascade to find face
        cascade = None
        for path in ["/opt/vilib/haarcascade_frontalface_default.xml",
                     str(Path(__file__).parent.parent / "vilib" / "workspace"
                         / "haarcascade_frontalface_default.xml")]:
            cascade = cv2.CascadeClassifier(path)
            if not cascade.empty():
                break

        enrolled = 0
        target = 5
        print("Position your face in the green box. Press 'q' to finish early.\n")

        while enrolled < target:
            frame = cam.capture_array()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 3, minSize=(40, 40))

            display = frame.copy()

            # Guide box in center
            gx, gy, gw, gh = 180, 100, 280, 280
            cv2.rectangle(display, (gx, gy), (gx + gw, gy + gh),
                         (0, 255, 0), 1)
            cv2.putText(display, "Position face here", (gx, gy - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            for (x, y, w, h) in faces:
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 255), 2)

            status = f"Enrolled: {enrolled}/{target} | '{args.enroll}'"
            cv2.putText(display, status, (10, 470),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

            cv2.imshow("Enroll Face", display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break

            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                # Only capture if face is reasonably large
                if w >= 60:
                    crop = frame[y:y+h, x:x+w]
                    emb = embedder.embed(crop)
                    database.add_face(args.enroll, emb)
                    enrolled += 1
                    print(f"  Sample {enrolled}: captured ({w}x{h})")
                    # Flash green
                    cv2.rectangle(display, (0, 0), (640, 480), (0, 255, 0), 10)
                    cv2.imshow("Enroll Face", display)
                    cv2.waitKey(300)
                    slp(0.3)  # Small delay between samples for variety

        cv2.destroyAllWindows()
        cam.stop()
        cam.close()
        print(f"\nEnrolled '{args.enroll}' with {enrolled} samples.")
        sys.exit(0)

    parser.print_help()
