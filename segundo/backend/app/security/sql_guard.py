"""AST-based SQL validation — the critical security invariant.

Every LLM-generated query must pass ``validate_sql`` before execution.
This module only validates; it NEVER executes SQL.
"""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

AUTHORIZED_TABLE = "metricas_campanas_ventas"

# Derived from the spec's column list. The SQL tool must never see other names.
ALLOWED_COLUMNS = frozenset(
    {
        "fecha",
        "google_ads_impresiones",
        "google_ads_clics",
        "google_ads_costo_usd",
        "google_ads_leads",
        "meta_ads_impresiones",
        "meta_ads_clics",
        "meta_ads_costo_usd",
        "meta_ads_leads",
        "total_leads",
        "cantidad_ventas",
        "vehiculo_tipo_principal",
        "vehiculo_modelo_principal",
        "ingresos_ventas_usd",
    }
)

# Explicitly banned regardless of the allow-list below — these are classic
# MySQL attack vectors (timing/DoS attacks, filesystem exfiltration) that
# have no legitimate use in an analytics read-only query.
BLOCKED_FUNCTIONS = frozenset(
    {
        "SLEEP",
        "BENCHMARK",
        "LOAD_FILE",
        "GET_LOCK",
        "RELEASE_LOCK",
        "UPDATEXML",
        "EXTRACTVALUE",
    }
)

# Small analytics allow-list, keyed by sqlglot's `Func.sql_name()` output for
# the surface SQL keyword. Any function call whose name is not in this set is
# rejected — an allow-list is safer than trying to enumerate every dangerous
# MySQL function individually.
#
# Note: sqlglot's MySQL parser decomposes some date functions (DATE(), YEAR(),
# DAY()) into an internal `TsOrDsToDate`/`TsOrDsToTimestamp` coercion node
# alongside the properly-typed node. Those internal names are included below
# — they are argument-coercion wrappers sqlglot inserts itself, never a call
# an attacker can introduce independently of the surface function they wrap.
#
# CURDATE()/CURRENT_DATE() parse to `exp.CurrentDate` (sql_name "CURRENT_DATE").
# It takes no arguments and can't reference a column/table/file, so it's a
# safe zero-risk addition used to bound forecast lookback windows.
ALLOWED_FUNCTIONS = frozenset(
    {
        "SUM",
        "AVG",
        "COUNT",
        "MIN",
        "MAX",
        "ROUND",
        "ABS",
        "DATE",
        "CURRENT_DATE",
        "YEAR",
        "MONTH",
        "DAY",
        "DATE_FORMAT",
        "DATE_SUB",
        "DATE_ADD",
        "DATEDIFF",
        "COALESCE",
        "IFNULL",
        "IF",
        "CAST",
        "CONCAT",
        "DISTINCT",
        # sqlglot internal decomposition helpers (see note above).
        "TS_OR_DS_TO_DATE",
        "TS_OR_DS_TO_TIMESTAMP",
        "TIME_TO_STR",
    }
)

# ``INTO OUTFILE`` / ``INTO DUMPFILE`` are the classic MySQL exfiltration
# vector for a SELECT. sqlglot's MySQL dialect already fails to parse them at
# all (they raise SqlglotError, caught below as a parse failure), but we also
# reject them at the raw-text level as a defense-in-depth layer that does not
# depend on that parser behavior staying stable across sqlglot versions.
_INTO_FILE_PATTERN = re.compile(r"\bINTO\s+(OUTFILE|DUMPFILE)\b", re.IGNORECASE)


class SqlValidationError(Exception):
    """Raised when a query violates the SQL security policy."""


def validate_sql(query: str) -> None:
    """Raise SqlValidationError unless ``query`` is a single safe SELECT.

    Rules:
    - no ``INTO OUTFILE`` / ``INTO DUMPFILE`` (checked on raw text first —
      see the comment on ``_INTO_FILE_PATTERN``)
    - must parse as exactly one statement (MySQL dialect)
    - the root statement must be a SELECT (no DML/DDL)
    - every referenced table must be the authorized table (subqueries included)
    - every referenced column must be in the allow-list
      (``*`` and aggregates over allowed columns are fine)
    - every function call is either in ``ALLOWED_FUNCTIONS`` or is rejected;
      names in ``BLOCKED_FUNCTIONS`` always raise, even if a future
      allow-list edit accidentally included them
    """
    if _INTO_FILE_PATTERN.search(query):
        raise SqlValidationError("'INTO OUTFILE'/'INTO DUMPFILE' are not allowed.")

    try:
        statements = sqlglot.parse(query, read="mysql")
    except SqlglotError as error:
        raise SqlValidationError(f"SQL could not be parsed: {error}") from error

    if len(statements) != 1 or statements[0] is None:
        raise SqlValidationError("Exactly one SQL statement is allowed.")

    statement = statements[0]

    if not isinstance(statement, exp.Select):
        raise SqlValidationError("Only SELECT statements are allowed.")

    for table in statement.find_all(exp.Table):
        if table.name != AUTHORIZED_TABLE:
            raise SqlValidationError(
                f"Table '{table.name}' is not authorized; only '{AUTHORIZED_TABLE}' can be queried."
            )

    for column in statement.find_all(exp.Column):
        if column.name not in ALLOWED_COLUMNS:
            raise SqlValidationError(f"Column '{column.name}' is not in the allow-list.")

    for function in statement.find_all(exp.Func):
        name = _function_name(function)
        if name in BLOCKED_FUNCTIONS:
            raise SqlValidationError(f"Function '{name}' is blocked.")
        if name not in ALLOWED_FUNCTIONS:
            raise SqlValidationError(f"Function '{name}' is not in the allow-list.")


def _function_name(function: exp.Func) -> str:
    """Return the uppercased SQL function name for an ``exp.Func`` node.

    sqlglot represents recognized functions (SUM, ROUND, YEAR, ...) as
    dedicated node types, and unrecognized ones (SLEEP, BENCHMARK,
    LOAD_FILE, ...) as ``exp.Anonymous`` with the raw name in ``.this``
    rather than reflected by ``sql_name()``. Both cases are handled here so
    the allow/block-list check upstream never has to special-case node type.
    """
    if isinstance(function, exp.Anonymous):
        return str(function.this).upper()
    return function.sql_name()
