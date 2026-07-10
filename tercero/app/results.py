"""Append-only JSONL results log — the checkpoint for idempotency.

One file (runs/results.jsonl) is both the result log AND the resume
point. Idempotency key: (form, ID_Cliente, content-hash). A prior
SUBMITTED entry with the SAME content-hash blocks re-processing.
SUBMIT_UNCONFIRMED ALSO blocks re-processing (specs.md: "marcar para
revisión") — a submit that may have gone through but was never
confirmed must never be silently re-submitted, since that risks a real
duplicate submission on this domain. DRY_RUN_OK never blocks a future
run — dry-run never counts as done. An edited record (different
content-hash) is always processed again.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

# These statuses count as "already done" for idempotency purposes and
# BLOCK automatic reprocessing:
# - SUBMITTED: confirmed success.
# - SUBMIT_UNCONFIRMED: the Enviar click may have gone through but no
#   confirmation was observed -- treated as "needs manual review", not
#   as "safe to retry automatically" (retrying could duplicate a real
#   submission that actually succeeded).
# Every other status (DRY_RUN_OK, SKIPPED_REQUIRED_EMPTY, and all
# other error codes) must allow a future run to reprocess the record.
_DONE_STATUSES = frozenset({"SUBMITTED", "SUBMIT_UNCONFIRMED"})


def content_hash(values: dict[str, str]) -> str:
    """sha256 hex digest of the normalized record values, sorted by key.

    Sorting keys before hashing makes the hash independent of dict
    insertion order, so the same logical record always hashes the same
    way regardless of how it was constructed.
    """
    serialized = json.dumps(values, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def append_result(
    path: str | Path,
    *,
    form: str,
    id_cliente: str,
    content_hash_value: str,
    status: str,
    detail: str,
    evidence: str | None,
) -> None:
    """Append one JSONL line to the results log. Creates the file/dirs if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "ts": time.time(),
        "form": form,
        "id_cliente": id_cliente,
        "content_hash": content_hash_value,
        "status": status,
        "detail": detail,
        "evidence": evidence,
    }

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def blocking_status(
    path: str | Path, form: str, id_cliente: str, content_hash_value: str
) -> str | None:
    """Return the blocking status (SUBMITTED or SUBMIT_UNCONFIRMED) of a
    prior matching entry for this exact key, or None if nothing blocks.

    Returns None if the results file doesn't exist yet, if no entry
    matches the (form, id_cliente, content_hash) triple, or if the
    matching entry's status is anything other than SUBMITTED or
    SUBMIT_UNCONFIRMED (e.g. DRY_RUN_OK, SKIPPED_REQUIRED_EMPTY, or any
    other error code never blocks a future run).

    Callers that only need the yes/no answer should use `already_done`;
    callers that need to tell the two blocking statuses apart (e.g. to
    surface SUBMIT_UNCONFIRMED as "needs manual review" rather than a
    generic "already submitted") should use this function.
    """
    path = Path(path)
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # A truncated/corrupt line must never abort the scan --
                # skip it and keep checking the remaining lines.
                continue
            status = record.get("status")
            if (
                record.get("form") == form
                and record.get("id_cliente") == id_cliente
                and record.get("content_hash") == content_hash_value
                and status in _DONE_STATUSES
            ):
                return status

    return None


def already_done(
    path: str | Path, form: str, id_cliente: str, content_hash_value: str
) -> bool:
    """True only if a prior SUBMITTED or SUBMIT_UNCONFIRMED entry exists
    for this exact key.

    Returns False if the results file doesn't exist yet, if no entry
    matches the (form, id_cliente, content_hash) triple, or if the
    matching entry's status is anything other than SUBMITTED or
    SUBMIT_UNCONFIRMED (e.g. DRY_RUN_OK, SKIPPED_REQUIRED_EMPTY, or any
    other error code never blocks a future run).
    """
    return blocking_status(path, form, id_cliente, content_hash_value) is not None
