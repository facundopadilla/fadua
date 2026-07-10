"""Allow-listed OpenCode GO model ids and the resolver that guards them.

This module has no side effects at import time — it only defines a constant
and a pure-ish function reading ``settings.llm_model`` — so it is always safe
to import regardless of whether ``settings.llm_api_key`` is configured.
"""

from __future__ import annotations

from app.config import settings

# The 20 OpenCode GO models exposed to the frontend's model picker, in the
# exact order the UI should list them (see GET /models). This tuple is the
# single source of truth for both the allow-list check in resolve_model()
# and the /models endpoint's response — there is no other place a model id
# is considered valid.
ALLOWED_MODELS: tuple[str, ...] = (
    "minimax-m3",
    "minimax-m2.7",
    "minimax-m2.5",
    "kimi-k2.7-code",
    "kimi-k2.6",
    "kimi-k2.5",
    "glm-5.2",
    "glm-5.1",
    "glm-5",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "qwen3.7-max",
    "qwen3.7-plus",
    "qwen3.6-plus",
    "qwen3.5-plus",
    "mimo-v2-pro",
    "mimo-v2-omni",
    "mimo-v2.5-pro",
    "mimo-v2.5",
    "hy3-preview",
)

# O(1) membership check for resolve_model(); ALLOWED_MODELS stays a tuple
# (ordered, immutable) so the /models endpoint can return it directly.
_ALLOWED_MODELS_SET: frozenset[str] = frozenset(ALLOWED_MODELS)


def resolve_model(requested: str | None) -> str:
    """Resolve a client-requested model id to a trusted id to build the LLM
    provider with.

    SECURITY BOUNDARY: this is the only place a model id coming from a
    client request is validated before it can reach ``OpenAIChatModel``/the
    OpenAI-compatible provider. An arbitrary, attacker-controlled string
    (e.g. a path, a SQL fragment, an unregistered model name) must NEVER be
    passed to the provider directly — doing so could probe internal
    endpoints, exhaust quota on unintended models, or otherwise abuse the
    provider credentials tied to ``settings.llm_api_key``. Every caller that
    eventually builds an ``Agent``/``OpenAIChatModel`` (currently
    ``app.agent.llm_agent.build_agent`` via ``stream_llm_response``) MUST
    route the incoming model id through this function first and only ever
    use the returned value.

    Behavior (deterministic, no exceptions raised):
    - ``requested`` is ``None`` -> returns ``settings.llm_model`` (server default).
    - ``requested`` is ``""`` (empty string) -> returns ``settings.llm_model``.
    - ``requested`` is present in ``ALLOWED_MODELS`` -> returns ``requested`` unchanged.
    - ``requested`` is any other string (whitespace-only, unknown id,
      malicious payload, etc.) -> returns ``settings.llm_model``.
    """
    if requested and requested in _ALLOWED_MODELS_SET:
        return requested
    return settings.llm_model
