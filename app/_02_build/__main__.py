"""Build edge-matched adm{n}_{polygons,lines,points} tables in tmp/build.duckdb."""

import app.config
from app.config import BUILD_DB
from app.utils import export_debug_tables, get_conn

from . import _02a_inputs, _02b_clip, _02c_validate


def main() -> None:
    """Run the global build stage end-to-end."""
    conn = get_conn(BUILD_DB, reset=True)
    _02a_inputs.load_adm0(conn)
    levels = _02b_clip.clip_and_package(conn)
    _02c_validate.validate(levels)
    if app.config.DEBUG:
        export_debug_tables(conn, "build")
    conn.close()


if __name__ == "__main__":
    main()
