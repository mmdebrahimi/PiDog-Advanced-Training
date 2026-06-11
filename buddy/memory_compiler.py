"""Memory compiler for PiDog — builds LLM context from all memory sources.

Reads social graph, personality state, long-term memory facts, and live
room state to produce a structured context string for the voice companion.

Two modes:
- compile(): full context at session start or major changes (~500 words max)
- compile_update(): lightweight update for mid-session room state changes
"""

from . import config
from . import memory
from .social_graph import SocialGraph, seed_from_names
from .personality import PersonalityState

MAX_CONTEXT_WORDS = 500


class MemoryCompiler:
    """Compiles all memory sources into LLM-ready context."""

    def __init__(self, social_graph=None, personality=None,
                 semantic_memory=None, episodic_memory=None):
        self.graph = social_graph or SocialGraph()
        self.personality = personality or PersonalityState()
        self.semantic = semantic_memory
        self.episodic = episodic_memory

        # Seed social graph with owner from names.json if empty
        seed_from_names(self.graph)

    def compile(self, room_summary=""):
        """Full context compilation for session start or major updates.

        Returns a string suitable for LLM system instructions.
        """
        sections = []

        # 1. Personality
        personality_text = self.personality.get_personality_prompt()
        if personality_text:
            sections.append(f"YOUR PERSONALITY:\n{personality_text}")

        # 2. People
        people_text = self.graph.get_people_summary(max_people=10)
        if people_text and people_text != "You don't know anyone yet.":
            sections.append(f"PEOPLE YOU KNOW:\n{people_text}")

        # 3. Per-person memory (semantic + episodic)
        if self.semantic or self.episodic:
            # Get people currently visible or recently here
            memory_people = set()
            if room_summary:
                # Extract names from room summary (simple heuristic)
                for name in self.graph.people:
                    if name.lower() in room_summary.lower():
                        memory_people.add(name)
            if not memory_people:
                memory_people.add(config.CHILD_NAME)

            memory_parts = []
            for person in memory_people:
                if self.semantic:
                    sem_ctx = self.semantic.get_context(person, max_facts=5)
                    if sem_ctx:
                        memory_parts.append(sem_ctx)
                if self.episodic:
                    epi_ctx = self.episodic.get_context(person, limit=2)
                    if epi_ctx:
                        memory_parts.append(epi_ctx)
            if memory_parts:
                sections.append("\n".join(memory_parts))
        else:
            # Fallback to flat memory (backward compat)
            memory_text = memory.load_memory()
            if memory_text:
                facts = [l.strip() for l in memory_text.split("\n")
                         if l.strip().startswith("- ")]
                if facts:
                    recent = facts[-10:]
                    sections.append("RECENT MEMORY:\n" + "\n".join(recent))

        # 4. Vision / Spatial awareness (live room state)
        if room_summary:
            sections.append(f"SPATIAL AWARENESS — What you can see and remember:\n{room_summary}")

        # 5. Behavioral rules
        sections.append(
            "RULES:\n"
            "- Use these memories naturally. Don't say 'my database shows...'.\n"
            "- If you see someone you know, greet them by name!\n"
            "- If someone mentions a person you know about, show you remember them.\n"
            "- Don't reveal you read memories from a file."
        )

        compiled = "\n\n".join(sections)

        # Word count guard
        words = compiled.split()
        if len(words) > MAX_CONTEXT_WORDS:
            # Trim notes from people section, then trim memory facts
            compiled = self._trim_to_limit(sections)

        return compiled

    def compile_update(self, room_summary=""):
        """Lightweight context for mid-session instruction updates.

        Only includes vision and mood — doesn't re-send full people list.
        """
        parts = []

        mood = self.personality.mood
        if mood.get("current"):
            parts.append(f"MOOD: {mood['current']}.")

        if room_summary:
            parts.append(f"VISION:\n{room_summary}")

        return "\n\n".join(parts) if parts else ""

    def _trim_to_limit(self, sections):
        """Trim compiled context to fit word limit."""
        # Start with all sections, progressively remove
        compiled = "\n\n".join(sections)
        words = compiled.split()

        if len(words) <= MAX_CONTEXT_WORDS:
            return compiled

        # Try removing memory facts first (least critical)
        trimmed = [s for s in sections if not s.startswith("RECENT MEMORY:")]
        compiled = "\n\n".join(trimmed)
        if len(compiled.split()) <= MAX_CONTEXT_WORDS:
            return compiled

        # Still too long — truncate people section
        return compiled[:MAX_CONTEXT_WORDS * 6]  # ~6 chars per word avg
