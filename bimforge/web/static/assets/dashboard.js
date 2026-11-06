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
 *
 * The BASIS the pay follows is chosen on the page: all cost (default), or
 * one kind of it (labour, material, equipment: each IfcCostValue's
 * Category, costs.shares[].categories / costs.tasks[].categories), or
 * labour hours. A kind that is zero everywhere for an element falls back
 * to all cost, so a material-only item is never earned on nothing.
 */
const CATS = ["Labor", "Material", "Equipment", "Subcontract", "Other"];
const CAT_LABEL = { Labor: "Labour", Material: "Material", Equipment: "Equipment", Subcontract: "Subcontract", Other: "Other" };
const CAT_COLOR = { Labor: "#f0883e", Material: "#a371f7", Equipment: "#39c5cf", Subcontract: "#db61a2", Other: "#8b949e" };
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
  // calendars: the schedule's own, and the named ones a task may use
  // (read_schedule: work_weekdays 0 = Monday, holidays as days, blackouts
  // as yearly MM-DD windows, inclusive, wrapping the year end)
  const projectCal = { work_weekdays: S && S.work_weekdays ? S.work_weekdays : [0, 1, 2, 3, 4],
    holidays: new Set(S && S.holidays ? S.holidays : []), blackouts: [] };
  const calendars = {};
  Object.keys(S && S.calendars ? S.calendars : {}).forEach(function (name) {
    const c = S.calendars[name];
    calendars[name] = { work_weekdays: c.work_weekdays || projectCal.work_weekdays,
      holidays: new Set(c.holidays || []), blackouts: c.blackouts || [] };
  });
  function calendarFor(t) { return (t.calendar && calendars[t.calendar]) || projectCal; }
  function inBlackout(iso, windows) {
    const md = iso.slice(5);
    return windows.some(function (w) {
      if (!w || !w.from || !w.to) return false;
      return w.from <= w.to ? (md >= w.from && md <= w.to) : (md >= w.from || md <= w.to);
    });
  }

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
  function isWorkDay(iso, cal) {
    const wd = (BF.parse(iso).getUTCDay() + 6) % 7;        // Monday = 0
    return cal.work_weekdays.indexOf(wd) >= 0 && !cal.holidays.has(iso) && !inBlackout(iso, cal.blackouts);
  }
  const taskDayCache = {};
  function taskDays(t) {
    if (taskDayCache[t.id]) return taskDayCache[t.id];
    const s = t.start, f = t.finish || t.start;
    let out = [];
    if (s) {
      const cal = calendarFor(t);
      const n = Math.max(1, BF.daysBetween(s, f) + 1);
      for (let i = 0; i < n; i++) { const d = BF.addDays(s, i); if (isWorkDay(d, cal)) out.push(d); }
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
  const catDaily = {}, catTotal = {};
  CATS.forEach(function (c) { catDaily[c] = new Float64Array(span + 1); catTotal[c] = 0; });
  tasks.forEach(function (t) {
    const c = taskCost[t.id]; if (!c || !c.categories) return;
    CATS.forEach(function (k) { const a = c.categories[k] || 0; if (a) { catTotal[k] += a; spread(catDaily[k], t, a); } });
  });
  const catCum = {}; CATS.forEach(function (c) { catCum[c] = cumulative(catDaily[c]); });
  const catsPresent = CATS.filter(function (c) { return catTotal[c] > 0; });

  // ---- what builds each element: its appear-type tasks, and the cost
  //      shares spent on it (element -> task -> {item -> cost, any})
  const elTasks = {};
  Object.keys(taskEls).forEach(function (tid) {
    const t = taskById[tid]; if (!t || !t.start) return;
    const k = (t.task_type || "NOTDEFINED").toUpperCase();
    if (!APPEAR[k]) return;                                 // only what BUILDS it: not operation, logistics, removal
    taskEls[tid].forEach(function (g) { (elTasks[g] || (elTasks[g] = [])).push(t); });
  });
  const elShare = {};                                     // g -> tid -> {item -> cost, _any, _cat: {kind -> cost}}
  shares.forEach(function (sh) {
    if (!sh.element) return;
    const byTask = elShare[sh.element] || (elShare[sh.element] = {});
    const rec = byTask[sh.task] || (byTask[sh.task] = { _any: 0, _cat: {}, _hours: null });
    rec._any += sh.cost || 0;
    if (sh.labor_hours != null) rec._hours = (rec._hours || 0) + sh.labor_hours;
    const keys = [sh.item_number, sh.code].filter(Boolean);
    keys.forEach(function (k) { rec[k] = (rec[k] || 0) + (sh.cost || 0); });
    CATS.forEach(function (c) { const a = (sh.categories || {})[c] || 0; if (a) rec._cat[c] = (rec._cat[c] || 0) + a; });
  });
  let basis = "cost";                                     // cost | Labor | Material | Equipment | Subcontract | Other | hours
  function kindWeight(g, t) {                             // the chosen kind's money, or null when none is recorded
    const sh = (elShare[g] || {})[t.id];
    if (sh) return sh._cat[basis] || 0;                   // the element's own share: a zero is a zero
    const c = taskCost[t.id];                             // no element share: the task's kind
    if (c && c.categories && c.categories[basis]) return c.categories[basis];
    return null;
  }
  function weightsFor(g, ts, row) {                       // the kind, else all cost, else even
    let w = ts.map(function (t) { return taskWeight(g, t, row); });
    if (basis !== "cost" && !w.some(function (x) { return x; })) {
      const saved = basis; basis = "cost"; w = ts.map(function (t) { return taskWeight(g, t, row); }); basis = saved;
    }
    return w.map(function (x) { return x || 0; });
  }
  function taskWeight(g, t, row) {
    if (basis === "hours") {
      const sh = (elShare[g] || {})[t.id];
      if (sh && sh._hours != null) return sh._hours;      // the element's own hours in this task
      const c = taskCost[t.id];
      return c && c.labor_hours ? c.labor_hours : null;
    }
    if (basis !== "cost") return kindWeight(g, t);
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
  let earned, priced, payTotal, cumPay, undatedPay;
  function computeEarned() {
    earned = rows.map(function (row) {
      const arr = new Float64Array(span + 1);
      let byTask = 0, byAppear = 0, undated = 0;
      row.elements.forEach(function (e) {
        const q = e.quantity || 0; if (!q) return;
        const ts = elTasks[e.global_id] || [];
        if (ts.length) {
          const w = weightsFor(e.global_id, ts, row);
          const W = w.reduce(function (s, x) { return s + x; }, 0);
          ts.forEach(function (t, i) { spread(arr, t, q * (W ? w[i] / W : 1 / ts.length)); });
          byTask += q;
        } else if ((E[e.global_id] || {}).appear) {
          const i = idx(E[e.global_id].appear); if (i >= 0 && i <= span) arr[i] += q; byAppear += q;
        } else undated += q;
      });
      return { row: row, cum: cumulative(arr), byTask: byTask, byAppear: byAppear, undated: undated,
        priced: row.unit_price != null };
    });
    priced = earned.filter(function (x) { return x.priced; });
    payTotal = priced.reduce(function (s, x) { return s + (x.row.bid_total != null ? x.row.bid_total : x.row.quantity * x.row.unit_price); }, 0);
    cumPay = new Float64Array(span + 1);
    priced.forEach(function (x) { for (let i = 0; i <= span; i++) cumPay[i] += x.cum[i] * x.row.unit_price; });
    undatedPay = priced.reduce(function (s, x) { return s + x.undated * x.row.unit_price; }, 0);
  }
  computeEarned();
  const basisSel = document.getElementById("basis");
  [["cost", "all cost"]].concat(catsPresent.map(function (c) { return [c, CAT_LABEL[c] + " $"]; }))
    .concat(hoursTotal ? [["hours", "labour hours"]] : []).forEach(function (o) {
      basisSel.appendChild(BF.h("option", { value: o[0] }, "Earn against " + BF.esc(o[1])));
    });
  basisSel.addEventListener("change", function () { basis = basisSel.value; computeEarned(); setDay(day, true); });
  // cost of each pay item, through the shares: a share with a bid item
  // number goes to that item's row; a share with none goes to the rows of
  // its cost code, shared out equally among them (the one rule that never
  // counts a dollar twice); spent over its task's working days
  const rowsByItem = {}, rowsByCode = {};
  rows.forEach(function (r, i) {
    if (r.item_number) (rowsByItem[r.item_number] || (rowsByItem[r.item_number] = [])).push(i);
    (rowsByCode[r.cost_code] || (rowsByCode[r.cost_code] = [])).push(i);
  });
  const rowCostDaily = rows.map(function () { return new Float64Array(span + 1); });
  const rowCostTotal = rows.map(function () { return 0; });
  shares.forEach(function (sh) {
    const t = taskById[sh.task]; if (!t) return;
    const targets = (sh.item_number && rowsByItem[sh.item_number]) || rowsByCode[sh.code] || [];
    if (!targets.length) return;
    const each = (sh.cost || 0) / targets.length;
    targets.forEach(function (ri) { rowCostTotal[ri] += each; spread(rowCostDaily[ri], t, each); });
  });
  const rowCostCum = rowCostDaily.map(cumulative);
  function rowCostTo(row, i) { return rowCostCum[rows.indexOf(row)][i]; }

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
      ["Cost to date", C ? BF.money(cumCost[i]) : "—", C ? "of " + BF.money(costTotal) + " (" + BF.fmt(costTotal ? 100 * cumCost[i] / costTotal : 0, 0) + "%)" +
        (catsPresent.length ? "<br>" + catsPresent.map(function (c) { return CAT_LABEL[c][0] + " " + BF.money(catCum[c][i]); }).join(" \u00b7 ") : "") : "no cost schedule"],
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
      tip.show("<b>" + dayAt(ii) + "</b><br>" + series.map(function (s) { return BF.esc(s.label) + ": " + BF.esc(s.fmt(s.data[ii])); }).join("<br>"), ev);
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
      catsPresent.forEach(function (c) {
        series.push({ data: catCum[c], max: top, scale: 1, color: CAT_COLOR[c], dash: "5 3", label: CAT_LABEL[c] + " $", fmt: BF.money });
      });
      series.push({ data: cumHours, max: top, scale: (hoursTotal ? top / hoursTotal : 0) * 0.9, color: "var(--milestone)", dash: "1 3", label: "Labour hours", fmt: function (v) { return BF.fmt(v, 0) + " h"; } });
    }
    lineChart(svg, series, { fmt: BF.money });
    const i = idx(day);
    lg.innerHTML = (priced.length ? '<span><i style="background:var(--ok)"></i>earned ' + BF.money(cumPay[i]) + " / " + BF.money(payTotal) + "</span>" : "") +
      (C ? '<span><i style="background:var(--accent)"></i>cost ' + BF.money(cumCost[i]) + " / " + BF.money(costTotal) + "</span>" +
        catsPresent.map(function (c) { return '<span><i style="background:' + CAT_COLOR[c] + '"></i>' + CAT_LABEL[c].toLowerCase() + " " + BF.money(catCum[c][i]) + " / " + BF.money(catTotal[c]) + "</span>"; }).join("") +
        '<span><i style="background:var(--milestone)"></i>labour ' + BF.fmt(cumHours[i], 0) + " / " + BF.fmt(hoursTotal, 0) + " h (own scale)</span>" : "");
    const parts = [];
    if (basis !== "cost") parts.push("pay follows " + (basis === "hours" ? "labour hours" : CAT_LABEL[basis].toLowerCase() + " cost") + " in the tasks that build each element (all cost where none is recorded)");
    else
    if (shares.some(function (s) { return s.element; })) parts.push("pay follows each element's cost shares in the tasks that build it (the estimate's activities)");
    else if (C) parts.push("pay follows each element's tasks, weighted by the task's cost under the item's code, else its hours");
    else parts.push("pay follows each element's tasks, evenly");
    if (!catsPresent.length && C) parts.push("the cost schedule records no labour / material / equipment split");
    if (C && shares.length) parts.push("an item's cost is its bid item's shares, or its code's shares shared equally among the items of that code");
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
      const g = BF.svg("g", { class: "taskrow" + (t.id === selectedTask ? " selected" : ""), "data-id": t.id,
        tabindex: "0", role: "button", "aria-label": (t.name || t.id) + (t.start ? ", " + t.start + " to " + (t.finish || t.start) : "") });
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
      g.onclick = function () { selectedTask = t.id; refocus = document.activeElement === g; renderGantt(); renderTask(t); };
      g.onkeydown = function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); refocus = true; g.onclick(); } };
      gantt.appendChild(g);
    });
    renderGanttLine();
    if (refocus) {                                          // keep the keyboard on the row it chose
      const sel = gantt.querySelector(".taskrow.selected"); if (sel) sel.focus();
      refocus = false;
    }
  }
  let refocus = false;
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
