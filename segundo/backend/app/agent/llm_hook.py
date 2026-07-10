"""Optional LLM wording hook — routes template output through an LLM for
phrasing polish, only when ``settings.llm_api_key`` is configured.

Invariant (CLAUDE.md #5): the LLM provider is swappable and never touches
MySQL or computes metrics — it only rewords a prose answer that was already
built from real tool data. This module MUST work with an empty API key: in
that case ``maybe_reword`` is a no-op passthrough and pydantic-ai is never
imported, so it stays out of the hard dependency set (pyproject.toml already
documents this).

pydantic-ai is imported lazily inside the function body specifically so a
missing/uninstalled package never breaks the template-only default path.
"""

from __future__ import annotations

from app.config import settings


async def maybe_reword(template_answer: str, *, user_message: str) -> str:
    """Return ``template_answer`` as-is, or LLM-polished wording if configured.

    The LLM is instructed to rephrase only — it receives the already-computed
    answer as ground truth and is told not to add new figures. If the LLM
    call fails for any reason (network, auth, missing package), this
    silently falls back to the deterministic template so a wording-layer
    outage never blocks a response the user is entitled to.
    """
    if not settings.llm_api_key:
        return template_answer

    try:
        return await _reword_with_pydantic_ai(template_answer, user_message=user_message)
    except Exception:  # noqa: BLE001 - LLM wording is best-effort, never blocking
        return template_answer


async def _reword_with_pydantic_ai(template_answer: str, *, user_message: str) -> str:
    from pydantic_ai import Agent  # lazy import — optional dependency

    model_identifier = settings.llm_model or "openai:gpt-4o-mini"
    agent: Agent = Agent(
        model_identifier,
        system_prompt=(
            "Sos un analista de datos comercial. Se te da una respuesta ya calculada a "
            "partir de datos reales. Tu única tarea es mejorar la redacción en español "
            "neutro, manteniendo el tono profesional. NUNCA agregues cifras, fechas o "
            "datos que no estén en el texto original. No inventes información."
        ),
    )
    prompt = (
        f"Pregunta del usuario: {user_message}\n\n"
        f"Respuesta calculada (no modificar los números): {template_answer}\n\n"
        "Reescribí esta respuesta de forma más natural, sin cambiar ningún dato."
    )
    result = await agent.run(prompt)
    reworded = getattr(result, "output", None) or getattr(result, "data", None)
    if not reworded or not isinstance(reworded, str):
        return template_answer
    return reworded
