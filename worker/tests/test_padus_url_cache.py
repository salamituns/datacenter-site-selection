"""
The PAD-US URL cache: the manifest is asked at most once per state, ever.

ScienceBase's release manifest has started answering datacenter IPs with a
Cloudflare 403. The download URLs are stable for the life of the release,
so a resolved URL is persisted beside the geodatabase cache and the
manifest is never re-asked for that state. The failure path must stay
honest: nothing cached, the gate reads UNKNOWN.
"""

import json

import pytest

import overlay_layers as ol


@pytest.fixture
def url_cache(tmp_path, monkeypatch):
    """Points the URL cache at a scratch file; the real one is untouched."""
    path = tmp_path / "gdb" / "padus_urls.json"
    monkeypatch.setattr(ol, "_padus_urls_cache", lambda: path)
    return path


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
        raise AssertionError("the manifest must not be re-asked for a "
                             "state whose URL is already resolved")
    monkeypatch.setattr(ol.requests, "get", no_network)

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
