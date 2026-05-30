"""Generate interior boundary lines for adm{1..4} from the polygon tables.

Each adm{lvl}_lines row (grouped per parent unit) is the interior boundary of the
children within their parent: the child boundary minus the parent's outer boundary,
unioned per parent. adm0 lines are out of scope.

The parent is the national outline (adm0_bounds) for level 1, and the adm{lvl-1}
polygon for deeper levels. With a sane-resolution clip boundary the per-parent
ST_Difference stays bounded, so this runs as one global query per level.
"""

import duckdb

from .utils import describe, src_id_cols, src_meta_cols


def generate_lines(conn: duckdb.DuckDBPyConnection) -> None:
    """Build adm{1..4}_lines from the polygon tables."""
    for lvl in range(1, 5):
        if lvl == 1:
            parent_table = "adm0_bounds"
            join_on = "a.iso3 = b.iso3"
        else:
            parent_id = f"adm{lvl - 1}_id"
            parent_table = f"adm{lvl - 1}_polygons"
            join_on = f'a.iso3 = b.iso3 AND a."{parent_id}" = b."{parent_id}"'
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE adm{lvl}_lines AS
            SELECT a.iso3,
                   {_attr_select(conn, f"adm{lvl}_polygons", lvl - 1, prefix="a.")},
                   ST_Multi(ST_Union_Agg(
                       ST_Difference(ST_Boundary(a.geom), ST_Boundary(b.geom))
                   ))::GEOMETRY AS geom
            FROM adm{lvl}_polygons a
            JOIN {parent_table} b ON {join_on}
            GROUP BY ALL
        """)


def _attr_select(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    level: int,
    prefix: str = "",
) -> str:
    """Return a comma-joined SQL column list (src_id + meta cols) present in `table`."""
    cols = describe(conn, table)
    attrs = [c for c in src_id_cols(level) + src_meta_cols() if c in cols]
    return ", ".join(f'{prefix}"{c}"' for c in attrs)
