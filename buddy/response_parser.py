"""Parse LLM responses into speech text and action list."""

import re

# Actions that are sound-only (no spoken text expected)
VOICE_ACTIONS = {"bark", "bark harder", "pant", "howling"}


def parse_response(text):
    """Parse LLM response into (speech_text, action_list).

    Expected format:
        Some spoken text here
        ACTIONS: action1, action2

    Returns:
        (speech_text, [action1, action2])
    """
    if not text:
        return "", ["nod"]

    # Case-insensitive split on "ACTIONS:" with flexible whitespace
    parts = re.split(r"(?i)\n*actions:\s*", text, maxsplit=1)

    speech_text = parts[0].strip()
    actions = []

    if len(parts) > 1:
        action_str = parts[1].strip()
        if action_str:
            actions = [a.strip().lower() for a in action_str.split(",") if a.strip()]

    # If no actions parsed, default to nod
    if not actions:
        actions = ["nod"]

    # If all actions are voice-only, clear the speech text
    if all(a in VOICE_ACTIONS for a in actions):
        speech_text = ""

    return speech_text, actions
