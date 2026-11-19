"""RS / Thrust / other column calculations.

RS(t)            = P(t) / B(t)
RS Thrust Rate % = 100 * count{k=1..6  : RS(0) > RS(-k)} / 6
1-Mth RS %       = 100 * count{k=1..20 : RS(0) > RS(-k)} / 20
"""
from __future__ import annotations

import math
from typing import Sequence

import pandas as pd

THRUST_LOOKBACK = 6
MONTH_LOOKBACK = 20
SPARK_DAYS = 30
HIGH_52W_DAYS = 252
PCT_1M_DAYS = 21


def rs_rank_pct(rs: Sequence[float], lookback: int) -> float | None:
    """% of the previous `lookback` days whose RS is strictly below today's.

    `rs` is ordered oldest -> newest; the last element is RS(0).
    Returns None if there isn't enough (valid) history.
    """
    vals = list(rs)
    if len(vals) < lookback + 1:
        return None
    window = vals[-(lookback + 1):]
    if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in window):
        return None
    today = window[-1]
    wins = sum(1 for prev in window[:-1] if today > prev)
    return round(100.0 * wins / lookback, 1)


def thrust_rate(rs: Sequence[float]) -> float | None:
    return rs_rank_pct(rs, THRUST_LOOKBACK)


def one_month_rs(rs: Sequence[float]) -> float | None:
    return rs_rank_pct(rs, MONTH_LOOKBACK)


def _pct(a: float, b: float) -> float | None:
    if a is None or b is None or b == 0 or pd.isna(a) or pd.isna(b):
        return None
    return round((a / b - 1.0) * 100.0, 2)


def _clean(seq) -> list[float]:
    return [round(float(x), 6) for x in seq]


def compute_row(ohlc: pd.DataFrame, bench_close: pd.Series) -> dict:
    """Compute all dashboard columns for one ETF.

    ohlc: DataFrame indexed by date with columns Open, High, Close (raw, not adjusted).
    bench_close: RSP Close series indexed by date.
    Both must already end on the same (latest) trading day.
    """
    df = ohlc[["Open", "High", "Close"]].dropna(subset=["Close"])
    joined = df.join(bench_close.rename("Bench"), how="inner").dropna(subset=["Close", "Bench"])
    if len(joined) < MONTH_LOOKBACK + 1:
        raise ValueError(f"not enough history ({len(joined)} rows)")

    rs = (joined["Close"] / joined["Bench"]).tolist()
    close = joined["Close"]
    c0, c1 = close.iloc[-1], close.iloc[-2]
    o0 = joined["Open"].iloc[-1]
    c21 = close.iloc[-1 - PCT_1M_DAYS] if len(close) > PCT_1M_DAYS else None
    high_52w = joined["High"].iloc[-HIGH_52W_DAYS:].max()
    # A day with missing High (rare yfinance gap) shouldn't hide a higher close.
    high_52w = max(high_52w, close.iloc[-HIGH_52W_DAYS:].max())

    return {
        "close": round(float(c0), 4),
        "rs": round(float(rs[-1]), 6),
        "thrust": thrust_rate(rs),
        "rs_1m": one_month_rs(rs),
        "pct_intraday": _pct(c0, o0),
        "pct_1d": _pct(c0, c1),
        "pct_gap": _pct(o0, c1),
        "pct_1m": _pct(c0, c21),
        "pct_off_high": _pct(c0, high_52w),
        "spark_price": _clean(close.iloc[-SPARK_DAYS:]),
        "spark_rs": _clean(rs[-SPARK_DAYS:]),
    }


def compute_benchmark_row(ohlc: pd.DataFrame) -> dict:
    df = ohlc[["Open", "High", "Close"]].dropna(subset=["Close"])
    close = df["Close"]
    c0, c1 = close.iloc[-1], close.iloc[-2]
    o0 = df["Open"].iloc[-1]
    c21 = close.iloc[-1 - PCT_1M_DAYS] if len(close) > PCT_1M_DAYS else None
    high_52w = max(df["High"].iloc[-HIGH_52W_DAYS:].max(), close.iloc[-HIGH_52W_DAYS:].max())
    return {
        "close": round(float(c0), 4),
        "rs": 1.0,
        "thrust": None,
        "rs_1m": None,
        "pct_intraday": _pct(c0, o0),
        "pct_1d": _pct(c0, c1),
        "pct_gap": _pct(o0, c1),
        "pct_1m": _pct(c0, c21),
        "pct_off_high": _pct(c0, high_52w),
        "spark_price": _clean(close.iloc[-SPARK_DAYS:]),
        "spark_rs": [],
    }


def summarize(rows: list[dict]) -> dict:
    scored = [r["thrust"] for r in rows if r.get("status") == "ok" and r.get("thrust") is not None]
    n = len(scored)
    return {
        "count": n,
        "thrust_100": sum(1 for t in scored if t >= 100.0),
        "thrust_ge_66": sum(1 for t in scored if t >= 66.7),
        "thrust_0": sum(1 for t in scored if t == 0.0),
        "avg_thrust": round(sum(scored) / n, 1) if n else None,
    }


# ---------------------------------------------------------------- Index condition
ATR_PERIOD = 28
ATR_YELLOW, ATR_RED = 4.0, 8.0
VIX_RED_BELOW, VIX_GREEN_ABOVE = 15.0, 30.0


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """ATR = simple average of True Range over `period` days.

    TR = MAX(High - Low, |High - prev Close|, |Low - prev Close|)
    """
    return true_range(df).rolling(period).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["Close"].shift(1)
    return pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()],
                     axis=1).max(axis=1)


def ema_light(price: float, e21: float, e50: float, e200: float, e9: float | None = None) -> str:
    """green : above 21/50/200
    orange: "Rebound below 200 EMA" - below 200 but above 9/21/50
    red   : below 50 and 200
    yellow: everything else"""
    if price > e21 and price > e50 and price > e200:
        return "green"
    if price < e50 and price < e200:
        return "red"
    if e9 is not None and price < e200 and price > e9 and price > e21 and price > e50:
        return "orange"
    return "yellow"


def _trend(df: pd.DataFrame | None) -> dict | None:
    if df is None or len(df) < 200:
        return None
    c = df["Close"]
    p, e9, e21, e50, e200 = (c.iloc[-1], ema(c, 9).iloc[-1], ema(c, 21).iloc[-1],
                             ema(c, 50).iloc[-1], ema(c, 200).iloc[-1])
    return {"light": ema_light(p, e21, e50, e200, e9),
            "ema9": round(float(e9), 2), "ema21": round(float(e21), 2), "ema50": round(float(e50), 2), "ema200": round(float(e200), 2)}


def condition_row(daily: pd.DataFrame | None, weekly: pd.DataFrame | None, is_vix: bool = False) -> dict:
    out: dict = {"price": None, "change": None, "pct": None, "date": None}
    if daily is None or len(daily) < 2:
        return out
    last, prev = float(daily["Close"].iloc[-1]), float(daily["Close"].iloc[-2])
    out.update(price=round(last, 2), change=round(last - prev, 2),
               pct=round((last / prev - 1) * 100, 2) if prev else None,
               date=daily.index[-1].date().isoformat())
    if is_vix:
        out["vix_light"] = "red" if last < VIX_RED_BELOW else "green" if last > VIX_GREEN_ABOVE else None
        return out
    out["short"] = _trend(daily)
    out["long"] = _trend(weekly)
    if len(daily) > max(50, ATR_PERIOD):
        a = atr(daily).iloc[-1]
        e50 = ema(daily["Close"], 50).iloc[-1]
        if a and not pd.isna(a):
            mult = (last - e50) / a
            out["atr_from_50"] = round(float(mult), 2)
            # (close - 50 EMA) / ATR(28): how many ATRs price is stretched from the 50 EMA (either side)
            out["atr_light"] = "red" if abs(mult) > ATR_RED else "yellow" if abs(mult) > ATR_YELLOW else None
    return out
