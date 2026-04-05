"""Personality state for PiDog — Nounou's inner life.

Fixed traits define character. Mood evolves between sessions.
Quirks add flavor. Preferences develop over time.

Storage: ~/.config/pidog/personality.json
"""

import json
import os
from datetime import datetime
from time import time

DEFAULT_PATH = os.path.expanduser("~/.config/pidog/personality.json")

# Default personality — Nounou's character
_DEFAULT_STATE = {
    "version": 1,
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
    "quirks": [
        "sometimes sneezes when excited",
        "loves belly rubs (touch sensor)",
        "gets a little shy around strangers at first",
        "does a happy wiggle when owner comes home",
    ],
    "preferences": {
        "favourite_game": None,
        "favourite_topic": None,
    },
}


class PersonalityState:
    """Persistent personality state for the robot dog."""

    def __init__(self, path=DEFAULT_PATH):
        self._path = path
        self._data = None
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            with open(self._path) as f:
                self._data = json.load(f)
        else:
            self._data = json.loads(json.dumps(_DEFAULT_STATE))
            self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, self._path)

    def on_session_start(self):
        """Adjust mood based on time since last interaction."""
        mood = self._data["mood"]
        last = mood.get("last_interaction")

        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                hours_since = (datetime.now() - last_dt).total_seconds() / 3600
            except (ValueError, TypeError):
                hours_since = 0

            if hours_since < 1:
                # Just saw them — calm contentment
                mood["excitement"] = 0.3
                mood["energy"] = 0.7
            elif hours_since < 8:
                # Few hours — normal happy
                mood["excitement"] = 0.5
                mood["energy"] = 0.7
                mood["current"] = "happy"
            elif hours_since < 24:
                # Half a day — excited to see them!
                mood["excitement"] = 0.8
                mood["energy"] = 0.8
                mood["current"] = "excited"
            elif hours_since < 72:
                # 1-3 days — very excited, missed them
                mood["excitement"] = 0.95
                mood["energy"] = 0.6
                mood["current"] = "missed you!"
            else:
                # Long absence — still excited but a bit low energy
                mood["excitement"] = 0.9
                mood["energy"] = 0.5
                mood["current"] = "missed you so much!"
        else:
            # First ever session
            mood["excitement"] = 0.7
            mood["energy"] = 0.8
            mood["current"] = "excited"

        self._save()

    def on_session_end(self, summary=""):
        """Update mood at end of session."""
        mood = self._data["mood"]
        mood["last_interaction"] = datetime.now().isoformat()
        mood["excitement"] = 0.3  # Content after a good session
        mood["energy"] = 0.6
        mood["current"] = "content"
        self._save()

    def on_person_seen(self, name, role=""):
        """React to seeing a person. Owner = big excitement spike."""
        mood = self._data["mood"]
        if role == "owner":
            mood["excitement"] = min(1.0, mood["excitement"] + 0.3)
            mood["current"] = "so happy!"
        elif role in ("parent", "family"):
            mood["excitement"] = min(1.0, mood["excitement"] + 0.15)
        self._save()

    def get_personality_prompt(self):
        """Format personality for LLM context injection."""
        traits = self._data["traits"]
        mood = self._data["mood"]
        quirks = self._data["quirks"]
        prefs = self._data["preferences"]

        # Traits description (map to adjective form)
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

        lines = [
            f"You are {', '.join(trait_desc)}.",
            f"Right now you're feeling: {mood['current']}.",
        ]

        # Energy/excitement context
        if mood["excitement"] >= 0.8:
            lines.append("You are VERY excited right now! Show it!")
        elif mood["excitement"] >= 0.5:
            lines.append("You're in a good mood, feeling bouncy.")

        if mood["energy"] < 0.4:
            lines.append("You're a little sleepy and mellow.")

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
        return self._data["mood"]

    @property
    def traits(self):
        return self._data["traits"]
