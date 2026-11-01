"""Join world-view attributes from adm0_wld onto every adm{N}_{geom} table."""

import duckdb

from app.config import GEOMS

from .utils import describe, wld_cols


def main(conn: duckdb.DuckDBPyConnection, levels: list[int]) -> None:
    """Apply world-view attributes to every adm{n}_{geom} table that has iso3."""
    for lvl in levels:
        for geom in GEOMS:
            _add_wld_attrs(conn, f"adm{lvl}_{geom}")


def _add_wld_attrs(conn: duckdb.DuckDBPyConnection, table: str) -> None:
    """Left-join adm0_wld attributes onto a build table on iso3.

    Columns already in `table` (notably adm0_id/_src/_name*) are not re-projected
    from adm0_wld — that filter is what excludes the adm0 ID/name overrides.
    """
    tbl_cols = describe(conn, table)
    if "iso3" not in tbl_cols:
        return
    wld_tbl_cols = describe(conn, "adm0_wld")

    new_wld = [c for c in wld_cols() if c in wld_tbl_cols and c not in tbl_cols]
    if not new_wld:
        return

    wld_select = ", ".join(f'b."{c}"' for c in new_wld)
    orig_select = ", ".join(f'a."{c}"' for c in tbl_cols if c != "geom")

    conn.execute(rf"""--sql
        CREATE OR REPLACE TABLE {table} AS
        SELECT {orig_select},
               {wld_select},
               a.geom
        FROM {table} a
        LEFT JOIN adm0_wld b ON regexp_replace(a.iso3, '_\d+$', '') = b.iso_3
    """)
