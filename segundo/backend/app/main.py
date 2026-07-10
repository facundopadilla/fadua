"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.models import ALLOWED_MODELS
from app.api.chat import router as chat_router
from app.config import settings
from app.memory.redis_store import RedisConversationMemory

# Module-level memory instance; the underlying Redis client connects lazily.
memory = RedisConversationMemory(
    url=settings.redis_url,
    ttl_seconds=settings.conversation_ttl_seconds,
)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.memory = memory
app.include_router(chat_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/models")
async def models() -> dict[str, list[str]]:
    """Return the hardcoded OpenCode GO model allow-list the frontend's model
    picker offers — never a live proxy of the provider's own /models list."""
    return {"models": list(ALLOWED_MODELS)}
