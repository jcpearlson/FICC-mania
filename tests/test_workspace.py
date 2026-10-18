import json
from pathlib import Path

import pytest

from ficc import workspace
from ficc.workspace import Watchlist, WatchlistError, load_watchlist, save_watchlist


def test_missing_file_uses_defaults_without_writing(tmp_path):
    path = tmp_path / "preferences" / "watchlist.json"
    assert load_watchlist(path) == Watchlist()
    assert not path.exists()


def test_roundtrip_preserves_order_and_unknown_instruments(tmp_path):
    path = tmp_path / "preferences" / "watchlist.json"
    saved = Watchlist(("HY OAS", "Unavailable instrument", "UST 2Y", "HY OAS"), "My watchlist")
    save_watchlist(saved, path)
    assert load_watchlist(path) == saved
    assert saved.labels == ("HY OAS", "Unavailable instrument", "UST 2Y")
    assert json.loads(path.read_text())["version"] == 1


@pytest.mark.parametrize("content", [b"{broken", b"\xff", b"[]", b"null"])
def test_malformed_file_is_reported_and_preserved(tmp_path, content):
    path = tmp_path / "watchlist.json"
    path.write_bytes(content)
    with pytest.raises(WatchlistError):
        load_watchlist(path)
    assert path.read_bytes() == content


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 2, "labels": [], "default_view": "All instruments"},
        {"version": True, "labels": [], "default_view": "All instruments"},
        {"version": 1, "labels": []},
        {"version": 1, "labels": "HY OAS", "default_view": "All instruments"},
        {"version": 1, "labels": [""], "default_view": "All instruments"},
        {"version": 1, "labels": [1], "default_view": "All instruments"},
        {"version": 1, "labels": [], "default_view": "Other view"},
    ],
)
def test_invalid_schema_is_reported(tmp_path, payload):
    path = tmp_path / "watchlist.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(WatchlistError):
        load_watchlist(path)


@pytest.mark.parametrize(
    "labels",
    [(" ",), ("x" * (workspace.MAX_LABEL_LENGTH + 1),), ("x",) * (workspace.MAX_LABELS + 1)],
)
def test_label_validation_is_bounded(labels):
    with pytest.raises(WatchlistError):
        Watchlist(labels)


def test_oversized_file_is_reported(tmp_path):
    path = tmp_path / "watchlist.json"
    path.write_bytes(b" " * (workspace.MAX_FILE_BYTES + 1))
    with pytest.raises(WatchlistError, match="exceeds"):
        load_watchlist(path)


@pytest.mark.parametrize("failure_point", ["write", "replace"])
def test_interrupted_save_keeps_previous_preferences(tmp_path, monkeypatch, failure_point):
    path = tmp_path / "watchlist.json"
    saved = Watchlist(("HY OAS",), "My watchlist")
    save_watchlist(saved, path)
    before = path.read_bytes()

    if failure_point == "write":

        def fail_write(payload, file, **kwargs):
            file.write("partial JSON")
            raise OSError("disk full")

        monkeypatch.setattr(workspace.json, "dump", fail_write)
    else:

        def fail_replace(self, target):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(WatchlistError, match="Could not save"):
        save_watchlist(Watchlist(("UST 2Y",)), path)
    assert path.read_bytes() == before
    assert load_watchlist(path) == saved
    assert not list(tmp_path.glob("*.tmp"))


def test_read_error_is_reported(tmp_path):
    with pytest.raises(WatchlistError, match="Could not read"):
        load_watchlist(tmp_path)
