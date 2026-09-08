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
                        "source_url,source_org,unit,valid_from")
                .order("valid_from", desc=True).execute().data or [])
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


def site_prep_cost(developable_acres: Optional[float],
                   assumption: Optional[Dict[str, Any]]
                   ) -> Optional[Dict[str, Any]]:
    """
    Clearing and rough grading over the developable area, as a range.

    Deliberately returns a low and a high with no expected value between
    them. The underlying unit cost is not authoritative, and a midpoint
    would invent a precision the source does not support.
    """
    if developable_acres is None or developable_acres <= 0 or assumption is None:
        return None
    p = assumption["params"]
    lo, hi = float(p["usd_per_acre_low"]), float(p["usd_per_acre_high"])
    acres = float(developable_acres)
    return {
        "low": round(acres * lo, 2),
        "high": round(acres * hi, 2),
        "details": {
            **_cite(assumption),
            "formula": "contiguous_developable_acreage * usd_per_acre",
            "inputs": {"developable_acres": round(acres, 3),
                       "usd_per_acre_low": lo, "usd_per_acre_high": hi},
            "scope": p.get("scope"),
            "excludes": p.get("excludes", []),
            "confidence": ("low — placeholder unit cost, replace with your "
                           "own cost model before relying on it"),
        },
    }
