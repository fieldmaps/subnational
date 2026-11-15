"""Write per-iso3 and global layers, check them and move them into catalog/."""

from contextlib import closing
from itertools import product
from logging import getLogger
from pathlib import Path
from shutil import move, rmtree

import duckdb

from app.config import CATALOG_DIR, GEOMS, MAX_LVL, PARQUET_OPTS
from app.publish.utils import portolan
from app.utils import get_conn, global_path

from ._02a_inputs import staged_columns
from ._02b_codes import CODES_DIR
from .config import BUILD_DIR, MATCH_KEY, WLD_COLS

logger = getLogger(__name__)

ISSUES_DIR = BUILD_DIR / "issues"
ISO3_DIR = CATALOG_DIR / "iso3"
# Merged layers wait here until every level passes its checks.
STAGE_DIR = BUILD_DIR / "global"
# Code of a per-code file: the name of its CODES_DIR subfolder.
_CODE = "parse_filename(parse_dirpath(filename, 'system'), false, 'system')"
# Hilbert order over the world box, so each row group covers one area.
_ORDER = (
    "ST_Hilbert(geometry, "
    "{'min_x': -180, 'min_y': -90, 'max_x': 180, 'max_y': 90}::BOX_2D)"
)
_LAYERS = list(product(range(1, MAX_LVL + 1), GEOMS))


def merge() -> None:
    """Write and check each code's and the global layers, move them into catalog/."""
    rmtree(STAGE_DIR, ignore_errors=True)
    STAGE_DIR.mkdir(parents=True)
    codes = sorted(p for p in CODES_DIR.iterdir() if p.is_dir())
    with closing(get_conn()) as conn:
        _check_lines(conn)
        for work in codes:
            _write_code(conn, work)
        for lvl in range(1, MAX_LVL + 1):
            for geom in GEOMS:
                src = (
                    f"read_parquet('{CODES_DIR}/*/{_name(lvl, geom)}', "
                    "union_by_name = true)"
                )
                _copy(conn, src, STAGE_DIR / _name(lvl, geom))
            _check(conn, lvl)
        _merge_issues(conn)
    for lvl, geom in _LAYERS:
        dest = global_path(lvl, geom)
        dest.parent.mkdir(parents=True, exist_ok=True)
        move(STAGE_DIR / _name(lvl, geom), dest)
    STAGE_DIR.rmdir()
    _move_codes(codes)
    rmtree(CODES_DIR)


def _write_code(conn: duckdb.DuckDBPyConnection, work: Path) -> None:
    """Write one code's adm{n}_{geom} layers from its package output."""
    for lvl, geom in _LAYERS:
        src = {
            "polygons": f"'{work}/admin{lvl}.parquet'",
            "points": f"'{work}/points.parquet' WHERE adm_lvl = {lvl}",
            "lines": f"'{work}/lines.parquet' WHERE adm_lvl <= {lvl}",
        }[geom]
        cols = {r[0] for r in conn.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()}
        drop = ", ".join(c for c in (MATCH_KEY, "overlay_fid") if c in cols)
        exclude = f" EXCLUDE ({drop})" if drop else ""
        _copy(conn, f"(SELECT *{exclude} FROM {src})", work / _name(lvl, geom))


def _copy(conn: duckdb.DuckDBPyConnection, src: str, dest: Path) -> None:
    """Write src to dest in Hilbert order."""
    conn.execute(
        f"COPY (SELECT * FROM {src} ORDER BY {_ORDER}) TO '{dest}' {PARQUET_OPTS}"
    )


def _name(lvl: int, geom: str) -> str:
    """Return adm{n}_{geom}.parquet."""
    return f"adm{lvl}_{geom}.parquet"


def _move_codes(codes: list[Path]) -> None:
    """Replace catalog/iso3/{code}/ layers, removing codes the build no longer has."""
    built = {w.name for w in codes}
    for old in sorted(ISO3_DIR.glob("*/")):
        if old.name not in built:
            logger.info("iso3/%s: no longer built, removing", old.name)
            portolan("rm", "-f", f"iso3/{old.name}")
    for work in codes:
        dest = ISO3_DIR / work.name
        dest.mkdir(parents=True, exist_ok=True)
        for lvl, geom in _LAYERS:
            move(work / _name(lvl, geom), dest / _name(lvl, geom))


def _check(conn: duckdb.DuckDBPyConnection, lvl: int) -> None:
    """Raise unless ids are unique, points pair with polygons and columns are kept."""
    poly, pts = STAGE_DIR / _name(lvl, "polygons"), STAGE_DIR / _name(lvl, "points")
    have = {r[0] for r in conn.execute(f"DESCRIBE FROM '{poly}'").fetchall()}
    want = {
        c
        for c, _ in staged_columns()
        if c != MATCH_KEY and not (c[:3] == "adm" and int(c[3]) > lvl)
    } | {*WLD_COLS, "adm_lvl"}
    if missing := want - have:
        msg = f"adm{lvl}_polygons is missing {sorted(missing)}"
        raise ValueError(msg)
    n_poly, n_ids, n_pts, n_pt_ids, n_orphan = conn.execute(f"""--sql
        SELECT (SELECT count(*) FROM '{poly}'),
               (SELECT count(DISTINCT adm{lvl}_id) FROM '{poly}'),
               (SELECT count(*) FROM '{pts}'),
               (SELECT count(DISTINCT id) FROM '{pts}'),
               (SELECT count(*) FROM '{pts}' p
                ANTI JOIN '{poly}' g ON p.id = g.adm{lvl}_id)
    """).fetchall()[0]
    if not 0 < n_poly == n_ids == n_pts == n_pt_ids or n_orphan:
        msg = (
            f"adm{lvl}: {n_poly} polygons, {n_ids} ids, {n_pts} points, "
            f"{n_pt_ids} point ids, {n_orphan} points with no polygon"
        )
        raise ValueError(msg)
    logger.info("adm%d: %d polygons and points", lvl, n_poly)


def _check_lines(conn: duckdb.DuckDBPyConnection) -> None:
    """Raise if any code's lines have a null adm_lvl or one outside 1..MAX_LVL."""
    bad = conn.execute(f"""--sql
        SELECT count(*) FROM read_parquet('{CODES_DIR}/*/lines.parquet')
        WHERE adm_lvl IS NULL OR adm_lvl NOT BETWEEN 1 AND {MAX_LVL}
    """).fetchall()[0][0]
    if bad:
        msg = f"{bad} per-code lines with a null adm_lvl or one outside 1..{MAX_LVL}"
        raise ValueError(msg)


def _merge_issues(conn: duckdb.DuckDBPyConnection) -> None:
    """Merge each issues file and the validation summaries across codes, with a code."""
    rmtree(ISSUES_DIR, ignore_errors=True)
    ISSUES_DIR.mkdir(parents=True)
    names = {
        "code_issues.parquet" if p.name.endswith("_code_issues.parquet") else p.name
        for p in CODES_DIR.glob("*/*_issues.parquet")
    }
    for name in sorted(names):
        glob = "*_code_issues.parquet" if name == "code_issues.parquet" else name
        conn.execute(f"""--sql
            COPY (
                SELECT {_CODE} AS build_iso3, * EXCLUDE (filename)
                FROM read_parquet('{CODES_DIR}/*/{glob}', union_by_name = true,
                                  filename = true)
            ) TO '{ISSUES_DIR / name}' {PARQUET_OPTS}
        """)
    summary = ISSUES_DIR / "validate_summary.csv"
    conn.execute(f"""--sql
        COPY (
            SELECT stage, kind, severity, sum(count)::BIGINT AS count,
                   count(DISTINCT {_CODE}) AS codes, reason
            FROM read_csv('{CODES_DIR}/*/*_validate_summary.csv', filename = true)
            GROUP BY ALL
            ORDER BY stage, severity, count DESC
        ) TO '{summary}'
    """)
    for stage, kind, count, codes in conn.execute(f"""--sql
        SELECT stage, kind, count, codes FROM '{summary}' WHERE severity = 'error'
    """).fetchall():
        logger.warning(
            "package: %d %s %s error(s) in %d code(s)", count, stage, kind, codes
        )
    logger.info("issues and validation summary: %s", ISSUES_DIR)
