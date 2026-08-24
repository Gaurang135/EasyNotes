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
  if (v === "search") { loadStats(); loadOverview(); }
  if (v === "add") loadRecent();
  if (v === "data") { loadAllTables(); loadFields(); }
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
  const btn = $("#search-btn"); if (btn) btn.textContent = searchMode === "ask" ? "Ask" : "Search";
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
  const bt = s.by_type || {};
  const order = ["pdf", "pptx", "docx", "xlsx", "csv", "md", "txt"];
  const tb = $("#type-breakdown");
  if (tb) tb.innerHTML = order.filter((t) => bt[t]).map((t) =>
    `<span class="tb"><b>${bt[t]}</b> ${t.toUpperCase()}</span>`).join("");
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
let recentSig = "";
async function loadRecent() {
  let docs = []; try { docs = await (await fetch("/documents")).json(); } catch { return; }
  $("#lib-count").textContent = docs.length ? `${docs.length} item${docs.length > 1 ? "s" : ""}` : "";
  const sig = docs.map((d) => d.id + d.status + (d.error || "")).join("|");
  if (sig !== recentSig) {                            // only re-render on real change — no flicker on poll
    recentSig = sig;
    $("#recent").innerHTML = docs.map((d) => `
      <li data-doc="${d.id}">
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
      recentSig = ""; toast("Deleted", ""); loadRecent(); loadStats();
    }));
  }
  const busy = docs.some((d) => d.status === "processing" || d.status === "pending");
  clearTimeout(pollTimer);
  if (busy) pollTimer = setTimeout(loadRecent, 1600);
}

/* ---------- search ---------- */
$("#search-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = $("#q").value.trim(); if (!q) return;
  const box = $("#results");
  if (searchMode === "ask") return runAsk(q, box);
  box.innerHTML = `<p class="empty">Searching…</p>`;
  const data = await (await fetch(`/search?q=${encodeURIComponent(q)}&mode=${searchMode}`)).json();
  const answersHtml = (data.answers && data.answers.length) ? `
    <div class="answers">
      <div class="answers-h">Direct answers</div>
      <div class="answers-grid">${data.answers.map((a) =>
        `<div class="ans" data-doc="${a.document_id}"><span class="ans-kind">${a.kind}</span><span class="ans-val">${esc(a.value)}</span><span class="ans-src">${esc(a.document_title)}</span></div>`).join("")}</div>
    </div>` : "";
  if (!data.results.length && !answersHtml) { box.innerHTML = `<p class="empty">No matches for “${esc(q)}”.</p>`; return; }
  if (!data.results.length) { box.innerHTML = answersHtml; wireAnswerClicks(); return; }
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
  box.innerHTML = answersHtml + box.innerHTML;
  $$("#results .card").forEach((el) => el.addEventListener("click", () => openDetail(el.dataset.doc)));
  wireAnswerClicks();
});
function wireAnswerClicks() {
  $$("#results .ans").forEach((el) => el.addEventListener("click", () => openDetail(el.dataset.doc)));
}

/* ---------- Ask (grounded RAG answer) ---------- */
async function runAsk(q, box) {
  box.innerHTML = `<div class="answer-card"><div class="answer-h">✦ Thinking…</div></div>`;
  let r, d;
  try {
    r = await fetch("/answer", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q }) });
    d = await r.json();
  } catch (e) { box.innerHTML = `<p class="empty">Ask failed: ${esc(String(e))}</p>`; return; }
  if (r.status === 501) {
    box.innerHTML = `<div class="answer-card off">
      <div class="answer-h">✦ Ask is off (LLM-free by default)</div>
      <div class="answer-body">EasyNotes answers are grounded in your documents but need a
      generation model, which is optional. Enable by setting <code>ANSWER_MODEL</code> +
      <code>ANSWER_API_KEY</code> (e.g. a free Groq key with
      <code>ANSWER_BASE_URL=https://api.groq.com/openai/v1</code>) or a local Ollama — see README.
      Meanwhile, Hybrid / Meaning / Keyword search work now.</div></div>`;
    return;
  }
  if (!r.ok) { box.innerHTML = `<p class="empty">${esc(d.detail || "answer error")}</p>`; return; }
  const cites = (d.citations || []).map((c) =>
    `<span class="cite" data-doc="${c.document_id}">${esc(c.document_title)}</span>`).join("");
  box.innerHTML = `<div class="answer-card">
    <div class="answer-h">✦ Answer</div>
    <div class="answer-body">${renderMarkdown(d.answer)}</div>
    ${cites ? `<div class="answer-cites"><span class="cites-l">Sources</span>${cites}</div>` : ""}</div>`;
  $$("#results .cite").forEach((el) => el.addEventListener("click", () => openDetail(el.dataset.doc)));
}

/* tiny markdown renderer for grounded answers (bold, bullets, inline citations) */
function renderMarkdown(raw) {
  const inline = (s) => s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/【([^】]+)】/g, '<span class="cite-mark">$1</span>')
    .replace(/\[([^\]]+)\]/g, '<span class="cite-mark">$1</span>');
  const lines = esc(raw || "").split(/\r?\n/);
  let html = "", inList = false;
  for (const line of lines) {
    const t = line.trim();
    if (/^[-*]\s+/.test(t)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += "<li>" + inline(t.replace(/^[-*]\s+/, "")) + "</li>";
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      if (t) html += "<p>" + inline(t) + "</p>";
    }
  }
  if (inList) html += "</ul>";
  return html;
}

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

/* ---------- landing overview: messy docs -> structured data, made visible ---------- */
async function loadOverview() {
  if ($("#q").value.trim()) return;                 // don't clobber active search results
  let docs = []; try { docs = await (await fetch("/overview")).json(); } catch { return; }
  const box = $("#results");
  const ready = docs.filter((d) => d.status === "ready");
  if (!ready.length) {
    box.innerHTML = `<p class="empty">Add documents (Add tab) — each one is turned into structured fields & tables you can query here.</p>`;
    return;
  }
  box.innerHTML = `<div class="overview-h">Your library — extracted into structured data</div>` +
    ready.map((d, i) => {
      let chips = "";
      if (d.table_count) chips += `<span class="ochip ochip-t">▦ ${d.table_count} table${d.table_count > 1 ? "s" : ""}</span>`;
      chips += d.fields.slice(0, 5).map((f) =>
        `<span class="ochip"><span class="ock">${f.kind}</span>${esc(f.value)}</span>`).join("");
      const badge = `${d.field_count} field${d.field_count !== 1 ? "s" : ""}${d.table_count ? ` · ${d.table_count} table${d.table_count !== 1 ? "s" : ""}` : ""}`;
      return `<article class="ocard" data-doc="${d.id}" style="animation-delay:${Math.min(i * 45, 400)}ms">
        <div class="ohead"><span class="ext">${EXT[d.file_type] || d.file_type}</span><span class="otitle">${esc(d.title)}</span><span class="obadge">${badge}</span></div>
        ${chips ? `<div class="ochips">${chips}</div>` : `<div class="ochips muted">indexed for semantic &amp; keyword search</div>`}
      </article>`;
    }).join("");
  $$("#results .ocard").forEach((el) => el.addEventListener("click", () => openDetail(el.dataset.doc)));
}

/* ---------- data: all tables together (cross-document) ---------- */
let allTables = [];
async function loadAllTables() {
  let meta = []; try { meta = await (await fetch("/tables")).json(); } catch { return; }
  if (!meta.length) { $("#tables-all").innerHTML = `<p class="empty">No tables yet — add a CSV, spreadsheet, or a doc with tables.</p>`; allTables = []; return; }
  allTables = [];
  for (const t of meta) {
    const r = await (await fetch(`/tables/${t.id}/rows?limit=200`)).json();
    allTables.push({ meta: t, columns: r.columns, rows: r.rows, total: r.total });
  }
  renderAllTables($("#table-filter").value);
}
function renderAllTables(filter) {
  const f = (filter || "").trim().toLowerCase();
  $("#tables-all").innerHTML = allTables.map((t) => {
    const rows = f ? t.rows.filter((r) => r.some((c) => String(c).toLowerCase().includes(f))) : t.rows;
    const types = t.columns.map((c) => c.type);
    const head = `<thead><tr>${t.columns.map((c) => `<th>${esc(c.name)}<span class="ty">${c.type}</span></th>`).join("")}</tr></thead>`;
    const body = rows.slice(0, 100).map((r) => `<tr>${r.map((cell, i) =>
      `<td class="${types[i] === "number" ? "num" : ""}">${esc(String(cell))}</td>`).join("")}</tr>`).join("");
    return `<div class="dtable-block">
      <div class="dtable-h" data-doc="${t.meta.document_id}"><span class="ext">${EXT[t.meta.file_type] || t.meta.file_type}</span>${esc(t.meta.document_title)} — ${esc(t.meta.name)} <span class="muted">${rows.length}/${t.total} rows</span></div>
      <div class="tablewrap"><table class="grid">${head}<tbody>${body}</tbody></table></div></div>`;
  }).join("") || `<p class="empty">No rows match “${esc(f)}”.</p>`;
  $$("#tables-all .dtable-h").forEach((el) => el.addEventListener("click", () => openDetail(el.dataset.doc)));
}
$("#table-filter").addEventListener("input", (e) => renderAllTables(e.target.value));

/* ---------- data: fields (all values across all docs) ---------- */
let fieldKind = "";
const KINDS = ["", "amount", "date", "email", "phone", "url", "pair"];
async function loadFields() {
  $("#field-kinds").innerHTML = KINDS.map((k) =>
    `<button class="chip ${k === fieldKind ? "is-active" : ""}" data-k="${k}">${k || "all"}</button>`).join("");
  $$("#field-kinds .chip").forEach((c) => c.addEventListener("click", () => { fieldKind = c.dataset.k; loadFields(); }));
  const q = $("#field-filter").value.trim();
  const params = new URLSearchParams();
  if (fieldKind) params.set("kind", fieldKind);
  if (q) params.set("q", q);
  let fields = []; try { fields = await (await fetch("/fields?" + params)).json(); } catch { return; }
  const g = $("#fields-grid");
  if (!fields.length) { g.innerHTML = `<tbody><tr><td class="empty" style="padding:24px">No fields match.</td></tr></tbody>`; return; }
  g.innerHTML = `<thead><tr><th>Document</th><th>Key</th><th>Value</th><th>Type</th></tr></thead><tbody>` +
    fields.map((f) => `<tr data-doc="${f.document_id}"><td>${esc(f.document_title)}</td><td class="field-key">${esc(f.key)}</td><td>${esc(f.value)}</td><td><span class="field-kind">${f.kind}</span></td></tr>`).join("") +
    `</tbody>`;
  $$("#fields-grid tr[data-doc]").forEach((el) => el.addEventListener("click", () => openDetail(el.dataset.doc)));
}
let fieldFilterTimer = null;
$("#field-filter").addEventListener("input", () => { clearTimeout(fieldFilterTimer); fieldFilterTimer = setTimeout(loadFields, 200); });

const STOP = new Set("a an the is are was were be been am im i who what when where why how which of to in on at for and or but if it its this that as by with from do does did can could will would my me you your we".split(" "));
function mark(text, q) {
  const terms = q.toLowerCase().split(/\s+/).filter((t) => t.length > 1 && !STOP.has(t)).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return terms.length ? text.replace(new RegExp(`(${terms.join("|")})`, "gi"), "<mark>$1</mark>") : text;
}

$("#q").addEventListener("input", () => { if (!$("#q").value.trim()) loadOverview(); });
loadStats();
loadOverview();
