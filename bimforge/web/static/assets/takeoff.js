/* The takeoff page: pay items against the bid schedule, the elements behind each. */
(function () {
  "use strict";
  const b = BF.bundle(); BF.header("takeoff.html");
  const rows = b.takeoff.rows.map(function (r, i) {
    return Object.assign({ _i: i, n: r.elements.length }, r);
  });
  const E = b.elements;
  const state = { k: "item_number", desc: false, q: "", schedule: "", onlyvar: false, open: new Set() };

  // ---- tiles
  const totals = rows.reduce(function (t, r) {
    t.items++; t.elements += r.n;
    if (r.official_quantity != null) { t.withOfficial++; if (Math.abs(r.variance_pct || 0) > 5) t.over++; }
    return t;
  }, { items: 0, elements: 0, withOfficial: 0, over: 0 });
  document.getElementById("tiles").innerHTML = [
    ["Pay items", totals.items, rows.filter(function (r) { return r.item_number; }).length + " with an item number"],
    ["Element rows", totals.elements, Object.keys(E).length + " elements in the model"],
    ["Against official", totals.withOfficial, totals.over + " beyond ±5%"],
    ["No pay code", b.takeoff.unclassified.length, "elements"],
  ].map(function (t) {
    return '<div class="tile"><div class="k">' + t[0] + '</div><div class="v">' + BF.esc(t[1]) + '</div><div class="s">' + BF.esc(t[2]) + "</div></div>";
  }).join("");

  // ---- schedule filter
  const schedules = Array.from(new Set(rows.map(function (r) { return r.schedule || ""; }).filter(Boolean))).sort();
  const sel = document.getElementById("schedule");
  schedules.forEach(function (s) { sel.appendChild(BF.h("option", { value: s }, "Schedule " + BF.esc(s))); });
  if (schedules.length < 2) sel.hidden = true;

  function matches(r) {
    if (state.schedule && (r.schedule || "") !== state.schedule) return false;
    if (state.onlyvar) {
      const has = r.variance_pct != null ? Math.abs(r.variance_pct) > 0.5
        : (r.variance != null && Math.abs(r.variance) > 0);      // an official 0 has no %
      if (!has) return false;
    }
    if (!state.q) return true;
    const q = state.q.toLowerCase();
    if ([r.item_number, r.cost_code, r.description, r.unit].some(function (v) { return v && String(v).toLowerCase().includes(q); })) return true;
    return r.elements.some(function (e) { return e.name.toLowerCase().includes(q) || e.global_id.toLowerCase() === q; });
  }
  function cmp(a, b) {
    const k = state.k; let x = a[k], y = b[k];
    if (x == null && y == null) return a._i - b._i;
    if (x == null) return 1; if (y == null) return -1;
    if (typeof x === "number" && typeof y === "number") return x - y;
    x = String(x); y = String(y);
    return x.localeCompare(y, undefined, { numeric: true });
  }
  function varClass(v) { return v == null ? "" : v > 0 ? "pos" : v < 0 ? "neg" : ""; }

  function elementRows(r) {
    const lines = r.elements.map(function (e) {
      const el = E[e.global_id] || {};
      const sp = el.appear || el.vanish ? (el.appear || "…") + " → " + (el.vanish || "…") : "";
      return "<tr>" +
        '<td><a href="#" class="sel-el" data-g="' + BF.esc(e.global_id) + '">' + BF.esc(e.name) + "</a>" +
        (el.whole && E[el.whole] ? ' <span class="muted small">part of ' + BF.esc(E[el.whole].name) + "</span>" : "") + "</td>" +
        '<td class="small">' + BF.esc(el.ifc_class || "") + (el.predefined_type ? " / " + BF.esc(el.predefined_type) : "") + "</td>" +
        '<td class="small">' + BF.esc(el.type || "") + "</td>" +
        '<td class="num">' + (e.count > 1 ? e.count : "") + "</td>" +
        '<td class="num">' + BF.fmt(e.quantity) + "</td>" +
        '<td class="small">' + BF.esc(e.measure || "") + "</td>" +
        '<td class="small mono">' + BF.esc(sp) + "</td>" +
        '<td class="mono small muted">' + BF.esc(e.global_id) + "</td></tr>";
    }).join("");
    return '<table class="small"><thead><tr><th>Element</th><th>Class</th><th>Type</th><th class="num">Count</th><th class="num">' +
      BF.esc(r.unit) + '</th><th>Measure</th><th>4D span</th><th>GlobalId</th></tr></thead><tbody>' + lines + "</tbody></table>";
  }

  function render() {
    const tbody = document.querySelector("#items tbody");
    const shown = rows.filter(matches).sort(cmp);
    if (state.desc) shown.reverse();
    document.getElementById("empty").hidden = shown.length > 0;
    tbody.innerHTML = shown.map(function (r) {
      const open = state.open.has(r._i);
      return '<tr class="row" data-i="' + r._i + '">' +
        '<td class="mono">' + BF.esc(r.item_number || "") + "</td>" +
        '<td class="mono">' + BF.esc(r.cost_code) + "</td>" +
        "<td>" + BF.esc(r.description || "") + (r.schedule ? ' <span class="pill">' + BF.esc(r.schedule) + "</span>" : "") + "</td>" +
        "<td>" + BF.esc(r.unit) + "</td>" +
        '<td class="num">' + BF.fmt(r.quantity) + "</td>" +
        '<td class="num">' + BF.fmt(r.official_quantity) + "</td>" +
        '<td class="num ' + varClass(r.variance) + '">' + (r.variance == null ? "—" : (r.variance > 0 ? "+" : "") + BF.fmt(r.variance)) + "</td>" +
        '<td class="num ' + varClass(r.variance_pct) + '">' + BF.pct(r.variance_pct) + "</td>" +
        '<td class="num">' + r.n + "</td>" +
        '<td><button class="small sel-row" data-i="' + r._i + '" title="Select these elements in the host">Select</button></td>' +
        "</tr>" +
        (open ? '<tr class="detail"><td colspan="10">' + elementRows(r) + "</td></tr>" : "");
    }).join("");
    const tq = shown.reduce(function (s, r) { return s + (r.n || 0); }, 0);
    document.querySelector("#items tfoot").innerHTML = '<tr><td colspan="8" class="muted small">' + shown.length +
      " of " + rows.length + ' pay items</td><td class="num">' + tq + "</td><td></td></tr>";
    document.querySelectorAll("#items thead th").forEach(function (th) {
      th.classList.toggle("sorted", th.dataset.k === state.k);
      th.classList.toggle("desc", th.dataset.k === state.k && state.desc);
    });
  }

  // ---- events
  document.querySelector("#items thead").addEventListener("click", function (ev) {
    const th = ev.target.closest("th"); if (!th || !th.dataset.k) return;
    if (state.k === th.dataset.k) state.desc = !state.desc; else { state.k = th.dataset.k; state.desc = false; }
    render();
  });
  document.querySelector("#items tbody").addEventListener("click", function (ev) {
    const btn = ev.target.closest("button.sel-row");
    if (btn) { const r = rows[+btn.dataset.i]; BF.select(r.elements.map(function (e) { return e.global_id; }), r.cost_code); return; }
    const a = ev.target.closest("a.sel-el");
    if (a) { ev.preventDefault(); BF.select([a.dataset.g], E[a.dataset.g] ? E[a.dataset.g].name : ""); return; }
    const tr = ev.target.closest("tr.row"); if (!tr) return;
    const i = +tr.dataset.i;
    if (state.open.has(i)) state.open.delete(i); else state.open.add(i);
    render();
  });
  document.getElementById("filter").addEventListener("input", function (ev) { state.q = ev.target.value.trim(); render(); });
  sel.addEventListener("change", function (ev) { state.schedule = ev.target.value; render(); });
  document.getElementById("onlyvar").addEventListener("change", function (ev) { state.onlyvar = ev.target.checked; render(); });
  document.getElementById("expandall").addEventListener("click", function (ev) {
    if (state.open.size) state.open.clear(); else rows.forEach(function (r) { state.open.add(r._i); });
    ev.target.textContent = state.open.size ? "Collapse all" : "Expand all";
    render();
  });
  document.getElementById("csv").addEventListener("click", function () {
    const out = [["Item #", "Cost code", "Bid item", "Schedule", "Unit", "Modelled", "Official", "Variance", "Variance %", "Elements"]];
    rows.filter(matches).sort(cmp).forEach(function (r) {
      out.push([r.item_number, r.cost_code, r.description, r.schedule, r.unit, r.quantity, r.official_quantity, r.variance, r.variance_pct, r.n]);
    });
    out.push([]); out.push(["Element", "GlobalId", "Cost code", "Unit", "Quantity", "Measure", "Appear", "Vanish"]);
    rows.forEach(function (r) {
      r.elements.forEach(function (e) {
        const el = E[e.global_id] || {};
        out.push([e.name, e.global_id, r.cost_code, r.unit, e.quantity, e.measure, el.appear, el.vanish]);
      });
    });
    BF.download((b.model.file || "model").replace(/\.ifc$/i, "") + "-takeoff.csv", BF.csv(out), "text/csv");
  });

  // ---- unclassified
  if (b.takeoff.unclassified.length) {
    const sec = document.getElementById("unclassified"); sec.hidden = false;
    document.getElementById("unclist").innerHTML = b.takeoff.unclassified.map(function (g) {
      const el = E[g] || {};
      return '<li><a href="#" class="sel-el" data-g="' + BF.esc(g) + '">' + BF.esc(el.name || g) + "</a>" +
        '<span class="muted">' + BF.esc(el.ifc_class || "") + "</span>" +
        '<span class="mono muted">' + BF.esc(g) + "</span></li>";
    }).join("");
    sec.addEventListener("click", function (ev) {
      const a = ev.target.closest("a.sel-el"); if (!a) return;
      ev.preventDefault(); BF.select([a.dataset.g], (E[a.dataset.g] || {}).name);
    });
  }
  document.getElementById("foot").textContent = b.model.generator + " · contract " + b.contract;
  render();
})();
