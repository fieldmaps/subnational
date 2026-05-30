"""Configuration constants for the build stage."""

ADM0_BASE = "https://data.fieldmaps.io/adm0/osm"

CENTROID_PRECISION = 0.000001

# Clip-boundary subdivision (lossless): each country's ADM0 boundary is cut into a
# grid of CLIP_CELL-degree pieces (see _03b) so no single GEOS clip ever sees a
# multi-million-vertex coastline — DuckDB OOMs on that. The union of the pieces is
# exactly the boundary; nothing is simplified.
CLIP_CELL = 1.0
