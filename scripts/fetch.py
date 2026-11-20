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
INTRADAY_CHUNK = 250


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


def _split(raw: pd.DataFrame, tickers: list[str], fields: list[str] = FIELDS) -> dict[str, pd.DataFrame]:
    """Per-ticker frames. A last bar with High/Low but no Close (Yahoo sometimes leaves the
    newest daily Close empty for hours) is kept and repaired by `patch_missing_closes`."""
    out: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out
    multi = isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        try:
            df = raw[t] if multi else raw
        except KeyError:
            continue
        df = df[[c for c in fields if c in df.columns]]
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        # empty rows come from other tickers' dates (e.g. crypto trades on days stocks don't)
        df = df.dropna(how="all", subset=[c for c in ("Open", "High", "Low", "Close") if c in df.columns])
        partial = df["Close"].isna() & df["High"].notna()
        keep = df["Close"].notna() | (partial & (df.index == df.index[-1]) if len(df) else partial)
        df = df[keep]
        if df["Close"].notna().any():
            out[t] = df
    return out


def needs_close(df: pd.DataFrame) -> bool:
    return len(df) > 0 and pd.isna(df["Close"].iloc[-1]) and pd.notna(df["High"].iloc[-1])


def apply_intraday_close(daily: pd.DataFrame, intraday: pd.DataFrame | None) -> pd.DataFrame:
    """Fill a missing Close on the last daily bar with that day's last intraday close
    (New York date), kept inside the bar's Low..High. Drops the bar if it can't be filled."""
    if not needs_close(daily):
        return daily
    day = daily.index[-1].date()
    close = None
    if intraday is not None and not intraday.empty:
        idx = pd.to_datetime(intraday.index)
        idx = idx.tz_convert(ET) if idx.tz is not None else idx
        c = intraday["Close"][[d.date() == day for d in idx]].dropna()
        if len(c):
            close = float(c.iloc[-1])
    out = daily.copy()
    if close is None:
        return out.iloc[:-1]
    lo, hi = out["Low"].iloc[-1], out["High"].iloc[-1]
    if pd.notna(lo) and pd.notna(hi):
        close = min(max(close, float(lo)), float(hi))
    out.iloc[-1, out.columns.get_loc("Close")] = close
    return out


def patch_missing_closes(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Repair empty last-bar Closes from 60-minute bars (batched); drop the bar if impossible."""
    todo = [t for t, df in frames.items() if needs_close(df)]
    if todo:
        log.warning("%d tickers have no Close on their last daily bar - filling from 60m bars", len(todo))
    for i in range(0, len(todo), INTRADAY_CHUNK):
        chunk = todo[i:i + INTRADAY_CHUNK]
        try:
            raw = yf.download(chunk, period="5d", interval="60m", auto_adjust=False, actions=False,
                              group_by="ticker", threads=True, progress=False)
        except Exception as e:  # noqa: BLE001
            log.warning("intraday close fill failed: %s", e)
            raw = None
        multi = raw is not None and isinstance(raw.columns, pd.MultiIndex)
        for t in chunk:
            intra = None
            if raw is not None and not raw.empty:
                try:
                    intra = raw[t] if multi else raw
                except KeyError:
                    intra = None
            frames[t] = apply_intraday_close(frames[t], intra)
    fixed = sum(1 for t in todo if len(frames[t]) and pd.notna(frames[t]["Close"].iloc[-1]))
    if todo:
        log.info("filled %d of %d missing closes", fixed, len(todo))
    return {t: df for t, df in frames.items() if len(df)}


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
    data = patch_missing_closes(_split(_download(tickers), tickers))
    missing = [t for t in tickers if t not in data]
    for attempt in range(retries):
        if not missing:
            break
        log.warning("retry %d for %d tickers: %s", attempt + 1, len(missing), " ".join(missing))
        time.sleep(2)
        for t in list(missing):
            try:
                got = patch_missing_closes(_split(_download([t]), [t]))
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
        frames = _split(raw, symbols)
        if key == "daily":
            frames = patch_missing_closes(frames)
        for s, df in frames.items():
            if key == "weekly" and needs_close(df):
                d = out[s].get("daily")  # this week's bar: use the latest daily close
                if d is not None and len(d) and d.index[-1] >= df.index[-1]:
                    df = df.copy()
                    df.iloc[-1, df.columns.get_loc("Close")] = float(d["Close"].iloc[-1])
                else:
                    df = df.iloc[:-1]
            out[s][key] = df
    return out
