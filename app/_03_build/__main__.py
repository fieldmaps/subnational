"""Build edge-matched DuckDB tables from prepare.duckdb's admin table.

Produces tmp/build.duckdb with 12 tables: adm{1..4}_{polygons,lines,points}. adm0
is produced by a separate pipeline; here the ADM0 layer (adm0_clip) is only the clip
boundary. Each country's boundary is grid-subdivided into small lossless pieces so a
per-country clip never touches the multi-million-vertex coastline that OOMs DuckDB's
GEOS layer. Polygons are clipped/dissolved one country at a time; interior lines come
from sibling shared borders (no national outline needed).
"""

import app.config
from app.config import BUILD_DB
from app.utils import export_debug_tables, get_conn

from . import _03a_inputs, _03b_clip, _03c_lines, _03d_points, _03e_attributes


def main() -> None:
    """Run the global build stage end-to-end."""
    conn = get_conn(BUILD_DB, reset=True)

    _03a_inputs.load_source(conn)
    _03a_inputs.load_adm0(conn)

    _03b_clip.clip_and_aggregate(conn)
    _03c_lines.generate_lines(conn)
    _03d_points.generate_points(conn)
    _03e_attributes.main(conn)

    if app.config.DEBUG:
        export_debug_tables(conn, "build")
    conn.close()


if __name__ == "__main__":
    main()
