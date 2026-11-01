"""Convert global GeoParquets to GPKG, GDB, and XLSX via DuckDB's built-in GDAL."""

from pathlib import Path
from shutil import make_archive, rmtree
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb

from app.config import CATALOG_DIR
from app.utils import get_conn

_GEOM_TYPE = {
    "polygons": "MULTIPOLYGON",
    "lines": "MULTILINESTRING",
    "points": "POINT",
}
_GDB_VALID_TYPES = {
    "polygons": "('POLYGON', 'MULTIPOLYGON')",
    "lines": "('LINESTRING', 'MULTILINESTRING')",
    "points": "('POINT', 'MULTIPOINT')",
}


def main() -> None:
    """Generate GPKG, GDB, and XLSX beside every catalog/global GeoParquet."""
    conn = get_conn()
    for parquet in sorted((CATALOG_DIR / "global").glob("*/adm*_*.parquet")):
        _export_one(conn, parquet, parquet.stem.split("_", 1)[1])
    conn.close()


def _zip(path: Path) -> None:
    zip_path = path.with_suffix(path.suffix + ".zip")
    zip_path.unlink(missing_ok=True)
    if path.is_file():
        with ZipFile(zip_path, "w", ZIP_DEFLATED) as z:
            z.write(path, path.name)
    elif path.is_dir():
        make_archive(str(zip_path.with_suffix("")), "zip", path)


def _export_one(conn: duckdb.DuckDBPyConnection, parquet: Path, geom: str) -> None:
    src = f"read_parquet('{parquet}')"

    gpkg = parquet.with_suffix(".gpkg")
    gpkg.unlink(missing_ok=True)
    conn.execute(f"COPY (SELECT * FROM {src}) TO '{gpkg}' (FORMAT GDAL, DRIVER 'GPKG')")
    _zip(gpkg)
    gpkg.unlink()

    gdb = parquet.with_suffix(".gdb")
    rmtree(gdb, ignore_errors=True)
    geom_type = _GEOM_TYPE[geom]
    geom_filter = f"ST_GeometryType(geometry) IN {_GDB_VALID_TYPES[geom]}"
    conn.execute(f"""--sql
        COPY (
            SELECT * FROM (
                SELECT * EXCLUDE geometry, ST_MakeValid(geometry) AS geometry FROM {src}
            ) WHERE {geom_filter}
        ) TO '{gdb}' (FORMAT GDAL, DRIVER 'OpenFileGDB', GEOMETRY_TYPE '{geom_type}')
    """)
    _zip(gdb)
    rmtree(gdb, ignore_errors=True)

    xlsx = parquet.with_suffix(".xlsx")
    xlsx.unlink(missing_ok=True)
    conn.execute(f"""--sql
        COPY (SELECT * EXCLUDE geometry FROM {src})
        TO '{xlsx}' (FORMAT GDAL, DRIVER 'XLSX')
    """)
