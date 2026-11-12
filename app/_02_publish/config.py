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
PMTILES_MAX_ZOOM = 12
CATALOG_TITLE = "FieldMaps Subnational Administrative Boundaries"
CATALOG_DESCRIPTION = (
    "Edge-matched admin level 1+ boundaries for every country and territory, "
    "always in the humanitarian world view, which groups disputed and autonomous "
    "areas with a neighbouring area. Built from one layer per iso3 (OCHA COD-AB "
    "on Source Cooperative, filled with EuroRegionalMap, legacy COD and "
    "geoBoundaries layers), published under iso3/, and clipped to the OSM-based "
    f"humanitarian admin 0 polygons of {INTERNATIONAL_URL}."
)
ISO3_TITLE = "Subnational boundaries by ISO3"
ISO3_DESCRIPTION = (
    "One collection per ISO3 country or area: the layer the global build uses, "
    "taken from OCHA COD-AB where available, else EuroRegionalMap, legacy COD, "
    "or geoBoundaries."
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
# Attribution each collection of that src must carry.
SRC_NOTICES = {
    "erm": (
        "This dataset includes Intellectual Property "
        "from European National Mapping and Cadastral Authorities and is licensed "
        "on behalf of these by EuroGeographics. Original dataset is available for "
        "free at https://www.mapsforeurope.org. Terms of the licence available at "
        "https://www.mapsforeurope.org/licence."
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
# Terms page of each non-SPDX license, else the source page is linked.
LICENSE_URLS = {
    "EuroGeographics Open Data Licence 2024": "https://www.mapsforeurope.org/licence",
}
