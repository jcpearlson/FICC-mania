"""Parsers against payloads shaped like each source's real wire format."""
import pandas as pd
import pytest

from ficc.sources import cftc, ecb, fred, market, mof, nyfed, treasury, treasurydirect


def test_fred_parses_missing_marker_and_drops_forward_dates(fake_net):
    s = fred.get("IORB", "IORB")
    assert s.ok and s.frame.index.max() <= pd.Timestamp.today()
    s = fred.get("DGS10")
    assert s.frame.iloc[:, 0].notna().all()          # "." rows dropped


def test_treasury_curve_is_sorted_and_deduplicated(fake_net):
    y = pd.Timestamp.today().year
    s = treasury.curve([y - 1, y])
    assert s.ok and s.frame.index.is_monotonic_increasing
    assert "10 Yr" in s.frame.columns


def test_mof_skips_banner_row(fake_net):
    s = mof.curve()
    assert s.ok and list(s.frame.columns)[:2] == ["1Y", "2Y"]


def test_nyfed_reference_rate(fake_net):
    s = nyfed.reference_rate("sofr")
    assert s.ok and "percentRate" in s.frame.columns


def test_ecb_curve_pivots_tenors(fake_net):
    s = ecb.curve()
    assert s.ok and {"2Y", "10Y", "30Y"} <= set(s.frame.columns)
    assert ecb.estr().ok


def test_ecb_parse_rejects_unexpected_schema():
    with pytest.raises(ValueError):
        ecb.parse_csv("a,b\n1,2\n")


def test_treasurydirect_excludes_bills_and_uses_competitive_base(fake_net):
    s = treasurydirect.auctions()
    assert s.ok and not (s.frame["type"] == "Bill").any()
    assert s.frame["indirect_pct"].iloc[-1] == pytest.approx(68.0)
    ctx = treasurydirect.with_context(s.frame)
    assert "btc_vs_avg" in ctx.columns


def test_treasurydirect_flags_tips():
    rec = {"auctionDate": "2026-01-02T00:00:00", "securityType": "Note",
           "securityTerm": "10-Year", "tips": "Yes", "bidToCoverRatio": "2.5",
           "competitiveAccepted": "100", "indirectBidderAccepted": "70"}
    f = treasurydirect.parse([rec])
    assert f["type"].iloc[0] == "TIPS"


def test_cftc_net_as_share_of_oi(fake_net):
    s = cftc.positioning("097741", weeks=60)
    assert s.ok and s.frame.index.is_monotonic_increasing
    row = s.frame.iloc[-1]
    assert row["lev_net_pct_oi"] == pytest.approx(row["lev_net"] / row["open_interest"] * 100)


def test_futures_strip_and_basket(fake_net):
    strip = market.futures_strip("SR3", 8, True)
    assert strip.ok and (strip.frame["implied_rate"] == 100 - strip.frame["price"]).all()
    b = market.basket({"GC=F": "Gold", "HG=F": "Copper"}, period="1y")
    assert all(s.ok for s in b.values())
