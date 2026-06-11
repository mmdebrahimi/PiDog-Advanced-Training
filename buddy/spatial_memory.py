"""Spatial memory for PiDog — mental map of the environment.

Tracks absolute angular positions of people, maintains position history
with velocity estimation, predicts positions during occlusion, and
generates rich spatial scene descriptions for the LLM.

Persistence: ~/.config/pidog/spatial_memory.json
"""

import json
import os
from collections import deque
from dataclasses import dataclass, field
from time import time

# Camera FOV constants (from servo_controller.py)
H_FOV = 62.0
V_FOV = 49.0
FRAME_W = 640
FRAME_H = 480
DPX_YAW = H_FOV / FRAME_W      # 0.096875 deg/px
DPX_PITCH = V_FOV / FRAME_H    # 0.102083 deg/px

# Distance bins based on person bbox height
NEAR_THRESHOLD = 300    # >300px bbox height → <1.5m
MEDIUM_THRESHOLD = 150  # 150-300px → 1.5-3m, <150px → >3m

# Prediction limits
MAX_PREDICT_SECONDS = 10.0  # Stop extrapolating after 10s
POSITION_HISTORY_SIZE = 20

DEFAULT_PATH = os.path.expanduser("~/.config/pidog/spatial_memory.json")


def pixel_to_absolute_angle(cx, cy, servo_yaw, servo_pitch):
    """Convert pixel center + servo angles to absolute angular position.

    Args:
        cx, cy: Detection center in frame pixels
        servo_yaw: Current head yaw servo angle (degrees)
        servo_pitch: Current head pitch servo angle (degrees)

    Returns:
        (abs_yaw, abs_pitch) in degrees
    """
    pixel_offset_yaw = (cx - FRAME_W / 2) * DPX_YAW
    pixel_offset_pitch = (cy - FRAME_H / 2) * DPX_PITCH
    return servo_yaw + pixel_offset_yaw, servo_pitch + pixel_offset_pitch


def bbox_to_distance_bin(bbox_h):
    """Estimate distance from person bounding box height."""
    if bbox_h > NEAR_THRESHOLD:
        return "near"
    if bbox_h > MEDIUM_THRESHOLD:
        return "medium"
    return "far"


@dataclass
class AngularPosition:
    """A single spatial observation."""
    abs_yaw: float
    abs_pitch: float
    distance_bin: str
    timestamp: float


class SpatialPersonState:
    """Spatial tracking state for one person."""

    def __init__(self, name):
        self.name = name
        self.positions = deque(maxlen=POSITION_HISTORY_SIZE)
        self.last_known = None          # Most recent AngularPosition
        self.last_velocity = (0.0, 0.0) # (vyaw, vpitch) degrees/sec
        self.disappeared_at = None      # Timestamp when lost
        self.typical_yaw = None         # EMA of typical position
        self.typical_pitch = None

    def record(self, abs_yaw, abs_pitch, distance_bin):
        """Record a new position observation."""
        now = time()
        pos = AngularPosition(abs_yaw, abs_pitch, distance_bin, now)

        # Compute velocity from previous position
        if self.last_known and now - self.last_known.timestamp < 5.0:
            dt = now - self.last_known.timestamp
            if dt > 0.05:  # Avoid division by tiny dt
                vyaw = (abs_yaw - self.last_known.abs_yaw) / dt
                vpitch = (abs_pitch - self.last_known.abs_pitch) / dt
                self.last_velocity = (vyaw, vpitch)

        self.positions.append(pos)
        self.last_known = pos
        self.disappeared_at = None

        # Update typical position with EMA (alpha=0.05 for slow convergence)
        alpha = 0.05
        if self.typical_yaw is None:
            self.typical_yaw = abs_yaw
            self.typical_pitch = abs_pitch
        else:
            self.typical_yaw += alpha * (abs_yaw - self.typical_yaw)
            self.typical_pitch += alpha * (abs_pitch - self.typical_pitch)

    def mark_disappeared(self):
        """Mark this person as no longer visible."""
        if self.disappeared_at is None:
            self.disappeared_at = time()

    def predict_position(self):
        """Predict current position using last velocity.

        Returns:
            (predicted_yaw, predicted_pitch) or None if too stale.
        """
        if not self.last_known or not self.disappeared_at:
            return None

        elapsed = time() - self.disappeared_at
        if elapsed > MAX_PREDICT_SECONDS:
            return None  # Too old, just use last_known

        vyaw, vpitch = self.last_velocity
        pred_yaw = self.last_known.abs_yaw + vyaw * elapsed
        pred_pitch = self.last_known.abs_pitch + vpitch * elapsed
        return pred_yaw, pred_pitch

    def get_movement_direction(self):
        """Describe movement direction based on velocity.

        Returns:
            str like "moving left", "moving right", "stationary", or None
        """
        vyaw, _ = self.last_velocity
        if abs(vyaw) < 1.0:  # Less than 1 deg/sec
            return "stationary"
        return "moving to your left" if vyaw > 0 else "moving to your right"

    def to_dict(self):
        """Serialize for JSON persistence."""
        return {
            "typical_yaw": self.typical_yaw,
            "typical_pitch": self.typical_pitch,
            "last_known": {
                "abs_yaw": self.last_known.abs_yaw,
                "abs_pitch": self.last_known.abs_pitch,
                "distance_bin": self.last_known.distance_bin,
                "timestamp": self.last_known.timestamp,
            } if self.last_known else None,
        }

    def load_from_dict(self, data):
        """Restore from JSON data."""
        self.typical_yaw = data.get("typical_yaw")
        self.typical_pitch = data.get("typical_pitch")


class SpatialMemory:
    """Persistent spatial memory — tracks where people are and have been."""

    SAVE_INTERVAL = 60.0  # Save to disk every 60 seconds

    def __init__(self, path=DEFAULT_PATH):
        self._path = path
        self._people = {}  # name → SpatialPersonState
        self._last_save = 0
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path) as f:
                    data = json.load(f)
                for name, pdata in data.get("people", {}).items():
                    state = SpatialPersonState(name)
                    state.load_from_dict(pdata)
                    self._people[name] = state
            except (json.JSONDecodeError, KeyError):
                pass

    def _save(self, force=False):
        now = time()
        if not force and now - self._last_save < self.SAVE_INTERVAL:
            return
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        data = {
            "version": 1,
            "people": {name: s.to_dict() for name, s in self._people.items()},
        }
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._path)
        self._last_save = now

    def update(self, tracked_people, servo_yaw, servo_pitch):
        """Update spatial state from tracked people.

        Args:
            tracked_people: list of dicts with {id, name, bbox, has_face}
            servo_yaw: current head yaw angle
            servo_pitch: current head pitch angle
        """
        seen_names = set()

        for person in tracked_people:
            name = person.get("name")
            if not name:
                continue

            bbox = person.get("bbox")
            if not bbox or len(bbox) < 4:
                continue

            x, y, w, h = bbox
            cx = x + w / 2
            cy = y + h / 2

            abs_yaw, abs_pitch = pixel_to_absolute_angle(
                cx, cy, servo_yaw, servo_pitch)
            distance_bin = bbox_to_distance_bin(h)

            if name not in self._people:
                self._people[name] = SpatialPersonState(name)

            self._people[name].record(abs_yaw, abs_pitch, distance_bin)
            seen_names.add(name)

        # Mark unseen people as disappeared
        for name, state in self._people.items():
            if name not in seen_names and state.disappeared_at is None:
                state.mark_disappeared()

        self._save()

    def get_scene_description(self):
        """Generate rich spatial description for LLM context.

        Returns 2-3 sentences describing who is where, with distance,
        direction, and temporal context.
        """
        now = time()
        visible = []
        recent = []
        gone = []

        for name, state in self._people.items():
            if not state.last_known:
                continue

            elapsed = now - state.last_known.timestamp

            if state.disappeared_at is None:
                # Currently visible
                direction = self._yaw_to_direction(state.last_known.abs_yaw)
                distance = self._distance_label(state.last_known.distance_bin)
                duration = self._format_duration(elapsed)
                movement = state.get_movement_direction()

                desc = f"{name} is {direction}{distance}"
                if movement and movement != "stationary":
                    desc += f", {movement}"
                if elapsed > 30:
                    desc += f" (been there for {duration})"
                visible.append(desc)

            elif elapsed < 60:
                # Recently disappeared
                direction = self._yaw_to_direction(state.last_known.abs_yaw)
                ago = self._format_duration(now - state.disappeared_at)
                movement = state.get_movement_direction()

                desc = f"{name} was {direction} {ago} ago"
                if movement and movement != "stationary":
                    desc += f", was {movement}"
                recent.append(desc)

            elif elapsed < 300:
                # Gone a while
                direction = self._yaw_to_direction(state.last_known.abs_yaw)
                ago = self._format_duration(elapsed)
                gone.append(f"{name} was last seen {direction} {ago} ago")

        parts = []
        if visible:
            parts.append("You can see: " + ". ".join(visible) + ".")
        if recent:
            parts.append("Recently: " + ". ".join(recent) + ".")
        if gone and not visible:
            parts.append(" ".join(gone) + ".")
        if not parts:
            parts.append("No one is around right now.")

        return " ".join(parts)

    def get_typical_position(self, name):
        """Where does this person usually sit/stand?

        Returns:
            str like "usually to your left" or None
        """
        state = self._people.get(name)
        if not state or state.typical_yaw is None:
            return None
        direction = self._yaw_to_direction(state.typical_yaw)
        return f"usually {direction}"

    def save(self):
        """Force save to disk (call on shutdown)."""
        self._save(force=True)

    @staticmethod
    def _yaw_to_direction(yaw):
        """Convert absolute yaw angle to direction description."""
        if yaw < -40:
            return "far to your right"
        if yaw < -15:
            return "to your right"
        if yaw > 40:
            return "far to your left"
        if yaw > 15:
            return "to your left"
        return "in front of you"

    @staticmethod
    def _distance_label(distance_bin):
        """Convert distance bin to natural language."""
        if distance_bin == "near":
            return ", very close"
        if distance_bin == "medium":
            return ", a couple meters away"
        if distance_bin == "far":
            return ", across the room"
        return ""

    @staticmethod
    def _format_duration(seconds):
        """Format seconds as natural language duration."""
        if seconds < 10:
            return "a few seconds"
        if seconds < 60:
            return f"{int(seconds)} seconds"
        if seconds < 120:
            return "about a minute"
        return f"{int(seconds / 60)} minutes"
