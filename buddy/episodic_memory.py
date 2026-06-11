"""Episodic memory for PiDog — rolling session summaries.

Stores the last N conversation sessions with summaries, emotional tone,
key moments, and which people were present. Enables "remember when we
talked about..." conversations.

Storage: ~/.config/pidog/episodic_memory.json
"""

import json
import os
from datetime import datetime

DEFAULT_PATH = os.path.expanduser("~/.config/pidog/episodic_memory.json")
MAX_SESSIONS = 10


class EpisodicMemory:
    """Rolling session summary storage."""

    def __init__(self, path=DEFAULT_PATH, max_sessions=MAX_SESSIONS):
        self._path = path
        self._max = max_sessions
        self._data = {"version": 1, "sessions": []}
        self._load()

    def _load(self):
        if os.path.exists(self._path) and os.path.getsize(self._path) > 0:
            with open(self._path) as f:
                self._data = json.load(f)

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, self._path)

    def add_session(self, session):
        """Add a session summary.

        Args:
            session: dict with keys:
                date (str): ISO datetime
                duration_minutes (float): session length
                people_present (list[str]): who was there
                summary (str): LLM-generated session summary
                emotional_tone (str): e.g. "happy, excited"
                key_moments (list[str]): notable moments
                new_facts_learned (list[str]): facts extracted this session
        """
        # Ensure required fields
        session.setdefault("date", datetime.now().isoformat())
        session.setdefault("people_present", [])
        session.setdefault("summary", "")
        session.setdefault("emotional_tone", "")
        session.setdefault("key_moments", [])
        session.setdefault("new_facts_learned", [])

        self._data["sessions"].append(session)

        # Cap total sessions
        if len(self._data["sessions"]) > self._max:
            self._data["sessions"] = self._data["sessions"][-self._max:]

        self._save()

    def get_recent(self, person=None, limit=5):
        """Get recent sessions, optionally filtered by person.

        Args:
            person: if provided, only return sessions where this person was present
            limit: max sessions to return

        Returns:
            list of session dicts, newest first
        """
        sessions = self._data["sessions"]
        if person:
            sessions = [s for s in sessions if person in s.get("people_present", [])]
        return list(reversed(sessions[-limit:]))

    def get_context(self, person, limit=3):
        """Format episodic memory for LLM context injection.

        Returns a string like:
        "Recent conversations with Alice:
         - Yesterday: You talked about the zoo trip. Alice loved the penguins. (happy, excited)
         - 2 days ago: Alice showed you her drawing. (proud, creative)"
        """
        sessions = self.get_recent(person, limit)
        if not sessions:
            return ""

        lines = [f"Recent conversations with {person}:"]
        today = datetime.now().date()

        for s in sessions:
            try:
                session_date = datetime.fromisoformat(s["date"]).date()
                days_ago = (today - session_date).days
                if days_ago == 0:
                    when = "Today"
                elif days_ago == 1:
                    when = "Yesterday"
                else:
                    when = f"{days_ago} days ago"
            except (ValueError, KeyError):
                when = "Recently"

            summary = s.get("summary", "You had a conversation.")
            tone = s.get("emotional_tone", "")
            tone_str = f" ({tone})" if tone else ""

            lines.append(f"- {when}: {summary}{tone_str}")

        return "\n".join(lines)

    @property
    def sessions(self):
        return self._data["sessions"]
