/* The 4D/5D dashboard: a Gantt of the IfcWorkSchedule, cumulative cost and
 * labour from the IfcCostSchedule, cumulative pay quantity from the takeoff
 * and each element's appear date, and what stands on a scrubbed day. */
(function () {
  "use strict";
  const b = BF.bundle(); BF.header("dashboard.html");
  const E = b.elements;
  const S = b.schedule;
  const C = b.costs;
  const tasks = S ? S.tasks : [];
  const taskEls = S ? (S.task_elements || {}) : {};
  const taskCost = C ? (C.tasks || {}) : {};
  const APPEAR = { CONSTRUCTION: 1, INSTALLATION: 1, NOTDEFINED: 1 };
  const REMOVE = { DEMOLITION: 1, DISMANTLE: 1, DISPOSAL: 1, REMOVAL: 1 };

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

  // ---- daily series: cost, hours, each pay item's quantity
  function taskDays(t) {
    const s = t.start, f = t.finish || t.start;
    if (!s) return [];
    const n = Math.max(1, BF.daysBetween(s, f) + 1);
    const out = []; for (let i = 0; i < n; i++) out.push(BF.addDays(s, i));
    return out;
  }
  const cost = new Float64Array(span + 1), hours = new Float64Array(span + 1);
  let costTotal = 0, hoursTotal = 0;
  tasks.forEach(function (t) {
    const c = taskCost[t.id]; if (!c) return;
    const ds = taskDays(t); if (!ds.length) return;
    const perC = (c.cost || 0) / ds.length, perH = (c.labor_hours || 0) / ds.length;
    costTotal += c.cost || 0; hoursTotal += c.labor_hours || 0;
    ds.forEach(function (d) { const i = BF.daysBetween(t0, d); if (i >= 0 && i <= span) { cost[i] += perC; hours[i] += perH; } });
  });
  function cumulative(arr) { const out = new Float64Array(arr.length); let s = 0; for (let i = 0; i < arr.length; i++) { s += arr[i]; out[i] = s; } return out; }
  const cumCost = cumulative(cost), cumHours = cumulative(hours);

  const rows = b.takeoff.rows;
  function qtySeries(row) {
    const arr = new Float64Array(span + 1); let dated = 0, undated = 0;
    row.elements.forEach(function (e) {
      const el = E[e.global_id]; const q = e.quantity || 0;
      if (el && el.appear) { const i = BF.daysBetween(t0, el.appear); if (i >= 0 && i <= span) arr[i] += q; dated += q; }
      else undated += q;
    });
    return { cum: cumulative(arr), dated: dated, undated: undated, total: row.quantity };
  }

  // ---- scrubber
  const scrub = document.getElementById("scrub"), scrubDate = document.getElementById("scrubdate"), scrubDay = document.getElementById("scrubday");
  scrub.max = span; scrubDate.min = t0; scrubDate.max = t1;
  let day = BF.today(); if (day < t0 || day > t1) day = days[0];
  function setDay(d, fromHost) {
    day = d < t0 ? t0 : d > t1 ? t1 : d;
    scrub.value = BF.daysBetween(t0, day); scrubDate.value = day; scrubDay.textContent = day;
    renderTiles(); renderCost(); renderQty(); renderGanttLine(); renderStanding();
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
    const i = BF.daysBetween(t0, day);
    const st = standingOn(day);
    const active = tasks.filter(function (t) { return t.start && t.start <= day && (t.finish || t.start) >= day; });
    const tiles = [
      ["Cost to date", C ? BF.money(cumCost[i]) : "—", C ? "of " + BF.money(costTotal) + " (" + BF.fmt(costTotal ? 100 * cumCost[i] / costTotal : 0, 0) + "%)" : "no cost schedule"],
      ["Labour to date", C ? BF.fmt(cumHours[i], 0) + " h" : "—", C ? "of " + BF.fmt(hoursTotal, 0) + " h" : ""],
      ["Standing", st.up.length, "of " + Object.keys(E).length + " elements, " + st.gone.length + " removed"],
      ["Active tasks", active.length, S ? "of " + tasks.length + " in " + BF.esc(S.name || "the schedule") : "no schedule"],
      ["Schedule", S && S.start_date ? S.start_date : days[0], "to " + days[days.length - 1] + " · " + BF.daysBetween(days[0], days[days.length - 1]) + " days"],
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
    // month ticks
    let d = t0.slice(0, 7) + "-01"; if (d < t0) d = BF.addDays(t0, 0);
    for (let m = BF.parse(t0); m <= BF.parse(t1); m.setUTCMonth(m.getUTCMonth() + 1)) {
      const iso = BF.day(new Date(Date.UTC(m.getUTCFullYear(), m.getUTCMonth(), 1)));
      if (iso < t0 || iso > t1) continue;
      const i = BF.daysBetween(t0, iso);
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
      svg.appendChild(BF.svg("path", { d: dpath, fill: "none", stroke: s.color, "stroke-width": 2 }));
    });
    const i = BF.daysBetween(t0, day);
    svg.appendChild(BF.svg("line", { x1: x(i), x2: x(i), y1: T, y2: H - B, stroke: "var(--bad)", "stroke-width": 1.5 }));
    const ti = BF.daysBetween(t0, BF.today());
    if (ti >= 0 && ti <= span) svg.appendChild(BF.svg("line", { x1: x(ti), x2: x(ti), y1: T, y2: H - B, stroke: "var(--warn)", "stroke-dasharray": "3 3" }));
    // hover readout
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
    const svg = document.getElementById("costchart");
    if (!C) { svg.innerHTML = ""; document.getElementById("costlegend").innerHTML = '<span class="muted">No IfcCostSchedule in this model (est-bim cost5d).</span>'; return; }
    const hm = hoursTotal || 1, cm = costTotal || 1;
    lineChart(svg, [
      { data: cumCost, max: costTotal, scale: 1, color: "var(--accent)", label: "Cost", fmt: BF.money },
      { data: cumHours, max: costTotal, scale: cm / hm, color: "var(--milestone)", label: "Labour hours", fmt: function (v) { return BF.fmt(v, 0) + " h"; } },
    ], { fmt: BF.money });
    const i = BF.daysBetween(t0, day);
    document.getElementById("costlegend").innerHTML =
      '<span><i style="background:var(--accent)"></i>cost ' + BF.money(cumCost[i]) + " / " + BF.money(costTotal) + "</span>" +
      '<span><i style="background:var(--milestone)"></i>labour ' + BF.fmt(cumHours[i], 0) + " / " + BF.fmt(hoursTotal, 0) + " h (scaled to the cost axis)</span>";
  }
  const paySel = document.getElementById("payitem");
  rows.forEach(function (r, i) {
    paySel.appendChild(BF.h("option", { value: i }, BF.esc((r.item_number ? r.item_number + " " : "") + r.cost_code + " — " + (r.description || "") + " (" + r.unit + ")")));
  });
  paySel.addEventListener("change", renderQty);
  function renderQty() {
    const svg = document.getElementById("qtychart"), lg = document.getElementById("qtylegend");
    if (!rows.length) { svg.innerHTML = ""; lg.innerHTML = '<span class="muted">No pay items.</span>'; return; }
    const r = rows[+paySel.value || 0], s = qtySeries(r);
    lineChart(svg, [{ data: s.cum, max: s.total || s.dated || 1, scale: 1, color: "var(--ok)", label: r.cost_code, fmt: function (v) { return BF.fmt(v) + " " + r.unit; } }],
      { fmt: function (v) { return BF.fmt(v, 0); } });
    const i = BF.daysBetween(t0, day);
    lg.innerHTML = '<span><i style="background:var(--ok)"></i>' + BF.fmt(s.cum[i]) + " of " + BF.fmt(r.quantity) + " " + BF.esc(r.unit) + " in place</span>" +
      (s.undated ? '<span class="warn">' + BF.fmt(s.undated) + " " + BF.esc(r.unit) + " on elements no task dates</span>" : "");
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
    const x = function (iso) { return LEFT + BF.daysBetween(t0, iso) * DAY; };
    // month grid
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
      g.appendChild(label);
      const clip = BF.svg("rect", { x: 0, y: y, width: LEFT - 4, height: ROW, fill: "var(--panel)" });
      g.insertBefore(clip, label);
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
            (t.duration_days != null ? " · " + t.duration_days + " d" : "") + "<br>" + BF.esc(t.task_type || "") +
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
    const x = function (iso) { return LEFT + BF.daysBetween(t0, iso) * DAY; };
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
    let html = '<p class="small">' + BF.esc(t.wbs || "") + " · " + (t.start || "?") + " → " + (t.finish || t.start || "?") +
      (t.duration_days != null ? " · " + t.duration_days + " d" : "") + " · " + BF.esc(t.task_type || "") +
      (t.is_milestone ? " · milestone" : "") + "</p>";
    if (c.cost != null) html += "<p>" + BF.money(c.cost) + (c.labor_hours != null ? " · " + BF.fmt(c.labor_hours, 0) + " labour hours" : "") +
      (codes.length ? '<br><span class="small muted">' + codes.map(function (k) { return BF.esc(k) + " " + BF.money(c.costs[k].cost); }).join(" · ") + "</span>" : "") + "</p>";
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
