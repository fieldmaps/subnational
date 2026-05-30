"""Build edge-matched DuckDB tables from prepare.duckdb's admin table.

Produces tmp/build.duckdb with 12 tables: adm{1..4}_{polygons,lines,points}. adm0
is produced by a separate pipeline; here the ADM0 template is only the clip
boundary. Polygons and interior lines are clipped and dissolved one country at a
time — against the ADM0 boundary's individual single-part polygons, not the whole
MultiPolygon, which OOMs DuckDB's GEOS layer on large coastlines.
"""

import app.config
from app.config import BUILD_DB
from app.utils import export_debug_tables, get_conn

from . import _03a_inputs, _03b_clip, _03c_lines, _03d_points, _03e_attributes


def main() -> None:
    """Run the global build stage end-to-end."""
    conn = get_conn(BUILD_DB, reset=True)

    _03a_inputs.load_adm0(conn)
    _03a_inputs.load_source(conn)

    _03b_clip.clip_and_aggregate(conn)
    _03c_lines.generate_lines(conn)
    _03d_points.generate_points(conn)
    _03e_attributes.main(conn)

    if app.config.DEBUG:
        export_debug_tables(conn, "build")
    conn.close()


if __name__ == "__main__":
    main()
