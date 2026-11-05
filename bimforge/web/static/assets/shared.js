/* BIMForge pages: the bundle, the host adapter, formatting and date helpers.
 *
 * A page reads ONE document, window.BIMFORGE_BUNDLE (data/bundle.js), of the
 * contract "bimforge-web/1" (bimforge.web.contract). It talks back to
 * whatever is hosting it through window.bimforgeHost, when present:
 *   bimforgeHost.select(globalIds, label)   -- select these elements
 *   bimforgeHost.gotoDate(isoDay)           -- show the model on that day
 * Standalone (no host) a selection is copied to the clipboard as GlobalIds.
 */
(function () {
  "use strict";
  const CONTRACT = "bimforge-web/1";
  const BF = {};

  BF.bundle = function () {
    const b = window.BIMFORGE_BUNDLE;
    if (!b || b.contract !== CONTRACT) {
      const got = b ? b.contract : "no bundle (data/bundle.js missing?)";
      const main = document.querySelector("main") || document.body;
      main.innerHTML = '<div class="panel"><h2>Cannot show this bundle</h2>' +
        "<p>This page reads contract <code>" + CONTRACT + "</code>; the bundle says <code>" +
        BF.esc(String(got)) + "</code>. Rebuild it with <code>est-bim web</code>.</p></div>";
      throw new Error("bundle contract mismatch: " + got);
    }
    return b;
  };

  BF.esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  BF.fmt = function (v, dp) {
    if (v == null || Number.isNaN(v)) return "—";
    if (dp == null) dp = Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2;
    return Number(v).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
  };
  BF.money = function (v) {
    if (v == null) return "—";
    return "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  };
  BF.pct = function (v) { return v == null ? "—" : (v > 0 ? "+" : "") + BF.fmt(v, 1) + "%"; };

  // ---- dates: ISO day strings only, no time zones
  BF.day = function (d) { return d.toISOString().slice(0, 10); };
  BF.parse = function (iso) { return new Date(iso.slice(0, 10) + "T00:00:00Z"); };
  BF.addDays = function (iso, n) { const d = BF.parse(iso); d.setUTCDate(d.getUTCDate() + n); return BF.day(d); };
  BF.daysBetween = function (a, b) { return Math.round((BF.parse(b) - BF.parse(a)) / 86400000); };
  BF.today = function () { return BF.day(new Date()); };
  BF.monthLabel = function (iso) {
    const d = BF.parse(iso);
    return d.toLocaleDateString(undefined, { month: "short", year: "2-digit", timeZone: "UTC" });
  };

  // ---- header: nav and model line
  BF.header = function (current) {
    const b = window.BIMFORGE_BUNDLE || {};
    const m = b.model || {};
    const nav = [["index.html", "Overview"], ["takeoff.html", "Takeoff"], ["dashboard.html", "4D/5D"]]
      .map(function (p) { return '<a href="' + p[0] + '"' + (p[0] === current ? ' class="current"' : "") + ">" + p[1] + "</a>"; })
      .join("");
    const el = document.querySelector("header.top");
    if (el) {
      el.innerHTML = "<h1>BIMForge</h1><nav>" + nav + "</nav>" +
        '<span class="model">' + BF.esc(m.project || "") + (m.file ? " · " + BF.esc(m.file) : "") +
        (m.schema ? " · " + BF.esc(m.schema) : "") + "</span>";
    }
  };

  // ---- the host adapter
  BF.toast = function (msg) {
    let t = document.querySelector(".toast");
    if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add("show");
    clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove("show"); }, 1800);
  };
  BF.select = function (globalIds, label) {
    const ids = Array.from(new Set(globalIds || []));
    const host = window.bimforgeHost;
    if (host && typeof host.select === "function") {
      host.select(ids, label || "");
      BF.toast("Selected " + ids.length + " element" + (ids.length === 1 ? "" : "s") + (label ? ": " + label : ""));
      return;
    }
    const text = ids.join("\n");
    const done = function () { BF.toast("Copied " + ids.length + " GlobalId" + (ids.length === 1 ? "" : "s") + " (no host to select in)"); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, done);
    else done();
  };
  BF.gotoDate = function (iso) {
    const host = window.bimforgeHost;
    if (host && typeof host.gotoDate === "function") host.gotoDate(iso);
  };

  // ---- tiny helpers
  BF.h = function (tag, attrs, html) {
    const el = document.createElement(tag);
    for (const k in (attrs || {})) el.setAttribute(k, attrs[k]);
    if (html != null) el.innerHTML = html;
    return el;
  };
  BF.svg = function (tag, attrs) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in (attrs || {})) el.setAttribute(k, attrs[k]);
    return el;
  };
  BF.csv = function (rows) {
    return rows.map(function (r) {
      return r.map(function (c) {
        const s = c == null ? "" : String(c);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      }).join(",");
    }).join("\n") + "\n";
  };
  BF.download = function (name, text, type) {
    const blob = new Blob([text], { type: type || "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  };
  BF.tip = function () {
    let t = document.querySelector(".svgtip");
    if (!t) { t = document.createElement("div"); t.className = "svgtip"; document.body.appendChild(t); }
    return {
      show: function (html, ev) { t.innerHTML = html; t.style.display = "block"; this.move(ev); },
      move: function (ev) { t.style.left = (ev.clientX + 14) + "px"; t.style.top = (ev.clientY + 12) + "px"; },
      hide: function () { t.style.display = "none"; }
    };
  };

  window.BF = BF;
})();
