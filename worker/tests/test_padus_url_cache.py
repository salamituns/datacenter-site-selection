"""
How a PAD-US state geodatabase URL is resolved, and why it is asked once.

ScienceBase challenges the CATALOG API and nothing else. The file endpoint
serves a named file from the release item with a plain 200, so that is the
primary route and the manifest is only a fallback. A resolved URL is
persisted beside the geodatabase cache either way: the URLs are stable for
the life of the release, so re-resolving per county bought nothing and
cost an outage per state once the challenge appeared.

Every test here stubs BOTH requests.head and requests.get. The suite is
deliberately offline, and a test that stubs only one of them does not fail
-- it quietly starts making real network calls, which is how the direct
route went untested when it was added.
"""

import json

import pytest

import overlay_layers as ol


@pytest.fixture
def url_cache(tmp_path, monkeypatch):
    """
    Points the URL cache at a scratch file and severs the network.

    requests.head is stubbed to refuse by default so each manifest test
    below exercises the fallback deliberately rather than by accident; a
    test that wants the direct route re-stubs it.
    """
    path = tmp_path / "gdb" / "padus_urls.json"
    monkeypatch.setattr(ol, "_padus_urls_cache", lambda: path)
    monkeypatch.setattr(
        ol.requests, "head",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    return path


class _HeadResponse:
    def __init__(self, status=200, content_type="application/zip"):
        self.status_code = status
        self.ok = 200 <= status < 400
        self.headers = {"Content-Type": content_type}


class _ManifestResponse:
    def __init__(self, files):
        self._files = files

    def raise_for_status(self):
        return None

    def json(self):
        return {"files": self._files}


def _files_for(state):
    name = ol.PADUS_FILE_PATTERN.format(state=state)
    return [{"name": "readme.txt", "url": "https://example/ignore"},
            {"name": name, "url": f"https://example/{state}.zip"}]


def test_a_cached_url_is_returned_without_touching_the_manifest(
        url_cache, monkeypatch):
    url_cache.parent.mkdir(parents=True)
    url_cache.write_text(json.dumps({"VA": "https://example/va.zip"}))

    def no_network(*a, **k):
        raise AssertionError("nothing must be re-asked for a state whose "
                             "URL is already resolved")
    monkeypatch.setattr(ol.requests, "get", no_network)
    monkeypatch.setattr(ol.requests, "head", no_network)

    assert ol._padus_state_url("va") == "https://example/va.zip"


def test_a_successful_resolution_is_persisted(url_cache, monkeypatch):
    monkeypatch.setattr(
        ol.requests, "get",
        lambda *a, **k: _ManifestResponse(_files_for("OH")))

    assert ol._padus_state_url("OH") == "https://example/OH.zip"
    assert json.loads(url_cache.read_text()) == {"OH": "https://example/OH.zip"}


def test_a_manifest_failure_returns_none_and_caches_nothing(
        url_cache, monkeypatch):
    def blocked(*a, **k):
        raise RuntimeError("403 Cloudflare")
    monkeypatch.setattr(ol.requests, "get", blocked)

    assert ol._padus_state_url("WV") is None
    assert not url_cache.exists(), \
        "a failed read must not leave an empty or partial cache behind"


def test_an_absent_state_file_is_not_cached_as_a_failure(
        url_cache, monkeypatch):
    """Absence is not a resolution: the next run may re-ask the manifest."""
    monkeypatch.setattr(
        ol.requests, "get",
        lambda *a, **k: _ManifestResponse([{"name": "readme.txt"}]))

    assert ol._padus_state_url("DE") is None
    assert not url_cache.exists()


# ---------------------------------------------------------------------------
# The direct file route
# ---------------------------------------------------------------------------


def test_the_named_file_url_is_used_before_the_manifest(url_cache, monkeypatch):
    monkeypatch.setattr(ol.requests, "head", lambda *a, **k: _HeadResponse())

    def no_manifest(*a, **k):
        raise AssertionError("the catalog API must not be touched when the "
                             "file endpoint answers — it is the half that "
                             "is challenged")
    monkeypatch.setattr(ol.requests, "get", no_manifest)

    url = ol._padus_state_url("PA")
    assert url.endswith("?name=PADUS4_0_State_PA_GDB.zip")
    assert "/catalog/file/get/" in url
    assert json.loads(url_cache.read_text()) == {"PA": url}


def test_a_non_zip_answer_falls_back_to_the_manifest(url_cache, monkeypatch):
    # A challenge page answers 200 with text/html. Content-Type is what
    # separates "here is your file" from "here is a interstitial".
    monkeypatch.setattr(
        ol.requests, "head",
        lambda *a, **k: _HeadResponse(content_type="text/html;charset=UTF-8"))
    monkeypatch.setattr(
        ol.requests, "get",
        lambda *a, **k: _ManifestResponse(_files_for("OH")))

    assert ol._padus_state_url("OH") == "https://example/OH.zip"


def test_both_routes_failing_returns_none_and_caches_nothing(
        url_cache, monkeypatch):
    monkeypatch.setattr(ol.requests, "head", lambda *a, **k: _HeadResponse(403))

    def blocked(*a, **k):
        raise RuntimeError("403 Cloudflare")
    monkeypatch.setattr(ol.requests, "get", blocked)

    assert ol._padus_state_url("MD") is None
    assert not url_cache.exists()
