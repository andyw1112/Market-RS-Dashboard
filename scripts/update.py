"""Main entry: fetch -> compute -> write data/latest.json + data/history/YYYY-MM-DD.json.

Usage:
    python scripts/update.py           # skip writing if the latest trading day is unchanged
    python scripts/update.py --force   # always rewrite
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compute import compute_benchmark_row, compute_row, condition_row, summarize  # noqa: E402
from calendar_fetch import build_calendar  # noqa: E402
from fetch import fetch_condition, fetch_ohlc  # noqa: E402
from scanner import scan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TICKERS_CSV = ROOT / "config" / "tickers.csv"
INDEX_CSV = ROOT / "config" / "index_condition.csv"
DATA_DIR = ROOT / "data"
LATEST = DATA_DIR / "latest.json"
CALENDAR = DATA_DIR / "calendar.json"
SCANNER = DATA_DIR / "scanner.json"
HISTORY_DIR = DATA_DIR / "history"
HISTORY_INDEX = HISTORY_DIR / "index.json"
BENCHMARK = "RSP"

log = logging.getLogger("update")


def load_tickers() -> list[dict]:
    with open(TICKERS_CSV, encoding="utf-8", newline="") as f:
        rows = [
            {k: (v or "").strip() for k, v in r.items()}
            for r in csv.DictReader(f)
            if (r.get("ticker") or "").strip()
        ]
    seen, out = set(), []
    for r in rows:
        t = r["ticker"].upper()
        if t in seen:
            log.warning("duplicate ticker %s in tickers.csv ignored", t)
            continue
        seen.add(t)
        out.append({"group": r["group"], "ticker": t, "name": r["name"]})
    return out


def load_index_condition() -> list[dict]:
    if not INDEX_CSV.exists():
        return []
    with open(INDEX_CSV, encoding="utf-8", newline="") as f:
        return [{"label": r["label"].strip(), "symbol": r["symbol"].strip()}
                for r in csv.DictReader(f) if (r.get("symbol") or "").strip()]


def build_index_condition() -> list[dict]:
    items = load_index_condition()
    bars = fetch_condition([i["symbol"] for i in items]) if items else {}
    out = []
    for i in items:
        b = bars.get(i["symbol"], {})
        try:
            row = condition_row(b.get("daily"), b.get("weekly"), is_vix=i["symbol"] == "^VIX")
        except Exception as e:  # noqa: BLE001
            log.warning("%s: %s", i["symbol"], e)
            row = {"price": None}
        out.append({**i, **row})
    return out


def build(tickers: list[dict], data: dict) -> dict:
    if BENCHMARK not in data:
        raise SystemExit(f"benchmark {BENCHMARK} has no data - aborting")
    bench = data[BENCHMARK]
    as_of = bench.index[-1]
    bench_close = bench["Close"]

    rows = []
    for meta in tickers:
        t = meta["ticker"]
        row = dict(meta)
        df = data.get(t)
        try:
            if t == BENCHMARK:
                row.update(compute_benchmark_row(bench))
                row["status"] = "benchmark"
            elif df is None or df.empty:
                row["status"] = "no_data"
                row["note"] = "No data"
            elif df.index[-1] != as_of:
                row["status"] = "no_data"
                row["note"] = f"Stale (last {df.index[-1].date()})"
            else:
                row.update(compute_row(df, bench_close))
                row["status"] = "ok"
        except Exception as e:  # noqa: BLE001
            log.warning("%s: %s", t, e)
            row["status"] = "no_data"
            row["note"] = "No data"
        rows.append(row)

    return {
        "as_of": as_of.date().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "benchmark": BENCHMARK,
        "summary": summarize(rows),
        "rows": rows,
    }


def write_json(path: Path, obj, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def write_history(result: dict) -> None:
    """Compact per-day snapshot (no sparklines) + an index for a breadth chart later."""
    snap = {
        "as_of": result["as_of"],
        "summary": result["summary"],
        "rows": [
            {k: r.get(k) for k in ("ticker", "status", "close", "rs", "thrust", "rs_1m", "pct_1d")}
            for r in result["rows"]
        ],
    }
    write_json(HISTORY_DIR / f"{result['as_of']}.json", snap, compact=True)

    index = []
    if HISTORY_INDEX.exists():
        index = json.loads(HISTORY_INDEX.read_text(encoding="utf-8"))
    index = [e for e in index if e["date"] != result["as_of"]]
    index.append({"date": result["as_of"], **result["summary"]})
    index.sort(key=lambda e: e["date"])
    write_json(HISTORY_INDEX, index)


def update_calendar() -> None:
    """Refresh data/calendar.json (runs even on market holidays / weekends).

    Only rewrites the file when the events change, so it doesn't cause empty commits.
    """
    prev = None
    if CALENDAR.exists():
        try:
            prev = json.loads(CALENDAR.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    try:
        cal = build_calendar(prev)
    except Exception as e:  # noqa: BLE001
        log.warning("calendar failed: %s", e)
        return
    strip = lambda c: {k: v for k, v in (c or {}).items() if k != "generated_at"}  # noqa: E731
    if strip(cal) == strip(prev):
        log.info("calendar unchanged")
        return
    write_json(CALENDAR, cal)
    log.info("calendar %s..%s | %d economic | %d earnings",
             cal["week_start"], cal["week_end"], len(cal["economic"]), len(cal["earnings"]))


def update_scanner(as_of: str) -> None:
    try:
        res = scan(as_of)
    except Exception as e:  # noqa: BLE001
        log.warning("scanner failed: %s", e)
        return
    res["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(SCANNER, res, compact=True)
    log.info("scanner: %d liquid of %d | %s", res["liquid"], res["universe"],
             " | ".join(f'{s["title"]} {s["count"]}' for s in res["scans"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="write even if trading day unchanged")
    ap.add_argument("--skip-scan", action="store_true", help="skip the (slow) stock scanners")
    ap.add_argument("--scan-only", action="store_true", help="only run the stock scanners")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.scan_only:
        update_scanner(json.loads(LATEST.read_text(encoding="utf-8"))["as_of"])
        return 0

    update_calendar()
    tickers = load_tickers()
    log.info("fetching %d tickers", len(tickers))
    data = fetch_ohlc([t["ticker"] for t in tickers])
    result = build(tickers, data)
    result["index_condition"] = build_index_condition()

    prev_as_of = None
    if LATEST.exists():
        try:
            prev_as_of = json.loads(LATEST.read_text(encoding="utf-8")).get("as_of")
        except json.JSONDecodeError:
            pass
    if prev_as_of == result["as_of"] and not args.force:
        log.info("latest trading day %s unchanged (holiday / already updated) - nothing written", prev_as_of)
        return 0

    write_json(LATEST, result, compact=True)
    write_history(result)
    if not args.skip_scan:
        update_scanner(result["as_of"])
    s = result["summary"]
    nodata = [r["ticker"] for r in result["rows"] if r["status"] == "no_data"]
    log.info("as_of %s | %d scored | avg thrust %s | no data: %s",
             result["as_of"], s["count"], s["avg_thrust"], " ".join(nodata) or "-")
    return 0


if __name__ == "__main__":
    sys.exit(main())
