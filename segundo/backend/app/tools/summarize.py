"""summarize_dataset tool — compress large result sets before they reach the LLM.

Spec: "Resume datasets grandes antes de enviarlos al LLM. Reduce consumo de
tokens." This never invents values — it only aggregates real rows returned
by execute_sql/calculate_kpis, using pandas describe/aggregation primitives.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Above this row count, callers should prefer the summary over raw rows when
# building LLM-facing context (the router decides that; this module only
# produces the summary).
LARGE_DATASET_THRESHOLD = 50


def summarize_dataset(rows: list[dict]) -> dict[str, Any]:
    """Summarize ``rows`` into row count, column stats, and a small sample.

    Numeric columns get min/max/mean/sum; non-numeric columns get a distinct
    value count. Always includes a ``sample`` of the first few rows so the
    caller retains concrete examples, not just aggregates.
    """
    if not rows:
        return {"row_count": 0, "columns": {}, "sample": []}

    frame = pd.DataFrame(rows)
    columns: dict[str, Any] = {}

    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series):
            columns[column] = {
                "type": "numeric",
                "min": _to_native(series.min()),
                "max": _to_native(series.max()),
                "mean": _to_native(series.mean()),
                "sum": _to_native(series.sum()),
            }
        else:
            columns[column] = {
                "type": "categorical",
                "distinct_count": int(series.nunique()),
                "top_values": [_to_native(value) for value in series.value_counts().head(5).index],
            }

    sample_size = min(5, len(rows))
    return {
        "row_count": len(rows),
        "columns": columns,
        "sample": rows[:sample_size],
    }


def _to_native(value: Any) -> Any:
    """Convert numpy/pandas scalars to plain Python types for JSON safety."""
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
