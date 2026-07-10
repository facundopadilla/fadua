"""Minimal, swappable AI provider abstraction.

This is the ONLY place in the codebase that references the AI
provider. Models are consumed through an OpenAI-compatible HTTP
endpoint (OpenCode GO: Qwen, Minimax, GLM, ...); swapping the provider
means changing environment variables, never application code.

CRITICAL PRIVACY INVARIANT: the LLM is used ONLY to resolve a
column->field mapping when the deterministic matcher (mapper.py)
leaves a REQUIRED field unmapped. It receives column headers and field
labels ONLY — never row values (names, emails, phones, amounts).
`build_mapping_prompt` has no parameter through which row data could
be threaded, by construction (see test_llm_privacy.py).
"""

from __future__ import annotations

import json
import os
import urllib.request

_ENV_BASE_URL = "OPENCODE_BASE_URL"
_ENV_API_KEY = "OPENCODE_API_KEY"
_ENV_MODEL = "OPENCODE_MODEL"


def is_configured() -> bool:
    """True if all required provider environment variables are set."""
    return bool(
        os.environ.get(_ENV_BASE_URL)
        and os.environ.get(_ENV_API_KEY)
        and os.environ.get(_ENV_MODEL)
    )


def build_mapping_prompt(headers: list[str], labels: list[str]) -> str:
    """Build the column->field mapping prompt.

    Only headers and labels are accepted — no row-value parameter
    exists, so this function structurally cannot leak PII into the
    prompt.
    """
    lines = [
        "You are mapping spreadsheet column headers to form field labels.",
        "Given the following unmapped column headers:",
        *[f"- {header}" for header in headers],
        "",
        "And the following unmapped form field labels:",
        *[f"- {label}" for label in labels],
        "",
        "Return a JSON object mapping each header to its best-matching "
        "label. Only use the labels provided above. If no label is a "
        "good match for a header, omit that header from the result.",
    ]
    return "\n".join(lines)


def complete(system: str, user: str) -> str:
    """Send a chat completion request to the configured provider.

    Uses an OpenAI-compatible /chat/completions endpoint via urllib
    (no extra HTTP dependency, per the stdlib-only constraint).
    """
    base_url = os.environ[_ENV_BASE_URL]
    api_key = os.environ[_ENV_API_KEY]
    model = os.environ[_ENV_MODEL]

    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    ).encode("utf-8")

    url = base_url.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        body = json.loads(response.read().decode("utf-8"))

    return body["choices"][0]["message"]["content"]


def suggest_mapping(headers: list[str], labels: list[str]) -> dict[str, str]:
    """Ask the LLM to map remaining unmapped headers to remaining labels.

    Returns a dict of {header: label}. Raises whatever complete()
    raises on provider failure — callers (mapper.py -> runner.py) treat
    that as LLM_ERROR: field left unmapped, required-field skip+report.
    """
    system = (
        "You are a precise data-mapping assistant. You only ever see "
        "column headers and field labels, never row data."
    )
    user = build_mapping_prompt(headers, labels)
    raw = complete(system, user)
    return json.loads(raw)
