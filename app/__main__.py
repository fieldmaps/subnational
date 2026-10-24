"""Pipeline entry point — runs the configured step(s) sequentially."""

from argparse import ArgumentParser
from os import getenv

import app.config as _config
from app import _01_sources, _02_publish, _03_build, _04_export

_STEPS = (
    ("_01_sources", _01_sources.main),
    ("_02_publish", _02_publish.main),
    ("_03_build", _03_build.main),
    ("_04_export", _04_export.main),
)

_ALIASES = {
    "sources": "_01_sources",
    "publish": "_02_publish",
    "build": "_03_build",
    "export": "_04_export",
}

_BOOL_VALS = ("YES", "ON", "TRUE", "1")


def main() -> None:
    """Run the requested stage(s) of the admin-boundaries pipeline."""
    step = _parse()
    for name, fn in _STEPS:
        if step in (None, name):
            fn()


def _parse() -> str | None:
    parser = ArgumentParser(description="Admin boundaries pipeline.")
    parser.add_argument(
        "--step",
        default=getenv("STEP"),
        choices=[name for name, _ in _STEPS] + list(_ALIASES),
        metavar="{sources,publish,build,export}",
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
        help="Push catalog changes to source.coop after publish/export.",
    )
    args = parser.parse_args()
    _config.PUSH = args.push
    _config.DEBUG = args.debug or bool(args.step)
    return _ALIASES.get(args.step, args.step)


if __name__ == "__main__":
    main()
