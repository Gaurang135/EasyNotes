"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

/* ---------- sliding-glow control helper ---------- */
function slide(glow, btn) {
  const p = btn.parentElement.getBoundingClientRect();
  const b = btn.getBoundingClientRect();
  glow.style.width = b.width + "px";
  glow.style.transform = `translateX(${b.left - p.left - 5}px)`;
}

/* ---------- tabs ---------- */
const tabGlow = $("#tab-glow");
function activateTab(btn) {
  $$(".tab").forEach((x) => x.classList.toggle("is-active", x === btn));
  $$(".view").forEach((v) => v.classList.remove("is-active"));
  $("#view-" + btn.dataset.view).classList.add("is-active");
  slide(tabGlow, btn);
  if (btn.dataset.view === "graph") renderGraph();
  if (btn.dataset.view === "add") loadRecent();
}
$$(".tab").forEach((t) => t.addEventListener("click", () => activateTab(t)));

/* ---------- add-mode segmented ---------- */
const segGlow = $("#seg-glow");
$$(".seg").forEach((s) => s.addEventListener("click", () => {
  $$(".seg").forEach((x) => x.classList.toggle("is-active", x === s));
  $$(".pane").forEach((p) => p.classList.remove("is-active"));
  $("#pane-" + s.dataset.mode).classList.add("is-active");
  slide(segGlow, s);
}));

/* ---------- search mode picker ---------- */
const modeGlow = $("#mode-glow");
let searchMode = "hybrid";
$$(".mode").forEach((m) => m.addEventListener("click", () => {
  $$(".mode").forEach((x) => x.classList.toggle("is-active", x === m));
  searchMode = m.dataset.m; slide(modeGlow, m);
}));

/* position all glows once fonts/layout settle */
function positionGlows() {
  slide(tabGlow, $(".tab.is-active"));
  slide(segGlow, $(".seg.is-active"));
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

/* ---------- upload ---------- */
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
      else if (j.status === "duplicate") toast(`${f.name} is already in your library`, "");
      else toast(`Added ${f.name}`, "ok");
    } catch (e) { toast(`${f.name}: ${e}`, "err"); }
  }
  fileInput.value = ""; loadRecent();
}

/* ---------- paste ---------- */
$("#paste-submit").addEventListener("click", async () => {
  const title = $("#paste-title").value.trim(), text = $("#paste-body").value.trim();
  if (!title || !text) return toast("Title and text are both required", "err");
  const r = await fetch("/documents/text", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, text }) });
  if (r.ok) { $("#paste-title").value = ""; $("#paste-body").value = ""; toast("Note added", "ok"); loadRecent(); }
  else toast("Could not add note", "err");
});

/* ---------- library (polls while busy) ---------- */
const EXT_ICON = { pdf: "pdf", docx: "doc", pptx: "ppt", xlsx: "xls", csv: "csv", md: "md", txt: "txt" };
let pollTimer = null;
async function loadRecent() {
  let docs = [];
  try { docs = await (await fetch("/documents")).json(); } catch { return; }
  $("#lib-count").textContent = docs.length ? `${docs.length} item${docs.length > 1 ? "s" : ""}` : "";
  const ul = $("#recent");
  ul.innerHTML = docs.map((d, i) => `
    <li style="animation-delay:${Math.min(i * 40, 400)}ms">
      <span class="doc-name"><span class="ext">${EXT_ICON[d.file_type] || d.file_type}</span>${esc(d.title)}</span>
      <span class="pill ${d.status}">${d.status}${d.error ? " · " + esc(d.error) : ""}</span>
    </li>`).join("") || `<li><span style="color:var(--faint)">Nothing yet — drop a file above.</span></li>`;
  const busy = docs.some((d) => d.status === "processing" || d.status === "pending");
  clearTimeout(pollTimer);
  if (busy) pollTimer = setTimeout(loadRecent, 1400);
}

/* ---------- search ---------- */
$("#search-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = $("#q").value.trim(); if (!q) return;
  const box = $("#results");
  box.innerHTML = `<p class="empty">Searching…</p>`;
  const data = await (await fetch(`/search?q=${encodeURIComponent(q)}&mode=${searchMode}`)).json();
  if (!data.results.length) { box.innerHTML = `<p class="empty">No matches for “${esc(q)}”.</p>`; return; }
  box.innerHTML = data.results.map((h, i) => `
    <article class="card" style="animation-delay:${Math.min(i * 55, 500)}ms">
      <div class="meta">
        <span class="title">${esc(h.document_title)} <span style="color:var(--faint)">· ${h.file_type}${h.location ? " · " + esc(h.location) : ""}</span></span>
        <span class="score">${h.score.toFixed(3)}</span>
      </div>
      <div class="snip">${mark(esc(h.snippet), q)}</div>
    </article>`).join("");
});

/* ---------- graph ---------- */
$("#graph-form").addEventListener("submit", (ev) => { ev.preventDefault(); renderGraph($("#graph-q").value.trim()); });
let cy = null;
async function renderGraph(q) {
  const empty = $("#cy-empty"), fb = $("#cy-fallback"), tip = $("#cy-tip");
  if (window.__noCyto || typeof cytoscape === "undefined") { $("#cy").style.display = "none"; fb.hidden = false; return; }
  const g = await (await fetch(q ? `/graph?q=${encodeURIComponent(q)}` : "/graph")).json();
  empty.style.display = g.nodes.length ? "none" : "flex";
  tip.textContent = g.nodes.length ? `${g.nodes.length} documents · ${g.edges.length} connections${q ? " · highlighting matches" : ""}` : "";
  const els = [...g.nodes.map((n) => ({ data: n.data })), ...g.edges.map((e) => ({ data: e.data }))];
  if (cy) cy.destroy();
  cy = cytoscape({
    container: $("#cy"), elements: els, minZoom: 0.3, maxZoom: 2.5,
    style: [
      { selector: "node", style: {
        "background-color": "data(color)", label: "data(label)", color: "#dfe3ec", "font-size": 11,
        "font-family": "Instrument Sans, sans-serif",
        width: "mapData(size,1,30,20,66)", height: "mapData(size,1,30,20,66)",
        "text-valign": "bottom", "text-margin-y": 6, "text-max-width": 120, "text-wrap": "ellipsis",
        "border-width": 2, "border-color": "rgba(255,255,255,.15)",
        "overlay-opacity": 0, opacity: q ? 0.22 : 1, "transition-property": "opacity, border-color, border-width",
        "transition-duration": "300ms" } },
      { selector: "node[?matched]", style: {
        opacity: 1, "border-width": 4, "border-color": "#f2a65a",
        "shadow-blur": 30, "shadow-color": "#f2a65a", "shadow-opacity": 0.9 } },
      { selector: "edge", style: {
        width: "data(weight)", "line-color": "#3a4356", "curve-style": "bezier",
        opacity: q ? 0.15 : 0.5, "transition-property": "opacity", "transition-duration": "300ms" } },
    ],
    layout: { name: "cose", animate: true, animationDuration: 700, idealEdgeLength: 120, nodeRepulsion: 9000 },
  });
  cy.on("tap", "node", (e) => {
    const d = e.target.data();
    toast(`${d.label} — ${d.size} chunk${d.size > 1 ? "s" : ""}`, "");
  });
}

/* ---------- helpers ---------- */
function esc(s) { return (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function mark(text, q) {
  const terms = q.split(/\s+/).filter((t) => t.length > 1).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return terms.length ? text.replace(new RegExp(`(${terms.join("|")})`, "gi"), "<mark>$1</mark>") : text;
}

loadRecent();
