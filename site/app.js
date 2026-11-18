(function () {
  "use strict";

  const SECTOR_MIN_RS1M = 90; // "Sector RS 90% above" = 1-Mth RS % >= 90

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  // ---------- data ----------
  async function load(file = "latest.json") {
    // Pages layout: data/ next to index.html. Local dev (serving repo root): ../data/
    for (const u of [`data/${file}`, `../data/${file}`]) {
      try {
        const r = await fetch(u + "?t=" + Date.now(), { cache: "no-store" });
        if (r.ok) return r.json();
      } catch (_) { /* try next */ }
    }
    throw new Error(`Cannot load data/${file}`);
  }

  // ---------- formatting ----------
  const fmtPct = (v, d = 2) => (v == null ? "–" : (v > 0 ? "+" : "") + v.toFixed(d) + "%");
  const fmtScore = (v) => (v == null ? "–" : v.toFixed(1) + "%");
  const fmtNum = (v) => (v == null ? "–" : v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const fmtChg = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + fmtNum(v));

  function heatStyle(v) {
    if (v == null) return "";
    const dist = Math.abs(v - 50) / 50; // 0 red -> 50 neutral -> 100 green
    const hue = v >= 50 ? 140 : 0;
    return `background-color: hsl(${hue} 70% 45% / calc(var(--heat-alpha) * ${dist.toFixed(3)}))`;
  }
  const signClass = (v) => (v == null ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "");
  const highClass = (v) => (v == null ? "" : v >= -5 ? "hi-ok" : v >= -15 ? "hi-mid" : "hi-bad");
  const escapeHtml = (s) => String(s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- sparklines ----------
  const W = 110, H = 28, P = 2;
  function scaler(vals) {
    let min = Math.min(...vals), max = Math.max(...vals);
    if (max === min) { max += 1e-9; min -= 1e-9; }
    return (v) => P + (H - 2 * P) * (1 - (v - min) / (max - min));
  }
  function priceSpark(vals) {
    if (!vals || vals.length < 2) return "";
    const y = scaler(vals), dx = (W - 2 * P) / (vals.length - 1);
    const pts = vals.map((v, i) => `${(P + i * dx).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const c = vals[vals.length - 1] >= vals[0] ? "var(--pos)" : "var(--neg)";
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true">
      <polyline points="${pts}" fill="none" stroke="${c}" stroke-width="1.4" stroke-linejoin="round"/>
      <circle cx="${(P + (vals.length - 1) * dx).toFixed(1)}" cy="${y(vals[vals.length - 1]).toFixed(1)}" r="1.8" fill="${c}"/>
    </svg>`;
  }
  function rsSpark(vals) {
    if (!vals || vals.length < 2) return "";
    const y = scaler(vals), n = vals.length, slot = (W - 2 * P) / n, bw = Math.max(1, slot - 1);
    const today = vals[n - 1], base = H - P;
    const bars = vals.map((v, i) => {
      const top = Math.min(y(v), base - 1);
      const fill = i === n - 1 ? "var(--spark)" : today > v ? "var(--spark-up)" : "var(--spark-dn)";
      return `<rect x="${(P + i * slot).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${(base - top).toFixed(1)}" fill="${fill}"/>`;
    }).join("");
    const ry = y(today).toFixed(1);
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true">${bars}
      <line x1="${P}" x2="${W - P}" y1="${ry}" y2="${ry}" stroke="var(--ref)" stroke-width="1" stroke-dasharray="3 2"/></svg>`;
  }

  // ---------- RS table (used by both Index/Macro and Sector) ----------
  const COLS = [
    { key: "ticker", label: "Ticker", cls: "sticky" },
    { key: "name", label: "Name" },
    { key: "thrust", label: "RS Thrust %", cls: "num" },
    { key: "rs_1m", label: "1-Mth RS %", cls: "num" },
    { label: "1-Mth Price" },
    { label: "1-Mth RS" },
    { key: "pct_intraday", label: "% Intraday", cls: "num" },
    { key: "pct_1d", label: "% 1D", cls: "num" },
    { key: "pct_gap", label: "% Gap", cls: "num" },
    { key: "pct_1m", label: "% 1-Mth", cls: "num" },
    { key: "pct_off_high", label: "% Off 52W High", cls: "num" },
  ];

  function rowHtml(r) {
    const yahoo = `https://finance.yahoo.com/quote/${encodeURIComponent(r.ticker)}`;
    const tickerCell = `<td class="ticker sticky"><a href="${yahoo}" target="_blank" rel="noopener">${r.ticker}</a></td>`;
    const nameCell = `<td class="name" title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</td>`;
    if (r.status === "no_data") {
      return `<tr class="nodata">${tickerCell}${nameCell}<td colspan="9"><span class="badge">${escapeHtml(r.note || "No data")}</span></td></tr>`;
    }
    const bench = r.status === "benchmark";
    const score = (v) => bench ? `<td class="heat">benchmark</td>`
      : `<td class="heat" style="${heatStyle(v)}">${fmtScore(v)}</td>`;
    const pct = (v) => `<td class="num ${signClass(v)}">${fmtPct(v)}</td>`;
    return `<tr class="${bench ? "benchmark" : ""}">${tickerCell}${nameCell}
      ${score(r.thrust)}${score(r.rs_1m)}
      <td class="spark">${priceSpark(r.spark_price)}</td>
      <td class="spark">${bench ? "" : rsSpark(r.spark_rs)}</td>
      ${pct(r.pct_intraday)}${pct(r.pct_1d)}${pct(r.pct_gap)}${pct(r.pct_1m)}
      <td class="num ${highClass(r.pct_off_high)}">${fmtPct(r.pct_off_high)}</td></tr>`;
  }

  function makeComparator(sort) {
    const rank = (r) => (r.status === "benchmark" ? 0 : r.status === "ok" ? 1 : 2);
    return (a, b) => {
      if (rank(a) !== rank(b)) return rank(a) - rank(b);
      const k = sort.key, dir = sort.asc ? 1 : -1, av = a[k], bv = b[k];
      if (typeof av === "string" || typeof bv === "string") return dir * String(av || "").localeCompare(String(bv || ""));
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av !== bv) return dir * (av - bv);
      if (k === "thrust" && (a.rs_1m ?? -1) !== (b.rs_1m ?? -1)) return (b.rs_1m ?? -1) - (a.rs_1m ?? -1);
      return a.ticker.localeCompare(b.ticker);
    };
  }

  // Creates a table bound to `getRows()`. Returns a render() function.
  // fixed: keep the order from config/tickers.csv, no click-to-sort.
  function rsTable(table, getRows, { fixed = false } = {}) {
    const sort = { key: "thrust", asc: false };
    table.innerHTML = `<thead><tr>${COLS.map((c) => {
      const sortable = c.key && !fixed;
      return `<th class="${c.cls || ""} ${sortable ? "" : "nosort"}" ${sortable ? `data-key="${c.key}"` : ""}>${c.label}</th>`;
    }).join("")}
      </tr></thead><tbody></tbody>`;
    const render = () => {
      const rows = fixed ? getRows() : getRows().slice().sort(makeComparator(sort));
      $("tbody", table).innerHTML = rows.length ? rows.map(rowHtml).join("")
        : `<tr><td colspan="11" class="empty">No ETFs match</td></tr>`;
      $$("th", table).forEach((th) => {
        const on = th.dataset.key === sort.key;
        th.classList.toggle("sorted", on);
        th.classList.toggle("asc", on && sort.asc);
      });
    };
    $$("th[data-key]", table).forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.key;
      if (sort.key === k) sort.asc = !sort.asc;
      else { sort.key = k; sort.asc = k === "ticker" || k === "name"; }
      render();
    }));
    render();
    return render;
  }

  // ---------- Index condition ----------
  const lamp = (color, title) => color
    ? `<span class="lamp ${color}" title="${escapeHtml(title)}"></span>`
    : `<span class="lamp off" title="${escapeHtml(title)}"></span>`;

  function emaTip(t, tf) {
    if (!t) return `${tf}: not enough history`;
    return `${tf} EMA21 ${fmtNum(t.ema21)} · EMA50 ${fmtNum(t.ema50)} · EMA200 ${fmtNum(t.ema200)}`;
  }

  function renderCondition(items) {
    const el = $("#cond");
    if (!items || !items.length) { el.innerHTML = `<p class="placeholder">No data</p>`; return; }
    const head = `<thead><tr><th></th><th class="num">Price</th><th class="num">Chg</th><th class="num">%</th>
      <th title="Daily 21/50/200 EMA">Short</th><th title="Weekly 21/50/200 EMA">Long</th>
      <th class="num" title="(Close − daily 50 EMA) ÷ ATR(28)">ATR×</th></tr></thead>`;
    const body = items.map((i) => {
      const c = signClass(i.pct);
      let lights;
      if (i.symbol === "^VIX") {
        lights = `<td>${lamp(i.vix_light, "VIX < 15 紅 · > 30 綠")}</td><td></td><td></td>`;
      } else {
        const atrCls = i.atr_light ? `atr-${i.atr_light}` : "";
        lights = `<td>${lamp(i.short && i.short.light, emaTip(i.short, "Daily"))}</td>
          <td>${lamp(i.long && i.long.light, emaTip(i.long, "Weekly"))}</td>
          <td class="num ${atrCls}">${i.atr_from_50 == null ? "–" : i.atr_from_50.toFixed(1)}</td>`;
      }
      return `<tr>
        <td class="cond-label" title="${escapeHtml(i.symbol)}">${escapeHtml(i.label)}</td>
        <td class="num">${fmtNum(i.price)}</td>
        <td class="num ${c}">${fmtChg(i.change)}</td>
        <td class="num ${c}">${fmtPct(i.pct)}</td>
        ${lights}
      </tr>`;
    }).join("");
    el.innerHTML = `<table class="cond-table">${head}<tbody>${body}</tbody></table>
      <div class="cond-remarks">
        <div class="remarks-title">Remarks</div>
        <ul>
          <li><span class="lamp red"></span> Red color = Poor market condition</li>
          <li><span class="lamp green"></span> Green color = Good market condition</li>
          <li><span class="rm-tag atr-yellow">&gt; 4</span> ATR% over 4 = Extended</li>
          <li><span class="rm-tag atr-red">&gt; 8</span> ATR% over 8 = Extremely extended</li>
          <li><b>VIX</b> below 15 = High risk to pullback</li>
          <li class="rm-warn">Index false BO is high risk, potential pullback 8% or above.
            If it cannot quickly reclaim weekly important levels (e.g. weekly 21/50 EMA), market condition is extremely poor.</li>
        </ul>
      </div>
      <p class="cond-legend">Short = daily、Long = weekly 21/50/200 EMA：🟢 企穩三條 · 🟡 中間 · 🔴 低過 50 同 200。
      ATR× = (收市 − daily 50 EMA) ÷ ATR(28)。VIX &gt; 30 綠。</p>`;
  }

  // ---------- Financial calendar ----------
  const HKT = "Asia/Hong_Kong";
  const dayKey = (d) => new Intl.DateTimeFormat("en-CA", { timeZone: HKT }).format(d); // YYYY-MM-DD in HKT
  const dayLabel = (iso) => new Date(iso + "T12:00:00Z")
    .toLocaleDateString("en-US", { weekday: "short", month: "numeric", day: "numeric", timeZone: "UTC" });
  const hkTime = (d) => d.toLocaleTimeString("en-GB", { timeZone: HKT, hour: "2-digit", minute: "2-digit", hour12: false });
  const capFmt = (v) => (v == null ? "" : v >= 1e12 ? `$${(v / 1e12).toFixed(2)}T`
    : v >= 1e9 ? `$${Math.round(v / 1e9)}B` : `$${Math.round(v / 1e6)}M`);

  function groupBy(items, keyFn) {
    const m = new Map();
    items.forEach((x) => { const k = keyFn(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x); });
    return m;
  }

  function econHtml(econ, today, now) {
    if (!econ.length) return `<p class="placeholder">No high-impact US data this week (or source unavailable)</p>`;
    return [...groupBy(econ, (e) => dayKey(e.t))].map(([day, list]) => `
      <div class="cal-day ${day < today ? "past" : day === today ? "today" : ""}">
        <div class="cal-date">${dayLabel(day)}</div>
        ${list.map((e) => `<div class="cal-item ${e.t.getTime() < now ? "done" : ""}">
          <span class="cal-time">${hkTime(e.t)}</span>
          <span class="cal-title">${escapeHtml(e.title)}</span>
          <span class="cal-meta">${e.forecast ? `F: ${escapeHtml(e.forecast)}` : ""}${e.previous ? ` · P: ${escapeHtml(e.previous)}` : ""}</span>
        </div>`).join("")}
      </div>`).join("");
  }

  function earnHtml(earn, today) {
    if (!earn.length) return `<p class="placeholder">No large-cap earnings this week (or source unavailable)</p>`;
    // grouped by US date (BMO / AMC are US-session terms)
    return [...groupBy(earn, (e) => e.date)].map(([day, list]) => `
      <div class="cal-day ${day < today ? "past" : ""}">
        <div class="cal-date">${dayLabel(day)} <span class="sub">US</span></div>
        ${list.map((e) => {
          const res = e.eps_reported != null
            ? `<span class="cal-meta">EPS ${e.eps_reported} vs ${e.eps_estimate ?? "–"} <b class="${signClass(e.surprise_pct)}">${fmtPct(e.surprise_pct, 1)}</b></span>`
            : `<span class="cal-meta">${e.eps_estimate != null ? `Est EPS ${e.eps_estimate}` : ""}</span>`;
          return `<div class="cal-item">
            <span class="cal-tag ${e.time.toLowerCase()}">${e.time}</span>
            <a class="cal-sym" href="https://finance.yahoo.com/quote/${encodeURIComponent(e.symbol)}" target="_blank" rel="noopener">${escapeHtml(e.symbol)}</a>
            <span class="cal-title" title="${escapeHtml(e.name)}">${escapeHtml(e.name)} <span class="sub">${capFmt(e.market_cap)}</span></span>
            ${res}
          </div>`;
        }).join("")}
      </div>`).join("");
  }

  function renderCalendar(c) {
    $("#cal-week").textContent = `${dayLabel(c.week_start)} – ${dayLabel(c.week_end)}`;
    $("#cal-cap").textContent = `market cap ≥ ${capFmt(c.earnings_min_cap)}`;
    const today = dayKey(new Date());
    const econ = (c.economic || []).map((e) => ({ ...e, t: new Date(e.datetime) }));
    $("#cal-econ").innerHTML = econHtml(econ, today, Date.now());
    $("#cal-earn").innerHTML = earnHtml(c.earnings || [], today);
  }

  function calendarUnavailable() {
    const msg = `<p class="placeholder">Calendar not available</p>`;
    $("#cal-econ").innerHTML = msg;
    $("#cal-earn").innerHTML = msg;
  }

  // ---------- Stocks scanner ----------
  const SCAN_COLORS = { htf30: "#facc15", htf60: "#2dd4bf", htf100: "#3b82f6", high52: "#fb923c" };
  const dvolFmt = (v) => (v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : `$${Math.round(v / 1e6)}M`);

  function scanSubtitle(sc) {
    return sc.days ? `≥ ${sc.min_gain}% from ${sc.days}D low · > 50 EMA` : "within 3% of 52W high";
  }

  // strong: Map of sector ETF -> 1-Mth RS % for ETFs with 1-Mth RS >= SECTOR_MIN_RS1M
  function renderScanner(d, strong = new Map()) {
    $("#scan-meta").textContent = `${d.as_of} close · ${d.liquid.toLocaleString()} liquid of ${d.universe.toLocaleString()} US stocks`;
    const cap = d.rules.min_market_cap ? ` · Mkt cap ≥ ${capFmt(d.rules.min_market_cap)}` : "";
    $("#scan-rules").innerHTML = `Price &gt; $${d.rules.min_price} · ${d.rules.dollar_vol_days}D avg $Vol &gt; ${dvolFmt(d.rules.min_dollar_vol)}${cap}
      · <span class="scan-legend">綠色 ticker</span> = 屬 1-Mth RS ≥ ${SECTOR_MIN_RS1M}% 嘅 sector`;
    $("#scan-cols").innerHTML = d.scans.map((sc) => `
      <div class="scan-col">
        <div class="scan-head" style="--c:${SCAN_COLORS[sc.key] || "var(--accent)"}">
          <div class="scan-count">${sc.count}</div>
          <div class="scan-title">${escapeHtml(sc.title)}</div>
          <div class="scan-sub">${scanSubtitle(sc)}</div>
        </div>
        <div class="scan-list">
          ${sc.items.slice().sort((a, b) => b.dollar_vol - a.dollar_vol).map((it) => {
            const badge = sc.days ? `+${it.gain.toFixed(0)}%` : `${it.off_high.toFixed(1)}%`;
            const hot = (it.etfs || []).filter((e) => strong.has(e));
            const tip = [
              it.name, `$${it.close} · ${dvolFmt(it.dollar_vol)}/day${it.market_cap ? ` · cap ${capFmt(it.market_cap)}` : ""}`,
              [it.sector, it.industry].filter(Boolean).join(" / "),
              hot.length ? `Strong sector: ${hot.map((e) => `${e} ${strong.get(e)}%`).join(", ")}` : "",
            ].filter(Boolean).join("\n");
            return `<a class="scan-item ${hot.length ? "strong" : ""}" href="https://finance.yahoo.com/quote/${encodeURIComponent(it.symbol)}" target="_blank" rel="noopener"
                title="${escapeHtml(tip)}">
              <span class="scan-sym">${escapeHtml(it.symbol)}</span>
              ${hot.length ? `<span class="scan-etf">${escapeHtml(hot[0])}</span>` : ""}
              <span class="scan-chg ${signClass(it.pct_1d)}">${fmtPct(it.pct_1d, 1)}</span>
              <span class="scan-badge" title="${sc.days ? `Gain from ${sc.days}D low` : "% off 52W high"}">${badge}</span>
              <span class="scan-dvol">${dvolFmt(it.dollar_vol)}</span>
            </a>`;
          }).join("") || `<p class="placeholder">None today</p>`}
        </div>
      </div>`).join("");
  }

  function scannerUnavailable() {
    $("#scan-cols").innerHTML = `<p class="placeholder">Scanner data not available</p>`;
  }

  // ---------- header ----------
  function renderHeader(d) {
    $("#asof").textContent = `Data as of ${d.as_of} close`;
    const hk = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(new Date(d.generated_at));
    $("#updated").textContent = `Updated ${hk} HKT`;
  }

  function bindTheme() {
    $("#theme-toggle").addEventListener("click", () => {
      const root = document.documentElement;
      const cur = root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      root.dataset.theme = cur === "dark" ? "light" : "dark";
      localStorage.setItem("theme", root.dataset.theme);
    });
  }

  load().then((d) => {
    renderHeader(d);
    bindTheme();
    renderCondition(d.index_condition);

    rsTable($("#tbl-index"), () => d.rows.filter((r) => r.group === "Index / Macro"), { fixed: true });

    const showAll = $("#show-all-sectors");
    const renderSector = rsTable($("#tbl-sector"), () => d.rows.filter((r) =>
      r.group === "Sectors / Themes" &&
      (showAll.checked || (r.status === "ok" && r.rs_1m >= SECTOR_MIN_RS1M))));
    showAll.addEventListener("change", () => {
      $("#sector-title").textContent = showAll.checked ? "Sectors / Themes (all)" : "Sector RS 90% above";
      renderSector();
    });
  }).catch((e) => {
    $("#asof").textContent = "Failed to load data: " + e.message;
  });

  load("calendar.json").then(renderCalendar).catch(calendarUnavailable);
  Promise.all([load("scanner.json"), load().catch(() => null)]).then(([scan, latest]) => {
    const strong = new Map((latest ? latest.rows : [])
      .filter((r) => r.status === "ok" && r.group === "Sectors / Themes" && r.rs_1m >= SECTOR_MIN_RS1M)
      .map((r) => [r.ticker, r.rs_1m]));
    renderScanner(scan, strong);
  }).catch(scannerUnavailable);
})();
