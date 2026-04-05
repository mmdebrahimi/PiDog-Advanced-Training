"""SORT tracker — Simple Online Realtime Tracking for PiDog.

Assigns persistent track IDs to detected people across frames.
Uses Kalman filter per track + Hungarian assignment for data association.

Based on the SORT algorithm (Bewley et al. 2016), simplified for single-camera
pan-tilt tracking on Pi 4.
"""

import numpy as np
from filterpy.kalman import KalmanFilter
from scipy.optimize import linear_sum_assignment


def _iou(bb1, bb2):
    """Compute IoU between two bboxes [x, y, w, h]."""
    x1 = max(bb1[0], bb2[0])
    y1 = max(bb1[1], bb2[1])
    x2 = min(bb1[0] + bb1[2], bb2[0] + bb2[2])
    y2 = min(bb1[1] + bb1[3], bb2[1] + bb2[3])

    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = bb1[2] * bb1[3]
    area2 = bb2[2] * bb2[3]
    union = area1 + area2 - inter

    return inter / union if union > 0 else 0


class _Track:
    """Internal track state managed by Kalman filter."""

    _next_id = 1

    def __init__(self, bbox):
        """Initialize track from first detection [x, y, w, h]."""
        self.id = _Track._next_id
        _Track._next_id += 1

        # Kalman filter: state [cx, cy, area, aspect, vcx, vcy, va]
        self.kf = KalmanFilter(dim_x=7, dim_z=4)
        self.kf.F = np.array([
            [1, 0, 0, 0, 1, 0, 0],
            [0, 1, 0, 0, 0, 1, 0],
            [0, 0, 1, 0, 0, 0, 1],
            [0, 0, 0, 1, 0, 0, 0],
            [0, 0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 1],
        ], dtype=float)
        self.kf.H = np.array([
            [1, 0, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0],
        ], dtype=float)
        self.kf.R *= 10.0
        self.kf.P[4:, 4:] *= 1000.0  # high uncertainty on velocities
        self.kf.Q[4:, 4:] *= 0.01

        # Initialize state from bbox
        cx, cy, area, aspect = self._bbox_to_z(bbox)
        self.kf.x[:4] = np.array([cx, cy, area, aspect]).reshape(4, 1)

        self.hits = 1
        self.age = 0
        self.time_since_update = 0
        self.name = None  # Set by face ID
        self.face_bbox = None  # Most recent face bbox if any

    def predict(self):
        """Advance state, return predicted bbox [x, y, w, h]."""
        if self.kf.x[6] + self.kf.x[2] <= 0:
            self.kf.x[6] = 0.0
        self.kf.predict()
        self.age += 1
        self.time_since_update += 1
        return self._z_to_bbox(self.kf.x[:4].flatten())

    def update(self, bbox):
        """Update track with matched detection."""
        self.time_since_update = 0
        self.hits += 1
        z = self._bbox_to_z(bbox)
        self.kf.update(np.array(z).reshape(4, 1))

    @property
    def bbox(self):
        """Current bbox estimate [x, y, w, h]."""
        return self._z_to_bbox(self.kf.x[:4].flatten())

    @property
    def center(self):
        """Current center (cx, cy)."""
        return float(self.kf.x[0]), float(self.kf.x[1])

    @staticmethod
    def _bbox_to_z(bbox):
        x, y, w, h = bbox[:4]
        cx = x + w / 2
        cy = y + h / 2
        area = w * h
        aspect = w / h if h > 0 else 1.0
        return cx, cy, area, aspect

    @staticmethod
    def _z_to_bbox(z):
        cx, cy, area, aspect = z
        area = max(area, 1.0)
        aspect = max(aspect, 0.1)
        w = np.sqrt(area * aspect)
        h = area / w if w > 0 else 1.0
        x = cx - w / 2
        y = cy - h / 2
        return [int(x), int(y), int(w), int(h)]


class SORTTracker:
    """Simple Online Realtime Tracker.

    Usage:
        tracker = SORTTracker()
        for each frame:
            tracks = tracker.update(detections)
            # tracks is list of _Track with .id, .bbox, .name, .face_bbox
    """

    def __init__(self, max_age=15, min_hits=3, iou_threshold=0.3):
        """
        Args:
            max_age: Frames to keep a track without matching detection.
            min_hits: Consecutive detections before track is confirmed.
            iou_threshold: Minimum IoU for detection-track matching.
        """
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self._tracks = []

    def update(self, detections):
        """Update tracks with new detections.

        Args:
            detections: list of (x, y, w, h, ...) bounding boxes.
                Extra fields after xywh are ignored for tracking.

        Returns:
            List of confirmed _Track objects (hits >= min_hits or recently updated).
        """
        # Predict existing tracks forward
        for track in self._tracks:
            track.predict()

        if not detections:
            # Remove dead tracks
            self._tracks = [t for t in self._tracks
                           if t.time_since_update <= self.max_age]
            return self._get_confirmed()

        det_bboxes = [d[:4] for d in detections]

        # Build IoU cost matrix
        if self._tracks:
            track_bboxes = [t.bbox for t in self._tracks]
            cost = np.zeros((len(det_bboxes), len(track_bboxes)))
            for d, det in enumerate(det_bboxes):
                for t, trk in enumerate(track_bboxes):
                    cost[d, t] = 1.0 - _iou(det, trk)

            # Hungarian assignment
            det_idx, trk_idx = linear_sum_assignment(cost)

            matched_det = set()
            matched_trk = set()
            for d, t in zip(det_idx, trk_idx):
                if cost[d, t] <= 1.0 - self.iou_threshold:
                    self._tracks[t].update(det_bboxes[d])
                    matched_det.add(d)
                    matched_trk.add(t)

            unmatched_det = [i for i in range(len(det_bboxes)) if i not in matched_det]
        else:
            unmatched_det = list(range(len(det_bboxes)))

        # Create new tracks for unmatched detections
        for i in unmatched_det:
            self._tracks.append(_Track(det_bboxes[i]))

        # Remove dead tracks
        self._tracks = [t for t in self._tracks
                       if t.time_since_update <= self.max_age]

        return self._get_confirmed()

    def _get_confirmed(self):
        """Return tracks that are confirmed (enough hits) or recently active."""
        return [t for t in self._tracks
                if t.hits >= self.min_hits or t.time_since_update == 0]

    def get_track(self, track_id):
        """Get a specific track by ID, or None."""
        for t in self._tracks:
            if t.id == track_id:
                return t
        return None

    @property
    def tracks(self):
        """All active tracks (including unconfirmed)."""
        return list(self._tracks)
