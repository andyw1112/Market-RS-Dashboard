"""Stock scanners over all US-listed common stocks.

Universe: Nasdaq Trader symbol directory (nasdaqlisted + otherlisted), excluding
ETFs, test issues, warrants, units, rights, preferreds, notes.

Scanners (all also require: close > $2, 20-day avg dollar volume > $10M, market cap >= $500M):
  HTF 30D : close / min(Low, last 30 days)  - 1 >= 50%, close > daily 50 EMA
  HTF 60D : close / min(Low, last 60 days)  - 1 >= 75%, close > daily 50 EMA
  HTF 100D: close / min(Low, last 100 days) - 1 >= 75%, close > daily 50 EMA
  52W High: close within 3% of the 52-week (252-day) high
"""
from __future__ import annotations

import csv
import logging
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

SYMDIR = "https://www.nasdaqtrader.com/dynamic/SymDir/{}.txt"
UA = "rs-dashboard/1.0"

SECTOR_MAP = Path(__file__).resolve().parent.parent / "config" / "sector_map.csv"

MIN_PRICE = 2.0
MIN_DOLLAR_VOL = 10e6
MIN_MARKET_CAP = 500e6
DOLLAR_VOL_DAYS = 20
NEAR_HIGH_PCT = 3.0
HIGH_52W_DAYS = 252

CHUNK = 250
PERIOD = "14mo"

EXCLUDE_NAME = re.compile(
    r"\b(warrants?|units?|rights?|preferred|preference|notes? due|debentures?|"
    r"depositary shares representing.*preferred|trust preferred)\b|\bWT\b|\d%",
    re.I,
)


@dataclass(frozen=True)
class Scan:
    key: str
    title: str
    days: int | None = None
    min_gain: float | None = None  # %


SCANS = [
    Scan("htf30", "30D HTF", 30, 50.0),
    Scan("htf60", "60D HTF", 60, 75.0),
    Scan("htf100", "100D HTF", 100, 75.0),
    Scan("high52", "52W High"),
]


# ------------------------------------------------------------------ universe
def _read_symdir(name: str) -> list[dict]:
    req = urllib.request.Request(SYMDIR.format(name), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("File Creation Time")]
    head = lines[0].split("|")
    return [dict(zip(head, ln.split("|"))) for ln in lines[1:]]


def load_universe() -> dict[str, str]:
    """{yahoo_symbol: name} for US-listed common stocks / ADRs."""
    out: dict[str, str] = {}
    for r in _read_symdir("nasdaqlisted"):
        if r.get("ETF") == "Y" or r.get("Test Issue") == "Y" or r.get("NextShares") == "Y":
            continue
        sym, name = r["Symbol"], r["Security Name"]
        if EXCLUDE_NAME.search(name) or not re.fullmatch(r"[A-Z]{1,5}", sym):
            continue
        out[sym] = name
    for r in _read_symdir("otherlisted"):
        if r.get("ETF") == "Y" or r.get("Test Issue") == "Y" or r.get("Exchange") not in ("N", "A", "P"):
            continue
        sym, name = r["ACT Symbol"], r["Security Name"]
        if EXCLUDE_NAME.search(name) or "$" in sym:
            continue
        if not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", sym):
            continue
        out[sym.replace(".", "-")] = name  # BRK.B -> BRK-B (Yahoo)
    return out


# ------------------------------------------------------------------ prices
def download(symbols: list[str]) -> dict[str, pd.DataFrame]:
    data: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        for attempt in range(3):
            try:
                raw = yf.download(chunk, period=PERIOD, interval="1d", auto_adjust=False, actions=False,
                                  group_by="ticker", threads=True, progress=False)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("chunk %d attempt %d: %s", i // CHUNK, attempt + 1, e)
                time.sleep(10 * (attempt + 1))
        else:
            continue
        for s in chunk:
            try:
                df = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            if len(df) >= 30:
                df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
                data[s] = df
        log.info("scanner download %d/%d (%d with data)", min(i + CHUNK, len(symbols)), len(symbols), len(data))
        time.sleep(1)
    return data


# ------------------------------------------------------------------ market cap / sector
def _info(sym: str) -> tuple[str, dict | None]:
    for attempt in range(2):
        try:
            i = yf.Ticker(sym).info or {}
            return sym, {"market_cap": i.get("marketCap"), "sector": i.get("sector"), "industry": i.get("industry")}
        except Exception as e:  # noqa: BLE001
            log.debug("%s info attempt %d: %s", sym, attempt + 1, e)
            time.sleep(2)
    return sym, None  # lookup failed (not the same as "no market cap")


def fetch_meta(symbols: list[str]) -> dict[str, dict | None]:
    with ThreadPoolExecutor(8) as ex:
        return dict(ex.map(_info, symbols))


def cap_ok(meta: dict | None) -> bool:
    """Market cap >= $500M. If the Yahoo lookup itself failed, keep the stock rather than drop it silently."""
    if meta is None:
        return True
    cap = meta.get("market_cap")
    return cap is not None and cap >= MIN_MARKET_CAP


def load_sector_map(path: Path = SECTOR_MAP) -> list[tuple[str, str, list[str]]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [(r["level"].strip(), r["match"].strip().lower(), r["etfs"].split())
                for r in csv.DictReader(f) if (r.get("match") or "").strip()]


def map_etfs(sector: str | None, industry: str | None, rules) -> list[str]:
    """Sector ETFs a stock belongs to: exact Yahoo sector match + industry substring match."""
    out: list[str] = []
    sec, ind = (sector or "").lower(), (industry or "").lower()
    for level, match, etfs in rules:
        if (level == "sector" and sec == match) or (level == "industry" and ind and match in ind):
            out += [e for e in etfs if e not in out]
    return out


# ------------------------------------------------------------------ rules
def evaluate(df: pd.DataFrame) -> dict | None:
    """Compute scan metrics for one stock; None if it fails the base filters."""
    c = df["Close"]
    close = float(c.iloc[-1])
    if close <= MIN_PRICE:
        return None
    dvol = float((c * df["Volume"]).iloc[-DOLLAR_VOL_DAYS:].mean())
    if not dvol > MIN_DOLLAR_VOL:
        return None
    ema50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1]) if len(c) >= 50 else None
    high52 = float(df["High"].iloc[-HIGH_52W_DAYS:].max())
    m = {
        "close": round(close, 2),
        "pct_1d": round((close / float(c.iloc[-2]) - 1) * 100, 2) if len(c) > 1 else None,
        "dollar_vol": round(dvol),
        "above_ema50": ema50 is not None and close > ema50,
        "off_high": round((close / high52 - 1) * 100, 2),
        "date": df.index[-1].date().isoformat(),
    }
    for s in SCANS:
        if s.days:
            if len(df) >= s.days:
                low = float(df["Low"].iloc[-s.days:].min())
                m[f"gain{s.days}"] = round((close / low - 1) * 100, 1) if low > 0 else None
            else:
                m[f"gain{s.days}"] = None
    return m


def passes(s: Scan, m: dict) -> bool:
    if s.days:
        g = m.get(f"gain{s.days}")
        return m["above_ema50"] and g is not None and g >= s.min_gain
    return m["off_high"] >= -NEAR_HIGH_PCT


def run_scans(names: dict[str, str], data: dict[str, pd.DataFrame], as_of: str) -> dict:
    metrics = {}
    for sym, df in data.items():
        if df.index[-1].date().isoformat() != as_of:  # stale / halted
            continue
        try:
            m = evaluate(df)
        except Exception as e:  # noqa: BLE001
            log.debug("%s: %s", sym, e)
            continue
        if m:
            metrics[sym] = m
    candidates = sorted({sym for sym, m in metrics.items() if any(passes(s, m) for s in SCANS)})
    meta = fetch_meta(candidates)
    rules = load_sector_map()
    small = sum(1 for s in candidates if not cap_ok(meta.get(s)))
    log.info("scanner: %d candidates, %d dropped by market cap < $%dM", len(candidates), small, MIN_MARKET_CAP / 1e6)

    out = []
    for s in SCANS:
        hits = []
        for sym, m in metrics.items():
            if not passes(s, m) or not cap_ok(meta.get(sym)):
                continue
            mt = meta.get(sym) or {}
            hits.append({"symbol": sym, "name": names.get(sym, ""), **{k: m[k] for k in (
                "close", "pct_1d", "dollar_vol", "off_high")},
                "gain": m.get(f"gain{s.days}") if s.days else None,
                "market_cap": mt.get("market_cap"), "sector": mt.get("sector"), "industry": mt.get("industry"),
                "etfs": map_etfs(mt.get("sector"), mt.get("industry"), rules)})
        hits.sort(key=lambda h: -h["dollar_vol"])  # most liquid first
        out.append({"key": s.key, "title": s.title, "days": s.days, "min_gain": s.min_gain,
                    "count": len(hits), "items": hits})
    return {
        "as_of": as_of,
        "universe": len(names),
        "with_data": len(data),
        "liquid": len(metrics),
        "rules": {"min_price": MIN_PRICE, "min_dollar_vol": MIN_DOLLAR_VOL, "min_market_cap": MIN_MARKET_CAP,
                  "dollar_vol_days": DOLLAR_VOL_DAYS, "near_high_pct": NEAR_HIGH_PCT},
        "scans": out,
    }


def scan(as_of: str) -> dict:
    names = load_universe()
    log.info("scanner universe: %d stocks", len(names))
    data = download(sorted(names))
    return run_scans(names, data, as_of)
