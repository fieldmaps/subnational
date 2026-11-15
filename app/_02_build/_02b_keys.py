"""Clip, fill down and package each input key on its own ADM0 parent, in parallel."""

import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import closing
from logging import WARNING, Handler, LogRecord, getLogger
from pathlib import Path
from shutil import rmtree

from topo_tools.api import edge_mosaic, package, schema_fill

from app._01_sources.utils import catalog_path
from app.config import PARQUET_OPTS
from app.utils import get_conn

from ._02a_inputs import PARENT, stage, staged_columns
from .config import (
    ADM0_FILL,
    BUILD_DIR,
    CODE_FIELD,
    MATCH_KEY,
    NAME_FIELD,
    THREADS,
    WLD_COLS,
    WORKERS,
)

logger = getLogger(__name__)

KEYS_DIR = BUILD_DIR / "keys"
# Job name for the ADM0 parts that no input covers.
FILL_JOB = "_fill"


class _Unpaired(Handler):
    """Record topo-tools' warning that an input ran without its originals."""

    def __init__(self) -> None:
        super().__init__(WARNING)
        self.hit = False

    def emit(self, record: LogRecord) -> None:
        self.hit |= "runs without originals" in record.getMessage()


def build_keys(sources: dict[str, tuple]) -> None:
    """Package every key into KEYS_DIR/{key}/, largest input first."""
    rmtree(KEYS_DIR, ignore_errors=True)
    KEYS_DIR.mkdir(parents=True)
    order = sorted(sources, key=lambda k: -catalog_path("extended", k).stat().st_size)
    pool = ProcessPoolExecutor(WORKERS)
    try:
        jobs = {pool.submit(_input_job, k, sources[k]): k for k in order}
        jobs[pool.submit(_fill_job, list(sources))] = FILL_JOB
        for done, job in enumerate(as_completed(jobs), 1):
            logger.info(
                "%s done in %.0fs (%d/%d)", jobs[job], job.result(), done, len(jobs)
            )
    finally:
        pool.shutdown(cancel_futures=True)


def _input_job(key: str, meta: tuple) -> float:
    """Stage key, edge-mosaic it to its parent with its own originals, package it."""
    t0 = time.perf_counter()
    work = KEYS_DIR / key
    work.mkdir()
    parent, staged, filled = (
        work / f"{n}.parquet" for n in ("parent", "staged", "filled")
    )
    with closing(get_conn()) as conn:
        conn.execute(
            f"COPY (SELECT * FROM '{PARENT}' WHERE {MATCH_KEY} = ?) "
            f"TO '{parent}' {PARQUET_OPTS}",
            [key.upper()],
        )
        stage(conn, key, meta, staged)
    originals = sorted(catalog_path("original", key).parent.glob("*_original.parquet"))
    unpaired = _Unpaired()
    mosaic_log = getLogger("topo_tools.api.edge_mosaic")
    mosaic_log.addHandler(unpaired)
    edge_mosaic(
        input_paths=[staged],
        overlay_path=parent,
        output_path=filled,
        issues_path=work / "mosaic_issues.parquet",
        original_paths=originals,
        match_column=MATCH_KEY,
        merge=True,
        overlay_include=[MATCH_KEY, *WLD_COLS],
        input_exclude=[MATCH_KEY],
        fill=ADM0_FILL,
        clean=False,
        fill_schema=True,
        name_field=NAME_FIELD,
        code_field=CODE_FIELD,
        threads=THREADS,
        tmp_dir=work,
    )
    mosaic_log.removeHandler(unpaired)
    if originals and unpaired.hit:
        msg = f"{key}: no original pairs with the staged layer by adm{{n}}_pcode"
        raise RuntimeError(msg)
    _package(work, filled)
    for path in (parent, staged, filled):
        path.unlink()
    return time.perf_counter() - t0


def _fill_job(keys: list[str]) -> float:
    """Package the parent rows of ADM0 parts that no input key covers."""
    t0 = time.perf_counter()
    work = KEYS_DIR / FILL_JOB
    work.mkdir()
    rows, filled = work / "rows.parquet", work / "filled.parquet"
    cols = [
        f"{ADM0_FILL[c]}::{t} AS {c}"
        if c in ADM0_FILL
        else f"geom AS {c}"
        if c == "geometry"
        else f"NULL::{t} AS {c}"
        for c, t in staged_columns()
        if c != MATCH_KEY
    ]
    with closing(get_conn()) as conn:
        conn.execute(
            f"""--sql
            COPY (
                SELECT {MATCH_KEY}, {", ".join(cols)}, {", ".join(WLD_COLS)}
                FROM '{PARENT}'
                WHERE NOT list_contains(?, {MATCH_KEY})
            ) TO '{rows}' {PARQUET_OPTS}
        """,
            [[k.upper() for k in keys]],
        )
    schema_fill(rows, filled, name_field=NAME_FIELD, code_field=CODE_FIELD)
    _package(work, filled)
    for path in (rows, filled):
        path.unlink()
    return time.perf_counter() - t0


def _package(work: Path, filled: Path) -> None:
    """Package filled into work/admin{n}, points and lines for levels 1 and up."""
    # Clip seams are accepted; validation errors are reported, not raised.
    package(
        filled,
        work / "{x}.parquet",
        name_field=NAME_FIELD,
        code_field=CODE_FIELD,
        min_level=1,
        clean=False,
        block=False,
        threads=THREADS,
        tmp_dir=work,
    )
