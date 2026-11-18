"""Validate the Thrust / 1-Mth formulas against the original Google Sheet export."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compute import compute_row, one_month_rs, thrust_rate  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "RS_strength_sectors_-_RS_thrust_Rate.csv"
RS_COLS = 30
TOL = 1.0


def _pct(s: str) -> float:
    return float(s.strip().rstrip("%"))


def load_sheet_rows():
    with open(FIXTURE, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    out = []
    for r in rows[1:]:
        if not r or not r[0].strip() or r[0].strip() == "RSP":
            continue
        try:
            rs = [float(x) for x in r[-RS_COLS:]]
            thrust, month = _pct(r[2]), _pct(r[3])
        except ValueError:
            continue  # blank / incomplete row
        if len(rs) != RS_COLS or any(v == 0 for v in rs):
            continue
        out.append((r[0].strip(), rs, thrust, month))
    return out


SHEET = load_sheet_rows()


def test_fixture_row_count():
    assert len(SHEET) == 170


@pytest.mark.parametrize("ticker,rs,thrust,month", SHEET, ids=[s[0] for s in SHEET])
def test_matches_sheet(ticker, rs, thrust, month):
    assert thrust_rate(rs) == pytest.approx(thrust, abs=TOL)
    assert one_month_rs(rs) == pytest.approx(month, abs=TOL)


@pytest.mark.parametrize(
    "ticker,thrust,month",
    [("XLV", 100.0, 100.0), ("BOAT", 100.0, 30.0), ("TLT", 83.3, 30.0), ("SPY", 16.7, 10.0), ("IGV", 0.0, 0.0)],
)
def test_spot_checks(ticker, thrust, month):
    rs = next(s[1] for s in SHEET if s[0] == ticker)
    assert thrust_rate(rs) == pytest.approx(thrust, abs=0.05)
    assert one_month_rs(rs) == pytest.approx(month, abs=0.05)


def test_strictly_greater_ties_dont_count():
    assert thrust_rate([1, 1, 1, 1, 1, 1, 1]) == 0.0
    assert thrust_rate([1, 2, 1, 1, 1, 1, 1.5]) == pytest.approx(83.3)


def test_not_enough_history():
    assert thrust_rate([1, 2, 3]) is None
    assert one_month_rs(list(range(20))) is None


def test_compute_row_fields():
    idx = pd.bdate_range("2025-01-01", periods=300)
    close = pd.Series([100 + i * 0.1 for i in range(300)], index=idx)
    ohlc = pd.DataFrame({"Open": close - 0.5, "High": close + 1, "Close": close}, index=idx)
    bench = pd.Series(50.0, index=idx)
    r = compute_row(ohlc, bench)
    c0, c1, c21 = close.iloc[-1], close.iloc[-2], close.iloc[-22]
    assert r["thrust"] == 100.0 and r["rs_1m"] == 100.0
    assert r["pct_1d"] == pytest.approx(round((c0 / c1 - 1) * 100, 2))
    assert r["pct_intraday"] == pytest.approx(round((c0 / (c0 - 0.5) - 1) * 100, 2))
    assert r["pct_gap"] == pytest.approx(round(((c0 - 0.5) / c1 - 1) * 100, 2))
    assert r["pct_1m"] == pytest.approx(round((c0 / c21 - 1) * 100, 2))
    assert r["pct_off_high"] == pytest.approx(round((c0 / (c0 + 1) - 1) * 100, 2))
    assert len(r["spark_price"]) == 30 and len(r["spark_rs"]) == 30


# ---------------------------------------------------------------- Index condition
from compute import condition_row, ema_light  # noqa: E402


@pytest.mark.parametrize("price,e21,e50,e200,expected", [
    (110, 100, 100, 100, "green"),   # above 21/50/200
    (95, 100, 90, 80, "yellow"),     # above 50/200, below 21
    (85, 100, 90, 80, "yellow"),     # below 50, above 200
    (85, 100, 80, 90, "yellow"),     # above 50, below 200
    (70, 100, 90, 80, "red"),        # below 50 and 200
])
def test_ema_light(price, e21, e50, e200, expected):
    assert ema_light(price, e21, e50, e200) == expected


@pytest.mark.parametrize("vix,expected", [(12, "red"), (15, None), (22, None), (30, None), (35, "green")])
def test_vix_light(vix, expected):
    idx = pd.bdate_range("2026-01-01", periods=5)
    df = pd.DataFrame({"Open": vix, "High": vix, "Low": vix, "Close": [20, 20, 20, 20, vix]}, index=idx)
    assert condition_row(df, None, is_vix=True)["vix_light"] == expected


def test_condition_row_uptrend_and_atr():
    idx = pd.bdate_range("2023-01-01", periods=600)
    close = pd.Series([100 + i for i in range(600)], index=idx, dtype=float)
    df = pd.DataFrame({"Open": close, "High": close + 0.5, "Low": close - 0.5, "Close": close})
    r = condition_row(df, df)
    assert r["short"]["light"] == "green" and r["long"]["light"] == "green"
    # steady +1/day trend, ATR ~1 -> far above the 50 EMA in ATR terms
    assert r["atr_from_50"] > 8 and r["atr_light"] == "red"


def test_true_range_matches_sheet():
    from compute import true_range
    # rows 2026-10-15 / 10-16 from the user's sheet
    df = pd.DataFrame({"High": [276.26, 278.43], "Low": [260.66, 236.85], "Close": [273.4, 244.37]})
    tr = true_range(df)
    assert tr.iloc[0] == pytest.approx(15.6)
    assert tr.iloc[1] == pytest.approx(41.58)


def test_atr_is_28_day_simple_average():
    from compute import atr
    idx = pd.bdate_range("2026-01-01", periods=40)
    df = pd.DataFrame({"High": 101.0, "Low": 99.0, "Close": 100.0}, index=idx)
    df.iloc[-1, df.columns.get_loc("High")] = 129.0  # last TR = 30, others = 2
    assert atr(df).iloc[-1] == pytest.approx((27 * 2 + 30) / 28)


def test_atr_light_both_directions():
    idx = pd.bdate_range("2023-01-01", periods=600)
    close = pd.Series([1000 - i for i in range(600)], index=idx, dtype=float)
    df = pd.DataFrame({"Open": close, "High": close + 0.5, "Low": close - 0.5, "Close": close})
    r = condition_row(df, df)
    assert r["atr_from_50"] < -8 and r["atr_light"] == "red"


def test_calendar_week_window():
    from datetime import date
    from calendar_fetch import week_window
    assert week_window(date(2026, 11, 18)) == (date(2026, 11, 16), date(2026, 11, 20))  # Wed
    assert week_window(date(2026, 11, 20)) == (date(2026, 11, 16), date(2026, 11, 20))  # Fri
    assert week_window(date(2026, 11, 22)) == (date(2026, 11, 23), date(2026, 11, 27))  # Sun -> next week


# ---------------------------------------------------------------- Stock scanners
from scanner import SCANS, evaluate, passes  # noqa: E402


def _stock(closes, vol=1_000_000, high_pad=0.0):
    idx = pd.bdate_range("2025-06-01", periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c, "High": c + high_pad, "Low": c, "Close": c, "Volume": vol})


def _scan(key):
    return next(s for s in SCANS if s.key == key)


def test_scanner_base_filters():
    assert evaluate(_stock([1.5] * 300, vol=50_000_000)) is None      # price <= $2
    assert evaluate(_stock([20.0] * 300, vol=100_000)) is None        # $2M dollar volume
    assert evaluate(_stock([20.0] * 300, vol=1_000_000)) is not None  # $20M


def test_htf30_gain_from_window_low():
    closes = [10.0] * 270 + [10 + i * 0.2 for i in range(30)]  # 10 -> 15.8 in 30 days
    m = evaluate(_stock(closes))
    assert m["gain30"] == pytest.approx(58.0, abs=0.1)
    assert m["above_ema50"]
    assert passes(_scan("htf30"), m)
    assert not passes(_scan("htf60"), m)  # 58% < 75%


def test_htf_requires_above_ema50():
    closes = [10.0] * 230 + [30.0] * 50 + [18.0] * 20  # low 10 in window, run to 30, fall to 18
    m = evaluate(_stock(closes))
    assert m["gain100"] == pytest.approx(80.0) and not m["above_ema50"]
    assert not passes(_scan("htf100"), m)


def test_52w_high_within_3pct():
    near = evaluate(_stock([50.0] * 299 + [49.0], high_pad=0.0))   # 2% off high
    far = evaluate(_stock([50.0] * 299 + [48.0], high_pad=0.0))    # 4% off high
    assert passes(_scan("high52"), near)
    assert not passes(_scan("high52"), far)


def test_market_cap_filter():
    from scanner import cap_ok
    assert cap_ok({"market_cap": 600e6})
    assert not cap_ok({"market_cap": 400e6})
    assert not cap_ok({"market_cap": None})   # Yahoo has no market cap -> drop
    assert cap_ok(None)                        # lookup failed -> keep


def test_sector_map():
    from scanner import load_sector_map, map_etfs
    rules = load_sector_map()
    assert map_etfs("Technology", "Semiconductors", rules)[:4] == ["XLK", "VGT", "IXN", "RSPT"]
    assert {"SMH", "SOXX", "XSD"} <= set(map_etfs("Technology", "Semiconductors", rules))
    assert {"XLV", "XBI", "IBB"} <= set(map_etfs("Healthcare", "Biotechnology", rules))
    assert "KIE" in map_etfs("Financial Services", "Insurance - Property & Casualty", rules)
    assert map_etfs(None, None, rules) == []


def test_sector_map_etfs_exist_in_tickers():
    import csv as _csv
    from scanner import load_sector_map
    tickers = {r["ticker"] for r in _csv.DictReader(open(ROOT / "config" / "tickers.csv", encoding="utf-8"))}
    missing = {e for _, _, etfs in load_sector_map() for e in etfs} - tickers
    assert not missing, missing


def test_scanner_sorted_by_dollar_volume(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, "fetch_meta", lambda syms: {s: {"market_cap": 1e9} for s in syms})
    closes = [50.0] * 300
    data = {"LOW": _stock(closes, vol=300_000), "HIGH": _stock(closes, vol=2_000_000), "MID": _stock(closes, vol=1_000_000)}
    as_of = data["LOW"].index[-1].date().isoformat()
    res = scanner.run_scans({k: k for k in data}, data, as_of)
    high52 = next(s for s in res["scans"] if s["key"] == "high52")
    assert [i["symbol"] for i in high52["items"]] == ["HIGH", "MID", "LOW"]
