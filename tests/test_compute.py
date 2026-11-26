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


def test_scanner_atr_from_ema50_matches_index_condition():
    from compute import condition_row
    idx = pd.bdate_range("2025-01-01", periods=300)
    close = pd.Series([50 + i * 0.3 + (i % 5) for i in range(300)], index=idx, dtype=float)
    df = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1_000_000})
    m = evaluate(df)
    assert m["atr50"] == pytest.approx(condition_row(df, None)["atr_from_50"], abs=0.01)


def test_scanner_quotes_for_watchlists(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, "fetch_meta", lambda syms: {s: {"market_cap": 1e9} for s in syms})
    data = {"AAA": _stock([50.0] * 300), "TINY": _stock([50.0] * 300, vol=10)}
    as_of = data["AAA"].index[-1].date().isoformat()
    res = scanner.run_scans({"AAA": "Alpha", "TINY": "Tiny"}, data, as_of)
    assert set(res["quotes"]) == {"AAA"}            # only liquid stocks
    name, close, pct_1d, atr50, thrust, rs_1m = res["quotes"]["AAA"]
    assert (name, close, pct_1d) == ("Alpha", 50.0, 0.0)


def test_stock_rs_vs_rsp():
    from scanner import stock_rs
    idx = pd.bdate_range("2025-01-01", periods=60)
    bench = pd.Series(100.0, index=idx)
    up = pd.Series([10 + i for i in range(60)], index=idx, dtype=float)
    assert stock_rs(up, bench) == (100.0, 100.0)
    # flat, with one lower day 3 days ago -> ties do not count
    flat = pd.Series(10.0, index=idx); flat.iloc[-4] = 9.0
    assert stock_rs(flat, bench) == (16.7, 5.0)  # 1 of 6 / 1 of 20
    assert stock_rs(up, None) == (None, None)


@pytest.mark.parametrize("price,e9,e21,e50,e200,expected", [
    (95, 90, 90, 90, 100, "orange"),   # below 200, above 9/21/50 -> rebound below 200 EMA
    (95, 96, 90, 90, 100, "yellow"),   # below 9 -> not orange
    (95, 90, 90, 96, 100, "red"),      # below 50 and 200
    (105, 90, 90, 90, 100, "green"),   # above everything
])
def test_orange_rebound_below_200(price, e9, e21, e50, e200, expected):
    assert ema_light(price, e21, e50, e200, e9) == expected


def test_condition_row_orange_daily_and_weekly():
    idx = pd.bdate_range("2023-01-01", periods=600)
    # long decline, then a sharp 20-day bounce that clears 9/21/50 but not 200
    closes = [300 - i * 0.4 for i in range(575)] + [70 + i * 0.8 for i in range(1, 26)]
    close = pd.Series(closes, index=idx, dtype=float)
    df = pd.DataFrame({"Open": close, "High": close + 0.5, "Low": close - 0.5, "Close": close})
    r = condition_row(df, df)
    t = r["short"]
    assert t["ema9"] < r["price"] < t["ema200"] and r["price"] > t["ema50"]
    assert t["light"] == "orange" and r["long"]["light"] == "orange"


def test_scanner_new_flag(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, "fetch_meta", lambda syms: {x: {"market_cap": 1e9} for x in syms})
    old = _stock([50.0] * 300)                       # at its 52W high for weeks -> seen last week
    fresh = _stock([50.0] * 100 + [40.0] * 199 + [50.0])  # back at the 52W high today only -> NEW
    gone = _stock([50.0] * 290 + [40.0] * 9 + [50.0])      # last at the high 10 days ago -> NEW again
    data = {"OLD": old, "FRESH": fresh, "BACK": gone}
    as_of = old.index[-1].date().isoformat()
    res = scanner.run_scans({k: k for k in data}, data, as_of)
    high52 = next(x for x in res["scans"] if x["key"] == "high52")
    flags = {i["symbol"]: i["new"] for i in high52["items"]}
    assert flags == {"OLD": False, "FRESH": True, "BACK": True}
    assert high52["new"] == 2


# ---------------------------------------------------------------- Yahoo empty-Close repair
def _daily_with_empty_close():
    idx = pd.bdate_range("2026-11-16", periods=4)  # Mon..Thu, Thu Close missing
    return pd.DataFrame({"Open": [10, 11, 12, 12.5], "High": [11, 12, 13, 13.0],
                         "Low": [9, 10, 11, 11.0], "Close": [10.5, 11.5, 12.5, float("nan")]}, index=idx)


def test_split_keeps_last_bar_without_close():
    from fetch import _split, needs_close
    raw = _daily_with_empty_close()
    df = _split(raw, ["X"])["X"]
    assert len(df) == 4 and needs_close(df)


def test_apply_intraday_close_uses_last_hour_of_that_day():
    from fetch import apply_intraday_close
    hrs = pd.DatetimeIndex(["2026-11-19 14:30", "2026-11-19 19:30", "2026-11-19 20:30"], tz="UTC")
    intra = pd.DataFrame({"Close": [12.0, 12.2, 11.69]}, index=hrs)
    out = apply_intraday_close(_daily_with_empty_close(), intra)
    assert out["Close"].iloc[-1] == pytest.approx(11.69)


def test_apply_intraday_close_clamps_and_drops():
    from fetch import apply_intraday_close
    hrs = pd.DatetimeIndex(["2026-11-19 20:30"], tz="UTC")
    out = apply_intraday_close(_daily_with_empty_close(), pd.DataFrame({"Close": [99.0]}, index=hrs))
    assert out["Close"].iloc[-1] == 13.0                       # clamped to the bar's High
    other_day = pd.DataFrame({"Close": [12.0]}, index=pd.DatetimeIndex(["2026-11-18 20:30"], tz="UTC"))
    assert len(apply_intraday_close(_daily_with_empty_close(), other_day)) == 3   # can't fill -> drop bar
    assert len(apply_intraday_close(_daily_with_empty_close(), None)) == 3


def test_split_ignores_empty_rows_from_other_tickers():
    from fetch import _split, needs_close
    raw = _daily_with_empty_close()
    raw.loc[pd.Timestamp("2026-11-20")] = [float("nan")] * 4   # e.g. a crypto-only date
    df = _split(raw, ["X"])["X"]
    assert df.index[-1] == pd.Timestamp("2026-11-19") and needs_close(df)


def test_info_empty_answer_is_a_failed_lookup(monkeypatch):
    import scanner
    class T:
        def __init__(self, sym): self.info = {"trailingPegRatio": None}   # what Yahoo returns on "Invalid Crumb"
    monkeypatch.setattr(scanner.yf, "Ticker", T)
    monkeypatch.setattr(scanner.time, "sleep", lambda s: None)
    sym, meta = scanner._info("ABC")
    assert meta is None and scanner.cap_ok(meta)       # kept, not dropped as "no market cap"


def test_meta_cache_fills_failed_lookups_and_rescales_cap():
    from scanner import merge_meta, cap_ok
    cache = {"OLD": {"market_cap": 1e9, "sector": "Technology", "industry": "Semiconductors",
                     "close": 50.0, "date": "2026-11-18"}}
    meta = {"OLD": None, "NEW": {"market_cap": 2e9, "sector": "Energy", "industry": "Oil & Gas E&P"},
            "GONE": None}
    n = merge_meta(meta, cache, {"OLD": 25.0, "NEW": 10.0, "GONE": 5.0}, "2026-11-19")
    assert n == 1
    assert meta["OLD"]["market_cap"] == pytest.approx(5e8) and meta["OLD"]["sector"] == "Technology"
    assert meta["OLD"]["cached"] == "2026-11-18"
    assert cache["NEW"]["close"] == 10.0 and cache["NEW"]["date"] == "2026-11-19"   # fresh lookup stored
    assert meta["GONE"] is None and cap_ok(meta["GONE"])                            # unknown -> kept


# ---------------------------------------------------------------- missing daily bars (^HSI)
def test_fill_missing_days_rebuilds_gap_from_60m():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from fetch import fill_missing_days
    hk = ZoneInfo("Asia/Hong_Kong")
    daily = pd.DataFrame({"Open": [100.0, 101.0], "High": [102.0, 103.0], "Low": [99.0, 100.0],
                          "Close": [101.0, 102.0]}, index=pd.to_datetime(["2026-11-23", "2026-11-24"]))
    # 60m bars in UTC: 11-25 HK session (missing from daily) + 11-26 (today, unfinished)
    utc = pd.DatetimeIndex(["2026-11-25 01:30", "2026-11-25 05:00", "2026-11-25 07:00", "2026-11-26 01:30"], tz="UTC")
    intra = pd.DataFrame({"Open": [102.0, 101.0, 100.5, 99.0], "High": [102.5, 101.5, 101.0, 99.5],
                          "Low": [101.0, 100.0, 99.8, 98.5], "Close": [101.2, 100.6, 100.1, 99.2]}, index=utc)
    out = fill_missing_days(daily, intra, hk, now=datetime(2026, 11, 26, 9, 0, tzinfo=hk))
    assert list(out.index.date.astype(str)) == ["2026-11-23", "2026-11-24", "2026-11-25"]   # today not added
    assert out.loc["2026-11-25"].tolist() == [102.0, 102.5, 99.8, 100.1]


def test_sync_week_close_uses_newest_daily():
    from fetch import sync_week_close
    weekly = pd.DataFrame({"Open": [100.0], "High": [103.0], "Low": [99.0], "Close": [102.0]},
                          index=pd.to_datetime(["2026-11-23"]))
    daily = pd.DataFrame({"Open": [100.0, 101.0, 102.0], "High": [102.0, 103.0, 102.5],
                          "Low": [99.0, 100.0, 98.0], "Close": [101.0, 102.0, 100.1]},
                         index=pd.to_datetime(["2026-11-23", "2026-11-24", "2026-11-25"]))
    out = sync_week_close(weekly, daily)
    assert out["Close"].iloc[-1] == 100.1 and out["Low"].iloc[-1] == 98.0 and out["High"].iloc[-1] == 103.0


def test_fill_missing_days_skips_futures_and_weekends():
    from datetime import datetime
    from fetch import ET, fill_missing_days
    daily = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0]},
                         index=pd.to_datetime(["2026-11-20"]))
    sunday = pd.DataFrame({"Open": [2.0], "High": [2.0], "Low": [2.0], "Close": [2.0]},
                          index=pd.DatetimeIndex(["2026-11-22 23:00"], tz="UTC"))   # Sun 18:00 ET
    now = datetime(2026, 11, 24, 9, 0, tzinfo=ET)
    assert len(fill_missing_days(daily, sunday, ET, now=now, symbol="GC=F")) == 1
    assert len(fill_missing_days(daily, sunday, ET, now=now, symbol="^DJI")) == 1
