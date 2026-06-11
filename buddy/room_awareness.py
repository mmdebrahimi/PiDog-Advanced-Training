"""Room awareness for PiDog.

Tracks who is in the room, where they were last seen, and provides
human-readable summaries for the voice companion's LLM context.
"""

from dataclasses import dataclass, field
from time import time


from .spatial_memory import pixel_to_absolute_angle, bbox_to_distance_bin


@dataclass
class PersonState:
    """State of a person known to the room."""
    name: str
    track_id: int = -1
    last_yaw: float = 0.0
    last_pitch: float = 0.0
    last_abs_yaw: float = 0.0
    last_abs_pitch: float = 0.0
    distance_bin: str = ""
    last_seen: float = 0.0
    visible: bool = False
    coasting: bool = False


class RoomState:
    """Tracks who is in the room and where they were last seen.

    Fed by FaceFollower's tracked people data each frame.
    Provides summaries for the voice companion's LLM context.
    """

    PRESENCE_TIMEOUT = 60.0  # Seconds before someone is "gone"
    RECENT_TIMEOUT = 300.0   # Seconds before someone is forgotten

    def __init__(self):
        self._people = {}  # name → PersonState
        self._unknown_tracks = {}  # track_id → PersonState (unnamed)

    def update(self, tracked_people, current_yaw, current_pitch):
        """Update room state from FaceFollower's tracked people.

        Args:
            tracked_people: list of dicts from FaceFollower.get_tracked_people()
                Each dict has: id, name, bbox, has_face
            current_yaw: current servo yaw angle
            current_pitch: current servo pitch angle
        """
        now = time()
        seen_names = set()
        seen_track_ids = set()

        for person in tracked_people:
            tid = person["id"]
            name = person["name"]
            seen_track_ids.add(tid)

            if name:
                seen_names.add(name)
                if name not in self._people:
                    self._people[name] = PersonState(name=name)

                ps = self._people[name]
                ps.track_id = tid
                ps.last_yaw = current_yaw
                ps.last_pitch = current_pitch
                ps.last_seen = now
                ps.visible = True
                ps.coasting = False

                # Compute absolute angular position from bbox
                bbox = person.get("bbox")
                if bbox and len(bbox) >= 4:
                    x, y, w, h = bbox
                    cx, cy = x + w / 2, y + h / 2
                    ps.last_abs_yaw, ps.last_abs_pitch = pixel_to_absolute_angle(
                        cx, cy, current_yaw, current_pitch)
                    ps.distance_bin = bbox_to_distance_bin(h)

                # Clean up from unknown tracks if was there
                self._unknown_tracks.pop(tid, None)
            else:
                # Unnamed track
                if tid not in self._unknown_tracks:
                    self._unknown_tracks[tid] = PersonState(
                        name=f"unknown #{tid}", track_id=tid)
                us = self._unknown_tracks[tid]
                us.last_yaw = current_yaw
                us.last_pitch = current_pitch
                us.last_seen = now
                us.visible = True

        # Mark people no longer visible
        for ps in self._people.values():
            if ps.name not in seen_names:
                ps.visible = False

        for tid, us in list(self._unknown_tracks.items()):
            if tid not in seen_track_ids:
                us.visible = False

        # Clean up old unknown tracks
        self._unknown_tracks = {
            tid: us for tid, us in self._unknown_tracks.items()
            if now - us.last_seen < self.RECENT_TIMEOUT
        }

    def who_is_here(self):
        """People seen in the last PRESENCE_TIMEOUT seconds."""
        now = time()
        return [name for name, ps in self._people.items()
                if now - ps.last_seen < self.PRESENCE_TIMEOUT]

    def who_is_visible(self):
        """People currently visible in the camera frame."""
        return [name for name, ps in self._people.items() if ps.visible]

    def where_is(self, name):
        """Describe where a person was last seen."""
        ps = self._people.get(name)
        if not ps:
            return f"I don't know {name}."

        now = time()
        # Prefer absolute yaw if available
        yaw = ps.last_abs_yaw if ps.last_abs_yaw != 0.0 else ps.last_yaw

        if ps.visible:
            direction = self._yaw_to_direction(yaw)
            distance = ""
            if ps.distance_bin == "near":
                distance = ", very close"
            elif ps.distance_bin == "far":
                distance = ", across the room"
            return f"{name} is {direction}{distance}."

        elapsed = now - ps.last_seen
        if elapsed < self.PRESENCE_TIMEOUT:
            direction = self._yaw_to_direction(yaw)
            return f"{name} was {direction} {self._format_ago(elapsed)} ago."

        return f"I haven't seen {name} in a while."

    def get_summary(self):
        """Human-readable summary for LLM context injection."""
        now = time()
        visible = []
        recent = []
        unknown_count = sum(1 for us in self._unknown_tracks.values()
                           if us.visible)

        for name, ps in self._people.items():
            if ps.visible:
                visible.append(name)
            elif now - ps.last_seen < self.PRESENCE_TIMEOUT:
                ago = self._format_ago(now - ps.last_seen)
                direction = self._yaw_to_direction(ps.last_yaw)
                recent.append(f"{name} (was {direction} {ago} ago)")

        parts = []
        if visible:
            parts.append(f"You can see: {', '.join(visible)}")
        if unknown_count:
            parts.append(f"{unknown_count} unknown person(s) visible")
        if recent:
            parts.append(f"Recently here: {', '.join(recent)}")
        if not parts:
            parts.append("No one is around right now")

        return ". ".join(parts) + "."

    def get_greeting(self):
        """Generate a personalized greeting based on who's visible.

        Returns a name to greet, or None if no one recognized.
        """
        visible = self.who_is_visible()
        if visible:
            return visible[0]  # Greet the first recognized person
        return None

    @staticmethod
    def _yaw_to_direction(yaw):
        """Convert yaw angle to human-readable direction."""
        if yaw < -40:
            return "far to your right"
        elif yaw < -15:
            return "to your right"
        elif yaw > 40:
            return "far to your left"
        elif yaw > 15:
            return "to your left"
        else:
            return "in front of you"

    @staticmethod
    def _format_ago(seconds):
        """Format elapsed seconds as human-readable string."""
        if seconds < 10:
            return "a few seconds"
        elif seconds < 60:
            return f"{int(seconds)} seconds"
        elif seconds < 120:
            return "about a minute"
        else:
            return f"{int(seconds / 60)} minutes"
