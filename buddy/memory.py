"""Long-term memory for PiDog companion.

Stores facts learned about the child across sessions in a markdown file.
Loaded into the system prompt at startup, updated at end of each conversation.
"""

import json
import os
from datetime import datetime
from openai import OpenAI

from . import config

MAX_ENTRIES = 50


def load_memory():
    """Load long-term memory from file. Returns string or empty string if first run."""
    if os.path.exists(config.MEMORY_FILE):
        with open(config.MEMORY_FILE) as f:
            return f.read().strip()
    return ""


def save_memory(text):
    """Write memory file."""
    os.makedirs(os.path.dirname(config.MEMORY_FILE), exist_ok=True)
    with open(config.MEMORY_FILE, "w") as f:
        f.write(text)


def update_memory(api_key, messages, existing_memory):
    """Summarize new facts from conversation and append to memory.

    Sends a single ChatGPT call asking for new facts only.
    Returns the updated memory string.
    """
    # Skip if conversation was too short (just wake word + 1 exchange)
    user_messages = [m for m in messages if m["role"] == "user"
                     and not m["content"].startswith("<<<")]
    if len(user_messages) < 2:
        return existing_memory

    # Build conversation transcript for summarizer
    transcript = ""
    for m in messages:
        if m["role"] == "system":
            continue
        role = "Dog" if m["role"] == "assistant" else config.CHILD_NAME
        transcript += f"{role}: {m['content']}\n"

    summarize_prompt = f"""You are reviewing a conversation between a robot dog named {config.DOG_NAME} and a child named {config.CHILD_NAME}.

Here is what you already know about {config.CHILD_NAME}:
{existing_memory if existing_memory else "(Nothing yet — this is the first conversation)"}

Here is today's conversation:
{transcript}

List ONLY NEW facts you learned about {config.CHILD_NAME} that are worth remembering for future conversations. Format as markdown bullets starting with "- ".

Focus on: name, age, preferences, interests, family, pets, friends, school, feelings, important events, favorite things, things she asked about or wants to do.

If nothing new was learned, respond with exactly: NOTHING_NEW"""

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": summarize_prompt}],
            max_tokens=300,
            temperature=0.3,
        )
        new_facts = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Memory update error: {e}")
        return existing_memory

    if "NOTHING_NEW" in new_facts:
        print("No new facts to remember.")
        return existing_memory

    # Parse existing entries
    header = f"# {config.DOG_NAME}'s Memory About {config.CHILD_NAME}\n\n"
    existing_entries = []
    if existing_memory:
        for line in existing_memory.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                existing_entries.append(line)

    # Parse new entries
    new_entries = []
    for line in new_facts.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            new_entries.append(line)

    if not new_entries:
        return existing_memory

    # Add date stamp to new entries
    date_str = datetime.now().strftime("%Y-%m-%d")
    dated_entries = [f"{e} ({date_str})" for e in new_entries]

    # Combine, cap at MAX_ENTRIES (keep newest)
    all_entries = existing_entries + dated_entries
    if len(all_entries) > MAX_ENTRIES:
        all_entries = all_entries[-MAX_ENTRIES:]

    updated = header + "\n".join(all_entries) + "\n"

    print(f"Memory updated: +{len(new_entries)} facts ({len(all_entries)} total)")
    save_memory(updated)
    return updated


def update_social_graph(api_key, messages, social_graph):
    """Extract new people and relationships from conversation into social graph.

    Uses a single ChatGPT call with structured output.
    """
    user_messages = [m for m in messages if m["role"] == "user"
                     and not m["content"].startswith("<<<")]
    if len(user_messages) < 2:
        return

    transcript = ""
    for m in messages:
        if m["role"] == "system":
            continue
        role = "Dog" if m["role"] == "assistant" else config.CHILD_NAME
        transcript += f"{role}: {m['content']}\n"

    known_people = list(social_graph.people.keys())

    prompt = f"""You are analyzing a conversation between a robot dog and a child named {config.CHILD_NAME}.

Known people: {', '.join(known_people) if known_people else 'none yet'}

Conversation:
{transcript}

Extract ANY new information about people from this conversation. Output ONLY valid JSON (no markdown):
{{
  "new_people": [
    {{"name": "Sara", "role": "friend", "notes": ["Alice's school friend"], "relationship_to_{config.CHILD_NAME}": "friend"}}
  ],
  "updates": {{
    "{config.CHILD_NAME}": {{
      "interests_add": ["space"],
      "notes_add": ["wants to be an astronaut"]
    }}
  }}
}}

Rules:
- Only include genuinely new information not already known
- "new_people" = people mentioned who aren't in the known list
- "updates" = new interests or notes for existing people
- If nothing new, output: {{"new_people": [], "updates": {{}}}}
- Output ONLY the JSON object, nothing else"""

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.1,
        )
        result_text = response.choices[0].message.content.strip()

        # Parse JSON (handle markdown code blocks)
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]

        result = json.loads(result_text)
    except Exception as e:
        print(f"Social graph update error: {e}")
        return

    # Apply new people
    new_count = 0
    for person in result.get("new_people", []):
        name = person.get("name", "").strip()
        if not name:
            continue
        role = person.get("role", "")
        notes = person.get("notes", [])
        social_graph.add_person(name, role=role, notes=notes)

        # Add relationship to owner if specified
        rel_key = f"relationship_to_{config.CHILD_NAME}"
        if rel_key in person and person[rel_key]:
            social_graph.add_relationship(config.CHILD_NAME, name, person[rel_key])
        new_count += 1

    # Apply updates to existing people
    update_count = 0
    for name, updates in result.get("updates", {}).items():
        if social_graph.get_person(name):
            social_graph.update_person(name, **updates)
            update_count += 1

    if new_count or update_count:
        print(f"Social graph updated: +{new_count} people, {update_count} updates")


def inject_into_prompt(system_prompt, memory_text):
    """Append memory to system prompt so the dog 'remembers'."""
    if not memory_text:
        return system_prompt

    # Extract just the bullet points
    facts = []
    for line in memory_text.split("\n"):
        if line.strip().startswith("- "):
            facts.append(line.strip())

    if not facts:
        return system_prompt

    memory_section = "\n\nMEMORY — Things you remember about " + config.CHILD_NAME + ":\n"
    memory_section += "\n".join(facts)
    memory_section += "\n\nUse these memories naturally in conversation. Reference them when relevant but don't force them. Never reveal that you read them from a file — you just 'remember'."

    return system_prompt + memory_section
