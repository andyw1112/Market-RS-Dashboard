"""Weekly financial calendar: US high-impact economic data + large-cap earnings.

Sources (free, no key):
  - Economic: ForexFactory weekly feed (this week only, Sun-Sat, times in US/Eastern)
  - Earnings: Yahoo earnings calendar via yfinance (market cap filter)

Any source failing just leaves that part empty / keeps the previous file's data;
it never fails the whole update run.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
UA = "Mozilla/5.0 (compatible; rs-dashboard/1.0)"

ECON_COUNTRY = "USD"
ECON_IMPACT = {"High"}
EARNINGS_MIN_CAP = 10e9  # market cap >= US$10B (100億)
EARNINGS_PAGE = 100
OTC_FOREIGN = re.compile(r"[A-Z]{4}[FY]")  # e.g. ACGYF, NSRGY: OTC foreign shares, not US-listed


def _get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def week_window(today: date) -> tuple[date, date]:
    """Mon-Fri of the current week; on Sat/Sun, the coming week."""
    if today.weekday() >= 5:
        today = today + timedelta(days=7 - today.weekday())
    mon = today - timedelta(days=today.weekday())
    return mon, mon + timedelta(days=4)


def fetch_economic(start: date, end: date) -> list[dict] | None:
    try:
        raw = _get_json(FF_URL)
    except Exception as e:  # noqa: BLE001
        log.warning("economic calendar failed: %s", e)
        return None
    out = []
    for e in raw:
        if e.get("country") != ECON_COUNTRY or e.get("impact") not in ECON_IMPACT:
            continue
        try:
            dt = datetime.fromisoformat(e["date"])
        except (KeyError, ValueError):
            continue
        if not (start <= dt.astimezone(ET).date() <= end):
            continue
        out.append({
            "datetime": dt.isoformat(),
            "title": e.get("title", ""),
            "impact": e.get("impact"),
            "forecast": e.get("forecast") or None,
            "previous": e.get("previous") or None,
        })
    out.sort(key=lambda x: x["datetime"])
    return out


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else round(f, 2)  # NaN -> None


def fetch_earnings(start: date, end: date, min_cap: float = EARNINGS_MIN_CAP) -> list[dict] | None:
    """Large-cap earnings via yfinance's Yahoo earnings calendar."""
    try:
        import yfinance as yf
        cal = yf.Calendars(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat())
        pages = []
        for offset in range(0, 1000, EARNINGS_PAGE):  # all of them, not only Yahoo's "most active"
            page = cal.get_earnings_calendar(market_cap=min_cap, filter_most_active=False,
                                             limit=EARNINGS_PAGE, offset=offset, force=True)
            if page is None or page.empty:
                break
            pages.append(page)
            if len(page) < EARNINGS_PAGE:
                break
        df = pd.concat(pages) if pages else None
    except Exception as e:  # noqa: BLE001
        log.warning("earnings calendar failed: %s", e)
        return None
    out = []
    if df is None or df.empty:
        return out
    df = df[~df.index.duplicated()]
    for sym, r in df.iterrows():
        if OTC_FOREIGN.fullmatch(str(sym)):
            continue
        ts = r.get("Event Start Date")
        if ts is None or ts != ts:
            continue
        d = ts.tz_convert(ET).date()
        if not (start <= d <= end):
            continue
        timing = str(r.get("Timing") or "")
        if timing not in ("BMO", "AMC"):  # e.g. "TAS": infer from the announced time
            t = ts.tz_convert(ET)
            if (t.hour, t.minute) != (0, 0):
                timing = "BMO" if (t.hour, t.minute) < (9, 30) else "AMC" if t.hour >= 16 else "TBD"
        out.append({
            "date": d.isoformat(),
            "symbol": str(sym),
            "name": r.get("Company"),
            "time": timing if timing in ("BMO", "AMC") else "TBD",
            "market_cap": _num(r.get("Marketcap")),
            "eps_estimate": _num(r.get("EPS Estimate")),
            "eps_reported": _num(r.get("Reported EPS")),
            "surprise_pct": _num(r.get("Surprise(%)")),
        })
    seen, uniq = set(), []
    for x in sorted(out, key=lambda x: x["symbol"]):  # one row per company (MOG-A / MOG-B)
        if x["name"] not in seen:
            seen.add(x["name"])
            uniq.append(x)
    out = uniq
    order = {"BMO": 0, "TBD": 1, "AMC": 2}
    out.sort(key=lambda x: (x["date"], order[x["time"]], -(x["market_cap"] or 0)))
    return out


def build_calendar(previous: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(ET)
    start, end = week_window(now.date())
    same_week = previous and previous.get("week_start") == start.isoformat()
    econ = fetch_economic(start, end)
    earn = fetch_earnings(start, end)
    if econ is None and earn is None and not same_week:
        raise RuntimeError("both calendar sources failed")
    # keep last good data for this week if a source is down
    if econ is None:
        econ = previous.get("economic", []) if same_week else []
    if earn is None:
        earn = previous.get("earnings", []) if same_week else []
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "generated_at": now.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds"),
        "earnings_min_cap": EARNINGS_MIN_CAP,
        "economic": econ,
        "earnings": earn,
    }
