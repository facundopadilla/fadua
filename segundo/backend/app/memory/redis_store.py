"""Redis-backed conversation memory.

Key layout: ``conv:{conversation_id}`` -> Redis list of JSON-encoded messages.
Every append refreshes the TTL, so active conversations stay alive while idle
ones expire after ``ttl_seconds`` (default 14 days — locked decision).
"""

import json

import redis.asyncio as redis


class RedisConversationMemory:
    def __init__(self, url: str, ttl_seconds: int = 1_209_600) -> None:
        # from_url does not connect eagerly; connections open on first command.
        self._client = redis.from_url(url, decode_responses=True)
        self._ttl_seconds = ttl_seconds

    async def get_history(self, conversation_id: str) -> list[dict]:
        raw = await self._client.lrange(self._key(conversation_id), 0, -1)
        return [json.loads(item) for item in raw]

    async def append(self, conversation_id: str, message: dict) -> None:
        key = self._key(conversation_id)
        await self._client.rpush(key, json.dumps(message, ensure_ascii=False))
        await self._client.expire(key, self._ttl_seconds)

    @staticmethod
    def _key(conversation_id: str) -> str:
        return f"conv:{conversation_id}"
