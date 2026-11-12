"""Shared utilities for the export stage."""

from pathlib import Path

import duckdb

from app.config import CATALOG_DIR

from .config import SUFFIXES


def build_levels(conn: duckdb.DuckDBPyConnection) -> list[int]:
    """Return the admin levels with an adm{n}_polygons table in the build DB."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE regexp_matches(table_name, '^adm[0-9]+_polygons$')"
    ).fetchall()
    return sorted(int(name[3:].split("_")[0]) for (name,) in rows)


def global_path(lvl: int, geom: str) -> Path:
    """Return catalog/global/admin{n}/admin{n}{suffix}.parquet (folder created)."""
    folder = CATALOG_DIR / "global" / f"admin{lvl}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"admin{lvl}{SUFFIXES[geom]}.parquet"
