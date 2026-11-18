"""Fetch daily OHLC (raw Close, not Adj Close) from yfinance."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
# ~400 calendar days comfortably covers 260+ trading days.
PERIOD = "400d"
FIELDS = ["Open", "High", "Low", "Close"]


def _download(tickers: list[str]) -> pd.DataFrame:
    return yf.download(
        tickers,
        period=PERIOD,
        interval="1d",
        auto_adjust=False,
        actions=False,
        group_by="ticker",
        threads=True,
        progress=False,
    )


def _split(raw: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out
    multi = isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        try:
            df = raw[t] if multi else raw
        except KeyError:
            continue
        df = df[[c for c in FIELDS if c in df.columns]].dropna(subset=["Close"])
        if df.empty:
            continue
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        out[t] = df
    return out


def drop_unfinished_session(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """If run during US trading hours, yfinance returns a partial bar for today. Drop it."""
    now = now or datetime.now(ET)
    if df.empty:
        return df
    last = df.index[-1].date()
    if last == now.date() and (now.hour, now.minute) < (16, 30):
        return df.iloc[:-1]
    return df


def fetch_ohlc(tickers: list[str], retries: int = 2) -> dict[str, pd.DataFrame]:
    """Return {ticker: DataFrame[Open, High, Low, Close]} for tickers that have data.

    Tickers that fail are simply absent from the result (caller marks them "No data").
    Missing tickers get one more individual retry pass.
    """
    data = _split(_download(tickers), tickers)
    missing = [t for t in tickers if t not in data]
    for attempt in range(retries):
        if not missing:
            break
        log.warning("retry %d for %d tickers: %s", attempt + 1, len(missing), " ".join(missing))
        time.sleep(2)
        for t in list(missing):
            try:
                got = _split(_download([t]), [t])
            except Exception as e:  # noqa: BLE001 - never let one ticker kill the run
                log.warning("%s: %s", t, e)
                continue
            if t in got:
                data[t] = got[t]
                missing.remove(t)
    return {t: drop_unfinished_session(df) for t, df in data.items()}


def fetch_condition(symbols: list[str]) -> dict[str, dict[str, pd.DataFrame]]:
    """Daily (3y) + weekly (10y) bars for the "Index condition" panel.

    Uses the newest bar as-is (crypto trades 24/7, HSI closes on HK time), so no
    unfinished-session trimming here. Weekly 200 EMA needs a long warm-up, hence 10y.
    """
    out: dict[str, dict[str, pd.DataFrame]] = {s: {} for s in symbols}
    for key, period, interval in (("daily", "3y", "1d"), ("weekly", "10y", "1wk")):
        try:
            raw = yf.download(symbols, period=period, interval=interval, auto_adjust=False,
                              actions=False, group_by="ticker", threads=True, progress=False)
        except Exception as e:  # noqa: BLE001
            log.warning("index condition %s failed: %s", key, e)
            continue
        for s, df in _split(raw, symbols).items():
            out[s][key] = df
    return out
