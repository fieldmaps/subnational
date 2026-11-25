"""Ingest a EuroGeographics EuroRegionalMap (ERM) release into catalog/source/.

Run: uv run python -m scripts.ingest_erm ~/Downloads/FullEurope [--icc DE,FR]
"""

import re
from datetime import date
from pathlib import Path

from scripts._ebm import Product, run

_ORG = re.compile(r"<gmd:organisationName>\s*<gco:CharacterString>([^<]+)")
_STAMP = re.compile(r"<gmd:dateStamp>\s*<gco:Date>([^<]+)")


def _agencies(root: Path, iccs: list[str]) -> tuple[list[str], list[date]]:
    """Return each ICC's mapping agency and metadata date from its country XML."""
    agencies, stamps = [], []
    for icc in iccs:
        xml = next((root / "Metadata" / "Countries").glob(f"{icc}_ERM_*_Metadata.xml"))
        text = xml.read_text(encoding="utf-8")
        if org := _ORG.search(text):
            agencies.append(org[1].strip())
        if stamp := _STAMP.search(text):
            stamps.append(date.fromisoformat(stamp[1].strip()[:10]))
    return agencies, stamps


ERM = Product(
    src="erm",
    src_url="https://www.mapsforeurope.org/datasets/euro-regional-map",
    src_lic="EuroGeographics Open Data Licence 2024",
    src_grp="ERM",
    gpkg="data/FullEurope/FullEurope.gpkg",
    shn=5,
    # Kept area types: 1 main, 3 branch, 4 special, 5 coastal water, 7 inland water.
    taa_keep=(1, 3, 4, 5, 7),
    taa_coastal=5,
    # ERM orders (USE 2..6) left out, matching Mapbox Boundaries v4.7 levels.
    skip={
        "DE": {3, 5},
        "FR": {5},
        "GF": {5},
        "GP": {5},
        "MQ": {5},
        "RE": {5},
        "YT": {5},
        "GB": {5},
        "CY": {4},
        "FI": {2, 4},
        "IE": {2},
        "PT": {2},
    },
    # ERM ICC folded into another country's layer.
    merge={"ND": "GB"},
    # ERM ICC whose units under one adm1 code form another ISO country: (iso2, name).
    split={"FI": {"FI72100000": ("AX", "Åland Islands")}},
    extra={},
    agencies=_agencies,
    adopt={"egm", "cod-ab-legacy", "geoboundaries"},
)

if __name__ == "__main__":
    run(ERM, __doc__)
