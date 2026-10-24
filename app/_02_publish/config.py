"""Configuration constants for the publish stage."""

CATALOG_ID = "subnational"
CATALOG_URL = "https://source.coop/fieldmaps/subnational"
INTERNATIONAL_URL = "https://source.coop/fieldmaps/international"
CONTACT = {"name": "Maxym Malynowsky", "email": "fieldmaps@maxmalynowsky.com"}
HOST = {
    "name": "FieldMaps",
    "roles": ["processor", "host"],
    "url": "https://fieldmaps.io",
}

CATALOG_TITLE = "FieldMaps Subnational Administrative Boundaries"
CATALOG_DESCRIPTION = (
    "Edge-matched admin level 1+ boundaries for every country and territory, "
    "always in the humanitarian world view, which groups disputed and autonomous "
    "areas with a neighbouring area. Built from OCHA COD-AB on Source Cooperative, "
    "filled with legacy COD and geoBoundaries layers, and clipped to the OSM-based "
    f"humanitarian admin 0 polygons of {INTERNATIONAL_URL}."
)
TIERS = {
    "original": (
        "Original source layers",
        "The full-coverage layer selected per iso3, as published by its source.",
    ),
    "extended": (
        "Extended source layers",
        (
            "The full-coverage layer selected per iso3, extended past its coastline "
            "and mapped to the pipeline schema. These are the inputs to global/."
        ),
    ),
}

SRC_NAMES = {
    "hdx": "OCHA COD-AB (Source Cooperative)",
    "cod": "OCHA COD-AB (legacy FieldMaps copy)",
    "geoboundaries": "geoBoundaries (legacy FieldMaps copy)",
}

SPDX = {
    "ODbL-1.0": "ODbL-1.0",
    "CC-BY-3.0-IGO": "CC-BY-3.0-IGO",
    "Creative Commons Attribution for Intergovernmental Organisations": (
        "CC-BY-3.0-IGO"
    ),
    "Creative Commons Attribution 3.0 Intergovernmental Organisations "
    "(CC BY 3.0 IGO)": "CC-BY-3.0-IGO",
    "Open Data Commons Open Database License 1.0": "ODbL-1.0",
    "Creative Commons Attribution 4.0 International (CC BY 4.0)": "CC-BY-4.0",
    "Creative Commons Attribution 4.0 (CC BY 4.0)": "CC-BY-4.0",
    "Creative Commons Attribution-ShareAlike 2.0": "CC-BY-SA-2.0",
    "CC0 1.0 Universal (CC0 1.0) Public Domain Dedication": "CC0-1.0",
    "Etalab Open License 2.0": "etalab-2.0",
    "Creative Commons Attribution-ShareAlike 3.0 Unported": "CC-BY-SA-3.0",
    "Creative Commons Attribution 3.0 License": "CC-BY-3.0",
    "Creative Commons Attribution 2.5 Generic": "CC-BY-2.5",
    "Open Government Licence v3.0": "OGL-UK-3.0",
    "Open Data Commons Public Domain Dedication and License (PDDL) v1.0": "PDDL-1.0",
    "Data license Germany - Attribution - Version 2.0": "DL-DE-BY-2.0",
}
