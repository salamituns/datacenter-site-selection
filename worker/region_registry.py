"""
The region model, derived from the Census county boundaries rather than typed.

Every region this engine surveys is a US county, and the Census publishes all
of them — geometry, FIPS code, state — in a 900 KB cartographic boundary file.
Until now the model was a hand-written dict of five counties with hand-typed
bounding boxes, plus a second hand-written dict mapping four of them to FIPS
codes. Two lists, maintained separately, neither derivable from the other.

Hand-typed bboxes are wrong in a way that does not announce itself. Measured
against the real county geometry on 2026-09-13:

    VA-LOUDOUN          66 mi2 of the county outside the box   (12.8%)
    TX-TAYLOR          291 mi2                                 (31.7%)
    OH-FRANKLIN        168 mi2                                 (30.4%)
    OR-MORROW        1,476 mi2                                 (71.7%)
    VA-PRINCEWILLIAM     0 mi2                                  (0.0%)

Four of six regions claimed a whole county and surveyed part of one. A parcel
in the missed strip does not read UNKNOWN in the dossier -- it is absent, and
absence is invisible. That is the failure mode this module exists to remove.

OH-LICKING's gap is different and stays: a deliberate corridor window recorded
in SURVEY_WINDOWS below, with its reason. The distinction this module draws is
between a scope that was chosen and a scope that was mistyped.

Deriving the model also makes a national run a data question rather than a
typing question: every county in the country is already in the file.
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

import geopandas as gpd
import requests

logger = logging.getLogger(__name__)

# The 1:20,000,000 cartographic boundary file: 900 KB for all 3,222 counties,
# against roughly 100 MB for the full-resolution TIGER/Line equivalent. The
# generalisation is irrelevant here because only the bounding box is read, and
# a bbox is insensitive to boundary simplification at this scale -- the extreme
# vertices are exactly the ones generalisation preserves.
CENSUS_COUNTY_URL = (
    "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_20m.zip"
)
CENSUS_VINTAGE = "2023"

# A small outward pad on every derived bbox. County geometry is generalised at
# 1:20m and a parcel may touch the boundary, so a box drawn exactly on the
# extremes can clip an edge parcel. At this latitude 0.01 degrees is about
# 0.7 miles -- enough to cover the generalisation, small enough not to pull in
# a meaningful amount of the neighbouring county.
BBOX_PAD_DEG = 0.01

# Deliberate sub-county survey windows. A region appears here only when the
# scope is a decision, and the reason is recorded with it. Everything absent
# from this dict gets its true county extent.
SURVEY_WINDOWS: Dict[str, Dict[str, Any]] = {
    "OH-LICKING": {
        "bbox": (-82.75, 39.95, -82.40, 40.25),
        "reason": (
            "The west-Licking corridor: Jersey, Etna, Monroe and Harrison "
            "townships along I-70, where the New Albany data-center campus "
            "and the Intel site actually sit. 2,853 parcels at the 20-acre "
            "floor (probed 2026-09-10); the full county would be 5,271."
        ),
    },
}

# Grid operator by region. Not derived: RTO footprints do not follow state
# lines (Ohio is split between PJM and MISO, Texas between ERCOT and SPP), so
# a state-level guess would assert a wrong operator for real counties. A region
# absent here has an unknown operator and must be treated as unknown rather
# than defaulted -- see the note in pipeline.resolve_region_args.
GRID_OPERATORS: Dict[str, str] = {
    "VA-LOUDOUN": "PJM Interconnection",
    "VA-PRINCEWILLIAM": "PJM Interconnection",
    "VA-FAUQUIER": "PJM Interconnection",
    "OH-FRANKLIN": "PJM Interconnection",
    "OH-LICKING": "PJM Interconnection",
    "OH-FAIRFIELD": "PJM Interconnection",
    "OH-UNION": "PJM Interconnection",
    "OH-DELAWARE": "PJM Interconnection",
    "TX-TAYLOR": "ERCOT",
    "OR-MORROW": "Bonneville Power Administration",
}


@dataclass(frozen=True)
class Region:
    """One surveyable region. `bbox` is (min_lon, min_lat, max_lon, max_lat)."""

    region_key: str
    state: str
    county: str
    fips: str
    bbox: Tuple[float, float, float, float]
    grid_operator: Optional[str]
    # None when the bbox is the county's own extent; the recorded reason when
    # the survey deliberately covers less than the county.
    survey_window_reason: Optional[str] = None

    @property
    def is_windowed(self) -> bool:
        return self.survey_window_reason is not None


# Census LSAD 25 is an independent city: a county-equivalent that sits outside
# any county. Virginia has most of them, and six of them share a name with the
# county they adjoin -- Fairfax, Franklin, Richmond and Roanoke in Virginia,
# Baltimore in Maryland, St. Louis in Missouri. Keying on the name alone gives
# two different county-equivalents the same region_key, and since region_key is
# what promote swaps on, one would silently overwrite the other's parcels.
#
# So every independent city carries a CITY suffix, whether or not it collides.
# Unconditionally, because a rule that only applies to the six ambiguous ones
# is a rule nobody can predict: VA-ROANOKE is the county and VA-ROANOKECITY is
# the city, and the same holds for Alexandria, which collides with nothing.
INDEPENDENT_CITY_LSAD = "25"


def slug(state: str, county: str, lsad: Optional[str] = None) -> str:
    """
    The region's identity in the database: STATE-COUNTY, uppercased, with
    punctuation and spaces removed. "Prince William" -> "PRINCEWILLIAM",
    matching the keys already published, so this is a derivation of the
    existing convention rather than a new one.

    An independent city (lsad 25) gets a CITY suffix to keep it distinct from
    the like-named county. Passing lsad=None keeps the bare form, which is what
    every already-published region is.
    """
    cleaned = "".join(ch for ch in county.upper() if ch.isalnum())
    if lsad is not None and str(lsad).strip() == INDEPENDENT_CITY_LSAD:
        cleaned += "CITY"
    return f"{state.upper()}-{cleaned}"


def _cache_path() -> Path:
    return (Path(__file__).parent / "cache"
            / f"census_counties_{CENSUS_VINTAGE}.gpkg")


def _load_counties() -> gpd.GeoDataFrame:
    """
    All US counties, cached as GeoPackage after the first download.

    Cached on disk rather than in memory alone because the pipeline runs as
    separate processes per region in CI; worker/cache is restored by
    actions/cache, so the download happens once per cache generation.
    """
    cache = _cache_path()
    if cache.exists():
        return gpd.read_file(cache)

    logger.info("Census counties: downloading %s (once; cached thereafter)",
                CENSUS_COUNTY_URL.rsplit("/", 1)[-1])
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "counties.zip"
        resp = requests.get(CENSUS_COUNTY_URL, stream=True, timeout=300)
        resp.raise_for_status()
        with open(zip_path, "wb") as out:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if chunk:
                    out.write(chunk)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        shp = next(Path(tmp).glob("*.shp"))
        gdf = gpd.read_file(str(shp)).to_crs("EPSG:4326")

    keep = gdf[["STATEFP", "COUNTYFP", "GEOID", "NAME", "NAMELSAD", "LSAD",
                "STUSPS", "STATE_NAME", "geometry"]].copy()
    keep["region_key"] = [slug(st, nm, ls) for st, nm, ls
                          in zip(keep.STUSPS, keep.NAME, keep.LSAD)]

    # A collision here means two county-equivalents would share a region_key,
    # and promote swaps on region_key -- one would overwrite the other's
    # parcels with no error anywhere. Fail the build of the cache instead.
    dupes = keep.region_key[keep.region_key.duplicated(keep=False)]
    if len(dupes):
        raise RuntimeError(
            "Census counties: region_key is not unique for "
            f"{sorted(set(dupes))} -- the slug rule cannot tell two "
            "county-equivalents apart and must be extended before use.")
    cache.parent.mkdir(parents=True, exist_ok=True)
    keep.to_file(cache, driver="GPKG")
    logger.info("Census counties: cached %d counties at %s", len(keep), cache)
    return keep


_COUNTIES: Optional[gpd.GeoDataFrame] = None


def _counties() -> gpd.GeoDataFrame:
    global _COUNTIES
    if _COUNTIES is None:
        _COUNTIES = _load_counties()
    return _COUNTIES


def _bbox_from_geometry(geom) -> Tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = geom.bounds
    return (round(min_lon - BBOX_PAD_DEG, 4), round(min_lat - BBOX_PAD_DEG, 4),
            round(max_lon + BBOX_PAD_DEG, 4), round(max_lat + BBOX_PAD_DEG, 4))


def resolve(region_key: str) -> Optional[Region]:
    """
    The Region for a slug, or None if no such county exists.

    None is returned rather than raised so a caller can distinguish "not a
    county" from a fetch failure, which raises.
    """
    key = (region_key or "").upper()
    df = _counties()
    row = df[df.region_key == key]
    if len(row) == 0:
        # Tolerate the bare name for an independent city ("VA-ALEXANDRIA")
        # when it is unambiguous. The canonical key still carries the suffix;
        # this only spares a caller from having to know the rule.
        alt = df[(df.region_key == key + "CITY")]
        if len(alt) != 1:
            return None
        row = alt
    r = row.iloc[0]
    # Everything below keys off the canonical slug, not the caller's, so a
    # tolerated spelling cannot miss a survey window or a grid operator.
    canonical = str(r.region_key)

    window = SURVEY_WINDOWS.get(canonical)
    if window:
        bbox = tuple(window["bbox"])
        reason = window["reason"]
    else:
        bbox = _bbox_from_geometry(r.geometry)
        reason = None

    return Region(
        # The canonical key from the matched row, never the caller's spelling.
        # Returning the input would let "VA-ALEXANDRIA" publish under a key
        # that is not VA-ALEXANDRIACITY, and the next canonical run would then
        # create a second region for the same county instead of replacing it.
        region_key=canonical,
        state=str(r.STUSPS),
        county=str(r.NAME),
        fips=str(r.GEOID),
        bbox=bbox,
        grid_operator=GRID_OPERATORS.get(canonical),
        survey_window_reason=reason,
    )


def all_regions(states: Optional[list] = None) -> Iterator[Region]:
    """
    Every county, or every county in the given state codes. The national
    screening set; ordered by region_key so a run is reproducible.
    """
    df = _counties()
    if states:
        wanted = {s.upper() for s in states}
        df = df[df.STUSPS.isin(wanted)]
    for key in sorted(df.region_key):
        region = resolve(key)
        if region is not None:
            yield region


def county_fips(region_key: str) -> Optional[str]:
    """The 5-digit state+county FIPS, or None. Replaces a hand-typed map."""
    region = resolve(region_key)
    return region.fips if region else None
