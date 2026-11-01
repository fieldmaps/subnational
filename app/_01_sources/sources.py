"""Index every catalog collection's metadata sidecar into the sources table."""

import duckdb

from app.config import CATALOG_DIR, PREFER, SOURCES, SOURCES_TABLE

from .schema import META_COLS


def build_sources_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Write SOURCES_TABLE: one row per (src, tier, key), `selected` by priority.

    Each base iso3 is built from its PREFER or highest-priority SOURCES src; every key
    of that src (e.g. pak_1, pak_2) is selected.
    """
    priority = ", ".join(f"'{s}'" for s in SOURCES)
    prefer = ", ".join(f"('{b}', '{s}')" for b, s in PREFER.items()) or "(NULL, NULL)"
    row = "STRUCT(" + ", ".join(f'"{c}" {t}' for c, t in META_COLS) + ")"
    SOURCES_TABLE.parent.mkdir(parents=True, exist_ok=True)
    conn.execute(f"""--sql
        COPY (
            WITH meta AS (
                SELECT *, split_part(key, '_', 1) AS base
                FROM (
                    SELECT unnest(rows, recursive := true)
                    FROM read_json(
                        '{CATALOG_DIR}/*/*/*_metadata.json',
                        columns = {{'rows': '{row}[]'}}
                    )
                )
            ),
            best AS (
                SELECT base, arg_min(src, CASE
                    WHEN (base, src) IN (VALUES {prefer}) THEN 0
                    ELSE list_position([{priority}], src)
                END) AS src
                FROM meta
                WHERE tier = 'extended'
                GROUP BY base
            )
            SELECT meta.*, best.src IS NOT NULL AS selected
            FROM meta
            LEFT JOIN best USING (base, src)
            ORDER BY src, tier, key
        ) TO '{SOURCES_TABLE}'
    """)
