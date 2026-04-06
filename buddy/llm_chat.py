"""ChatGPT conversation manager with streaming."""

import re
from openai import OpenAI

from . import config


class LLMChat:
    """Manages conversation with ChatGPT, streams responses."""

    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key)
        self.messages = [
            {"role": "system", "content": config.SYSTEM_PROMPT}
        ]

    def chat(self, user_text):
        """Send user message, return full response text.

        Caps message history to MAX_MESSAGES to control costs.
        """
        self.messages.append({"role": "user", "content": user_text})

        # Cap history (keep system prompt + last N messages)
        if len(self.messages) > config.MAX_MESSAGES + 1:
            self.messages = [self.messages[0]] + self.messages[-(config.MAX_MESSAGES):]

        try:
            response = self.client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=self.messages,
                max_tokens=150,
                temperature=0.8,
            )
            reply = response.choices[0].message.content.strip()
            self.messages.append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            print(f"LLM error: {e}")
            return "Woof! My brain is a bit fuzzy right now.\nACTIONS: shake head"

    def add_sensor_event(self, event_text):
        """Add a sensor event as a user message (<<<...>>> format)."""
        self.messages.append({"role": "user", "content": event_text})

    def get_history(self):
        """Return full message history for memory summarization."""
        return self.messages
