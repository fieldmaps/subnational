"""Merge the per-key packages into catalog/global/ and check the result."""

from contextlib import closing
from itertools import product
from logging import getLogger
from pathlib import Path
from shutil import move, rmtree

import duckdb

from app.config import GEOMS, MAX_LVL, PARQUET_OPTS
from app.utils import get_conn, global_path

from ._02a_inputs import staged_columns
from ._02b_keys import KEYS_DIR
from .config import BUILD_DIR, MATCH_KEY, WLD_COLS

logger = getLogger(__name__)

ISSUES_DIR = BUILD_DIR / "issues"
# Merged layers wait here until every level passes its checks.
STAGE_DIR = BUILD_DIR / "global"
# Key of a per-key file: the name of its KEYS_DIR subfolder.
_KEY = "parse_filename(parse_dirpath(filename, 'system'), false, 'system')"
_ORDER = {
    "points": "id",
    "lines": "adm_lvl, a_id, b_id",
}


def merge() -> None:
    """Write and check adm{n}_{polygons,points,lines}, move them into catalog/."""
    rmtree(STAGE_DIR, ignore_errors=True)
    STAGE_DIR.mkdir(parents=True)
    with closing(get_conn()) as conn:
        for lvl in range(1, MAX_LVL + 1):
            _write(conn, lvl)
        _merge_issues(conn)
    for lvl, geom in product(range(1, MAX_LVL + 1), GEOMS):
        move(_staged(lvl, geom), global_path(lvl, geom))
    STAGE_DIR.rmdir()
    rmtree(KEYS_DIR)


def _write(conn: duckdb.DuckDBPyConnection, lvl: int) -> None:
    """Write and check one level's three layers."""
    sources = {
        "polygons": _read(f"admin{lvl}"),
        "points": f"{_read('points')} WHERE adm_lvl = {lvl}",
        "lines": f"{_read('lines')} WHERE adm_lvl <= {lvl}",
    }
    ids = ", ".join(f"adm{n}_id" for n in range(1, lvl + 1))
    for geom, src in sources.items():
        cols = {r[0] for r in conn.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()}
        drop = ", ".join(c for c in (MATCH_KEY, "overlay_fid") if c in cols)
        exclude = f" EXCLUDE ({drop})" if drop else ""
        dest = _staged(lvl, geom)
        conn.execute(
            f"COPY (SELECT *{exclude} FROM {src} ORDER BY {_ORDER.get(geom, ids)}) "
            f"TO '{dest}' {PARQUET_OPTS}"
        )
    _check(conn, lvl)


def _staged(lvl: int, geom: str) -> Path:
    """Return STAGE_DIR/adm{n}_{geom}.parquet."""
    return STAGE_DIR / f"adm{lvl}_{geom}.parquet"


def _read(name: str) -> str:
    """Return a read of every key's {name}.parquet, columns matched by name."""
    return f"read_parquet('{KEYS_DIR}/*/{name}.parquet', union_by_name = true)"


def _check(conn: duckdb.DuckDBPyConnection, lvl: int) -> None:
    """Raise unless ids are unique, points pair with polygons and columns are kept."""
    poly, pts = _staged(lvl, "polygons"), _staged(lvl, "points")
    have = {r[0] for r in conn.execute(f"DESCRIBE FROM '{poly}'").fetchall()}
    want = {
        c
        for c, _ in staged_columns()
        if c != MATCH_KEY and not (c[:3] == "adm" and int(c[3]) > lvl)
    } | {*WLD_COLS, "adm_lvl"}
    if missing := want - have:
        msg = f"adm{lvl}_polygons is missing {sorted(missing)}"
        raise ValueError(msg)
    n_poly, n_ids, n_pts, n_pt_ids, n_orphan, bad_lvl = conn.execute(f"""--sql
        SELECT (SELECT count(*) FROM '{poly}'),
               (SELECT count(DISTINCT adm{lvl}_id) FROM '{poly}'),
               (SELECT count(*) FROM '{pts}'),
               (SELECT count(DISTINCT id) FROM '{pts}'),
               (SELECT count(*) FROM '{pts}' p
                ANTI JOIN '{poly}' g ON p.id = g.adm{lvl}_id),
               (SELECT count(*) FROM {_read("lines")}
                WHERE adm_lvl IS NULL OR adm_lvl NOT BETWEEN 1 AND {MAX_LVL})
    """).fetchall()[0]
    if not n_poly == n_ids == n_pts == n_pt_ids or n_orphan or bad_lvl:
        msg = (
            f"adm{lvl}: {n_poly} polygons, {n_ids} ids, {n_pts} points, "
            f"{n_pt_ids} point ids, {n_orphan} points with no polygon, "
            f"{bad_lvl} per-key lines with a null adm_lvl "
            f"or one outside 1..{MAX_LVL}"
        )
        raise ValueError(msg)
    logger.info("adm%d: %d polygons and points", lvl, n_poly)


def _merge_issues(conn: duckdb.DuckDBPyConnection) -> None:
    """Merge each issues file and the validation summaries across keys, with a key."""
    rmtree(ISSUES_DIR, ignore_errors=True)
    ISSUES_DIR.mkdir(parents=True)
    for name in sorted({p.name for p in KEYS_DIR.glob("*/*_issues.parquet")}):
        conn.execute(f"""--sql
            COPY (
                SELECT {_KEY} AS build_key, * EXCLUDE (filename)
                FROM read_parquet('{KEYS_DIR}/*/{name}', union_by_name = true,
                                  filename = true)
            ) TO '{ISSUES_DIR / name}' {PARQUET_OPTS}
        """)
    summary = ISSUES_DIR / "validate_summary.csv"
    conn.execute(f"""--sql
        COPY (
            SELECT stage, kind, severity, sum(count)::BIGINT AS count,
                   count(DISTINCT {_KEY}) AS keys, reason
            FROM read_csv('{KEYS_DIR}/*/*_validate_summary.csv', filename = true)
            GROUP BY ALL
            ORDER BY stage, severity, count DESC
        ) TO '{summary}'
    """)
    for stage, kind, count, keys in conn.execute(f"""--sql
        SELECT stage, kind, count, keys FROM '{summary}' WHERE severity = 'error'
    """).fetchall():
        logger.warning(
            "package: %d %s %s error(s) in %d key(s)", count, stage, kind, keys
        )
    logger.info("issues and validation summary: %s", ISSUES_DIR)
