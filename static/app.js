"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (s) => (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function slide(glow, btn) {
  if (!glow || !btn) return;
  const p = btn.parentElement.getBoundingClientRect(), b = btn.getBoundingClientRect();
  glow.style.width = b.width + "px";
  glow.style.transform = `translateX(${b.left - p.left - (parseFloat(getComputedStyle(btn.parentElement).paddingLeft) || 5)}px)`;
}

/* ---------- tabs ---------- */
const tabGlow = $("#tab-glow");
function activateTab(btn) {
  $$(".tab").forEach((x) => x.classList.toggle("is-active", x === btn));
  $$(".view").forEach((v) => v.classList.remove("is-active"));
  $("#view-" + btn.dataset.view).classList.add("is-active");
  slide(tabGlow, btn);
  const v = btn.dataset.view;
  if (v === "search") loadStats();
  if (v === "graph") renderGraph();
  if (v === "add") loadRecent();
  if (v === "data") { loadTables(); loadFields(); }
}
$$(".tab").forEach((t) => t.addEventListener("click", () => activateTab(t)));

/* ---------- generic segmented (add + data) ---------- */
function wireSegmented(rootSel, glowSel, attr) {
  const glow = $(glowSel);
  $$(rootSel + " .seg").forEach((s) => s.addEventListener("click", () => {
    const root = s.closest(".view");
    $$(rootSel + " .seg").forEach((x) => x.classList.toggle("is-active", x === s));
    $$(".pane", root).forEach((p) => p.classList.remove("is-active"));
    $("#pane-" + s.dataset[attr], root).classList.add("is-active");
    slide(glow, s);
  }));
}
wireSegmented("#add-modes", "#seg-glow", "mode");
wireSegmented("#data-modes", "#dseg-glow", "dmode");

/* ---------- search mode picker ---------- */
const modeGlow = $("#mode-glow");
let searchMode = "hybrid";
$$(".mode").forEach((m) => m.addEventListener("click", () => {
  $$(".mode").forEach((x) => x.classList.toggle("is-active", x === m));
  searchMode = m.dataset.m; slide(modeGlow, m);
}));

function positionGlows() {
  slide(tabGlow, $(".tab.is-active"));
  slide($("#seg-glow"), $("#add-modes .seg.is-active"));
  slide($("#dseg-glow"), $("#data-modes .seg.is-active"));
  slide(modeGlow, $(".mode.is-active"));
}
window.addEventListener("load", positionGlows);
window.addEventListener("resize", positionGlows);
setTimeout(positionGlows, 300);

/* ---------- toasts ---------- */
function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind; el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 320); }, 3600);
}

/* ---------- dashboard stats ---------- */
async function loadStats() {
  let s; try { s = await (await fetch("/stats")).json(); } catch { return; }
  const tiles = [["Documents", s.documents], ["Tables", s.tables], ["Fields", s.fields], ["Chunks", s.chunks]];
  $("#stats").innerHTML = tiles.map(([l, n], i) =>
    `<div class="stat" style="animation-delay:${i * 60}ms"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");
}

/* ---------- upload / paste ---------- */
const drop = $("#drop"), fileInput = $("#file-input");
["dragover", "dragenter"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("hot"); }));
["dragleave", "drop"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.remove("hot"); }));
drop.addEventListener("drop", (ev) => uploadFiles(ev.dataTransfer.files));
fileInput.addEventListener("change", () => uploadFiles(fileInput.files));
async function uploadFiles(files) {
  for (const f of files) {
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await fetch("/documents", { method: "POST", body: fd });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) toast(`${f.name}: ${j.detail || r.status}`, "err");
      else if (j.status === "duplicate") toast(`${f.name} already added`, "");
      else toast(`Added ${f.name}`, "ok");
    } catch (e) { toast(`${f.name}: ${e}`, "err"); }
  }
  fileInput.value = ""; loadRecent();
}
$("#paste-submit").addEventListener("click", async () => {
  const title = $("#paste-title").value.trim(), text = $("#paste-body").value.trim();
  if (!title || !text) return toast("Title and text are both required", "err");
  const r = await fetch("/documents/text", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, text }) });
  if (r.ok) { $("#paste-title").value = ""; $("#paste-body").value = ""; toast("Note added", "ok"); loadRecent(); }
  else toast("Could not add note", "err");
});

/* ---------- library ---------- */
const EXT = { pdf: "pdf", docx: "doc", pptx: "ppt", xlsx: "xls", csv: "csv", md: "md", txt: "txt" };
let pollTimer = null;
async function loadRecent() {
  let docs = []; try { docs = await (await fetch("/documents")).json(); } catch { return; }
  $("#lib-count").textContent = docs.length ? `${docs.length} item${docs.length > 1 ? "s" : ""}` : "";
  $("#recent").innerHTML = docs.map((d, i) => `
    <li data-doc="${d.id}" style="animation-delay:${Math.min(i * 40, 400)}ms">
      <span class="doc-name"><span class="ext">${EXT[d.file_type] || d.file_type}</span>${esc(d.title)}</span>
      <span class="doc-actions">
        <span class="pill ${d.status}">${d.status}${d.error ? " · " + esc(d.error) : ""}</span>
        <a class="iconbtn" href="/documents/${d.id}/download" title="Download original" download onclick="event.stopPropagation()">↓</a>
        <button class="iconbtn del" data-del="${d.id}" title="Delete" onclick="event.stopPropagation()">✕</button>
      </span></li>`).join("")
    || `<li><span style="color:var(--faint)">Nothing yet — drop a file above.</span></li>`;
  $$("#recent li[data-doc]").forEach((el) => el.addEventListener("click", () => openDetail(el.dataset.doc)));
  $$("#recent .del").forEach((b) => b.addEventListener("click", async () => {
    await fetch(`/documents/${b.dataset.del}`, { method: "DELETE" });
    toast("Deleted", ""); loadRecent(); loadStats();
  }));
  const busy = docs.some((d) => d.status === "processing" || d.status === "pending");
  clearTimeout(pollTimer);
  if (busy) pollTimer = setTimeout(() => { loadRecent(); loadStats(); }, 1400);
}

/* ---------- search ---------- */
$("#search-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = $("#q").value.trim(); if (!q) return;
  const box = $("#results"); box.innerHTML = `<p class="empty">Searching…</p>`;
  const data = await (await fetch(`/search?q=${encodeURIComponent(q)}&mode=${searchMode}`)).json();
  if (!data.results.length) { box.innerHTML = `<p class="empty">No matches for “${esc(q)}”.</p>`; return; }
  const top = Math.max(...data.results.map((h) => h.score)) || 1;
  const isTable = (h) => ["csv", "xlsx"].includes(h.file_type) || (h.location || "").match(/row|sheet/i);
  box.innerHTML = data.results.map((h, i) => {
    const rel = Math.round((h.score / top) * 100);
    const preview = isTable(h)
      ? `<span class="snip-badge">▦ structured table</span> <span style="color:var(--muted)">— open to filter rows</span>`
      : mark(esc(h.snippet), q);
    return `<article class="card" data-doc="${h.document_id}" style="animation-delay:${Math.min(i * 55, 500)}ms">
      <div class="meta">
        <span class="title">${esc(h.document_title)} <span style="color:var(--faint)">· ${h.file_type}${h.location ? " · " + esc(h.location) : ""}</span></span>
        <span class="rel" title="fused score ${h.score.toFixed(3)}"><span class="relbar"><span style="width:${rel}%"></span></span><span class="rellabel">${i === 0 ? "Best match" : rel + "%"}</span></span>
      </div><div class="snip">${preview}</div>
      <div class="card-cta">Open document →</div></article>`;
  }).join("");
  $$("#results .card").forEach((el) => el.addEventListener("click", () => openDetail(el.dataset.doc)));
});

/* ---------- document detail (messy doc -> extracted structured data) ---------- */
async function openDetail(docId) {
  let d; try { d = await (await fetch(`/documents/${docId}/detail`)).json(); } catch { return; }
  const fields = d.fields.length
    ? `<div class="fieldgrid">${d.fields.map((f) =>
        `<div class="fcard"><div class="fk"><span>${esc(f.key)}</span><span class="kind">${f.kind}</span></div><div class="fv">${esc(f.value)}</div></div>`).join("")}</div>`
    : `<p class="d-empty">No key-value fields extracted.</p>`;
  const tables = d.tables.length
    ? d.tables.map((t) => `<div id="dt-${t.id}" class="dtable" data-tid="${t.id}"><div class="d-empty">Loading ${esc(t.name)}…</div></div>`).join("")
    : `<p class="d-empty">No tables in this document.</p>`;
  const text = d.text_preview
    ? `<div class="d-text">${esc(d.text_preview)}</div>` : `<p class="d-empty">No text preview.</p>`;
  $("#detail-body").innerHTML = `
    <div class="d-head"><span class="ext">${EXT[d.file_type] || d.file_type}</span><span class="d-title">${esc(d.title)}</span></div>
    <div class="d-sub">${d.file_type} · ${d.status}${d.error ? " · " + esc(d.error) : ""} · ${d.fields.length} fields · ${d.tables.length} tables</div>
    <div class="d-section"><h4>Extracted fields</h4>${fields}</div>
    <div class="d-section"><h4>Tables</h4>${tables}</div>
    <div class="d-section"><h4>Text</h4>${text}</div>`;
  $("#detail").hidden = false;
  for (const t of d.tables) renderMiniTable(t.id);
}
async function renderMiniTable(tid) {
  const r = await (await fetch(`/tables/${tid}/rows?limit=25`)).json();
  const types = r.columns.map((c) => c.type);
  const head = `<thead><tr>${r.columns.map((c) => `<th>${esc(c.name)}<span class="ty">${c.type}</span></th>`).join("")}</tr></thead>`;
  const body = r.rows.map((row) => `<tr>${row.map((cell, i) =>
    `<td class="${types[i] === "number" ? "num" : ""}">${esc(String(cell))}</td>`).join("")}</tr>`).join("");
  const el = $(`#dt-${tid}`);
  if (el) el.innerHTML = `<div class="tablewrap"><table class="grid">${head}<tbody>${body}</tbody></table>` +
    `<div class="grid-foot">${r.total} row${r.total !== 1 ? "s" : ""}</div></div>`;
}
$("#detail-close").addEventListener("click", () => { $("#detail").hidden = true; });
$("#detail").addEventListener("click", (e) => { if (e.target.id === "detail") $("#detail").hidden = true; });

/* ---------- data: tables ---------- */
let curTable = null;
async function loadTables() {
  let tables = []; try { tables = await (await fetch("/tables")).json(); } catch { return; }
  const pick = $("#table-pick");
  if (!tables.length) {
    pick.innerHTML = `<option>No tables yet</option>`; pick.disabled = true;
    $("#table-controls").hidden = true;
    $("#table-view").innerHTML = `<p class="empty">No tables yet — add a CSV, spreadsheet, or a doc with tables.</p>`;
    return;
  }
  pick.disabled = false;
  pick.innerHTML = tables.map((t) => `<option value="${t.id}">${esc(t.document_title)} — ${esc(t.name)} (${t.row_count} rows)</option>`).join("");
  curTable = tables[0];
  pick.onchange = () => { curTable = tables.find((t) => t.id == pick.value); setupControls(); runTableQuery(); };
  setupControls(); runTableQuery();
}
function setupControls() {
  $("#table-controls").hidden = false;
  const cols = curTable.columns;
  $("#f-col").innerHTML = cols.map((c) => `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join("");
  $("#s-col").innerHTML = `<option value="">—</option>` + cols.map((c) => `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join("");
}
$("#f-apply").addEventListener("click", runTableQuery);
$("#f-val").addEventListener("keydown", (e) => { if (e.key === "Enter") runTableQuery(); });
async function runTableQuery() {
  if (!curTable) return;
  const p = new URLSearchParams();
  const val = $("#f-val").value.trim();
  if (val) { p.set("col", $("#f-col").value); p.set("op", $("#f-op").value); p.set("val", val); }
  if ($("#s-col").value) { p.set("sort", $("#s-col").value); p.set("dir", $("#s-dir").value); }
  p.set("limit", "100");
  const r = await (await fetch(`/tables/${curTable.id}/rows?` + p)).json();
  const types = r.columns.map((c) => c.type);
  const head = `<thead><tr>${r.columns.map((c) => `<th>${esc(c.name)}<span class="ty">${c.type}</span></th>`).join("")}</tr></thead>`;
  const body = r.rows.map((row) => `<tr>${row.map((cell, i) =>
    `<td class="${types[i] === "number" ? "num" : ""}">${esc(String(cell))}</td>`).join("")}</tr>`).join("");
  $("#table-view").innerHTML = `<table class="grid">${head}<tbody>${body}</tbody></table>` +
    `<div class="grid-foot">${r.total} row${r.total !== 1 ? "s" : ""}${r.total > r.rows.length ? ` · showing ${r.rows.length}` : ""}</div>`;
}

/* ---------- data: fields ---------- */
let fieldKind = "";
const KINDS = ["", "amount", "date", "email", "phone", "url", "pair"];
async function loadFields() {
  $("#field-kinds").innerHTML = KINDS.map((k) =>
    `<button class="chip ${k === fieldKind ? "is-active" : ""}" data-k="${k}">${k || "all"}</button>`).join("");
  $$("#field-kinds .chip").forEach((c) => c.addEventListener("click", () => { fieldKind = c.dataset.k; loadFields(); }));
  const url = "/fields" + (fieldKind ? `?kind=${fieldKind}` : "");
  let fields = []; try { fields = await (await fetch(url)).json(); } catch { return; }
  const g = $("#fields-grid");
  if (!fields.length) { g.innerHTML = `<tbody><tr><td class="empty" style="padding:24px">No fields extracted yet.</td></tr></tbody>`; return; }
  g.innerHTML = `<thead><tr><th>Document</th><th>Key</th><th>Value</th><th>Type</th></tr></thead><tbody>` +
    fields.map((f) => `<tr><td>${esc(f.document_title)}</td><td class="field-key">${esc(f.key)}</td><td>${esc(f.value)}</td><td><span class="field-kind">${f.kind}</span></td></tr>`).join("") +
    `</tbody>`;
}

/* ---------- graph ---------- */
$("#graph-form").addEventListener("submit", (ev) => { ev.preventDefault(); renderGraph($("#graph-q").value.trim()); });
let cy = null;
async function renderGraph(q) {
  if (window.__noCyto || typeof cytoscape === "undefined") { $("#cy").style.display = "none"; $("#cy-fallback").hidden = false; return; }
  const g = await (await fetch(q ? `/graph?q=${encodeURIComponent(q)}` : "/graph")).json();
  $("#cy-empty").style.display = g.nodes.length ? "none" : "flex";
  $("#cy-tip").textContent = g.nodes.length ? `${g.nodes.length} documents · ${g.edges.length} connections${q ? " · highlighting matches" : ""}` : "";
  const els = [...g.nodes.map((n) => ({ data: n.data })), ...g.edges.map((e) => ({ data: e.data }))];
  if (cy) cy.destroy();
  cy = cytoscape({
    container: $("#cy"), elements: els, minZoom: 0.3, maxZoom: 2.5,
    style: [
      { selector: "node", style: { "background-color": "data(color)", label: "data(label)", color: "#dfe3ec",
        "font-size": 11, "font-family": "Instrument Sans, sans-serif", width: "mapData(size,1,30,20,66)", height: "mapData(size,1,30,20,66)",
        "text-valign": "bottom", "text-margin-y": 6, "text-max-width": 120, "text-wrap": "ellipsis", "border-width": 2,
        "border-color": "rgba(255,255,255,.15)", opacity: q ? 0.22 : 1, "transition-property": "opacity", "transition-duration": "300ms" } },
      { selector: "node[?matched]", style: { opacity: 1, "border-width": 4, "border-color": "#f2a65a", "shadow-blur": 30, "shadow-color": "#f2a65a", "shadow-opacity": 0.9 } },
      { selector: "edge", style: { width: "data(weight)", "line-color": "#3a4356", "curve-style": "bezier", opacity: q ? 0.12 : 0.5, "transition-property": "opacity", "transition-duration": "300ms" } },
    ],
    layout: { name: "cose", animate: true, animationDuration: 700, idealEdgeLength: 120, nodeRepulsion: 9000 },
  });
  cy.on("tap", "node", (e) => { const d = e.target.data(); toast(`${d.label} — ${d.size} chunk${d.size > 1 ? "s" : ""}`, ""); });
}

const STOP = new Set("a an the is are was were be been am im i who what when where why how which of to in on at for and or but if it its this that as by with from do does did can could will would my me you your we".split(" "));
function mark(text, q) {
  const terms = q.toLowerCase().split(/\s+/).filter((t) => t.length > 1 && !STOP.has(t)).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return terms.length ? text.replace(new RegExp(`(${terms.join("|")})`, "gi"), "<mark>$1</mark>") : text;
}

loadStats();
