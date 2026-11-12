"""Configuration constants for the export stage."""

GLOBAL_LICENSE = "ODbL-1.0"
# admin{N}{suffix}.parquet per build table geometry.
SUFFIXES = {"polygons": "", "points": "_points", "lines": "_lines"}
