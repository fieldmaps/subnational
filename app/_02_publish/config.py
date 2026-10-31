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

# PMTiles max zoom; tylertoo "auto" stops at z7 for adm3, too coarse to inspect units.
PMTILES_MAX_ZOOM = 10
CATALOG_TITLE = "FieldMaps Subnational Administrative Boundaries"
CATALOG_DESCRIPTION = (
    "Edge-matched admin level 1+ boundaries for every country and territory, "
    "always in the humanitarian world view, which groups disputed and autonomous "
    "areas with a neighbouring area. Built from OCHA COD-AB on Source Cooperative, "
    "filled with legacy COD and geoBoundaries layers, all backed up in this "
    "catalog, and clipped to the OSM-based humanitarian admin 0 polygons of "
    f"{INTERNATIONAL_URL}."
)
TIERS = {
    "original": "The layer with its source geometry, in the cod-ab schema",
    "extended": "The layer extended past its coastline, in the cod-ab schema",
}
SRC_NAMES = {
    "cod-ab": "OCHA COD-AB (Source Cooperative)",
    "erm": "EuroGeographics EuroRegionalMap",
    "cod-ab-legacy": "OCHA COD-AB (legacy FieldMaps copy)",
    "geoboundaries": "geoBoundaries (legacy FieldMaps copy)",
}
SRC_DESCRIPTIONS = {
    "erm": (
        "EuroRegionalMap administrative units, one layer per country, ingested "
        "from each yearly release. This dataset includes Intellectual Property "
        "from European National Mapping and Cadastral Authorities and is licensed "
        "on behalf of these by EuroGeographics. Original dataset is available for "
        "free at https://www.mapsforeurope.org. Terms of the licence available at "
        "https://www.mapsforeurope.org/licence."
    ),
    "cod-ab": (
        "Backup of the latest full-coverage layer per iso3 from "
        "https://source.coop/hdx/cod-ab, refreshed on every pipeline run."
    ),
    "cod-ab-legacy": (
        "COD-AB layers migrated from FieldMaps' legacy copies, kept for iso3 "
        "and extents not yet on source.coop/hdx/cod-ab."
    ),
    "geoboundaries": (
        "geoBoundaries layers migrated from FieldMaps' legacy copies, used where "
        "no COD-AB layer exists."
    ),
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
