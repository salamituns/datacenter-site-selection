"""
Taylor County, Texas parcel ingestion — the third parcel jurisdiction.

Abilene sits in ERCOT, not PJM, so unlike Ohio nothing from the power
diligence layer carries over: RTEP upgrade cost, the empirical schedule
slip and the energization windows have no Texas equivalent in this
engine, and the power gate is recorded UNKNOWN. What does carry is every
national overlay — wetlands, floodplain, slope, protected land, roads —
and the interconnection layer.

Texas publishes differently again. There is no queryable county service:
the statewide StratMap parcel layer advertises a Query capability and
refuses every query form, and the appraisal district instead publishes
files. So this adapter downloads the district's own shapefile, the same
download-once-and-cache pattern already used for PAD-US, the NWI
geodatabases and the Loudoun assessment roll.

WHAT IS NOT HERE, and why:

  * Assessed value, tax and agricultural deferral live in the certified
    appraisal roll — a 60 MB archive expanding to 2 GB of fixed-width CAMA
    files against a separately published layout. Real, free and public,
    but a separate ingestion; until it lands those metrics are absent
    rather than guessed.
  * Zoning is largely absent by law. Texas counties have no general
    zoning authority over unincorporated land, so most of the county has
    no ordinance to test against. That is a finding rather than a gap —
    but it is not a pass either, so the gate stays UNKNOWN.
"""

import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional

import geopandas as gpd
import requests

logger = logging.getLogger("taylor_api")

# Taylor Central Appraisal District publishes the parcel shapefile as a
# dated file, so the URL moves when they republish. Overridable without a
# code change; an unreachable file leaves the layer absent, never stale.
PARCEL_ZIP_URL = (
    "https://taylor-cad.org/wp-content/uploads/2026/07/"
    "TaylorCAD_GIS_Shapefile_as_of_20Jul26.zip"
)
PARCEL_CACHE = Path(__file__).parent / "cache" / "taylor_cad_parcels.zip"
SHAPEFILE_MEMBER = "PARCELS.shp"

# The district publishes on WordPress.com, which blocks datacenter IP
# ranges: the same request that succeeds from a laptop is answered 429
# from a CI runner, and no amount of backoff changes that. The file is
# therefore mirrored, unmodified, as a release asset on this repository —
# transport only. The district remains the source of record, and
# data_sources.taylor_cad_parcels points at them rather than at the
# mirror. The mirror is tried first in CI and the district is the
# fallback, so a workstation with no token still fetches from source.
MIRROR_TAG = os.getenv("TAYLOR_MIRROR_TAG", "taylor-cad-20260720")
MIRROR_ASSET = "TaylorCAD_GIS_Shapefile_as_of_20Jul26.zip"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Equal-area projection for the acreage check; the shapefile itself is
# Texas North Central (EPSG:2276), which geopandas reads from the .prj.
AREA_CRS = "EPSG:5070"
M2_PER_ACRE = 4046.8564224


def _download_from_mirror(dest: Path) -> bool:
    """
    Fetches the mirrored shapefile from this repository's releases.

    Returns False rather than raising when there is no token or no
    mirror, so the caller falls back to the district. The repository is
    private, so the asset is fetched through the API with the workflow's
    token; a public download URL would 404.
    """
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if not token or not repo:
        return False
    api = f"https://api.github.com/repos/{repo}"
    headers = {"Authorization": f"Bearer {token}",
               "X-GitHub-Api-Version": "2022-11-28"}
    try:
        rel = requests.get(f"{api}/releases/tags/{MIRROR_TAG}",
                           headers={**headers, "Accept": "application/vnd.github+json"},
                           timeout=60)
        if rel.status_code != 200:
            logger.info("No parcel mirror at tag %s — using the district.", MIRROR_TAG)
            return False
        asset = next((a for a in rel.json().get("assets", [])
                      if a.get("name") == MIRROR_ASSET), None)
        if asset is None:
            return False
        logger.info("Fetching Taylor CAD parcels from the repository mirror…")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(asset["url"],
                          headers={**headers, "Accept": "application/octet-stream"},
                          timeout=300, stream=True) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
            tmp.replace(dest)
        return True
    except Exception as e:  # noqa: BLE001
        logger.info("Parcel mirror unavailable (%s) — trying the district.", e)
        return False


def _download(url: str, dest: Path, attempts: int = 4) -> None:
    """
    Fetches a published file, retrying a throttle rather than giving up.

    The district serves from an ordinary web host that rate-limits, and it
    answered a CI runner with 429 Too Many Requests where the same request
    from a laptop succeeded. A 429 is a request to wait, not a refusal, so
    it is waited out; a 404 is a real answer and is not retried.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(attempts):
        try:
            r = requests.get(url, headers={"User-Agent": BROWSER_UA},
                             timeout=300, stream=True)
            if r.status_code in (429, 503):
                raise requests.HTTPError(f"status {r.status_code}")
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
            tmp.replace(dest)
            return
        except Exception:  # noqa: BLE001
            if attempt == attempts - 1:
                raise
            wait = 5 * (2 ** attempt) + random.uniform(0, 3)
            logger.info("Taylor CAD download throttled or failed; retrying in %.0fs.",
                        wait)
            time.sleep(wait)


class TaylorParcelAPI:
    """Taylor CAD cadastral parcels for a survey bbox."""

    MIN_SOURCE_ACRES = 20.0

    def layer_sources(self) -> Dict[str, Dict[str, Optional[str]]]:
        """
        Zoning, wetlands and flood are declared with a null endpoint: they
        were sought and this jurisdiction does not publish them, which the
        snapshot should record rather than silently omit. Wetlands and
        flood are picked up from the national layers by the pipeline.
        """
        return {
            "parcels": {"source_key": "taylor_cad_parcels", "endpoint": PARCEL_ZIP_URL},
            "zoning": {"source_key": None, "endpoint": None},
            "wetlands": {"source_key": "nwi_wetlands", "endpoint": None},
            "nfhl": {"source_key": None, "endpoint": None},
        }

    def fetch_all(self, min_lon: float, min_lat: float,
                  max_lon: float, max_lat: float,
                  min_acres: float = MIN_SOURCE_ACRES
                  ) -> Dict[str, Optional[gpd.GeoDataFrame]]:
        return {
            "parcels": self.fetch_parcels(min_lon, min_lat, max_lon, max_lat, min_acres),
            "zoning": None,
            "wetlands": None,
            "nfhl": None,
        }

    def fetch_parcels(self, min_lon: float, min_lat: float,
                      max_lon: float, max_lat: float, min_acres: float
                      ) -> Optional[gpd.GeoDataFrame]:
        """
        Parcels at or above the acreage floor, keyed by appraisal account.

        GEO_ID is the key rather than PROP_ID. PROP_ID is zero on 124
        parcels here — unassigned, not shared — and keying on it would
        have collapsed 124 distinct properties covering some 9,500 acres
        into one row, silently.

        A single account can be mapped as several polygons where a road or
        river splits it, so features are dissolved by account: those parts
        are one parcel and their acreage belongs together.
        """
        try:
            if not PARCEL_CACHE.exists():
                if not _download_from_mirror(PARCEL_CACHE):
                    _download(PARCEL_ZIP_URL, PARCEL_CACHE)

            gdf = gpd.read_file(f"zip://{PARCEL_CACHE}!{SHAPEFILE_MEMBER}")
        except Exception as e:  # noqa: BLE001
            logger.warning("Taylor CAD parcels unavailable (%s) — layer absent.", e)
            return None

        if gdf.crs is None:
            logger.warning("Taylor CAD shapefile has no CRS — refusing to guess.")
            return None
        gdf = gdf.to_crs("EPSG:4326")

        gdf = gdf.cx[min_lon:max_lon, min_lat:max_lat].copy()
        gdf["pin"] = gdf["GEO_ID"].astype(str).str.strip()
        gdf = gdf[(gdf["pin"] != "") & (gdf["pin"].str.lower() != "nan")]
        if gdf.empty:
            logger.warning("Taylor CAD parcels: nothing in the survey bbox.")
            return None

        parts = len(gdf)
        gdf = gdf.dissolve(by="pin", aggfunc={"C_ACRE": "sum"}).reset_index()

        measured = gdf.to_crs(AREA_CRS).geometry.area / M2_PER_ACRE
        gdf = gdf[measured >= min_acres].copy()
        if gdf.empty:
            logger.warning("Taylor CAD parcels: none at or above %g acres.", min_acres)
            return None

        # The district's own acreage, kept as the legal figure where it
        # agrees with the mapped boundary and dropped where it does not —
        # the engine measures GIS acreage from the geometry regardless.
        agree = measured.loc[gdf.index]
        gdf["legal_acreage"] = [
            float(c) if c and 0.5 <= (c / m) <= 2.0 else None
            for c, m in zip(gdf["C_ACRE"], agree)
        ]
        gdf = gdf[["pin", "legal_acreage", "geometry"]]

        logger.info("Taylor CAD parcels: %d accounts >= %g acres "
                    "(dissolved from %d mapped parts).",
                    len(gdf), min_acres, parts)
        return gdf
