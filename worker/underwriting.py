"""
Commercial underwriting — estimated costs, each tied to a named assumption.

Everything here is modelled, which is exactly why it is separated from the
observed layers. The rule this module exists to enforce: an estimated
metric never travels alone. It carries the observed inputs it was computed
from, the assumption key and version that priced it, and the formula — so
a reader can always take the number apart, and revising an assumption is a
row in cost_assumptions rather than a code change.

The two estimates are deliberately not equally confident, and say so:

  * roll-back tax exposure — every input is a published statutory or
    adopted figure, so the arithmetic is sound and only the simplifications
    are open to argument.
  * site preparation — no authoritative public unit cost exists for
    data-center site work, so this is a range from non-authoritative
    pricing guides, flagged as a placeholder. It is emitted as a low and a
    high, never a point estimate.
"""

import logging
import math
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("underwriting")


def load_assumptions(client: Any = None) -> Dict[str, Dict[str, Any]]:
    """
    The current assumption for each key, newest valid_from first.

    cost_assumptions is world-readable, so a dry run with no write client
    still reads it and exercises the same estimate path the publishing run
    takes — otherwise the only code that prices anything would never run
    in CI.

    Returns an empty dict when unavailable. Estimates are then skipped
    entirely rather than falling back to hard-coded numbers, which is the
    failure mode this whole structure exists to prevent.
    """
    if client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        if not url or not key:
            logger.info("No client for cost assumptions — estimates skipped.")
            return {}
        try:
            from supabase import create_client
            client = create_client(url, key)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read cost assumptions (%s) — estimates skipped.", e)
            return {}
    try:
        rows = (client.table("cost_assumptions")
                .select("assumption_key,assumption_version,params,basis,"
                        "source_url,source_org,unit,valid_from,valid_to,created_at")
                # Superseded rows stay in the table — history is the point of
                # a versioned ledger — but only a currently valid one may
                # price anything. created_at breaks the tie when two versions
                # share a valid_from, which they do when a revision lands the
                # same day as the original.
                .is_("valid_to", "null")
                .order("valid_from", desc=True)
                .order("created_at", desc=True)
                .execute().data or [])
    except Exception as e:  # noqa: BLE001
        logger.warning("Cost assumptions unavailable (%s) — estimates skipped.", e)
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out.setdefault(r["assumption_key"], r)
    logger.info("Cost assumptions loaded: %s", sorted(out))
    return out


def _cite(a: Dict[str, Any]) -> Dict[str, Any]:
    """The provenance every estimated metric carries."""
    return {
        "assumption": a["assumption_key"],
        "assumption_version": a["assumption_version"],
        "basis": a["basis"],
        "source_url": a.get("source_url"),
        "source_org": a.get("source_org"),
    }


def rollback_tax_exposure(deferred_value: Optional[float],
                          assumption: Optional[Dict[str, Any]]
                          ) -> Optional[Dict[str, Any]]:
    """
    What converting a land-use deferred parcel would cost in roll-back tax.

    Returns None when the parcel is not deferred or the assumption is
    missing. A parcel assessed at full fair market value has no exposure —
    that is a real zero, and it is reported as such by the caller rather
    than silently omitted.
    """
    if deferred_value is None or assumption is None:
        return None
    p = assumption["params"]
    rate = float(p["tax_rate_per_100_usd"]) / 100.0
    years = int(p["rollback_years"])
    annual = float(deferred_value) * rate
    return {
        "value": round(annual * years, 2),
        "details": {
            **_cite(assumption),
            "formula": "deferred_value * (rate_per_100 / 100) * rollback_years",
            "inputs": {"deferred_value_usd": float(deferred_value),
                       "tax_rate_per_100_usd": p["tax_rate_per_100_usd"],
                       "rollback_years": years},
            "annual_deferred_tax_usd": round(annual, 2),
            "excludes": ["statutory simple interest",
                         "50% penalty where rezoned within five years"],
            "statute": "Code of Virginia 58.1-3237",
        },
    }


SQFT_PER_ACRE = 43560.0
CUFT_PER_CY = 27.0


def _graded_cut_cy(pad_acres: float, slope_pct: float,
                   terrace_relief_ft: float, max_terraces: int) -> Dict[str, Any]:
    """
    Cut volume to grade a pad, in cubic yards, allowing for terracing.

    Levelling a square pad to a single plane costs slope * side^3 / 8. On
    any real site that is a fiction: an 80-acre pad on a 4% grade falls
    about 75 feet corner to corner, and no one cuts 37 feet to flatten it.
    Campuses are built in steps.

    Splitting the pad into N terraces across the fall line divides the
    earthwork by N, since each step levels a shorter run. N is set by how
    much relief a single step may carry, and then capped: a hyperscale
    campus needs large contiguous pads and cannot be stepped indefinitely.
    The cap is what keeps the estimate sensitive to terrain — past it, a
    steeper site really is moving more earth.

    Returns the volume with the terrace count used, so the estimate can be
    read back rather than taken on faith.
    """
    side_ft = (pad_acres * SQFT_PER_ACRE) ** 0.5
    relief_ft = (slope_pct / 100.0) * side_ft
    single_plane_cy = (slope_pct / 100.0) * (side_ft ** 3) / 8.0 / CUFT_PER_CY
    wanted = math.ceil(relief_ft / terrace_relief_ft) if terrace_relief_ft > 0 else 1
    terraces = max(1, min(wanted, max_terraces))
    return {
        "cut_cubic_yards": single_plane_cy / terraces,
        "terraces": terraces,
        "terraces_wanted": max(1, wanted),
        "site_relief_ft": relief_ft,
        "terrace_capped": wanted > terraces,
    }


def site_prep_cost(developable_acres: Optional[float],
                   median_slope_pct: Optional[float],
                   assumption: Optional[Dict[str, Any]]
                   ) -> Optional[Dict[str, Any]]:
    """
    Clearing and mass earthwork for a graded pad, as an AACE Class 5
    screening estimate.

    AACE International 18R-97 classifies an estimate made at 0-2% project
    definition by parametric methods, for go/no-go screening, as Class 5,
    and gives it an expected accuracy of -50% to +100%. That is exactly
    what this is, so the published band is applied rather than a range
    invented for the purpose — the low and high are the standard's, not
    ours.

    Quantities come from the parcel's own measurements: developable
    acreage, and median slope sampled per parcel from the 3DEP elevation
    model. Two sites of equal size and different terrain therefore price
    differently, which a flat per-acre rate could never show.

    Returns None when slope is unsampled. Earthwork is most of the cost on
    any site with relief, so an area-only figure would understate a steep
    parcel while looking just as confident.
    """
    if (developable_acres is None or developable_acres <= 0
            or median_slope_pct is None or assumption is None):
        return None
    p = assumption["params"]
    pad = min(float(developable_acres), float(p["graded_pad_cap_acres"]))
    grade = _graded_cut_cy(pad, float(median_slope_pct),
                           float(p["terrace_relief_ft"]), int(p["max_terraces"]))
    cy = grade["cut_cubic_yards"]

    clearing = pad * float(p["clearing_usd_per_acre"])
    earthwork = cy * float(p["earthwork_usd_per_cy"])
    base = clearing + earthwork
    lo = base * (1.0 + float(p["accuracy_low_pct"]) / 100.0)
    hi = base * (1.0 + float(p["accuracy_high_pct"]) / 100.0)

    return {
        "low": round(lo, 2),
        "high": round(hi, 2),
        "base": round(base, 2),
        "details": {
            **_cite(assumption),
            "method": ("AACE International 18R-97 Class 5 parametric estimate; "
                       "accuracy band -50%/+100% is the standard's own for this "
                       "level of project definition"),
            "formula": ("clearing = pad_acres * usd_per_acre; "
                        "earthwork = (slope * sqrt(pad_area)^3 / 8 / terraces) "
                        "* usd_per_cy; "
                        "band applied to their sum"),
            "inputs": {
                "developable_acres": round(float(developable_acres), 3),
                "graded_pad_acres": round(pad, 3),
                "median_slope_pct": round(float(median_slope_pct), 3),
                "clearing_usd_per_acre": p["clearing_usd_per_acre"],
                "earthwork_usd_per_cy": p["earthwork_usd_per_cy"],
            },
            "quantities": {
            "cut_cubic_yards": round(cy),
            "terraces_assumed": grade["terraces"],
            "site_relief_ft": round(grade["site_relief_ft"], 1),
            # True where terrain wanted more steps than a campus can take,
            # which is where a steeper site genuinely costs more.
            "terrace_cap_reached": grade["terrace_capped"],
        },
            "components_usd": {"clearing": round(clearing, 2),
                               "earthwork": round(earthwork, 2)},
            "point_estimate_usd": round(base, 2),
            "scope": p.get("scope"),
            "excludes": p.get("excludes", []),
        },
    }
