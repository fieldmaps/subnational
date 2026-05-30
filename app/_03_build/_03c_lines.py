"""Generate interior boundary lines for adm{1..4} via sibling shared borders.

Each adm{lvl}_lines row (grouped per parent unit) is the union of the borders shared
between sibling children of that parent — computed as the line-dimension intersection
of adjacent siblings' boundaries. This never touches the national outline (the full
ADM0 coastline), so it sidesteps the multi-million-vertex geometry that OOMs DuckDB.
Adjacency is a scalar bbox prefilter (no SPATIAL_JOIN); a.id < b.id counts each pair
once. adm0 lines are out of scope.
"""

import duckdb

from .utils import describe, src_id_cols, src_meta_cols


def generate_lines(conn: duckdb.DuckDBPyConnection) -> None:
    """Build adm{1..4}_lines from sibling shared borders."""
    for lvl in range(1, 5):
        child = f"adm{lvl}_polygons"
        id_col = f"adm{lvl}_id"
        if lvl == 1:
            parent_match = "a.iso3 = b.iso3"
        else:
            parent_id = f"adm{lvl - 1}_id"
            parent_match = f'a.iso3 = b.iso3 AND a."{parent_id}" = b."{parent_id}"'
        attr_select = _attr_select(conn, child, lvl - 1, prefix="a.")
        conn.execute(f"""--sql
            CREATE OR REPLACE TABLE adm{lvl}_lines AS
            SELECT a.iso3,
                   {attr_select},
                   ST_Multi(ST_Union_Agg(ST_CollectionExtract(
                       ST_Intersection(ST_Boundary(a.geom), ST_Boundary(b.geom)), 2
                   )))::GEOMETRY AS geom
            FROM {child} a
            JOIN {child} b
              ON {parent_match}
             AND a."{id_col}" < b."{id_col}"
             AND ST_XMax(b.geom) >= ST_XMin(a.geom)
             AND ST_XMin(b.geom) <= ST_XMax(a.geom)
             AND ST_YMax(b.geom) >= ST_YMin(a.geom)
             AND ST_YMin(b.geom) <= ST_YMax(a.geom)
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
