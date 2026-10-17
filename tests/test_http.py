"""HTTP retries and provider isolation without network access."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
import requests

from ficc import http


@pytest.fixture(autouse=True)
def isolated_http(monkeypatch):
    monkeypatch.setattr(http, "_sessions", {})
    monkeypatch.setattr(http, "_source_locks", {})
    monkeypatch.setattr(http, "_last_call", {})
    monkeypatch.setattr(http, "_PROFILES", http._PROFILES.copy())
    monkeypatch.setattr(http.time, "sleep", lambda _: None)


def response(status):
    result = requests.Response()
    result.status_code = status
    result._content = b""
    result.raw = Mock()
    return result


@pytest.mark.parametrize(
    "failure", [429, 500, 503, requests.Timeout("timeout"), requests.ConnectionError("offline")]
)
def test_transient_failures_retry_once(monkeypatch, failure):
    first = response(failure) if isinstance(failure, int) else failure
    good = response(200)
    client = Mock()
    client.get.side_effect = [first, good]
    monkeypatch.setattr(http, "session", lambda _: client)
    assert http.get("fred", "https://example.test") is good
    assert client.get.call_count == 2


@pytest.mark.parametrize("status,attempts", [(404, 1), (429, 2), (503, 2)])
def test_http_errors_are_not_swallowed(monkeypatch, status, attempts):
    client = Mock()
    client.get.side_effect = [response(status) for _ in range(attempts)]
    monkeypatch.setattr(http, "session", lambda _: client)
    with pytest.raises(requests.HTTPError):
        http.get("fred", "https://example.test")
    assert client.get.call_count == attempts


def test_same_provider_is_serialized_while_other_provider_can_progress(monkeypatch):
    entered, release, second_entered = Event(), Event(), Event()

    def download(url, **kwargs):
        if url.endswith("first"):
            entered.set()
            assert release.wait(5)
        else:
            second_entered.set()
        return response(200)

    slow, independent = Mock(), Mock()
    slow.get.side_effect = download
    independent.get.return_value = response(200)
    monkeypatch.setattr(http, "session", lambda source: slow if source == "fred" else independent)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(http.get, "fred", "https://example.test/first")
        try:
            assert entered.wait(5)
            second = pool.submit(http.get, "fred", "https://example.test/second")
            other = pool.submit(http.get, "nyfed", "https://example.test/other")
            assert other.result(timeout=5).status_code == 200
            assert not second_entered.is_set()
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
        assert second.result(timeout=5).status_code == 200


@pytest.mark.parametrize("payload", ["[]", "null", '{"fred": {"Cookie": 3}}', "{invalid"])
def test_invalid_header_overrides_preserve_defaults(tmp_path, payload):
    path = tmp_path / "headers.json"
    path.write_text(payload)
    before = http._PROFILES.copy()
    http._load_overrides(path)
    assert http._PROFILES == before


def test_provider_sessions_use_separate_headers():
    fred, treasury = http.session("fred"), http.session("treasury")
    assert fred is not treasury
    assert "User-Agent" not in fred.headers
    assert treasury.headers["User-Agent"] == http.CHROME_UA


def test_requests_are_spaced_by_the_provider_interval(monkeypatch):
    client = Mock()
    client.get.return_value = response(200)
    monkeypatch.setattr(http, "session", lambda _: client)
    times = iter([0.0, 0.1, 0.35])
    waits = []
    monkeypatch.setattr(http.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(http.time, "sleep", waits.append)
    http.get("fred", "https://example.test")
    http.get("fred", "https://example.test")
    assert waits == pytest.approx([0.25])
