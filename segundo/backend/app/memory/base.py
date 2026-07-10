"""Storage contract for per-conversation message history.

The API layer and the agent depend on this protocol only, so the Redis
implementation can later be swapped (e.g. for a MySQL archive) without
touching them.
"""

from typing import Protocol


class ConversationMemory(Protocol):
    async def get_history(self, conversation_id: str) -> list[dict]:
        """Return all messages of a conversation, oldest first."""
        ...

    async def append(self, conversation_id: str, message: dict) -> None:
        """Append one message (e.g. {"role": "user", "content": "..."})."""
        ...
