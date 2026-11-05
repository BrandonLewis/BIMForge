/* The 4D/5D dashboard: a Gantt of the IfcWorkSchedule, cost and labour from
 * the IfcCostSchedule, pay EARNED as the work is done, and what stands on
 * a scrubbed day.
 *
 * Pay follows the labour, the tasks and the materials. An element's pay
 * quantity is earned over the tasks that build it, in proportion to the
 * cost the 5D schedule spends on that element in each task (costs.shares:
 * the estimate's activity shares), else the task's cost under the pay
 * item's code, else its labour hours, else its cost, else evenly; within a
 * task, evenly over its working days. An element no dated task builds is
 * earned on its appear date, and one with neither is reported as undated.
 * Earned dollars are the earned quantity at the bid item's unit price.
 */
(function () {
  "use strict";
  const b = BF.bundle(); BF.header("dashboard.html");
  const E = b.elements;
  const S = b.schedule;
  const C = b.costs;
  const tasks = S ? S.tasks : [];
  const taskById = {}; tasks.forEach(function (t) { taskById[t.id] = t; });
  const taskEls = S ? (S.task_elements || {}) : {};
  const taskCost = C ? (C.tasks || {}) : {};
  const shares = C ? (C.shares || []) : [];
  const APPEAR = { CONSTRUCTION: 1, INSTALLATION: 1, NOTDEFINED: 1 };
  const REMOVE = { DEMOLITION: 1, DISMANTLE: 1, DISPOSAL: 1, REMOVAL: 1 };
  const workWeekdays = S && S.work_weekdays ? S.work_weekdays : [0, 1, 2, 3, 4];   // 0 = Monday
  const holidays = new Set(S && S.holidays ? S.holidays : []);

  // ---- the time axis: the schedule's span, else the elements' dates
  let days = [];
  tasks.forEach(function (t) { if (t.start) days.push(t.start); if (t.finish) days.push(t.finish); });
  Object.values(E).forEach(function (e) { if (e.appear) days.push(e.appear); if (e.vanish) days.push(e.vanish); });
  days.sort();
  if (!days.length) {
    document.querySelector("main").innerHTML = '<div class="panel"><h2>No dates in this model</h2>' +
      "<p>The dashboard needs an IfcWorkSchedule (est-bim schedule) or dated elements. The <a href=\"takeoff.html\">takeoff</a> still works.</p></div>";
    return;
  }
  const t0 = BF.addDays(days[0], -7), t1 = BF.addDays(days[days.length - 1], 14);
  const span = BF.daysBetween(t0, t1);
  const dayAt = function (i) { return BF.addDays(t0, i); };
  const idx = function (iso) { return BF.daysBetween(t0, iso); };

  // ---- working days of a task (the schedule's week and holidays)
  function isWorkDay(iso) {
    const wd = (BF.parse(iso).getUTCDay() + 6) % 7;        // Monday = 0
    return workWeekdays.indexOf(wd) >= 0 && !holidays.has(iso);
  }
  const taskDayCache = {};
  function taskDays(t) {
    if (taskDayCache[t.id]) return taskDayCache[t.id];
    const s = t.start, f = t.finish || t.start;
    let out = [];
    if (s) {
      const n = Math.max(1, BF.daysBetween(s, f) + 1);
      for (let i = 0; i < n; i++) { const d = BF.addDays(s, i); if (isWorkDay(d)) out.push(d); }
      if (!out.length) out = [s];                           // a weekend task still spends its day
    }
    return (taskDayCache[t.id] = out);
  }
  function spread(arr, t, amount) {                        // amount over the task's working days
    const ds = taskDays(t); if (!ds.length || !amount) return false;
    const per = amount / ds.length;
    ds.forEach(function (d) { const i = idx(d); if (i >= 0 && i <= span) arr[i] += per; });
    return true;
  }
  function cumulative(arr) { const out = new Float64Array(arr.length); let s = 0; for (let i = 0; i < arr.length; i++) { s += arr[i]; out[i] = s; } return out; }

  // ---- cost and labour, daily
  const cost = new Float64Array(span + 1), hours = new Float64Array(span + 1);
  let costTotal = 0, hoursTotal = 0;
  tasks.forEach(function (t) {
    const c = taskCost[t.id]; if (!c) return;
    costTotal += c.cost || 0; hoursTotal += c.labor_hours || 0;
    spread(cost, t, c.cost || 0); spread(hours, t, c.labor_hours || 0);
  });
  const cumCost = cumulative(cost), cumHours = cumulative(hours);

  // ---- what builds each element: its appear-type tasks, and the cost
  //      shares spent on it (element -> task -> {item -> cost, any})
  const elTasks = {};
  Object.keys(taskEls).forEach(function (tid) {
    const t = taskById[tid]; if (!t || !t.start) return;
    const k = (t.task_type || "NOTDEFINED").toUpperCase();
    if (REMOVE[k]) return;
    taskEls[tid].forEach(function (g) { (elTasks[g] || (elTasks[g] = [])).push(t); });
  });
  const elShare = {};                                     // g -> tid -> {item -> cost, _any}
  shares.forEach(function (sh) {
    if (!sh.element) return;
    const byTask = elShare[sh.element] || (elShare[sh.element] = {});
    const rec = byTask[sh.task] || (byTask[sh.task] = { _any: 0 });
    rec._any += sh.cost || 0;
    const keys = [sh.item_number, sh.code].filter(Boolean);
    keys.forEach(function (k) { rec[k] = (rec[k] || 0) + (sh.cost || 0); });
  });
  function taskWeight(g, t, row) {
    const sh = (elShare[g] || {})[t.id];
    if (sh) {
      if (row.item_number && sh[row.item_number]) return sh[row.item_number];
      if (sh[row.cost_code]) return sh[row.cost_code];
      if (sh._any) return sh._any;
    }
    const c = taskCost[t.id];
    if (c) {
      if (c.costs && c.costs[row.cost_code] && c.costs[row.cost_code].cost) return c.costs[row.cost_code].cost;
      if (c.labor_hours) return c.labor_hours;
      if (c.cost) return c.cost;
    }
    return 1;
  }

  // ---- earned pay quantity per row, daily; and earned dollars
  const rows = b.takeoff.rows;
  const earned = rows.map(function (row) {
    const arr = new Float64Array(span + 1);
    let byTask = 0, byAppear = 0, undated = 0;
    row.elements.forEach(function (e) {
      const q = e.quantity || 0; if (!q) return;
      const ts = elTasks[e.global_id] || [];
      if (ts.length) {
        const w = ts.map(function (t) { return taskWeight(e.global_id, t, row); });
        const W = w.reduce(function (s, x) { return s + x; }, 0) || ts.length;
        ts.forEach(function (t, i) { spread(arr, t, q * (W ? w[i] / W : 1 / ts.length)); });
        byTask += q;
      } else if ((E[e.global_id] || {}).appear) {
        const i = idx(E[e.global_id].appear); if (i >= 0 && i <= span) arr[i] += q; byAppear += q;
      } else undated += q;
    });
    return { row: row, cum: cumulative(arr), byTask: byTask, byAppear: byAppear, undated: undated,
      priced: row.unit_price != null };
  });
  const priced = earned.filter(function (x) { return x.priced; });
  const payTotal = priced.reduce(function (s, x) { return s + (x.row.bid_total != null ? x.row.bid_total : x.row.quantity * x.row.unit_price); }, 0);
  const cumPay = new Float64Array(span + 1);
  priced.forEach(function (x) { for (let i = 0; i <= span; i++) cumPay[i] += x.cum[i] * x.row.unit_price; });
  const undatedPay = priced.reduce(function (s, x) { return s + x.undated * x.row.unit_price; }, 0);
  // cost under each row's code, for the per-item margin
  function rowCostTo(row, i) {
    let s = 0;
    tasks.forEach(function (t) {
      const c = taskCost[t.id]; if (!c || !c.costs || !c.costs[row.cost_code]) return;
      const ds = taskDays(t); if (!ds.length) return;
      const per = c.costs[row.cost_code].cost / ds.length;
      ds.forEach(function (d) { if (idx(d) <= i) s += per; });
    });
    return s;
  }

  // ---- scrubber
  const scrub = document.getElementById("scrub"), scrubDate = document.getElementById("scrubdate"), scrubDay = document.getElementById("scrubday");
  scrub.max = span; scrubDate.min = t0; scrubDate.max = t1;
  let day = BF.today(); if (day < t0 || day > t1) day = days[0];
  function setDay(d, fromHost) {
    day = d < t0 ? t0 : d > t1 ? t1 : d;
    scrub.value = idx(day); scrubDate.value = day; scrubDay.textContent = day;
    renderTiles(); renderCost(); renderQty(); renderPayRows(); renderGanttLine(); renderStanding();
    if (!fromHost) BF.gotoDate(day);
  }
  scrub.addEventListener("input", function () { setDay(dayAt(+scrub.value)); });
  scrubDate.addEventListener("change", function () { if (scrubDate.value) setDay(scrubDate.value); });
  document.getElementById("totoday").addEventListener("click", function () { setDay(BF.today()); });
  window.addEventListener("bimforge:date", function (ev) { if (ev.detail) setDay(ev.detail, true); });

  function standingOn(d) {
    const up = [], gone = [];
    Object.keys(E).forEach(function (g) {
      const e = E[g];
      if (e.vanish && e.vanish <= d) { gone.push(g); return; }
      if (!e.appear || e.appear <= d) up.push(g);
    });
    return { up: up, gone: gone };
  }
  document.getElementById("selstanding").addEventListener("click", function () {
    BF.select(standingOn(day).up, "standing on " + day);
  });

  // ---- tiles
  function renderTiles() {
    const i = idx(day);
    const st = standingOn(day);
    const active = tasks.filter(function (t) { return t.start && t.start <= day && (t.finish || t.start) >= day; });
    const margin = cumPay[i] - cumCost[i];
    const tiles = [
      ["Earned to date", priced.length ? BF.money(cumPay[i]) : "—",
        priced.length ? "of " + BF.money(payTotal) + " (" + BF.fmt(payTotal ? 100 * cumPay[i] / payTotal : 0, 0) + "%) on " + priced.length + " priced item" + (priced.length === 1 ? "" : "s") : "no unit prices (bid list or estimate)"],
      ["Cost to date", C ? BF.money(cumCost[i]) : "—", C ? "of " + BF.money(costTotal) + " (" + BF.fmt(costTotal ? 100 * cumCost[i] / costTotal : 0, 0) + "%)" : "no cost schedule"],
      ["Margin to date", priced.length && C ? '<span class="' + (margin < 0 ? "pos" : "neg") + '">' + BF.money(margin) + "</span>" : "—",
        priced.length && C ? (cumPay[i] ? BF.fmt(100 * margin / cumPay[i], 1) + "% of earned" : "") : ""],
      ["Labour to date", C ? BF.fmt(cumHours[i], 0) + " h" : "—", C ? "of " + BF.fmt(hoursTotal, 0) + " h" : ""],
      ["Standing", st.up.length, "of " + Object.keys(E).length + " elements, " + st.gone.length + " removed"],
      ["Active tasks", active.length, S ? "of " + tasks.length + " in " + BF.esc(S.name || "the schedule") : "no schedule"],
    ];
    document.getElementById("tiles").innerHTML = tiles.map(function (t) {
      return '<div class="tile"><div class="k">' + t[0] + '</div><div class="v">' + t[1] + '</div><div class="s">' + t[2] + "</div></div>";
    }).join("");
  }

  // ---- line charts
  function lineChart(svg, series, opts) {
    const W = 640, H = +svg.getAttribute("viewBox").split(" ")[3], L = 56, R = 12, T = 10, B = 26;
    svg.innerHTML = "";
    const max = Math.max(1e-9, ...series.map(function (s) { return s.max; }));
    const x = function (i) { return L + (W - L - R) * i / span; };
    const y = function (v) { return T + (H - T - B) * (1 - v / max); };
    for (let m = BF.parse(t0); m <= BF.parse(t1); m.setUTCMonth(m.getUTCMonth() + 1)) {
      const iso = BF.day(new Date(Date.UTC(m.getUTCFullYear(), m.getUTCMonth(), 1)));
      if (iso < t0 || iso > t1) continue;
      const i = idx(iso);
      svg.appendChild(BF.svg("line", { x1: x(i), x2: x(i), y1: T, y2: H - B, stroke: "var(--line)" }));
      const tx = BF.svg("text", { x: x(i) + 3, y: H - 8, fill: "var(--muted)", "font-size": "11" }); tx.textContent = BF.monthLabel(iso); svg.appendChild(tx);
    }
    [0, 0.5, 1].forEach(function (f) {
      svg.appendChild(BF.svg("line", { x1: L, x2: W - R, y1: y(max * f), y2: y(max * f), stroke: "var(--line)" }));
      const tx = BF.svg("text", { x: L - 6, y: y(max * f) + 4, "text-anchor": "end", fill: "var(--muted)", "font-size": "11" });
      tx.textContent = opts.fmt(max * f); svg.appendChild(tx);
    });
    series.forEach(function (s) {
      let dpath = "";
      for (let i = 0; i <= span; i++) dpath += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(s.data[i] * s.scale).toFixed(1);
      svg.appendChild(BF.svg("path", { d: dpath, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-dasharray": s.dash || "" }));
    });
    const i = idx(day);
    svg.appendChild(BF.svg("line", { x1: x(i), x2: x(i), y1: T, y2: H - B, stroke: "var(--bad)", "stroke-width": 1.5 }));
    const ti = idx(BF.today());
    if (ti >= 0 && ti <= span) svg.appendChild(BF.svg("line", { x1: x(ti), x2: x(ti), y1: T, y2: H - B, stroke: "var(--warn)", "stroke-dasharray": "3 3" }));
    const tip = BF.tip();
    svg.onmousemove = function (ev) {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) / r.width * W;
      const ii = Math.max(0, Math.min(span, Math.round((px - L) / (W - L - R) * span)));
      tip.show("<b>" + dayAt(ii) + "</b><br>" + series.map(function (s) { return s.label + ": " + s.fmt(s.data[ii]); }).join("<br>"), ev);
    };
    svg.onmouseleave = function () { tip.hide(); };
  }
  function renderCost() {
    const svg = document.getElementById("costchart"), lg = document.getElementById("costlegend"), note = document.getElementById("earnnote");
    if (!C && !priced.length) { svg.innerHTML = ""; lg.innerHTML = '<span class="muted">No IfcCostSchedule (est-bim cost5d) and no unit prices in this model.</span>'; note.textContent = ""; return; }
    // modelled quantity can beat the bid quantity, so the earned curve can
    // end above the bid total: the axis follows whichever is higher
    const top = Math.max(costTotal, payTotal, cumPay[span]) || 1;
    const series = [];
    if (priced.length) series.push({ data: cumPay, max: top, scale: 1, color: "var(--ok)", label: "Earned pay", fmt: BF.money });
    if (C) {
      series.push({ data: cumCost, max: top, scale: 1, color: "var(--accent)", label: "Cost", fmt: BF.money });
      series.push({ data: cumHours, max: top, scale: (hoursTotal ? top / hoursTotal : 0) * 0.9, color: "var(--milestone)", dash: "4 3", label: "Labour hours", fmt: function (v) { return BF.fmt(v, 0) + " h"; } });
    }
    lineChart(svg, series, { fmt: BF.money });
    const i = idx(day);
    lg.innerHTML = (priced.length ? '<span><i style="background:var(--ok)"></i>earned ' + BF.money(cumPay[i]) + " / " + BF.money(payTotal) + "</span>" : "") +
      (C ? '<span><i style="background:var(--accent)"></i>cost ' + BF.money(cumCost[i]) + " / " + BF.money(costTotal) + "</span>" +
        '<span><i style="background:var(--milestone)"></i>labour ' + BF.fmt(cumHours[i], 0) + " / " + BF.fmt(hoursTotal, 0) + " h (own scale)</span>" : "");
    const parts = [];
    if (shares.some(function (s) { return s.element; })) parts.push("pay follows each element's cost shares in the tasks that build it (the estimate's activities)");
    else if (C) parts.push("pay follows each element's tasks, weighted by the task's cost under the item's code, else its hours");
    else parts.push("pay follows each element's tasks, evenly");
    if (undatedPay) parts.push(BF.money(undatedPay) + " sits on elements no task dates");
    const notPriced = rows.length - priced.length;
    if (notPriced) parts.push(notPriced + " item" + (notPriced === 1 ? "" : "s") + " without a unit price earn quantity only");
    note.textContent = parts.join(" · ") + ".";
  }
  const paySel = document.getElementById("payitem");
  rows.forEach(function (r, i) {
    paySel.appendChild(BF.h("option", { value: i }, BF.esc((r.item_number ? r.item_number + " " : "") + r.cost_code + " — " + (r.description || "") + " (" + r.unit + ")")));
  });
  paySel.addEventListener("change", renderQty);
  function renderQty() {
    const svg = document.getElementById("qtychart"), lg = document.getElementById("qtylegend");
    if (!rows.length) { svg.innerHTML = ""; lg.innerHTML = '<span class="muted">No pay items.</span>'; return; }
    const x = earned[+paySel.value || 0], r = x.row;
    lineChart(svg, [{ data: x.cum, max: r.quantity || 1, scale: 1, color: "var(--ok)", label: r.cost_code, fmt: function (v) { return BF.fmt(v) + " " + r.unit; } }],
      { fmt: function (v) { return BF.fmt(v, 0); } });
    const i = idx(day);
    lg.innerHTML = '<span><i style="background:var(--ok)"></i>' + BF.fmt(x.cum[i]) + " of " + BF.fmt(r.quantity) + " " + BF.esc(r.unit) + " earned" +
      (r.unit_price != null ? " · " + BF.money(x.cum[i] * r.unit_price) + " at " + BF.money(r.unit_price) + "/" + BF.esc(r.unit) : "") + "</span>" +
      (x.byAppear ? '<span class="muted">' + BF.fmt(x.byAppear) + " " + BF.esc(r.unit) + " earned on an appear date (no task builds it)</span>" : "") +
      (x.undated ? '<span class="warn">' + BF.fmt(x.undated) + " " + BF.esc(r.unit) + " undated</span>" : "");
  }
  function renderPayRows() {
    const i = idx(day);
    const tb = document.querySelector("#payrows tbody");
    let tE = 0, tC = 0;
    const ordered = earned.slice().sort(function (a, b) {
      return String(a.row.item_number || "~").localeCompare(String(b.row.item_number || "~"), undefined, { numeric: true }) ||
        a.row.cost_code.localeCompare(b.row.cost_code);
    });
    tb.innerHTML = ordered.map(function (x) {
      const r = x.row, q = x.cum[i];
      const e$ = r.unit_price != null ? q * r.unit_price : null;
      const c$ = C ? rowCostTo(r, i) : null;
      if (e$ != null) tE += e$; if (c$ != null) tC += c$;
      const m = e$ != null && c$ != null ? e$ - c$ : null;
      return "<tr>" + '<td class="mono">' + BF.esc(r.item_number || "") + '</td><td class="mono">' + BF.esc(r.cost_code) + "</td><td>" + BF.esc(r.description || "") + "</td><td>" + BF.esc(r.unit) + "</td>" +
        '<td class="num">' + BF.fmt(q) + '</td><td class="num">' + BF.fmt(r.quantity) + '</td><td class="num">' + BF.fmt(r.quantity ? 100 * q / r.quantity : 0, 0) + "</td>" +
        '<td class="num">' + (e$ == null ? "—" : BF.money(e$)) + '</td><td class="num">' + (c$ == null ? "—" : BF.money(c$)) + "</td>" +
        '<td class="num ' + (m == null ? "" : m < 0 ? "pos" : "neg") + '">' + (m == null ? "—" : BF.money(m)) + "</td></tr>";
    }).join("");
    document.querySelector("#payrows tfoot").innerHTML = '<tr><td colspan="7" class="muted small">' + rows.length + " pay items on " + day + "</td>" +
      '<td class="num">' + (priced.length ? BF.money(tE) : "—") + '</td><td class="num">' + (C ? BF.money(tC) : "—") + '</td><td class="num">' + (priced.length && C ? BF.money(tE - tC) : "—") + "</td></tr>";
  }

  // ---- Gantt
  const gantt = document.getElementById("gantt");
  const ROW = 22, LEFT = 300, DAY = 4, TOP = 28;
  let selectedTask = null;
  const gstate = { q: "", linked: false };
  function visibleTasks() {
    return tasks.filter(function (t) {
      if (gstate.linked && !(taskEls[t.id] || []).length) return false;
      if (gstate.q) { const q = gstate.q.toLowerCase(); return (t.name || "").toLowerCase().includes(q) || (t.wbs || "").includes(q) || (t.id || "").toLowerCase().includes(q); }
      return true;
    });
  }
  function kind(t) {
    const k = (t.task_type || "NOTDEFINED").toUpperCase();
    return APPEAR[k] ? k : REMOVE[k] ? k : "OTHER";
  }
  function renderGantt() {
    const vis = visibleTasks();
    const W = LEFT + span * DAY + 20, H = TOP + vis.length * ROW + 10;
    gantt.setAttribute("width", W); gantt.setAttribute("height", H); gantt.setAttribute("viewBox", "0 0 " + W + " " + H);
    gantt.innerHTML = "";
    document.getElementById("taskcount").textContent = vis.length + " of " + tasks.length + " tasks";
    const x = function (iso) { return LEFT + idx(iso) * DAY; };
    for (let m = BF.parse(t0); m <= BF.parse(t1); m.setUTCMonth(m.getUTCMonth() + 1)) {
      const iso = BF.day(new Date(Date.UTC(m.getUTCFullYear(), m.getUTCMonth(), 1)));
      if (iso < t0 || iso > t1) continue;
      const g = BF.svg("g", { class: "tick" });
      g.appendChild(BF.svg("line", { x1: x(iso), x2: x(iso), y1: TOP - 6, y2: H }));
      const tx = BF.svg("text", { x: x(iso) + 3, y: 14 }); tx.textContent = BF.monthLabel(iso); g.appendChild(tx);
      gantt.appendChild(g);
    }
    const tip = BF.tip();
    vis.forEach(function (t, i) {
      const y = TOP + i * ROW;
      const g = BF.svg("g", { class: "taskrow" + (t.id === selectedTask ? " selected" : ""), "data-id": t.id });
      const depth = (t.wbs || "").split(".").length - 1;
      const label = BF.svg("text", { x: 8 + depth * 12, y: y + 15, class: "label" });
      const n = (taskEls[t.id] || []).length;
      label.textContent = (t.name || t.id).slice(0, 44) + (n ? "  [" + n + "]" : "");
      g.appendChild(BF.svg("rect", { x: 0, y: y, width: LEFT - 4, height: ROW, fill: "var(--panel)" }));
      g.appendChild(label);
      if (t.start) {
        const c = taskCost[t.id];
        if (t.is_milestone || !t.finish || t.finish === t.start) {
          const cx = x(t.start), cy = y + ROW / 2;
          g.appendChild(BF.svg("path", { d: "M" + cx + " " + (cy - 6) + " l6 6 l-6 6 l-6 -6 z", class: t.is_milestone ? "milestone" : "bar " + kind(t) }));
        } else {
          const isSummary = tasks.some(function (o) { return o.wbs && t.wbs && o !== t && o.wbs.indexOf(t.wbs + ".") === 0; });
          g.appendChild(BF.svg("rect", { x: x(t.start), y: y + (isSummary ? 8 : 5), width: Math.max(2, (BF.daysBetween(t.start, t.finish) + 1) * DAY), height: isSummary ? 6 : ROW - 10, class: (isSummary ? "summary " : "") + "bar " + kind(t) }));
        }
        g.onmousemove = function (ev) {
          tip.show("<b>" + BF.esc(t.name) + "</b> <span class='muted'>" + BF.esc(t.wbs || "") + "</span><br>" + t.start + " → " + (t.finish || t.start) +
            (t.duration_days != null ? " · " + t.duration_days + " d" : "") + " · " + taskDays(t).length + " working days<br>" + BF.esc(t.task_type || "") +
            (c ? "<br>" + BF.money(c.cost) + (c.labor_hours != null ? " · " + BF.fmt(c.labor_hours, 0) + " h" : "") : "") +
            (n ? "<br>" + n + " element" + (n === 1 ? "" : "s") : ""), ev);
        };
        g.onmouseleave = function () { tip.hide(); };
      }
      g.onclick = function () { selectedTask = t.id; renderGantt(); renderTask(t); };
      gantt.appendChild(g);
    });
    renderGanttLine();
  }
  function renderGanttLine() {
    gantt.querySelectorAll(".scrub, .today").forEach(function (n) { n.remove(); });
    const H = +gantt.getAttribute("height") || 0;
    const x = function (iso) { return LEFT + idx(iso) * DAY; };
    gantt.appendChild(BF.svg("line", { x1: x(day), x2: x(day), y1: TOP - 10, y2: H, class: "scrub" }));
    const td = BF.today();
    if (td >= t0 && td <= t1) gantt.appendChild(BF.svg("line", { x1: x(td), x2: x(td), y1: TOP - 10, y2: H, class: "today" }));
  }
  document.getElementById("taskfilter").addEventListener("input", function (ev) { gstate.q = ev.target.value.trim(); renderGantt(); });
  document.getElementById("linked").addEventListener("change", function (ev) { gstate.linked = ev.target.checked; renderGantt(); });

  function renderTask(t) {
    document.getElementById("taskhead").textContent = t.name || t.id;
    const c = taskCost[t.id] || {}, ids = taskEls[t.id] || [];
    const codes = c.costs ? Object.keys(c.costs) : [];
    const mine = shares.filter(function (s) { return s.task === t.id; });
    let html = '<p class="small">' + BF.esc(t.wbs || "") + " · " + (t.start || "?") + " → " + (t.finish || t.start || "?") +
      (t.duration_days != null ? " · " + t.duration_days + " d" : "") + " · " + taskDays(t).length + " working days · " + BF.esc(t.task_type || "") +
      (t.is_milestone ? " · milestone" : "") + "</p>";
    if (c.cost != null) html += "<p>" + BF.money(c.cost) + (c.labor_hours != null ? " · " + BF.fmt(c.labor_hours, 0) + " labour hours" : "") +
      (codes.length ? '<br><span class="small muted">' + codes.map(function (k) { return BF.esc(k) + " " + BF.money(c.costs[k].cost); }).join(" · ") + "</span>" : "") + "</p>";
    if (mine.length) html += '<p class="small muted">' + mine.length + " cost share" + (mine.length === 1 ? "" : "s") + ": " +
      mine.slice(0, 8).map(function (s) { return (s.element && E[s.element] ? BF.esc(E[s.element].name) + " " : "") + (s.item_number ? "item " + BF.esc(s.item_number) + " " : "") + BF.money(s.cost); }).join(" · ") +
      (mine.length > 8 ? " …" : "") + "</p>";
    if (t.dependencies && t.dependencies.length) html += '<p class="small muted">after ' + t.dependencies.map(function (d) { return BF.esc(d.predecessor) + " (" + d.type + (d.lag_days ? " +" + d.lag_days + "d" : "") + ")"; }).join(", ") + "</p>";
    if (t.notes) html += '<p class="small">' + BF.esc(t.notes) + "</p>";
    if (ids.length) {
      html += '<p><button class="primary" id="seltask">Select ' + ids.length + " element" + (ids.length === 1 ? "" : "s") + "</button> " +
        '<button id="gototask">Go to start</button></p><ul class="plain small">' +
        ids.map(function (g) { const e = E[g] || {}; return '<li><a href="#" class="sel-el" data-g="' + BF.esc(g) + '">' + BF.esc(e.name || g) + '</a><span class="muted">' + BF.esc(e.ifc_class || "") + "</span></li>"; }).join("") + "</ul>";
    } else html += '<p class="muted small">This task moves no element.</p>';
    const box = document.getElementById("taskdetail"); box.className = ""; box.innerHTML = html;
    const sb = document.getElementById("seltask"); if (sb) sb.onclick = function () { BF.select(ids, t.name); };
    const gb = document.getElementById("gototask"); if (gb) gb.onclick = function () { if (t.start) setDay(t.start); };
    box.onclick = function (ev) { const a = ev.target.closest("a.sel-el"); if (a) { ev.preventDefault(); BF.select([a.dataset.g], (E[a.dataset.g] || {}).name); } };
  }

  // ---- standing on the day, by class
  function renderStanding() {
    const by = {};
    const weekAgo = BF.addDays(day, -7);
    Object.values(E).forEach(function (e) {
      const r = by[e.ifc_class] || (by[e.ifc_class] = { n: 0, up: 0, week: 0, gone: 0 });
      r.n++;
      const gone = e.vanish && e.vanish <= day;
      if (gone) r.gone++;
      else if (!e.appear || e.appear <= day) { r.up++; if (e.appear && e.appear > weekAgo) r.week++; }
    });
    document.querySelector("#standing tbody").innerHTML = Object.keys(by).sort().map(function (k) {
      const r = by[k];
      return "<tr><td>" + BF.esc(k) + '</td><td class="num">' + r.up + '</td><td class="num">' + r.n + '</td><td class="num">' + (r.week || "") + '</td><td class="num">' + (r.gone || "") + "</td></tr>";
    }).join("");
  }

  document.getElementById("foot").textContent = b.model.generator + " · contract " + b.contract +
    (S ? " · schedule " + (S.name || "") : "");
  renderGantt();
  setDay(day, true);
})();
