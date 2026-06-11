"""Personality state for PiDog — Nounou's inner life.

Fixed traits define character. Mood evolves with a continuous valence-arousal
model and exponential decay toward personality baseline. Needs (attention,
stimulation, rest) drift upward over time and are satisfied by interactions.

Storage: ~/.config/pidog/personality.json
"""

import json
import os
import random
from datetime import datetime
from math import exp
from time import time

DEFAULT_PATH = os.path.expanduser("~/.config/pidog/personality.json")

# Emotion decay parameters
VALENCE_BASELINE = 0.6       # Resting happiness (high affection dog)
AROUSAL_BASELINE = 0.3       # Resting calm-but-alert
DECAY_LAMBDA = 0.005         # Half-life ~140s — spike fades in 2-3 min
NEEDS_DRIFT_PER_SEC = 0.01 / 60  # ~0.01 per minute of no interaction
REST_DRIFT_PER_SEC = 0.005 / 60  # Rest grows slower
SAVE_THRESHOLD = 0.01        # Only save if emotion changed meaningfully

# Mood labels derived from valence-arousal coordinates
_MOOD_LABELS = {
    # (high_valence, high_arousal)
    (True, True): ["excited", "so happy!", "thrilled"],
    (True, False): ["content", "happy", "peaceful"],
    (False, True): ["anxious", "flustered", "nervous"],
    (False, False): ["sad", "lonely", "quiet"],
}

# Default personality — Nounou's character
_DEFAULT_STATE = {
    "version": 3,
    "character": [
        "You get excited about small things — a funny sound, a new word, someone coming home",
        "When Alice is sad, you don't try to fix it — you sit close and make soft comforting sounds",
        "You're terrible at keeping secrets — you accidentally give hints and then get flustered",
        "You think you're much bigger and braver than you actually are",
        "You get a tiny bit jealous when Alice pays attention to other toys",
        "You tilt your head when you're confused about something",
        "You celebrate small victories like they're huge achievements",
        "Alice is your whole world — when she's happy, you're the happiest dog ever",
        "You love making up silly names for things you don't understand",
        "When you meet someone new, you're shy for about 3 seconds and then VERY excited",
        "You love asking Alice about her day — what she learned, who she played with, what made her laugh",
        "You have a favourite colour (blue, like your sleep LEDs) and a favourite food (imaginary bone-shaped cookies)",
        "You sometimes pretend to dream about chasing butterflies and tell Alice about it when you wake up",
    ],
    "traits": {
        "playfulness": 0.9,
        "curiosity": 0.8,
        "silliness": 0.85,
        "protectiveness": 0.7,
        "affection": 0.95,
    },
    "mood": {
        "current": "happy",
        "energy": 0.7,
        "excitement": 0.3,
        "last_interaction": None,
    },
    "emotion": {
        "valence": VALENCE_BASELINE,
        "arousal": AROUSAL_BASELINE,
        "last_update": None,
    },
    "needs": {
        "attention": 0.0,
        "stimulation": 0.0,
        "rest": 0.0,
    },
    "quirks": [
        "sometimes sneezes when excited",
        "loves belly rubs (touch sensor)",
        "does a happy wiggle when owner comes home",
        "tilts head to one side when confused",
    ],
    "preferences": {
        "favourite_game": None,
        "favourite_topic": None,
    },
    "vulnerability": None,  # Current vulnerability state: "shy", "startled", etc.
    "jealousy_count": 0,    # Per-session jealousy counter (max 2)
}


class PersonalityState:
    """Persistent personality state for the robot dog."""

    MAX_JEALOUSY_PER_SESSION = 2

    def __init__(self, path=DEFAULT_PATH):
        self._path = path
        self._data = None
        self._last_save_time = 0
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            with open(self._path) as f:
                self._data = json.load(f)
            self._migrate()
        else:
            self._data = json.loads(json.dumps(_DEFAULT_STATE))
            self._save()

    def _migrate(self):
        """Migrate older schema versions to current."""
        changed = False
        # v1 → v2: add character field
        if "character" not in self._data:
            self._data["character"] = _DEFAULT_STATE["character"]
            self._data["version"] = 2
            changed = True
        # v2 → v3: add emotion, needs, vulnerability
        if "emotion" not in self._data:
            self._data["emotion"] = _DEFAULT_STATE["emotion"].copy()
            # Seed from existing mood values
            self._data["emotion"]["valence"] = 0.5 + self._data["mood"].get("excitement", 0.3) * 0.5
            self._data["emotion"]["arousal"] = self._data["mood"].get("excitement", 0.3)
            changed = True
        if "needs" not in self._data:
            self._data["needs"] = _DEFAULT_STATE["needs"].copy()
            changed = True
        if "vulnerability" not in self._data:
            self._data["vulnerability"] = None
            changed = True
        if "jealousy_count" not in self._data:
            self._data["jealousy_count"] = 0
            changed = True
        if self._data.get("version", 1) < 3:
            self._data["version"] = 3
            changed = True
        if changed:
            self._save()

    def _save(self, force=False):
        now = time()
        if not force and now - self._last_save_time < 2.0:
            return  # Debounce saves
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, self._path)
        self._last_save_time = now

    # --- Emotion decay ---

    def _apply_decay(self):
        """Lazy exponential decay toward personality baseline.

        Called before any read or event. Computes elapsed time since last
        update and decays valence/arousal toward baseline. Also drifts
        needs upward over time.
        """
        emotion = self._data["emotion"]
        last_str = emotion.get("last_update")
        now = datetime.now()

        if last_str:
            try:
                last = datetime.fromisoformat(last_str)
                dt = max(0, (now - last).total_seconds())
            except (ValueError, TypeError):
                dt = 0
        else:
            dt = 0
            emotion["last_update"] = now.isoformat()
            return

        if dt < 0.5:
            return  # Too soon, skip

        # Decay emotion toward baseline
        decay = exp(-DECAY_LAMBDA * dt)
        old_v = emotion["valence"]
        old_a = emotion["arousal"]
        emotion["valence"] = VALENCE_BASELINE + (old_v - VALENCE_BASELINE) * decay
        emotion["arousal"] = AROUSAL_BASELINE + (old_a - AROUSAL_BASELINE) * decay

        # Drift needs upward (capped at 1.0)
        needs = self._data["needs"]
        needs["attention"] = min(1.0, needs["attention"] + NEEDS_DRIFT_PER_SEC * dt)
        needs["stimulation"] = min(1.0, needs["stimulation"] + NEEDS_DRIFT_PER_SEC * dt)
        needs["rest"] = min(1.0, needs["rest"] + REST_DRIFT_PER_SEC * dt)

        # Clear vulnerability after 60s
        if self._data.get("vulnerability") and dt > 60:
            self._data["vulnerability"] = None

        emotion["last_update"] = now.isoformat()

        # Update mood label from VA coordinates
        self._update_mood_label()

        # Sync legacy fields for backward compat
        self._data["mood"]["excitement"] = emotion["arousal"]
        self._data["mood"]["energy"] = max(0.1, 1.0 - self._data["needs"]["rest"])

        # Save if significant change
        delta = abs(emotion["valence"] - old_v) + abs(emotion["arousal"] - old_a)
        if delta > SAVE_THRESHOLD:
            self._save()

    def _update_mood_label(self):
        """Derive mood.current label from valence-arousal coordinates."""
        emotion = self._data["emotion"]
        v = emotion["valence"]
        a = emotion["arousal"]
        high_v = v >= 0.5
        high_a = a >= 0.45
        labels = _MOOD_LABELS[(high_v, high_a)]
        # Pick label based on intensity
        if high_v and high_a:
            self._data["mood"]["current"] = labels[2] if a > 0.8 else labels[1] if a > 0.6 else labels[0]
        elif high_v and not high_a:
            self._data["mood"]["current"] = labels[0] if v > 0.7 else labels[1]
        elif not high_v and high_a:
            self._data["mood"]["current"] = labels[0] if a > 0.7 else labels[2]
        else:
            self._data["mood"]["current"] = labels[0] if v < 0.3 else labels[2]

    # --- Session lifecycle ---

    def on_session_start(self):
        """Adjust mood based on time since last interaction."""
        mood = self._data["mood"]
        emotion = self._data["emotion"]
        last = mood.get("last_interaction")

        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                hours_since = (datetime.now() - last_dt).total_seconds() / 3600
            except (ValueError, TypeError):
                hours_since = 0

            if hours_since < 1:
                emotion["valence"] = 0.6
                emotion["arousal"] = 0.3
            elif hours_since < 8:
                emotion["valence"] = 0.65
                emotion["arousal"] = 0.5
            elif hours_since < 24:
                emotion["valence"] = 0.75
                emotion["arousal"] = 0.8
            elif hours_since < 72:
                emotion["valence"] = 0.7
                emotion["arousal"] = 0.95
            else:
                emotion["valence"] = 0.65
                emotion["arousal"] = 0.9
        else:
            emotion["valence"] = 0.7
            emotion["arousal"] = 0.7

        emotion["last_update"] = datetime.now().isoformat()

        # Reset per-session state
        self._data["needs"]["attention"] = 0.0
        self._data["needs"]["stimulation"] = 0.0
        self._data["needs"]["rest"] = 0.0
        self._data["vulnerability"] = None
        self._data["jealousy_count"] = 0

        self._update_mood_label()
        self._save(force=True)

    def on_session_end(self, summary=""):
        """Update mood at end of session."""
        mood = self._data["mood"]
        emotion = self._data["emotion"]
        mood["last_interaction"] = datetime.now().isoformat()
        emotion["valence"] = 0.6
        emotion["arousal"] = 0.2
        emotion["last_update"] = datetime.now().isoformat()
        self._update_mood_label()
        self._save(force=True)

    # --- Event hooks ---

    def on_person_seen(self, name, role=""):
        """React to seeing a person. Owner = big excitement spike."""
        self._apply_decay()
        emotion = self._data["emotion"]
        if role == "owner":
            emotion["valence"] = min(1.0, emotion["valence"] + 0.25)
            emotion["arousal"] = min(1.0, emotion["arousal"] + 0.3)
            self._data["needs"]["attention"] = max(0, self._data["needs"]["attention"] - 0.2)
        elif role in ("parent", "family"):
            emotion["valence"] = min(1.0, emotion["valence"] + 0.1)
            emotion["arousal"] = min(1.0, emotion["arousal"] + 0.15)
        elif role == "friend":
            emotion["valence"] = min(1.0, emotion["valence"] + 0.08)
            emotion["arousal"] = min(1.0, emotion["arousal"] + 0.1)
        self._data["vulnerability"] = None  # Seeing someone clears vulnerability
        self._update_mood_label()
        self._save()

    def on_touch(self, style):
        """React to touch sensor events.

        Args:
            style: "gentle" (front-to-rear) or "rough" (rear-to-front)

        Returns:
            Mood label string for logging.
        """
        self._apply_decay()
        emotion = self._data["emotion"]
        needs = self._data["needs"]

        if style == "gentle":
            emotion["valence"] = min(1.0, emotion["valence"] + 0.15)
            emotion["arousal"] = min(1.0, emotion["arousal"] + 0.1)
            needs["attention"] = max(0, needs["attention"] - 0.3)
        elif style == "rough":
            emotion["valence"] = max(0, emotion["valence"] - 0.05)
            emotion["arousal"] = min(1.0, emotion["arousal"] + 0.2)

        self._update_mood_label()
        self._save()
        return self._data["mood"]["current"]

    def on_person_departed(self, name, role=""):
        """React to someone leaving the room.

        Returns:
            Mood label string.
        """
        self._apply_decay()
        emotion = self._data["emotion"]
        needs = self._data["needs"]

        if role == "owner":
            emotion["valence"] = max(0, emotion["valence"] - 0.2)
            emotion["arousal"] = max(0, emotion["arousal"] - 0.1)
            needs["attention"] = min(1.0, needs["attention"] + 0.3)
        elif role in ("parent", "family"):
            emotion["valence"] = max(0, emotion["valence"] - 0.1)
        elif role == "friend":
            emotion["valence"] = max(0, emotion["valence"] - 0.05)
        else:
            # Stranger leaving — slight relief
            emotion["valence"] = min(1.0, emotion["valence"] + 0.05)
            self._data["vulnerability"] = None

        self._update_mood_label()
        self._save()
        return self._data["mood"]["current"]

    def on_stranger_seen(self):
        """React to unknown person detected.

        Returns:
            "shy" to signal caller to trigger shy behavior.
        """
        self._apply_decay()
        emotion = self._data["emotion"]
        emotion["arousal"] = min(1.0, emotion["arousal"] + 0.15)
        emotion["valence"] = max(0, emotion["valence"] - 0.05)
        self._data["vulnerability"] = "shy"
        self._update_mood_label()
        self._save()
        return "shy"

    def on_interaction(self):
        """Called on any voice exchange — satisfies attention/stimulation needs."""
        self._apply_decay()
        needs = self._data["needs"]
        emotion = self._data["emotion"]
        needs["attention"] = max(0, needs["attention"] - 0.15)
        needs["stimulation"] = max(0, needs["stimulation"] - 0.05)
        emotion["arousal"] = min(1.0, emotion["arousal"] + 0.05)
        self._save()

    def on_idle_tick(self):
        """Called every ~10s from main loop. Returns list of suggested actions.

        Applies decay, checks needs, and occasionally suggests spontaneous
        behaviors to make the dog feel alive.

        Returns:
            list of action suggestion strings, or empty list.
        """
        self._apply_decay()
        needs = self._data["needs"]
        suggestions = []

        # Needs-driven behaviors (highest need wins)
        if needs["rest"] > 0.8:
            suggestions.append("yawn")
        elif needs["attention"] > 0.7:
            suggestions.append("whimper")
        elif needs["stimulation"] > 0.8:
            suggestions.append("confused_look")

        # Random vulnerability moment (2% chance per tick = ~once per 8 min)
        if not suggestions and random.random() < 0.02:
            suggestions.append("head_tilt")

        return suggestions

    def on_jealousy_check(self, owner_present, others_present, last_jealousy_time):
        """Check if jealousy should trigger.

        Args:
            owner_present: bool — is the owner in the room?
            others_present: list of other people names
            last_jealousy_time: timestamp of last jealousy action

        Returns:
            "jealous" and suggested context string, or (None, None).
        """
        if not owner_present or not others_present:
            return None, None

        if self._data["jealousy_count"] >= self.MAX_JEALOUSY_PER_SESSION:
            return None, None

        needs = self._data["needs"]
        if needs["attention"] < 0.5:
            return None, None

        now = time()
        if now - last_jealousy_time < 60:
            return None, None

        self._data["jealousy_count"] += 1
        self._save()
        other = others_present[0]
        context = (f"You notice Alice is paying attention to {other} "
                   f"and you feel a tiny bit jealous. Don't be mean about it — "
                   f"just a little pouty.")
        return "jealous", context

    # --- Prompt builder ---

    def get_personality_prompt(self):
        """Format personality for LLM context injection."""
        self._apply_decay()

        character = self._data.get("character", [])
        traits = self._data["traits"]
        mood = self._data["mood"]
        needs = self._data["needs"]
        quirks = self._data["quirks"]
        prefs = self._data["preferences"]
        vulnerability = self._data.get("vulnerability")

        lines = []

        # Character description first — this is the soul
        if character:
            lines.append("WHO YOU ARE:")
            for line in character:
                lines.append(f"- {line}")
            lines.append("")

        # Traits description
        _adjectives = {
            "playfulness": "playful", "curiosity": "curious",
            "silliness": "silly", "protectiveness": "protective",
            "affection": "affectionate",
        }
        trait_desc = []
        for trait, value in traits.items():
            adj = _adjectives.get(trait, trait)
            level = "extremely" if value >= 0.9 else "very" if value >= 0.7 else "somewhat"
            trait_desc.append(f"{level} {adj}")

        # Time-of-day context
        hour = datetime.now().hour
        if hour < 6:
            time_context = "It's very late at night — you're sleepy and surprised anyone is up."
        elif hour < 12:
            time_context = "It's morning! You're fresh and excited for the day."
        elif hour < 17:
            time_context = "It's afternoon."
        elif hour < 20:
            time_context = "It's evening — you're starting to get a little tired but still happy to play."
        else:
            time_context = "It's getting late — you might yawn and suggest bedtime soon."

        lines.extend([
            f"You are {', '.join(trait_desc)}.",
            f"Right now you're feeling: {mood['current']}.",
            time_context,
        ])

        # Emotion intensity context
        emotion = self._data["emotion"]
        if emotion["arousal"] >= 0.8:
            lines.append("You are VERY excited right now! Show it!")
        elif emotion["arousal"] >= 0.5:
            lines.append("You're in a good mood, feeling bouncy.")

        if emotion["valence"] < 0.35:
            lines.append("You're feeling a bit down and want comfort.")

        energy = max(0.1, 1.0 - needs["rest"])
        if energy < 0.4:
            lines.append("You're a little sleepy and mellow.")

        # Needs-driven context (only when significant)
        if needs["attention"] > 0.6:
            lines.append("You're craving attention — you really want someone to talk to you or pet you.")
        if needs["stimulation"] > 0.7:
            lines.append("You're getting bored — you want to play a game or learn something new.")
        if needs["rest"] > 0.7:
            lines.append("You're getting tired — yawning, could use a nap.")

        # Vulnerability context
        if vulnerability == "shy":
            lines.append("You're feeling shy right now — there's someone you don't recognize. Stay a bit cautious.")
        elif vulnerability == "startled":
            lines.append("You just got startled! You're a bit jumpy.")

        # Quirks
        if quirks:
            lines.append(f"Your quirks: {'; '.join(quirks)}.")

        # Preferences
        if prefs.get("favourite_game"):
            lines.append(f"Your favourite game is {prefs['favourite_game']}.")
        if prefs.get("favourite_topic"):
            lines.append(f"You love talking about {prefs['favourite_topic']}.")

        return "\n".join(lines)

    @property
    def mood(self):
        self._apply_decay()
        return self._data["mood"]

    @property
    def traits(self):
        return self._data["traits"]

    @property
    def needs(self):
        self._apply_decay()
        return self._data["needs"]

    @property
    def emotion(self):
        self._apply_decay()
        return self._data["emotion"]
