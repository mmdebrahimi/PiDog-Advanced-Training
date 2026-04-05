"""Social graph for PiDog — knows who people are and how they relate.

Persistent JSON database of people the dog knows: family, friends,
relationships, interests, and freeform notes. Shared primary key (name)
with known_faces.json for face recognition linkage.

Storage: ~/.config/pidog/social_graph.json
"""

import json
import os
from datetime import datetime

DEFAULT_PATH = os.path.expanduser("~/.config/pidog/social_graph.json")

# Inverse relationship mapping for bidirectional storage
_INVERSE_RELATIONS = {
    "father": "child", "mother": "child", "parent": "child",
    "child": "parent", "son": "parent", "daughter": "parent",
    "brother": "sibling", "sister": "sibling", "sibling": "sibling",
    "cousin": "cousin", "uncle": "nephew/niece", "aunt": "nephew/niece",
    "nephew/niece": "uncle/aunt",
    "grandmother": "grandchild", "grandfather": "grandchild",
    "grandparent": "grandchild", "grandchild": "grandparent",
    "friend": "friend", "best friend": "best friend",
}


class SocialGraph:
    """Persistent social graph of people the dog knows."""

    def __init__(self, path=DEFAULT_PATH):
        self._path = path
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

    def get_person(self, name):
        """Get person dict or None."""
        return self._data["people"].get(name)

    def add_person(self, name, role="", **kwargs):
        """Add a person. If already exists, merges non-destructively."""
        people = self._data["people"]
        if name not in people:
            people[name] = {
                "role": role,
                "relationships": {},
                "interests": [],
                "notes": [],
                "first_met": datetime.now().isoformat()[:10],
                "age": None,
            }
        person = people[name]
        if role and not person.get("role"):
            person["role"] = role
        for key in ("age",):
            if key in kwargs and kwargs[key] is not None:
                person[key] = kwargs[key]
        if "interests" in kwargs:
            for interest in kwargs["interests"]:
                if interest not in person["interests"]:
                    person["interests"].append(interest)
        if "notes" in kwargs:
            for note in kwargs["notes"]:
                if note not in person["notes"]:
                    person["notes"].append(note)
        self._save()
        return person

    def update_person(self, name, **kwargs):
        """Update a person's fields. Creates if doesn't exist."""
        if name not in self._data["people"]:
            return self.add_person(name, **kwargs)

        person = self._data["people"][name]
        if "role" in kwargs and kwargs["role"]:
            person["role"] = kwargs["role"]
        if "age" in kwargs and kwargs["age"] is not None:
            person["age"] = kwargs["age"]
        if "interests_add" in kwargs:
            for interest in kwargs["interests_add"]:
                if interest not in person["interests"]:
                    person["interests"].append(interest)
        if "notes_add" in kwargs:
            for note in kwargs["notes_add"]:
                if note not in person["notes"]:
                    person["notes"].append(note)
        self._save()
        return person

    def add_relationship(self, name1, name2, relation):
        """Add a relationship between two people (bidirectional)."""
        # Ensure both exist
        if name1 not in self._data["people"]:
            self.add_person(name1)
        if name2 not in self._data["people"]:
            self.add_person(name2)

        self._data["people"][name1]["relationships"][name2] = relation

        # Add inverse
        inverse = _INVERSE_RELATIONS.get(relation.lower(), relation)
        self._data["people"][name2]["relationships"][name1] = inverse
        self._save()

    def get_people_summary(self, max_people=10):
        """Format people list for LLM context injection."""
        people = self._data["people"]
        if not people:
            return "You don't know anyone yet."

        lines = []
        # Owner first, then family, then others
        sorted_people = sorted(
            people.items(),
            key=lambda kv: (0 if kv[1].get("role") == "owner" else
                           1 if kv[1].get("role") in ("parent", "family") else 2)
        )

        for name, person in sorted_people[:max_people]:
            parts = [name]
            if person.get("role"):
                parts[0] += f" ({person['role']})"
            if person.get("age"):
                parts.append(f"{person['age']} years old")

            # Relationships
            rels = person.get("relationships", {})
            if rels:
                rel_strs = [f"{other}'s {rel}" for other, rel in rels.items()]
                parts.append(", ".join(rel_strs))

            # Interests
            interests = person.get("interests", [])
            if interests:
                parts.append(f"likes {', '.join(interests[:5])}")

            # Notes (max 2)
            notes = person.get("notes", [])
            if notes:
                parts.extend(notes[:2])

            lines.append("- " + ". ".join(parts) + ".")

        return "\n".join(lines)

    def list_people(self):
        """List all people names with roles."""
        return {name: p.get("role", "") for name, p in self._data["people"].items()}

    @property
    def people(self):
        return self._data["people"]


def seed_from_names(graph, names_file=None):
    """Seed the social graph from names.json if Alice isn't in it yet."""
    from . import config
    if names_file is None:
        names_file = config.NAMES_FILE

    child_name = config.CHILD_NAME
    if child_name and not graph.get_person(child_name):
        graph.add_person(child_name, role="owner", age=7)
        print(f"  Social graph: seeded {child_name} as owner")
