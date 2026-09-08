"""
Real property assessment evidence — Loudoun County's published roll.

The Office of the Commissioner of the Revenue publishes the annual
assessed-value extract for every parcel in the county. It is the observed,
dated basis for the commercial underwriting layer:

  * FAIR MARKET LAND / BUILDING / TOTAL — the assessor's opinion of value
  * LAND USE VALUE / DEFERRED VALUE     — Virginia's land-use assessment
    program (Code of Virginia 58.1-3230 et seq.). Agricultural, horticultural,
    forestal and open-space land is taxed on use value rather than fair
    market value; DEFERRED VALUE is the untaxed difference. A change to a
    more intensive use triggers roll-back taxes under 58.1-3237 — the five
    most recent complete tax years of deferred tax, plus simple interest —
    so a deferred parcel carries a conversion liability that no suitability
    score would surface.
  * EST TAX — the county's own estimated annual levy, carried verbatim
    rather than recomputed from a rate.

Values are the assessor's, not the market's, and are recorded as observed
facts of the roll. Parcels absent from the roll (splits and renumberings
between the extract and the cadastral layer) stay UNKNOWN — never zero,
which would read as "worthless" rather than "unrecorded".
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger("assessment_evidence")

# Annual extract, Loudoun County DocumentCenter. The document id changes
# each assessment year, so it is overridable without a code change; the
# fetcher fails to UNKNOWN rather than guessing at a successor id.
ASSESSMENT_XLSX_URL = os.getenv(
    "LOUDOUN_ASSESSMENT_URL",
    "https://www.loudoun.gov/DocumentCenter/View/212731/"
    "2026-Assessed-Values---Countywide-and-ADU-XLSX",
)
ASSESSMENT_YEAR = os.getenv("LOUDOUN_ASSESSMENT_YEAR", "2026")
ASSESSMENT_CACHE = Path(__file__).parent / "cache" / f"loudoun_assessed_{ASSESSMENT_YEAR}.xlsx"
ASSESSMENT_SOURCE = (
    "Loudoun County Office of the Commissioner of the Revenue, "
    f"{ASSESSMENT_YEAR} Assessed Values (Countywide)"
)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Roll column -> the name used downstream. The published header is a human
# report heading, not a stable schema, so it is mapped explicitly and a
# missing column is a hard failure rather than a silently absent metric.
_COLUMNS = {
    "PARID": "parcel_id",
    "CLASS": "assessment_class",
    "FAIR MARKET LAND": "land_value",
    "FAIR MARKET BUILDING": "building_value",
    "FAIR MARKET TOTAL": "total_value",
    "LAND USE VALUE": "land_use_value",
    "DEFERRED VALUE": "deferred_value",
    "TAXABLE VALUE": "taxable_value",
    "EST TAX": "annual_tax",
}


def fetch_assessments(refresh: bool = False) -> Optional[pd.DataFrame]:
    """
    The county assessment roll, one row per parcel id.

    Cached on disk: the extract is a ~12 MB annual publication, so it is
    downloaded once and reused. Returns None when the roll is unreachable
    or its columns have moved — the caller then records the assessment
    metrics as UNKNOWN rather than publishing values it cannot source.
    """
    try:
        if refresh or not ASSESSMENT_CACHE.exists():
            ASSESSMENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Downloading %s assessment roll…", ASSESSMENT_YEAR)
            r = requests.get(
                ASSESSMENT_XLSX_URL,
                headers={"User-Agent": BROWSER_UA},
                timeout=180,
                stream=True,
            )
            r.raise_for_status()
            tmp = ASSESSMENT_CACHE.with_suffix(".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
            tmp.replace(ASSESSMENT_CACHE)

        df = pd.read_excel(
            ASSESSMENT_CACHE, sheet_name=0, engine="openpyxl", dtype={"PARID": str}
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Assessment roll unavailable (%s) — values stay UNKNOWN.", e)
        return None

    missing = [c for c in _COLUMNS if c not in df.columns]
    if missing:
        logger.warning(
            "Assessment roll columns moved (%s) — values stay UNKNOWN.", missing
        )
        return None

    out = df[list(_COLUMNS)].rename(columns=_COLUMNS)
    out["parcel_id"] = out["parcel_id"].astype(str).str.strip()
    out = out[out["parcel_id"].str.len() > 0]
    # One row per parcel: the roll carries per-jurisdiction rows for parcels
    # that straddle a town, and the countywide row is the one that matches
    # the cadastral id.
    out = out.drop_duplicates(subset="parcel_id", keep="first")
    logger.info("Assessment roll: %d parcels (%s).", len(out), ASSESSMENT_YEAR)
    return out.set_index("parcel_id")


def assessment_of(roll: Optional[pd.DataFrame], parcel_id: str
                  ) -> Optional[Dict[str, Any]]:
    """
    One parcel's assessment record, or None when it is not on the roll.

    Absence is a real answer — parcels split or renumbered between the
    extract and the cadastral layer genuinely have no roll entry yet — and
    is reported as unknown rather than as zero value.
    """
    if roll is None or parcel_id not in roll.index:
        return None
    r = roll.loc[parcel_id]

    def num(key: str) -> Optional[float]:
        v = r.get(key)
        return None if pd.isna(v) else float(v)

    deferred = num("deferred_value")
    return {
        "assessment_class": (None if pd.isna(r.get("assessment_class"))
                             else str(r.get("assessment_class"))),
        "land_value": num("land_value"),
        "building_value": num("building_value"),
        "total_value": num("total_value"),
        "land_use_value": num("land_use_value"),
        "deferred_value": deferred,
        "taxable_value": num("taxable_value"),
        "annual_tax": num("annual_tax"),
        # The flag an underwriter needs before the dollar figure: this
        # parcel is taxed on use value, and converting it triggers
        # roll-back taxes under Code of Virginia 58.1-3237.
        "in_land_use_deferral": bool(deferred and deferred > 0),
        "assessment_year": ASSESSMENT_YEAR,
        "source": ASSESSMENT_SOURCE,
    }
