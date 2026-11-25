"""Ingest a EuroGeographics EuroGlobalMap (EGM) release into catalog/source/.

Run: uv run python -m scripts.ingest_egm ~/Downloads/euro-global-map-GPKG [--icc BA]
"""

from datetime import date
from pathlib import Path

from scripts._ebm import Product, run

# Copyright holder per ICC, from the EGM User Guide.
AGENCIES = {
    "BA": "Federal Administration for Geodetic and Real Property Affairs",
    "GL": "Kort og Matrikelstyrelsen",
    "RS": "Republički geodetski zavod",
}


def _agencies(_root: Path, iccs: list[str]) -> tuple[list[str], list[date]]:
    """Return each ICC's mapping agency; EGM has no per-country metadata date."""
    return [AGENCIES[icc] for icc in iccs if icc in AGENCIES], []


EGM = Product(
    src="egm",
    src_url="https://www.mapsforeurope.org/datasets/euro-global-map",
    src_lic="EuroGeographics Open Data Licence 2024",
    src_grp="EGM",
    gpkg="DATA/FullEurope/EuroGlobalMap_*.gpkg",
    shn=4,
    # Kept area types: 2 main, 5 coastal water; 8 (in dispute) has no codes.
    taa_keep=(2, 5),
    taa_coastal=5,
    # RS: USE 2 codes only Vojvodina and Kosovo, USE 4 only a few cities.
    skip={"RS": {2, 4}},
    merge={"ND": "GB"},
    split={},
    # Serbia is only in the option layers; optionRS keeps Kosovo within Serbia.
    extra={"RS": ("PolbndA_optionRS", "EBM_NAM_optionRS")},
    agencies=_agencies,
    adopt={"cod-ab-legacy", "geoboundaries"},
    clean_original=True,
)

if __name__ == "__main__":
    run(EGM, __doc__)
