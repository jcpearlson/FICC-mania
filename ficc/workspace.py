"""Local watchlist preferences, stored separately from market data caches."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

WATCHLIST_PATH = Path(__file__).resolve().parent.parent / ".local" / "watchlist.json"
VIEWS = ("All instruments", "My watchlist")
MAX_LABELS = 500
MAX_LABEL_LENGTH = 200
MAX_FILE_BYTES = 1024 * 1024


class WatchlistError(ValueError):
    """Preferences could not be read, validated, or saved."""


def _labels(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_LABELS:
        raise WatchlistError(f"Watchlist must contain at most {MAX_LABELS} instrument labels.")
    if any(
        not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL_LENGTH
        for label in value
    ):
        raise WatchlistError(
            f"Instrument labels must be nonempty strings of at most {MAX_LABEL_LENGTH} characters."
        )
    return tuple(dict.fromkeys(value))


@dataclass(frozen=True)
class Watchlist:
    labels: tuple[str, ...] = ()
    default_view: str = VIEWS[0]

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", _labels(self.labels))
        if self.default_view not in VIEWS:
            raise WatchlistError(f"Default view must be one of: {', '.join(VIEWS)}.")


def load_watchlist(path: Path | None = None) -> Watchlist:
    """Return saved preferences or defaults when no file exists.

    Invalid files are left untouched so a failed read cannot discard preferences.
    """
    target = WATCHLIST_PATH if path is None else Path(path)
    try:
        with target.open("rb") as file:
            raw = file.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return Watchlist()
    except OSError as exc:
        raise WatchlistError(f"Could not read watchlist at {target}: {exc}") from exc

    if len(raw) > MAX_FILE_BYTES:
        raise WatchlistError(f"Watchlist at {target} exceeds {MAX_FILE_BYTES} bytes.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise WatchlistError(f"Watchlist at {target} is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise WatchlistError(f"Watchlist at {target} must contain a JSON object.")
    if type(payload.get("version")) is not int or payload["version"] != 1:
        raise WatchlistError(f"Watchlist at {target} has an unsupported version.")
    if "labels" not in payload or "default_view" not in payload:
        raise WatchlistError(f"Watchlist at {target} is missing labels or default_view.")
    return Watchlist(labels=payload["labels"], default_view=payload["default_view"])


def save_watchlist(watchlist: Watchlist, path: Path | None = None) -> None:
    """Atomically replace preferences only after writing a complete valid file."""
    target = WATCHLIST_PATH if path is None else Path(path)
    payload = {
        "version": 1,
        "labels": list(watchlist.labels),
        "default_view": watchlist.default_view,
    }
    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=".watchlist-",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(target)
    except OSError as exc:
        raise WatchlistError(f"Could not save watchlist at {target}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
