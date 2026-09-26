import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


@pytest.fixture
def fake_net(monkeypatch, tmp_path):
    """Route every source through tests/fakenet.py and isolate the disk cache."""
    import fakenet
    import yfinance

    from ficc import cache, http

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(http, "get", fakenet.fake_get)
    monkeypatch.setattr(yfinance, "download", fakenet.fake_download)
    return fakenet
