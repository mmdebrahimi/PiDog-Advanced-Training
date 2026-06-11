"""Semantic memory for PiDog — per-person long-term fact storage.

Stores facts, milestones, and topic frequency counters for each person
the dog knows. Facts are deduplicated by substring matching against
existing entries for the same person.

Storage: ~/.config/pidog/semantic_memory.json
"""

import json
import os
from datetime import datetime

DEFAULT_PATH = os.path.expanduser("~/.config/pidog/semantic_memory.json")
MAX_FACTS_PER_PERSON = 50


class SemanticMemory:
    """Per-person fact and milestone storage."""

    def __init__(self, path=DEFAULT_PATH):
        self._path = path
        self._data = {"version": 1, "people": {}}
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

    def _ensure_person(self, person):
        if person not in self._data["people"]:
            self._data["people"][person] = {
                "facts": [],
                "milestones": [],
                "topics_discussed": {},
            }
        return self._data["people"][person]

    def add_fact(self, person, fact, source="conversation"):
        """Add a fact about a person, skipping if duplicate."""
        entry = self._ensure_person(person)
        fact_lower = fact.lower().strip()

        # Dedup: skip if existing fact contains this as substring or vice versa
        for existing in entry["facts"]:
            existing_lower = existing["fact"].lower()
            if fact_lower in existing_lower or existing_lower in fact_lower:
                return False  # duplicate

        entry["facts"].append({
            "fact": fact,
            "learned": datetime.now().strftime("%Y-%m-%d"),
            "confidence": "high" if source == "told-by-person" else "medium",
            "source": source,
        })

        # Cap per person
        if len(entry["facts"]) > MAX_FACTS_PER_PERSON:
            entry["facts"] = entry["facts"][-MAX_FACTS_PER_PERSON:]

        self._save()
        return True

    def get_facts(self, person, limit=10):
        """Get recent facts for a person."""
        entry = self._data["people"].get(person)
        if not entry:
            return []
        return entry["facts"][-limit:]

    def add_milestone(self, person, event):
        """Record a milestone event for a person."""
        entry = self._ensure_person(person)
        entry["milestones"].append({
            "event": event,
            "date": datetime.now().strftime("%Y-%m-%d"),
        })
        self._save()

    def increment_topic(self, person, topic):
        """Increment the discussion count for a topic."""
        entry = self._ensure_person(person)
        topics = entry["topics_discussed"]
        topics[topic] = topics.get(topic, 0) + 1
        self._save()

    def get_top_topics(self, person, limit=5):
        """Get most-discussed topics for a person."""
        entry = self._data["people"].get(person)
        if not entry:
            return []
        topics = entry.get("topics_discussed", {})
        return sorted(topics.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_context(self, person, max_facts=8):
        """Format semantic memory for LLM context injection.

        Returns a string like:
        "Things you know about Alice:
         - Alice is 7 years old (high confidence)
         - Alice loves penguins
         - You talk about animals a lot (8 times)"
        """
        entry = self._data["people"].get(person)
        if not entry:
            return ""

        lines = [f"Things you know about {person}:"]

        # Recent facts
        facts = entry["facts"][-max_facts:]
        for f in facts:
            lines.append(f"- {f['fact']}")

        # Top topics
        topics = self.get_top_topics(person, limit=3)
        if topics:
            topic_strs = [f"{t} ({c} times)" for t, c in topics]
            lines.append(f"- You often talk about: {', '.join(topic_strs)}")

        # Milestones
        milestones = entry.get("milestones", [])
        if milestones:
            latest = milestones[-1]
            lines.append(f"- Milestone: {latest['event']} ({latest['date']})")

        return "\n".join(lines)

    @property
    def people(self):
        return self._data["people"]
