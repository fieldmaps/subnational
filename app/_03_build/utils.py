"""Shared utilities for the build stage."""

import duckdb


def describe(conn: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Return the column names of a DuckDB table."""
    return [row[0] for row in conn.execute(f"DESCRIBE {table}").fetchall()]


def wld_cols() -> list[str]:
    """Return ordered list of world-view attribute column names."""
    return [
        "adm0_id",
        "adm0_src",
        "adm0_name",
        "adm0_name1",
        "adm0_name2",
        "iso_cd",
        "iso_2",
        "iso_3",
        "iso_3_grp",
        "region3_cd",
        "region3_nm",
        "region2_cd",
        "region2_nm",
        "region1_cd",
        "region1_nm",
        "status_cd",
        "status_nm",
        "wld_date",
        "wld_update",
        "wld_view",
        "wld_notes",
    ]
