"""POST /chat — SSE endpoint.

Locked API contract: stream the answer as ``token`` events, then emit exactly
one ``done`` event carrying the full structured ChatResponse. Never stream the
structured object incrementally.
"""

import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.agent.engine import AnalyticsEngine
from app.memory.base import ConversationMemory
from app.schemas.chat import ChatRequest

router = APIRouter()


@router.post("/chat")
async def chat(chat_request: ChatRequest, request: Request) -> StreamingResponse:
    memory: ConversationMemory = request.app.state.memory
    conversation_id = chat_request.conversation_id or str(uuid4())

    # Prior turns feed the engine so short follow-ups ("¿y el peor?") resolve
    # against the previous question, per CLAUDE.md's conversational memory.
    history = await memory.get_history(conversation_id)
    await memory.append(conversation_id, {"role": "user", "content": chat_request.message})

    agent = AnalyticsEngine()

    async def event_stream() -> AsyncIterator[str]:
        async for event_type, event_data in agent.stream(chat_request, conversation_id, history):
            if event_type == "token":
                payload = json.dumps({"text": event_data}, ensure_ascii=False)
                yield f"event: token\ndata: {payload}\n\n"
            else:
                await memory.append(
                    conversation_id, {"role": "assistant", "content": event_data.answer}
                )
                yield f"event: done\ndata: {event_data.model_dump_json()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
