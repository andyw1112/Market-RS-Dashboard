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
    const lbl = { green: "Good", orange: "Rebound under 200 EMA", yellow: "Mixed", red: "Poor" }[t.light] || "";
    return `${tf}: ${lbl}\n${t.ema9 != null ? `EMA9 ${fmtNum(t.ema9)} · ` : ""}EMA21 ${fmtNum(t.ema21)} · EMA50 ${fmtNum(t.ema50)} · EMA200 ${fmtNum(t.ema200)}`;
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
          <li><span class="lamp orange"></span> Orange color = Rebound under 200 EMA (below 200 EMA, above 9/21/50 EMA)</li>
          <li><span class="rm-tag atr-yellow">&gt; 4</span> ATR% over 4 = Extended</li>
          <li><span class="rm-tag atr-red">&gt; 8</span> ATR% over 8 = Extremely extended</li>
          <li><b>VIX</b> below 15 = High risk to pullback</li>
          <li class="rm-warn">Index false BO is high risk, potential pullback 8% or above.
            If it cannot quickly reclaim weekly important levels (e.g. weekly 21/50 EMA), market condition is extremely poor.</li>
        </ul>
      </div>
      <p class="cond-legend">Short = daily、Long = weekly 21/50/200 EMA：🟢 企穩 21/50/200 · 🟠 低過 200 但企穩 9/21/50 · 🟡 中間 · 🔴 低過 50 同 200。
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

  // Earnings dates / BMO / AMC are US-session terms, so "past" is judged in New York time.
  function nyNow() {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).formatToParts(new Date()).map((x) => [x.type, x.value]));
    return { date: `${p.year}-${p.month}-${p.day}`, mins: (+p.hour % 24) * 60 + +p.minute };
  }

  // An earnings release is over once it's reported, or once its US session has passed:
  // earlier days; today's BMO after the 09:30 open; today's TBD / AMC after 20:00 ET.
  function earningsDone(e, ny) {
    if (e.eps_reported != null || e.date < ny.date) return true;
    if (e.date > ny.date) return false;
    return e.time === "BMO" ? ny.mins >= 9 * 60 + 30 : ny.mins >= 20 * 60;
  }

  let calData = null;
  function renderCalendar(c) {
    calData = c || calData;
    c = calData;
    $("#cal-week").textContent = `${dayLabel(c.week_start)} – ${dayLabel(c.week_end)}`;
    $("#cal-cap").textContent = `market cap ≥ ${capFmt(c.earnings_min_cap)}`;
    const now = Date.now(), ny = nyNow(), today = dayKey(new Date());
    const allEcon = (c.economic || []).map((e) => ({ ...e, t: new Date(e.datetime) }));
    const econ = allEcon.filter((e) => e.t.getTime() >= now);           // hide released data
    const earn = (c.earnings || []).filter((e) => !earningsDone(e, ny)); // hide reported earnings
    const done = (n, total) => (n < total && !n ? `<p class="placeholder">今個星期嘅已經全部過咗</p>` : "");
    $("#cal-econ").innerHTML = done(econ.length, allEcon.length) || econHtml(econ, today, now);
    $("#cal-earn").innerHTML = done(earn.length, (c.earnings || []).length) || earnHtml(earn, today);
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
      · <span class="scan-legend">綠色 ticker</span> = 屬 1-Mth RS ≥ ${SECTOR_MIN_RS1M}% 嘅 sector
      · <span class="scan-new">NEW</span> = 上星期未出現過`;
    const newDays = d.rules.new_lookback_days || 5;
    $("#scan-cols").innerHTML = d.scans.map((sc) => `
      <div class="scan-col">
        <div class="scan-head" style="--c:${SCAN_COLORS[sc.key] || "var(--accent)"}">
          <div class="scan-count">${sc.count}${sc.new ? ` <span class="scan-count-new">${sc.new} new</span>` : ""}</div>
          <div class="scan-title">${escapeHtml(sc.title)}</div>
          <div class="scan-sub">${scanSubtitle(sc)}</div>
        </div>
        <div class="scan-list">
          ${sc.items.slice().sort((a, b) => b.dollar_vol - a.dollar_vol).map((it) => {
            const badge = sc.days ? `+${it.gain.toFixed(0)}%` : `${it.off_high.toFixed(1)}%`;
            const hot = (it.etfs || []).filter((e) => strong.has(e));
            const tip = [
              it.name, `$${it.close} · ${dvolFmt(it.dollar_vol)}/day${it.atr50 != null ? ` · ATR× ${it.atr50.toFixed(1)}` : ""}${it.market_cap ? ` · cap ${capFmt(it.market_cap)}` : ""}`,
              [it.sector, it.industry].filter(Boolean).join(" / "),
              hot.length ? `Strong sector: ${hot.map((e) => `${e} ${strong.get(e)}%`).join(", ")}` : "",
            ].filter(Boolean).join("\n");
            const snap = JSON.stringify({ name: it.name, close: it.close, atr50: it.atr50 });
            return `<a class="scan-item ${hot.length ? "strong" : ""}" draggable="true" data-sym="${escapeHtml(it.symbol)}"
                data-snap="${escapeHtml(snap)}" href="https://finance.yahoo.com/quote/${encodeURIComponent(it.symbol)}" target="_blank" rel="noopener"
                title="${escapeHtml(tip)}">
              <span class="scan-sym">${escapeHtml(it.symbol)}</span>
              ${it.new ? `<span class="scan-new" title="上星期（之前 ${newDays} 個交易日）未喺任何 scanner 出現過">NEW</span>` : ""}
              ${hot.length ? `<span class="scan-etf">${escapeHtml(hot[0])}</span>` : ""}
              <span class="scan-chg ${signClass(it.pct_1d)}">${fmtPct(it.pct_1d, 1)}</span>
              <span class="scan-badge" title="${sc.days ? `Gain from ${sc.days}D low` : "% off 52W high"}">${badge}</span>
              <span class="scan-dvol">${dvolFmt(it.dollar_vol)}</span>
              <span class="scan-marks">${WL_LISTS.map((l) =>
                `<span class="wl-mark" role="button" data-list="${l.key}" style="--c:${l.color}">${l.title[0]}</span>`).join("")}</span>
            </a>`;
          }).join("") || `<p class="placeholder">None today</p>`}
        </div>
      </div>`).join("");
  }

  function scannerUnavailable() {
    $("#scan-cols").innerHTML = `<p class="placeholder">Scanner data not available</p>`;
  }

  // ---------- Today / Focus / Stalk lists ----------
  // Stored in the repo (data/watchlists.json) through the GitHub API: everyone can read,
  // only a browser holding the owner's GitHub token can edit. localStorage is just a cache.
  const WL_KEY = "watchlists.v1";
  const WL_LISTS = [
    { key: "today", title: "Today", color: "#38bdf8" },
    { key: "focus", title: "Focus list", color: "#f472b6" },
    { key: "stalk", title: "Stalk list", color: "#a78bfa" },
  ];
  const TAGS = [
    { key: "flag", icon: "🚩", label: "Flag" },
    { key: "cwh", icon: "☕", label: "CWH", tip: "Cup with handle" },
    { key: "fw", icon: "📐", label: "FW", tip: "Falling wedge" },
    { key: "peg", icon: "⚡", label: "PEG", tip: "Power earnings gap" },
  ];
  const DRAG_TYPE = "application/x-rs-symbol";
  const wl = { quotes: {}, state: { today: [], focus: [], stalk: [] } };

  const normSym = (s) => String(s || "").trim().toUpperCase().replace(/\./g, "-").replace(/[^A-Z0-9^=-]/g, "");
  function normState(s) {
    const out = {};
    WL_LISTS.forEach((l) => {
      out[l.key] = (Array.isArray(s && s[l.key]) ? s[l.key] : []).filter((e) => e && e.sym).map((e) => ({
        sym: normSym(e.sym), tags: Array.isArray(e.tags) ? e.tags : [], added: String(e.added || ""),
        ...(e.snap ? { snap: e.snap } : {}),
      }));
    });
    return out;
  }

  function wlLoad() {
    try { wl.state = normState(JSON.parse(localStorage.getItem(WL_KEY) || "{}")); } catch (_) { /* keep */ }
  }
  const wlCache = () => localStorage.setItem(WL_KEY, JSON.stringify(wl.state));
  function wlSave() {
    wlCache();
    ghScheduleSave();
  }

  // ---------- GitHub sync ----------
  const GH = { owner: "andyw1112", repo: "Market-RS-Dashboard", path: "data/watchlists.json", branch: "main" };
  const GH_API = `https://api.github.com/repos/${GH.owner}/${GH.repo}`;
  const TOKEN_KEY = "gh-token.v1";
  const sync = { token: localStorage.getItem(TOKEN_KEY) || "", sha: null, timer: null, saving: false, again: false };
  const canEdit = () => !!sync.token;

  const b64enc = (str) => {
    let bin = "";
    new TextEncoder().encode(str).forEach((b) => { bin += String.fromCharCode(b); });
    return btoa(bin);
  };
  const b64dec = (b64) => new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\s/g, "")), (c) => c.charCodeAt(0)));
  const ghHeaders = () => ({
    Accept: "application/vnd.github+json",
    ...(sync.token ? { Authorization: `Bearer ${sync.token}` } : {}),
  });

  function syncStatus(text, cls = "") {
    const el = $("#wl-sync");
    el.textContent = text;
    el.className = `wl-sync ${cls}`;
  }

  async function ghGet() {
    const r = await fetch(`${GH_API}/contents/${GH.path}?ref=${GH.branch}&t=${Date.now()}`,
      { headers: ghHeaders(), cache: "no-store" });
    if (r.status === 404) return { state: null, sha: null };
    if (!r.ok) throw new Error(`GitHub ${r.status}`);
    const j = await r.json();
    return { state: normState(JSON.parse(b64dec(j.content))), sha: j.sha };
  }

  async function ghPut() {
    const body = {
      message: "watchlists: update",
      content: b64enc(JSON.stringify(wl.state, null, 1) + "\n"),
      branch: GH.branch,
      // keep the owner's real e-mail out of the public history
      committer: { name: GH.owner, email: "264357720+andyw1112@users.noreply.github.com" },
      ...(sync.sha ? { sha: sync.sha } : {}),
    };
    const r = await fetch(`${GH_API}/contents/${GH.path}`, {
      method: "PUT", headers: { ...ghHeaders(), "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (r.status === 409 || r.status === 422) { // file changed elsewhere: take the new sha, our edit wins
      sync.sha = (await ghGet()).sha;
      throw Object.assign(new Error("conflict"), { retry: true });
    }
    if (r.status === 401 || r.status === 403) throw new Error("token 冇權限或者過咗期");
    if (!r.ok) throw new Error(`GitHub ${r.status}`);
    sync.sha = (await r.json()).content.sha;
  }

  function ghScheduleSave() {
    if (!canEdit()) return;
    syncStatus("未儲存…", "busy");
    clearTimeout(sync.timer);
    sync.timer = setTimeout(ghSave, 1200);
  }

  async function ghSave() {
    if (sync.saving) { sync.again = true; return; }
    sync.saving = true;
    syncStatus("同步緊 GitHub…", "busy");
    try {
      try { await ghPut(); } catch (e) { if (e.retry) await ghPut(); else throw e; }
      syncStatus("✓ 已同步 GitHub", "ok");
    } catch (e) {
      syncStatus(`⚠ 同步失敗：${e.message}（改動仲喺呢個 browser）`, "err");
    } finally {
      sync.saving = false;
      if (sync.again) { sync.again = false; ghSave(); }
    }
  }

  async function ghLoad() {
    syncStatus("讀取緊 GitHub…", "busy");
    try {
      const { state, sha } = await ghGet();
      sync.sha = sha;
      if (state) {
        wl.state = state;
        wlCache();
      } else if (canEdit() && WL_LISTS.some((l) => wl.state[l.key].length)) {
        ghSave(); // first sync: upload what this browser already has
      }
      syncStatus(canEdit() ? "✓ 已同步 GitHub" : "唯讀", canEdit() ? "ok" : "");
    } catch (e) {
      // API rate limit for anonymous visitors (60/h): fall back to the copy deployed with the site
      if (!canEdit()) {
        try { wl.state = normState(await load("watchlists.json")); } catch (_) { /* keep cache */ }
        syncStatus("唯讀（可能慢幾分鐘）");
      } else {
        syncStatus(`⚠ 讀唔到 GitHub：${e.message}，顯示呢個 browser 嘅版本`, "err");
      }
    }
    renderLists();
  }

  async function ghConnect() {
    if (canEdit()) {
      if (!confirm("喺呢個 browser 移除 GitHub token？之後呢度會變唯讀。")) return;
      localStorage.removeItem(TOKEN_KEY);
      sync.token = "";
      applyMode();
      return;
    }
    const t = (prompt(`貼上你嘅 GitHub fine-grained token\n（只揀 ${GH.repo} 呢個 repo，Contents: Read and write）`) || "").trim();
    if (!t) return;
    syncStatus("檢查緊 token…", "busy");
    try {
      const r = await fetch(GH_API, { headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${t}` } });
      const j = r.ok ? await r.json() : null;
      if (!j || !j.permissions || !j.permissions.push) throw new Error("token 冇呢個 repo 嘅寫入權限");
    } catch (e) {
      syncStatus(`⚠ ${e.message}`, "err");
      return;
    }
    sync.token = t;
    localStorage.setItem(TOKEN_KEY, t);
    applyMode();
    ghLoad();
  }

  function applyMode() {
    $("#sec-lists").classList.toggle("readonly", !canEdit());
    document.body.classList.toggle("wl-ro", !canEdit());
    $("#wl-connect").textContent = canEdit() ? "🔓 已連接" : "🔑 連接 GitHub";
    $("#wl-connect").title = canEdit() ? "撳嚟喺呢個 browser 移除 token" : "貼 GitHub token 先可以編輯";
    $("#wl-import").disabled = !canEdit();
    if (!canEdit()) syncStatus("唯讀");
    renderLists();
  }

  // Add (or move) `sym` into `list`; a stock lives in one list at a time and keeps its tags when moved.
  function wlAdd(list, sym, snap) {
    sym = normSym(sym);
    if (!sym || !canEdit()) return;
    let entry = null;
    WL_LISTS.forEach((l) => {
      const i = wl.state[l.key].findIndex((e) => e.sym === sym);
      if (i >= 0) entry = wl.state[l.key].splice(i, 1)[0];
    });
    entry = entry || { sym, tags: [], added: new Date().toISOString().slice(0, 10) };
    if (snap) entry.snap = snap; // last seen values, shown if the stock drops out of today's data
    wl.state[list].unshift(entry);
    wlSave();
    renderLists();
  }

  // "Applovin Corporation - Class A Common Stock" -> "Applovin Corporation"
  const shortName = (n) => String(n || "").replace(/\s+-\s+.*$/, "").replace(/,?\s+(Common Stock|Ordinary Shares|American Depositary Shares).*$/i, "");

  function atrCell(v) {
    if (v == null) return `<td class="num">–</td>`;
    const a = Math.abs(v), cls = a > 8 ? "atr-red" : a > 4 ? "atr-yellow" : "";
    return `<td class="num ${cls}">${v.toFixed(1)}</td>`;
  }

  function wlRow(list, e) {
    const q = wl.quotes[e.sym];
    const [name, close, pct, atr50, thrust, rs1m] = q || [e.snap?.name, e.snap?.close, null, e.snap?.atr50, null, null];
    const stale = !q;
    const ro = canEdit() ? "" : "disabled";
    const tags = TAGS.map((t) => `<button class="tag ${e.tags.includes(t.key) ? "on" : ""}" data-tag="${t.key}" ${ro}
        title="${t.tip ? `${t.label} – ${t.tip}` : t.label}">${t.icon}</button>`).join("");
    return `<tr draggable="${canEdit()}" data-sym="${escapeHtml(e.sym)}" class="${stale ? "stale" : ""}"
        title="${stale ? "冇今日數據（唔夠流動性或者 ticker 唔啱），顯示上次見到嘅數" : ""}">
      <td class="tags">${tags}</td>
      <td class="ticker" title="${escapeHtml(shortName(name))}"><a href="https://finance.yahoo.com/quote/${encodeURIComponent(e.sym)}" target="_blank" rel="noopener">${escapeHtml(e.sym)}</a></td>
      <td class="num">${close == null ? "–" : fmtNum(close)}</td>
      <td class="num ${signClass(pct)}">${fmtPct(pct, 1)}</td>
      <td class="heat" style="${heatStyle(thrust)}">${fmtScore(thrust)}</td>
      <td class="heat" style="${heatStyle(rs1m)}">${fmtScore(rs1m)}</td>
      ${atrCell(atr50)}
      <td class="added">${escapeHtml(e.added.slice(5))}</td>
      <td><button class="rm" title="Remove">×</button></td>
    </tr>`;
  }

  // Light up the T / F / S marks on scanner rows for stocks already in a list.
  function syncScanMarks() {
    const where = new Map();
    WL_LISTS.forEach((l) => wl.state[l.key].forEach((e) => where.set(e.sym, l.key)));
    $$("#scan-cols .scan-item").forEach((a) => {
      const inList = where.get(a.dataset.sym);
      $$(".wl-mark", a).forEach((m) => {
        const l = WL_LISTS.find((x) => x.key === m.dataset.list);
        const on = inList === l.key;
        m.classList.toggle("on", on);
        m.title = canEdit()
          ? (on ? `喺 ${l.title} 度 · 撳嚟移除` : `加入 ${l.title}`)
          : (on ? `喺 ${l.title} 度` : l.title);
      });
    });
  }

  function wlToggle(list, sym, snap) {
    if (!canEdit()) return;
    const arr = wl.state[list], i = arr.findIndex((e) => e.sym === sym);
    if (i >= 0) {
      arr.splice(i, 1);
      wlSave();
      renderLists();
    } else {
      wlAdd(list, sym, snap); // moves it out of any other list
    }
  }

  function renderLists() {
    syncScanMarks();
    WL_LISTS.forEach((l) => {
      const box = $(`.wl[data-list="${l.key}"]`), items = wl.state[l.key];
      $(".wl-count", box).textContent = items.length;
      $("tbody", box).innerHTML = items.map((e) => wlRow(l.key, e)).join("")
        || `<tr><td colspan="9" class="empty">${!canEdit() ? "Empty" : l.key === "today" ? "打 ticker 加" : "拖 stock 落嚟"}</td></tr>`;
    });
  }

  function initLists() {
    wlLoad();
    $("#wl-legend").innerHTML = TAGS.map((t) => `${t.icon} ${t.label}${t.tip ? ` = ${t.tip}` : ""}`).join(" · ")
      + ` · 撳 icon 開 / 熄 · RS Thrust % / 1-Mth RS % = 今日 RS（÷ RSP）高過之前 6 / 20 日嘅比例 · ATR× = (收市 − daily 50 EMA) ÷ ATR(28)，&gt;4 黃、&gt;8 紅 · 行可以喺 list 之間拖（一隻股票只會喺一個 list）`;
    WL_LISTS.forEach((l) => {
      const box = $(`.wl[data-list="${l.key}"]`);
      box.style.setProperty("--c", l.color);
      box.innerHTML = `
        <div class="wl-head"><span class="wl-title">${l.title}</span><span class="wl-count">0</span>
          <form class="wl-add"><input placeholder="+ Ticker" maxlength="10" aria-label="Add ticker to ${l.title}"></form></div>
        <div class="table-wrap"><table class="wl-table"><thead><tr>
          <th>Remarks</th><th>Ticker</th><th class="num">Close</th><th class="num">% 1D</th>
          <th class="num" title="今日 RS（股價 ÷ RSP）高過之前 1–6 日嘅比例">RS Thrust %</th>
          <th class="num" title="今日 RS（股價 ÷ RSP）高過之前 1–20 日嘅比例">1-Mth RS %</th>
          <th class="num" title="(Close − daily 50 EMA) ÷ ATR(28)">ATR×</th><th>Added</th><th></th>
        </tr></thead><tbody></tbody></table></div>`;
      $("form", box).addEventListener("submit", (ev) => {
        ev.preventDefault();
        const inp = $("input", box);
        inp.value.split(/[\s,]+/).forEach((s) => s && wlAdd(l.key, s));
        inp.value = "";
      });
      box.addEventListener("click", (ev) => {
        const tr = ev.target.closest("tr[data-sym]");
        if (!tr || !canEdit()) return;
        const list = wl.state[l.key], i = list.findIndex((e) => e.sym === tr.dataset.sym);
        if (i < 0) return;
        const tag = ev.target.closest(".tag");
        if (tag) {
          const t = tag.dataset.tag, tags = list[i].tags;
          list[i].tags = tags.includes(t) ? tags.filter((x) => x !== t) : [...tags, t];
        } else if (ev.target.closest(".rm")) {
          list.splice(i, 1);
        } else return;
        wlSave();
        renderLists();
      });
      box.addEventListener("dragstart", (ev) => {
        const tr = ev.target.closest && ev.target.closest("tr[data-sym]");
        if (tr) ev.dataTransfer.setData(DRAG_TYPE, tr.dataset.sym);
      });
      box.addEventListener("dragover", (ev) => {
        if (!canEdit() || !ev.dataTransfer.types.includes(DRAG_TYPE)) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "copy";
        box.classList.add("drop");
      });
      box.addEventListener("dragleave", (ev) => { if (!box.contains(ev.relatedTarget)) box.classList.remove("drop"); });
      box.addEventListener("drop", (ev) => {
        ev.preventDefault();
        box.classList.remove("drop");
        const sym = ev.dataTransfer.getData(DRAG_TYPE);
        let snap = null;
        try { snap = JSON.parse(ev.dataTransfer.getData(DRAG_TYPE + "+snap") || "null"); } catch (_) { /* none */ }
        if (sym) wlAdd(l.key, sym, snap);
      });
    });

    $("#scan-cols").addEventListener("click", (ev) => {
      const m = ev.target.closest(".wl-mark");
      if (!m) return;
      ev.preventDefault();
      ev.stopPropagation();
      const a = m.closest(".scan-item");
      let snap = null;
      try { snap = JSON.parse(a.dataset.snap || "null"); } catch (_) { /* none */ }
      wlToggle(m.dataset.list, a.dataset.sym, snap);
    });

    // scanner items are the drag source
    $("#scan-cols").addEventListener("dragstart", (ev) => {
      const a = ev.target.closest && ev.target.closest(".scan-item");
      if (!a) return;
      ev.dataTransfer.setData(DRAG_TYPE, a.dataset.sym);
      ev.dataTransfer.setData(DRAG_TYPE + "+snap", a.dataset.snap || "null");
      ev.dataTransfer.effectAllowed = "copy";
    });

    $("#wl-export").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(wl.state, null, 2)], { type: "application/json" });
      const a = Object.assign(document.createElement("a"), {
        href: URL.createObjectURL(blob), download: `rs-watchlists-${new Date().toISOString().slice(0, 10)}.json`,
      });
      a.click();
      URL.revokeObjectURL(a.href);
    });
    $("#wl-import").addEventListener("change", async (ev) => {
      const f = ev.target.files[0];
      ev.target.value = "";
      if (!f || !canEdit()) return;
      try {
        const s = JSON.parse(await f.text());
        if (!WL_LISTS.some((l) => Array.isArray(s[l.key]))) throw new Error("not a watchlist file");
        if (!confirm("用呢個 file 取代而家嘅 Today / Focus / Stalk list？")) return;
        wl.state = normState(s);
        wlSave();
        renderLists();
      } catch (err) {
        alert("Import 唔到：" + err.message);
      }
    });
    $("#wl-connect").addEventListener("click", ghConnect);
    applyMode();
    ghLoad();
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
  setInterval(() => calData && renderCalendar(), 60 * 1000); // drop items as they pass while the page is open
  initLists();
  Promise.all([load("scanner.json"), load().catch(() => null)]).then(([scan, latest]) => {
    const strong = new Map((latest ? latest.rows : [])
      .filter((r) => r.status === "ok" && r.group === "Sectors / Themes" && r.rs_1m >= SECTOR_MIN_RS1M)
      .map((r) => [r.ticker, r.rs_1m]));
    renderScanner(scan, strong);
    syncScanMarks();
    wl.quotes = scan.quotes || {};
    renderLists();
  }).catch(scannerUnavailable);
})();
