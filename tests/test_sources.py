"""Parsers against payloads shaped like each source's real wire format."""

import pandas as pd
import pytest

from ficc.sources import cftc, ecb, fred, market, mof, nyfed, treasury, treasurydirect


def test_fred_parses_missing_marker_and_drops_forward_dates(fake_net):
    s = fred.get("IORB", "IORB")
    assert s.ok and s.frame.index.max() <= pd.Timestamp.today()
    s = fred.get("DGS10")
    assert s.frame.iloc[:, 0].notna().all()  # "." rows dropped


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
    rec = {
        "auctionDate": "2026-01-02T00:00:00",
        "securityType": "Note",
        "securityTerm": "10-Year",
        "tips": "Yes",
        "bidToCoverRatio": "2.5",
        "competitiveAccepted": "100",
        "indirectBidderAccepted": "70",
    }
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


def test_mof_current_file_wins_over_historical_overlap(fake_net, monkeypatch):
    dates = pd.to_datetime(["2026-01-05", "2026-01-06"])
    monkeypatch.setattr(
        mof,
        "_download",
        lambda url: pd.DataFrame(
            {"10Y": [2.0, 3.0] if url == mof.CURRENT else [1.0, 1.0]}, index=dates
        ),
    )
    result = mof.curve()
    assert result.ok
    assert list(result.frame["10Y"]) == [2.0, 3.0]


def test_nyfed_converts_numeric_strings(fake_net, monkeypatch):
    monkeypatch.setattr(
        nyfed,
        "_json",
        lambda _: {
            "refRates": [
                {"effectiveDate": "2026-01-05", "percentRate": "4.25", "volumeInBillions": "2000"}
            ]
        },
    )
    result = nyfed.reference_rate()
    assert result.ok
    assert result.latest("percentRate") == 4.25
    assert result.change(column="percentRate") is None


def test_auction_shares_require_a_competitive_award():
    records = [
        {
            "auctionDate": "2026-01-05",
            "securityType": "Note",
            "securityTerm": "10-Year",
            "bidToCoverRatio": "2.5",
            "competitiveAccepted": "0",
            "totalAccepted": "100",
            "indirectBidderAccepted": "70",
        }
    ]
    frame = treasurydirect.parse(records)
    assert pd.isna(frame["indirect_pct"].iloc[0])


def test_cftc_zero_open_interest_is_unusable():
    frame = cftc.parse(
        [
            {
                "report_date_as_yyyy_mm_dd": "2026-01-06",
                "open_interest_all": "0",
                "lev_money_positions_long": "10",
                "lev_money_positions_short": "5",
            }
        ]
    )
    assert frame.empty


def test_curve_shape_uses_delivery_months_instead_of_row_count():
    frame = pd.DataFrame(
        {"price": [110.0, 100.0]}, index=pd.to_datetime(["2026-01-01", "2026-07-01"])
    )
    assert market.curve_shape(frame) == pytest.approx(20.0)


def test_futures_strip_stops_at_missing_contract(fake_net, monkeypatch):
    import yfinance

    def missing_contract(*args, **kwargs):
        frame = fake_net.fake_download(*args, **kwargs)
        symbol = args[0][1]
        frame[("Close", symbol)] = float("nan")
        return frame

    monkeypatch.setattr(yfinance, "download", missing_contract)
    strip = market.futures_strip("SR3", 4)
    assert strip.ok and len(strip.frame) == 1
