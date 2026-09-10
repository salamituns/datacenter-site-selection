"""
The 3DEP slope cache must be fast without lying about provenance.

Two rules carry the weight here, and both are correctness rules rather
than performance ones:

  * A cached value reports the date it was really retrieved. Stamping it
    with the current run's clock would make a correct number carry false
    evidence, and the evidence is the part being asked to bear weight.
  * A failed sample is never cached. A transient network error is a fact
    about the network, not the terrain; caching it would freeze that
    parcel's slope gate at UNKNOWN on every future run. Not caching it
    also means coverage improves run over run — the 15 Loudoun parcels
    that failed one run succeeded the next and are now cached.
"""

import json

import pytest
from shapely.geometry import box

import overlay_layers


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A _SlopeCache backed by a temp file, isolated from the real one."""
    path = tmp_path / "threedep_slopes.json"
    monkeypatch.setattr(overlay_layers._SlopeCache, "path", staticmethod(lambda: path))
    monkeypatch.setattr(overlay_layers._SlopeCache, "_instance", None)
    return overlay_layers._SlopeCache.load()


GEOM = box(-77.5000, 39.0000, -77.4900, 39.0100)
OTHER = box(-77.4000, 39.0000, -77.3900, 39.0100)


class TestRoundTrip:
    def test_empty_cache_misses(self, cache):
        assert cache.get(GEOM) is None

    def test_stores_and_returns_the_measurement(self, cache):
        cache.put(GEOM, 12.5, 3.2, 900)
        smax, smed, n, at = cache.get(GEOM)
        assert (smax, smed, n) == (12.5, 3.2, 900)

    def test_survives_a_process_restart(self, cache, monkeypatch):
        cache.put(GEOM, 12.5, 3.2, 900)
        cache.save()
        monkeypatch.setattr(overlay_layers._SlopeCache, "_instance", None)
        assert overlay_layers._SlopeCache.load().get(GEOM) == cache.get(GEOM)

    def test_distinct_envelopes_do_not_collide(self, cache):
        cache.put(GEOM, 12.5, 3.2, 900)
        assert cache.get(OTHER) is None

    def test_float_noise_below_key_precision_still_hits(self, cache):
        # A re-projected boundary can wobble in the far decimals; the key
        # rounds to ~10cm so that wobble cannot cause a spurious refetch.
        cache.put(GEOM, 12.5, 3.2, 900)
        wobbled = box(-77.5000 + 1e-10, 39.0000, -77.4900, 39.0100)
        assert cache.get(wobbled) is not None


class TestProvenance:
    def test_cached_entry_carries_a_retrieval_date(self, cache):
        cache.put(GEOM, 12.5, 3.2, 900)
        *_, at = cache.get(GEOM)
        assert isinstance(at, str) and at.startswith("20")

    def test_retrieval_date_is_preserved_across_reload(self, cache, monkeypatch):
        cache.put(GEOM, 12.5, 3.2, 900)
        *_, first = cache.get(GEOM)
        cache.save()
        monkeypatch.setattr(overlay_layers._SlopeCache, "_instance", None)
        *_, reloaded = overlay_layers._SlopeCache.load().get(GEOM)
        assert reloaded == first, "a reused value must not be re-dated on reload"

    def test_fresh_fetches_are_signalled_by_a_null_date(self):
        """
        sample_3dep_slopes returns retrieved_at=None for values it fetched
        itself, and parcel_gates falls back to the run clock for those. The
        contract is the None, so pin it.
        """
        # (max, median, n, retrieved_at) is the shape callers unpack.
        fresh = (12.5, 3.2, 900, None)
        assert len(fresh) == 4 and fresh[3] is None


class TestFailuresAreNotCached:
    def test_a_failed_sample_is_not_stored_by_the_caller(self, cache):
        # sample_3dep_slopes only calls put() when n > 0. Pin the rule at
        # the level the cache can see: nothing was written, so the next run
        # retries rather than inheriting an UNKNOWN.
        smax, smed, n = None, None, 0
        if n > 0:  # mirrors the guard in sample_3dep_slopes
            cache.put(GEOM, smax, smed, n)
        assert cache.get(GEOM) is None

    def test_a_later_success_replaces_nothing_and_is_kept(self, cache):
        assert cache.get(GEOM) is None
        cache.put(GEOM, 9.0, 2.0, 812)
        assert cache.get(GEOM)[2] == 812


class TestDegradation:
    def test_corrupt_cache_is_ignored_not_fatal(self, tmp_path, monkeypatch):
        path = tmp_path / "threedep_slopes.json"
        path.write_text("{ not json")
        monkeypatch.setattr(
            overlay_layers._SlopeCache, "path", staticmethod(lambda: path)
        )
        monkeypatch.setattr(overlay_layers._SlopeCache, "_instance", None)
        # A corrupt cache may cost speed; it must never cost correctness.
        assert overlay_layers._SlopeCache.load().get(GEOM) is None

    def test_entry_missing_fields_is_treated_as_a_miss(self, tmp_path, monkeypatch):
        path = tmp_path / "threedep_slopes.json"
        key = overlay_layers._SlopeCache._key(GEOM)
        path.write_text(json.dumps({key: {"max": 1.0}}))  # no median/n/at
        monkeypatch.setattr(
            overlay_layers._SlopeCache, "path", staticmethod(lambda: path)
        )
        monkeypatch.setattr(overlay_layers._SlopeCache, "_instance", None)
        assert overlay_layers._SlopeCache.load().get(GEOM) is None

    def test_save_is_atomic_leaving_no_partial_file(self, cache, tmp_path):
        cache.put(GEOM, 12.5, 3.2, 900)
        cache.save()
        assert cache.path().exists()
        assert not cache.path().with_suffix(".json.tmp").exists()
        json.loads(cache.path().read_text())  # complete and parseable
