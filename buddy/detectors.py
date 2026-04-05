"""Person and face detection for PiDog.

PersonDetector: TFLite SSD MobileNet (COCO) for full-body person detection.
FaceDetector: OpenCV Haar cascade for face detection (within person ROI or full frame).
HeadEstimator: Infers head position from person bounding box when face is not visible.
"""

import cv2
import numpy as np
from pathlib import Path

# Haar cascade paths (same as face_follower.py)
CASCADE_PATHS = [
    "/opt/vilib/haarcascade_frontalface_default.xml",
    str(Path(__file__).parent.parent / "vilib" / "workspace" / "haarcascade_frontalface_default.xml"),
]

# Default TFLite model path
DEFAULT_MODEL_PATH = str(
    Path(__file__).parent.parent / "vilib" / "workspace" / "detect.tflite"
)

# COCO class ID for "person"
PERSON_CLASS_ID = 0


class PersonDetector:
    """Detect people using TFLite SSD MobileNet (COCO).

    Input: 300x300 RGB/BGR uint8 frame.
    Output: list of (x, y, w, h, confidence) bounding boxes for detected persons.
    """

    def __init__(self, model_path=DEFAULT_MODEL_PATH, confidence_threshold=0.5,
                 num_threads=4):
        from ai_edge_litert.interpreter import Interpreter

        self._interp = Interpreter(model_path=model_path, num_threads=num_threads)
        self._interp.allocate_tensors()

        self._input_detail = self._interp.get_input_details()[0]
        self._output_details = self._interp.get_output_details()
        self._input_size = tuple(self._input_detail['shape'][1:3])  # (300, 300)
        self._threshold = confidence_threshold

    def detect(self, frame):
        """Detect persons in a frame.

        Args:
            frame: numpy array (H, W, 3) uint8.

        Returns:
            List of (x, y, w, h, confidence) tuples in original frame coordinates.
        """
        h, w = frame.shape[:2]

        # Resize to model input size
        resized = cv2.resize(frame, self._input_size)
        input_data = np.expand_dims(resized, axis=0).astype(np.uint8)

        self._interp.set_tensor(self._input_detail['index'], input_data)
        self._interp.invoke()

        # Post-processed SSD outputs: boxes, classes, scores, count
        boxes = self._interp.get_tensor(self._output_details[0]['index'])[0]
        classes = self._interp.get_tensor(self._output_details[1]['index'])[0]
        scores = self._interp.get_tensor(self._output_details[2]['index'])[0]

        persons = []
        for i in range(len(scores)):
            if scores[i] < self._threshold:
                continue
            if int(classes[i]) != PERSON_CLASS_ID:
                continue

            # Boxes are [ymin, xmin, ymax, xmax] normalized to 0-1
            ymin, xmin, ymax, xmax = boxes[i]
            px = int(xmin * w)
            py = int(ymin * h)
            pw = int((xmax - xmin) * w)
            ph = int((ymax - ymin) * h)

            # Clamp to frame bounds
            px = max(0, px)
            py = max(0, py)
            pw = min(pw, w - px)
            ph = min(ph, h - py)

            if pw > 10 and ph > 10:  # ignore tiny detections
                persons.append((px, py, pw, ph, float(scores[i])))

        return persons


class FaceDetector:
    """Detect faces using OpenCV Haar cascade.

    Can run on a full frame or a cropped ROI for faster/more accurate detection.
    """

    def __init__(self, scale_factor=1.2, min_neighbors=5, min_size=(30, 30)):
        self._cascade = None
        for path in CASCADE_PATHS:
            cascade = cv2.CascadeClassifier(path)
            if not cascade.empty():
                self._cascade = cascade
                break
        if self._cascade is None:
            raise RuntimeError("Haar cascade model not found.")

        self._scale_factor = scale_factor
        self._min_neighbors = min_neighbors
        self._min_size = min_size

    def detect(self, frame, roi=None):
        """Detect faces in a frame or ROI.

        Args:
            frame: numpy array (H, W, 3) uint8.
            roi: optional (x, y, w, h) tuple to restrict detection area.

        Returns:
            List of (x, y, w, h) face bounding boxes in original frame coordinates.
        """
        if roi is not None:
            rx, ry, rw, rh = roi
            crop = frame[ry:ry+rh, rx:rx+rw]
            offset_x, offset_y = rx, ry
        else:
            crop = frame
            offset_x, offset_y = 0, 0

        # Downsample for speed
        ch, cw = crop.shape[:2]
        scale = max(1, cw // 320)
        small_w, small_h = cw // scale, ch // scale
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (small_w, small_h))

        faces = self._cascade.detectMultiScale(
            small,
            scaleFactor=self._scale_factor,
            minNeighbors=self._min_neighbors,
            minSize=self._min_size,
        )

        results = []
        for (fx, fy, fw, fh) in faces:
            # Scale back to original frame coordinates
            results.append((
                fx * scale + offset_x,
                fy * scale + offset_y,
                fw * scale,
                fh * scale,
            ))
        return results


class HeadEstimator:
    """Estimate head position from a person bounding box when no face is detected.

    When the camera sees a body but not the face, the head is ABOVE the
    visible bbox. We aim above the top of the bbox to tilt the camera up
    and bring the face into view.
    """

    # How far above the bbox top to aim (fraction of bbox height)
    # 0.3 = aim 30% of the person's height above the top of the bbox
    ABOVE_FRACTION = 0.3

    @staticmethod
    def estimate(person_bbox):
        """Estimate head center from person bounding box.

        Aims above the bbox to tilt camera up toward the face.

        Args:
            person_bbox: (x, y, w, h) of detected person.

        Returns:
            (head_cx, head_cy) estimated head center in frame coordinates.
        """
        px, py, pw, ph = person_bbox[:4]
        head_cx = px + pw // 2
        # Aim above the top of the bbox — the face is higher than the body
        head_cy = max(0, py - int(ph * HeadEstimator.ABOVE_FRACTION))
        return head_cx, head_cy
