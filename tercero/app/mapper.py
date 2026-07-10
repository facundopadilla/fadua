"""Deterministic column->field mapping, with an LLM fallback of last resort.

Column names and field labels are tokenized (via normalize.fold, then
split on underscores/spaces/parentheses/slashes) and Spanish stopwords
are dropped. Matching is a greedy bipartite assignment: candidate
(column, field) pairs are sorted by shared-token count DESCENDING, and
the best-scoring pairs are locked in first, removing both sides from
the pool before weaker pairs are considered. This resolves genuine
tokenization ties correctly — e.g. "Nombre_Cliente" shares exactly one
token with BOTH "Nombre Completo" (via "nombre") and "ID del Cliente"
(via "cliente"); the tie only breaks because "ID_Cliente" locks "ID del
Cliente" FIRST with a stronger 2-token match, freeing "Nombre Completo"
as the sole remaining candidate for "Nombre_Cliente".

The LLM (see llm.py) is invoked ONLY when a REQUIRED field is left
unmapped after the deterministic pass — it never sees row values, only
headers and labels (see llm.suggest_mapping and test_llm_privacy.py).

Resolved mappings are cached to mapping.json so repeat runs against the
same schema/headers skip re-computation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from app.normalize import fold

if TYPE_CHECKING:
    from app.forms_schema import Field

# Spanish stopwords: tokens that carry no discriminating signal for
# mapping (generic connectors and words that appear across many
# labels without distinguishing one field from another).
_STOPWORDS = {
    "de",
    "del",
    "la",
    "el",
    "si",
    "aplica",
    "actual",
    "asociado",
    "registrado",
    "total",
    "contacto",
    "completo",
}

# Minimal synonym seed — only what the real data requires. Each key is
# a token that should ALSO be treated as equivalent to the tokens in
# its value set (bidirectional: if either side has the token, add the
# synonyms to that side's token set).
_SYNONYMS: dict[str, set[str]] = {
    "email": {"correo", "electronico", "mail"},
    "correo": {"email", "electronico", "mail"},
    "electronico": {"email", "correo", "mail"},
    "mail": {"email", "correo", "electronico"},
}

_SPLIT_PATTERN = re.compile(r"[()/]")


def _tokenize(text: str) -> set[str]:
    """Fold, split on separators, drop stopwords, expand synonyms."""
    folded = fold(text)
    folded = _SPLIT_PATTERN.sub(" ", folded)
    raw_tokens = [tok for tok in re.split(r"[_\s]+", folded) if tok]
    tokens = {tok for tok in raw_tokens if tok not in _STOPWORDS}

    expanded = set(tokens)
    for token in tokens:
        expanded |= _SYNONYMS.get(token, set())

    return expanded


def _greedy_assign(
    headers: list[str], fields: list["Field"]
) -> dict[str, "Field"]:
    """Score every (header, field) pair and assign greedily by score DESC."""
    header_tokens = {h: _tokenize(h) for h in headers}
    field_tokens = {f.item_id: _tokenize(f.label) for f in fields}
    fields_by_id = {f.item_id: f for f in fields}

    candidates: list[tuple[int, str, str]] = []
    for header, htoks in header_tokens.items():
        for field_id, ftoks in field_tokens.items():
            shared = htoks & ftoks
            if shared:
                candidates.append((len(shared), header, field_id))

    # Sort by score DESC; stable sort preserves original relative
    # order for equal scores (deterministic tie behavior for cases
    # that aren't resolved by a stronger competing match).
    candidates.sort(key=lambda c: -c[0])

    mapped_headers: set[str] = set()
    mapped_field_ids: set[str] = set()
    result: dict[str, "Field"] = {}

    for _score, header, field_id in candidates:
        if header in mapped_headers or field_id in mapped_field_ids:
            continue
        result[header] = fields_by_id[field_id]
        mapped_headers.add(header)
        mapped_field_ids.add(field_id)

    return result


def map_columns(
    headers: list[str],
    fields: list["Field"],
    cache_path: str | Path | None = None,
    llm_failed_labels: set[str] | None = None,
) -> dict[str, "Field"]:
    """Map sheet column headers to form fields.

    Deterministic tokenized matching first; if any REQUIRED field is
    still unmapped afterward, falls back to the LLM (see llm.py) for
    just those unmapped required fields. If the LLM is not configured,
    the condition is left for the caller (runner.py) to skip+report
    per the LLM_ERROR taxonomy — this function does not raise.

    If the LLM call itself fails (provider down, malformed JSON
    response, etc.), the failure is caught here and NEVER propagates:
    the affected fields simply stay unmapped, exactly as if the LLM
    had not been configured. This function never raises because of an
    LLM failure — a bad provider must never abort the whole batch.

    `llm_failed_labels`, when provided by the caller, is populated
    (via `.add()`) with the labels of the required fields that were
    left unmapped SPECIFICALLY because the LLM call failed — as
    opposed to fields that are simply unmapped with no LLM involved.
    Callers use this to distinguish LLM_ERROR from SCHEMA_DRIFT for
    the same "unmapped required field" symptom. Passing None (the
    default) preserves the original call signature and behavior for
    every existing caller.

    Resolved mapping is cached to `cache_path` (default: mapping.json
    in the current working directory) when a cache_path is provided.
    """
    mapping = _greedy_assign(headers, fields)

    unmapped_required = [
        f for f in fields if f.required and f.item_id not in {v.item_id for v in mapping.values()}
    ]

    if unmapped_required:
        from app import llm as llm_module

        if llm_module.is_configured():
            mapped_field_ids = {f.item_id for f in mapping.values()}
            remaining_headers = [h for h in headers if h not in mapping]
            remaining_labels = [f.label for f in fields if f.item_id not in mapped_field_ids]
            try:
                suggestion = llm_module.suggest_mapping(remaining_headers, remaining_labels)
            except Exception:  # noqa: BLE001 - provider failure degrades, never crashes
                suggestion = {}
                if llm_failed_labels is not None:
                    still_unmapped_labels = {
                        f.label
                        for f in unmapped_required
                        if f.item_id not in {v.item_id for v in mapping.values()}
                    }
                    llm_failed_labels.update(still_unmapped_labels)
            for header, label in suggestion.items():
                match = next((f for f in fields if f.label == label), None)
                if match is not None:
                    mapping[header] = match

    if cache_path is not None:
        _save_cache(cache_path, mapping)

    return mapping


def _save_cache(cache_path: str | Path, mapping: dict[str, "Field"]) -> None:
    serializable = {
        header: {
            "item_id": field.item_id,
            "entry_id": field.entry_id,
            "label": field.label,
        }
        for header, field in mapping.items()
    }
    Path(cache_path).write_text(json.dumps(serializable, indent=2, ensure_ascii=False))
