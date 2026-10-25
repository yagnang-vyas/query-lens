// QueryLens playground. All rendering uses textContent / DOM nodes, never innerHTML, so log
// content (which ends up in query text) cannot inject markup.
"use strict";

const MAX_BYTES = 5 * 1024 * 1024;
const TIMEOUT_MS = 60000;
const $ = (id) => document.getElementById(id);

const state = { worker: null, ready: false, busy: false, nextId: 1, timer: null, pending: null, data: null, outputs: null, bytes: null };

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  if (props) for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

const fmtMs = (n) => (n == null ? "–" : n.toLocaleString("en-US", { maximumFractionDigits: n >= 100 ? 0 : 1 }) + " ms");
const fmtInt = (n) => (n == null ? "–" : n.toLocaleString("en-US"));
const fmtBytes = (n) => (n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB");

// ---- worker lifecycle ------------------------------------------------------------------------
function startWorker() {
  state.ready = false;
  setEngine("Loading the analysis engine… (first load downloads about 10 MB)");
  syncControls();
  const worker = new Worker("worker.js");
  state.worker = worker;
  worker.onmessage = (event) => {
    const msg = event.data;
    if (worker !== state.worker) return;
    if (msg.type === "ready") {
      state.ready = true;
      setEngine("Engine ready: querylens " + msg.version + " running locally in your browser.");
      syncControls();
    } else if (msg.type === "fatal") {
      setEngine("");
      showError("The analysis engine could not be loaded (" + msg.message + "). Check your connection and reload the page. The engine is downloaded from the jsDelivr CDN.");
    } else if (msg.type === "result" && state.pending === msg.id) {
      finish(); showResult(msg.result);
    } else if (msg.type === "failure" && state.pending === msg.id) {
      finish(); showError("The analysis failed unexpectedly: " + msg.message);
    }
  };
  worker.onerror = () => { setEngine(""); showError("The analysis engine crashed. Reload the page to try again."); };
}

function finish() {
  clearTimeout(state.timer);
  state.pending = null; state.busy = false;
  $("run-status").textContent = "";
  syncControls();
}

function setEngine(text) { $("engine-status").textContent = text; }

function syncControls() {
  const ready = state.ready && !state.busy;
  $("run").disabled = !ready;
  document.querySelectorAll("[data-sample]").forEach((b) => { b.disabled = !ready; });
}

// ---- input -----------------------------------------------------------------------------------
function setLog(text, bytes, label) {
  $("log").value = text;
  state.bytes = bytes || null;
  updateMeta(label);
}

function updateMeta(label) {
  const size = state.bytes ? state.bytes.length : new TextEncoder().encode($("log").value).length;
  $("log-meta").textContent = "(" + (label ? label + ", " : "") + fmtBytes(size) + ")";
}

async function loadSample(name) {
  clearOutput();
  try {
    const response = await fetch("samples/" + name);
    if (!response.ok) throw new Error("HTTP " + response.status);
    const text = await response.text();
    setLog(text, null, name);
    analyze();
  } catch (error) {
    showError("Could not load the sample: " + error.message);
  }
}

async function loadFile(file) {
  clearOutput();
  if (!file) return;
  if (file.size > MAX_BYTES) { showError("That file is " + fmtBytes(file.size) + ". The demo accepts logs up to 5 MB; use the CLI for larger files, or paste an excerpt."); return; }
  const buffer = new Uint8Array(await file.arrayBuffer());
  if (buffer[0] === 0x1f && buffer[1] === 0x8b) { showError("That looks like a gzip file. Decompress it first (the demo reads plain text only), or use the CLI, which reads .gz directly."); return; }
  const text = new TextDecoder("utf-8", { fatal: false }).decode(buffer);
  setLog(text, buffer, file.name);
}

// ---- running ---------------------------------------------------------------------------------
function readOptions() {
  const top = Math.min(500, Math.max(1, parseInt($("opt-top").value, 10) || 50));
  return {
    format: $("opt-format").value, sort: $("opt-sort").value, top,
    minDuration: $("opt-min").value.trim() === "" ? 0 : $("opt-min").value.trim(),
    failOverMs: $("opt-over").value.trim(), failOnHint: $("opt-hints").value.trim(),
  };
}

function analyze() {
  if (!state.ready || state.busy) return;
  clearOutput();
  const text = $("log").value;
  const bytes = state.bytes || new TextEncoder().encode(text);
  if (bytes.length === 0 || text.trim() === "") { showError("Nothing to analyze. Paste a log, load a sample or choose a file."); return; }
  if (bytes.length > MAX_BYTES) { showError("The log is " + fmtBytes(bytes.length) + ". The demo accepts up to 5 MB."); return; }
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) { showError("Compressed input is not supported in the demo. Decompress it first."); return; }
  state.busy = true; syncControls();
  $("run-status").textContent = "Analyzing " + fmtBytes(bytes.length) + "…";
  const id = state.nextId++;
  state.pending = id;
  state.timer = setTimeout(() => {
    state.worker.terminate();
    finish();
    showError("The analysis took longer than 60 seconds and was stopped. Try a smaller excerpt or use the CLI.");
    startWorker();
  }, TIMEOUT_MS);
  state.worker.postMessage({ type: "analyze", id, bytes: bytes.slice(), options: readOptions() });
}

function clearOutput() {
  $("error").hidden = true; $("results").hidden = true;
  state.data = null; state.outputs = null;
}

function showError(message) {
  const box = $("error");
  box.textContent = message; box.hidden = false;
  $("results").hidden = true;
}

// ---- results ---------------------------------------------------------------------------------
function showResult(result) {
  if (result.code === 2) {
    showError((result.stderr || "QueryLens could not analyze this input.").trim().replace(/^querylens: error: /, "") +
      "\n\nThe demo supports PostgreSQL stderr logs and MySQL slow query logs.");
    return;
  }
  let data;
  try { data = JSON.parse(result.json); } catch { showError("The engine returned an unreadable report."); return; }
  state.data = data;
  state.outputs = { text: result.text, markdown: result.markdown, json: result.json };
  renderSummary(data);
  const gate = $("gate");
  gate.hidden = result.code !== 1;
  if (result.code === 1) gate.textContent = "CI gate: the CLI would exit with code 1. " + result.stderr.replace(/^querylens: failing: /m, "").trim();
  renderHintFilter(data);
  ["text", "markdown", "json"].forEach(renderReportTab);
  renderList();
  $("results").hidden = false;
  selectTab("patterns", false);
}

function renderSummary(data) {
  const { input, summary } = data;
  const items = [
    ["Format", input.format], ["Entries parsed", fmtInt(input.entries)], ["Malformed (skipped)", fmtInt(input.malformed)],
    ["Duration-only", fmtInt(input.duration_only)], ["Skipped phases", fmtInt(input.skipped_phase)], ["Filtered out", fmtInt(input.filtered_out)],
    ["Total time", fmtMs(summary.total_ms)], ["Unique patterns", fmtInt(summary.unique_fingerprints)],
  ];
  const dl = $("summary"); dl.replaceChildren();
  for (const [name, value] of items) dl.append(el("div", null, el("dt", { text: name }), el("dd", { text: String(value) })));
}

function renderHintFilter(data) {
  const select = $("hint-filter"); select.replaceChildren(el("option", { value: "", text: "any" }));
  select.append(el("option", { value: "*", text: "has any hint" }));
  for (const [id, hint] of Object.entries(data.hints || {})) select.append(el("option", { value: id, text: id + " " + hint.title }));
}

function visibleItems() {
  const term = $("q").value.trim().toLowerCase();
  const hint = $("hint-filter").value;
  const key = $("view-sort").value;
  const items = state.data.fingerprints.filter((f) =>
    (!term || f.query.includes(term) || f.id.includes(term)) &&
    (!hint || (hint === "*" ? f.hints.length > 0 : f.hints.includes(hint))));
  items.sort((a, b) => (b[key] - a[key]) || (a.id < b.id ? -1 : 1));
  return items;
}

function renderList() {
  const items = visibleItems();
  const total = state.data.fingerprints.length;
  const all = state.data.summary.unique_fingerprints;
  $("shown").textContent = "Showing " + items.length + " of " + total + " patterns";
  const note = $("truncated");
  note.hidden = all <= total;
  if (all > total) note.textContent = "The log has " + all + " unique patterns; the top " + total + " by the chosen --sort are loaded. Raise Top N (max 500) to see more.";
  $("empty").hidden = items.length > 0;
  const list = $("list"); list.replaceChildren();
  const max = Math.max(1, ...items.map((f) => f.share_pct));
  for (const f of items) list.append(patternNode(f, max));
}

function patternNode(f, maxShare) {
  const badges = el("div", { class: "badges" });
  for (const id of f.hints) badges.append(el("span", { class: "badge", text: id + " " + (state.data.hints[id]?.title || "") }));
  const bar = el("div", { class: "bar-track", "aria-hidden": "true" }, el("span", { class: "bar-fill" }));
  bar.firstChild.style.width = (f.share_pct / maxShare * 100).toFixed(1) + "%";
  const nums = el("div", { class: "nums" },
    el("strong", { text: fmtMs(f.total_ms) }), document.createTextNode(" total · " + fmtInt(f.count) + "× · p95 " + fmtMs(f.p95_ms) + " · " + f.share_pct + "%"));
  const summary = el("summary", null, el("div", { class: "q", text: f.query }), nums, bar);
  if (f.hints.length) summary.append(badges);
  const stat = (name, value) => el("div", null, el("dt", { text: name }), el("dd", { text: value }));
  const stats = el("dl", { class: "stats" },
    stat("Count", fmtInt(f.count)), stat("Total", fmtMs(f.total_ms)), stat("Mean", fmtMs(f.mean_ms)), stat("p50", fmtMs(f.p50_ms)),
    stat("p95", fmtMs(f.p95_ms)), stat("Max", fmtMs(f.max_ms)), stat("Share", f.share_pct + "%"), stat("ID", f.id));
  if (f.rows_examined_total != null) {
    stats.append(stat("Rows sent", fmtInt(f.rows_sent_total)), stat("Rows examined", fmtInt(f.rows_examined_total)), stat("Examined / sent", f.examined_per_sent == null ? "–" : String(f.examined_per_sent)));
  }
  const detail = el("div", { class: "detail" },
    el("div", { class: "report-actions" }, copyButton("Copy normalized SQL", () => f.query)),
    el("pre", { class: "sql", text: f.query }), stats);
  if (f.hints.length) {
    const ul = el("ul", { class: "hint-list" });
    for (const id of f.hints) {
      const hint = state.data.hints[id] || {};
      ul.append(el("li", null, el("strong", { text: id + " " + (hint.title || "") + ": " }), document.createTextNode(hint.description || "")));
    }
    detail.append(el("p", { class: "muted", text: "Hints are heuristics on query text only. They do not see schemas, indexes or plans." }), ul);
  }
  return el("details", { class: "pattern" }, summary, detail);
}

function copyButton(label, getText) {
  const button = el("button", { type: "button", class: "btn small", text: label });
  button.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(getText()); button.textContent = "Copied"; }
    catch { button.textContent = "Copy failed: select the text manually"; }
    setTimeout(() => { button.textContent = label; }, 1800);
  });
  return button;
}

function renderReportTab(kind) {
  const panel = $("panel-" + kind); panel.replaceChildren();
  const ext = { text: "txt", markdown: "md", json: "json" }[kind];
  const download = el("button", { type: "button", class: "btn small", text: "Download" });
  download.addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([state.outputs[kind]], { type: "text/plain" }));
    const a = el("a", { href: url, download: "querylens-report." + ext }); a.click(); URL.revokeObjectURL(url);
  });
  panel.append(el("p", { class: "muted", text: "Output of the real querylens CLI for these options (--output " + kind + ")." }),
    el("div", { class: "report-actions" }, copyButton("Copy", () => state.outputs[kind]), download),
    el("pre", { class: "report", tabindex: "0", text: state.outputs[kind] }));
}

// ---- tabs ------------------------------------------------------------------------------------
const TABS = ["patterns", "text", "markdown", "json"];
function selectTab(name, focus) {
  for (const t of TABS) {
    const tab = $("tab-" + t), on = t === name;
    tab.setAttribute("aria-selected", String(on)); tab.tabIndex = on ? 0 : -1;
    $("panel-" + t).hidden = !on;
    if (on && focus) tab.focus();
  }
}

// ---- wiring ----------------------------------------------------------------------------------
document.querySelectorAll("[data-sample]").forEach((b) => b.addEventListener("click", () => loadSample(b.dataset.sample)));
$("file").addEventListener("change", (e) => { loadFile(e.target.files[0]); e.target.value = ""; });
$("log").addEventListener("input", () => { state.bytes = null; updateMeta(""); });
$("run").addEventListener("click", analyze);
$("clear").addEventListener("click", () => { setLog("", null, ""); clearOutput(); });
["q", "hint-filter", "view-sort"].forEach((id) => $(id).addEventListener("input", () => state.data && renderList()));
TABS.forEach((t, i) => $("tab-" + t).addEventListener("click", () => selectTab(t, false)));
$("tab-patterns").parentElement.addEventListener("keydown", (e) => {
  const current = TABS.findIndex((t) => $("tab-" + t).getAttribute("aria-selected") === "true");
  const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
  if (step) { e.preventDefault(); selectTab(TABS[(current + step + TABS.length) % TABS.length], true); }
  else if (e.key === "Home") { e.preventDefault(); selectTab(TABS[0], true); }
  else if (e.key === "End") { e.preventDefault(); selectTab(TABS[TABS.length - 1], true); }
});
updateMeta("");
startWorker();
