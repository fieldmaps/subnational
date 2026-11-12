"""Pipeline entry point: runs the requested step, or all of them in order."""

from argparse import ArgumentParser
from os import getenv

import app.config as _config
from app import _01_sources, _02_build, _03_export

_STEPS = {
    "sources": _01_sources.main,
    "build": _02_build.main,
    "export": _03_export.main,
}

_BOOL_VALS = ("YES", "ON", "TRUE", "1")


def main() -> None:
    """Run the requested stage(s) of the subnational pipeline."""
    step = _parse()
    for name, fn in _STEPS.items():
        if step in (None, name):
            fn()


def _parse() -> str | None:
    parser = ArgumentParser(description="Admin boundaries pipeline.")
    parser.add_argument(
        "--step",
        default=getenv("STEP"),
        choices=list(_STEPS),
        help="Run only the named stage (default: run all).",
    )
    parser.add_argument(
        "--debug",
        default=getenv("DEBUG", "").upper() in _BOOL_VALS,
        type=lambda v: v is None or v.upper() in _BOOL_VALS,
        nargs="?",
        const=True,
        help="Enable profiling and write parquet snapshots to tmp/.",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        default=_config.PUSH,
        help="Push catalog changes to source.coop after the sources and export steps.",
    )
    parser.add_argument(
        "--force-pmtiles",
        action="store_true",
        default=_config.FORCE_PMTILES,
        help="Rebuild every PMTiles, even for unchanged parquets.",
    )
    args = parser.parse_args()
    _config.PUSH = args.push
    _config.FORCE_PMTILES = args.force_pmtiles
    _config.DEBUG = args.debug or bool(args.step)
    return args.step


if __name__ == "__main__":
    main()
