// ============================================================
// Retail POS Automation Console - front end.
// Polls /api/status + /api/logs, renders progress, the audit
// step timeline, failures, history. No framework, no build.
// ============================================================

const $ = (id) => document.getElementById(id);
const logOutput = $("log-output");
const suiteButtons = document.querySelectorAll(".suite-card");
const stopBtn = $("stop-btn");
const reportLink = $("report-link");

let logCursor = 0;
let logStarted = false;
// A refresh must come up in the initial state: a run that FINISHED before
// this page loaded is treated as idle and its log is not replayed. Only a
// run still in progress (or one started after load) is shown.
const pageLoadedAt = Date.now() / 1000;
let seenRunningSinceLoad = false;
let logPrimed = false;
let logFilter = "all";
let lastStatus = null;
let historyLoadedFor = null;

// ---------- helpers ----------
function fmtElapsed(ms) {
  const t = Math.max(0, Math.floor(ms / 1000));
  return Math.floor(t / 60) + "m " + String(t % 60).padStart(2, "0") + "s";
}
function fmtWhen(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " +
         d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
function classify(line) {
  if (/FAILED|ERROR|Traceback|AssertionError|RuntimeError/.test(line)) return "line-fail";
  if (/PASSED/.test(line)) return "line-pass";
  if (/^\[audit_flow\]/.test(line)) return "line-step";
  if (/^---/.test(line)) return "line-muted";
  return "";
}
function matchesFilter(line, cls) {
  if (logFilter === "all") return true;
  if (logFilter === "steps") return cls === "line-step" || cls === "line-muted";
  if (logFilter === "tests") return /::test_/.test(line);
  if (logFilter === "errors") return cls === "line-fail";
  return true;
}

// ---------- run a suite ----------
const emailToggle = $("email-toggle");
try { emailToggle.checked = localStorage.getItem("emailDevs") === "1"; } catch (e) {}
emailToggle.addEventListener("change", () => { try { localStorage.setItem("emailDevs", emailToggle.checked ? "1" : "0"); } catch (e) {} });

async function loadMailStatus() {
  try {
    const s = await (await fetch("/api/mail-status")).json();
    $("mail-cfg").classList.toggle("hidden", s.configured);
    $("email-wrap").title = s.configured ? "Will send to: " + s.to.join(", ") : "Set SMTP_* and MAIL_TO in pos_framework/.env";
  } catch (e) {}
}

async function runSuite(key, options) {
  options = Object.assign({}, options || {}, { email: emailToggle.checked, group_flag_pin: groupPin.checked });
  const res = await fetch("/api/run/" + key, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(options),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
  return data.ok;
}

// The Exe Setup tasks take the back office to fetch the token from, chosen
// in the folder header. Remembered, so the next run defaults to the same one.
const setupEnv = document.getElementById("setup-env");
if (setupEnv) {
  const saved = localStorage.getItem("setup-env");
  if (saved) setupEnv.value = saved;
  setupEnv.addEventListener("change", () => {
    try { localStorage.setItem("setup-env", setupEnv.value); } catch (e) {}
  });
}

suiteButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.hasOptions === "1") { openAuditModal(); return; }
    const extra = {};
    if (setupEnv && btn.dataset.suite.startsWith("setup_")) {
      extra.setup_env = setupEnv.value;
    }
    runSuite(btn.dataset.suite, extra);
  });
});

stopBtn.addEventListener("click", async () => {
  if (!confirm("Stop the running suite? The browser / POS app is killed mid-action.")) return;
  const res = await fetch("/api/stop", { method: "POST" });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

function resetView() {
  logOutput.textContent = "Waiting for a run…"; logStarted = false;
  seenRunningSinceLoad = false;
  document.querySelectorAll("[data-last]").forEach((el) => { el.innerHTML = '<span class="text-slate-600">never run</span>'; });
  renderStatus({ status: "idle", suite: null, label: null, options: {} });
}
$("reset-btn").addEventListener("click", async () => {
  if (!confirm("Reset the console? This also clears the run history.")) return;
  const data = await (await fetch("/api/reset", { method: "POST" })).json();
  if (!data.ok) { alert(data.message); return; }
  const d = await (await fetch("/api/logs?since=0")).json(); logCursor = d.next;
  resetView();
  historyLoadedFor = null;   // the table is stale now, draw it again
  loadHistory();
});

$("clear-btn").addEventListener("click", async () => {
  await fetch("/api/clear-logs", { method: "POST" });
  logOutput.textContent = "Waiting for a run…";
  logStarted = false; logCursor = 0;
});

document.querySelectorAll("#log-filters .chip").forEach((c) => {
  c.addEventListener("click", () => {
    document.querySelectorAll("#log-filters .chip").forEach((x) => x.classList.remove("chip-on"));
    c.classList.add("chip-on");
    logFilter = c.dataset.filter;
    logOutput.querySelectorAll("div").forEach((d) => {
      d.classList.toggle("hidden", !matchesFilter(d.textContent, d.dataset.cls || ""));
    });
  });
});

// ---------- audit modal ----------
const modal = $("audit-modal");
const envSelect = $("audit-env-tag");
function modeRadio(v) { return document.querySelector("input[name='audit-mode'][value='" + v + "']"); }

function openAuditModal() { modal.classList.remove("hidden"); loadAuditEnvs(); }
function closeAuditModal() { modal.classList.add("hidden"); }
$("audit-close").addEventListener("click", closeAuditModal);
$("audit-cancel").addEventListener("click", closeAuditModal);
modal.addEventListener("click", (e) => { if (e.target === modal) closeAuditModal(); });

async function loadAuditEnvs() {
  envSelect.innerHTML = "<option value=''>loading…</option>"; envSelect.disabled = true;
  try {
    const data = await (await fetch("/api/audit-envs")).json();
    envSelect.innerHTML = "";
    if (!data.envs || !data.envs.length) {
      envSelect.innerHTML = "<option value=''>no earlier data — build fresh</option>";
      modeRadio("build").checked = true;
    } else {
      for (const e of data.envs) {
        const o = document.createElement("option");
        o.value = e.tag; o.textContent = e.tag + "  ·  " + e.suppliers + " suppliers, " + e.items + " items";
        envSelect.appendChild(o);
      }
      modeRadio("reuse").checked = true;
    }
  } catch (e) {
    envSelect.innerHTML = "<option value=''>DB not reachable</option>"; modeRadio("build").checked = true;
  } finally { syncMode(); }
}
function syncMode() {
  const mode = document.querySelector("input[name='audit-mode']:checked").value;
  const hasEnvs = envSelect.options.length && envSelect.options[0].value !== "";
  envSelect.disabled = (mode === "build") || !hasEnvs;   // reuse AND resume both need one
}
document.querySelectorAll("input[name='audit-mode']").forEach((r) => r.addEventListener("change", syncMode));

$("audit-start").addEventListener("click", async () => {
  const mode = document.querySelector("input[name='audit-mode']:checked").value;
  const opts = { mode, env_tag: mode === "build" ? "" : envSelect.value, headed: $("audit-headed").checked,
                 seed: $("audit-seed").value.trim() };
  if (mode !== "build" && !opts.env_tag) { alert("Pick an environment first, or choose Build fresh data."); return; }
  if (await runSuite("audit", opts)) closeAuditModal();
});

// ---------- rendering ----------
function renderTimeline(steps) {
  const box = $("timeline");
  if (!steps || !steps.length) { box.classList.add("hidden"); box.innerHTML = ""; return; }
  box.classList.remove("hidden");
  box.innerHTML = steps.map((s, i) =>
    `<div class="step step-${s.state}"><div class="n">${s.state === "done" ? "✓" : s.state === "failed" ? "✕" : i + 1}</div>` +
    `<div class="l">${s.label}</div><div class="d">${s.detail || ""}</div></div>`).join("");
}

function renderFailures(list) {
  const wrap = $("failures"), ul = $("failure-list");
  if (!list || !list.length) { wrap.classList.add("hidden"); ul.innerHTML = ""; return; }
  wrap.classList.remove("hidden");
  ul.innerHTML = list.map((f) => `<li class="fail-item"><span class="t">${esc(f.test)}</span><span class="r">${esc(f.reason)}</span></li>`).join("");
}
function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

function isStaleRun(s) {
  if (s.status === "running") { seenRunningSinceLoad = true; return false; }
  if (s.status === "idle") return false;
  if (seenRunningSinceLoad) return false;
  return (s.finished_at || 0) < pageLoadedAt;
}

function renderStatus(s) {
  if (isStaleRun(s)) s = { status: "idle", suite: null, label: null, options: {} };
  const running = s.status === "running";
  suiteButtons.forEach((b) => { b.disabled = running; b.classList.toggle("is-running", running && b.dataset.suite === s.suite); });
  stopBtn.disabled = !running;

  const badge = $("status-badge");
  const map = { idle: ["Idle", "badge-idle"], running: ["Running", "badge-running"], stopped: ["Stopped", "badge-stopped"],
                done: [s.exit_code === 0 ? "Passed" : "Failed", s.exit_code === 0 ? "badge-passed" : "badge-failed"] };
  const [txt, cls] = map[s.status] || map.idle;
  badge.textContent = txt; badge.className = "badge " + cls;

  $("status-title").textContent = s.label || "No run yet";
  const opts = s.options || {};
  const optTxt = s.suite === "audit" ? (opts.mode === "reuse" ? "reusing data " + opts.env_tag : "building fresh data") + (opts.headed ? " · headed" : " · headless") : "";
  $("status-sub").textContent = s.status === "idle" ? "Pick a suite on the left." :
    s.status === "running" ? (s.current_test ? "▸ " + s.current_test : "starting…") + (optTxt ? "  ·  " + optTxt : "") :
    s.status === "stopped" ? "Stopped by user." : "Finished with exit code " + s.exit_code + (optTxt ? "  ·  " + optTxt : "");

  // progress
  const total = s.tests_total || 0, done = (s.passed || 0) + (s.failed || 0) + (s.errors || 0) + (s.skipped || 0);
  const prog = document.querySelector(".progress");
  prog.classList.toggle("indeterminate", running && !total);
  $("bar-pass").style.width = total ? (100 * (s.passed || 0) / total) + "%" : "0%";
  $("bar-fail").style.width = total ? (100 * ((s.failed || 0) + (s.errors || 0)) / total) + "%" : "0%";
  $("progress-text").textContent = total ? `${done} / ${total} tests` : (running ? "collecting…" : "—");
  $("current-test").textContent = running && s.current_test ? s.current_test : "";

  $("k-pass").textContent = s.passed || 0;
  $("k-fail").textContent = s.failed || 0;
  $("k-err").textContent = (s.errors || 0) + " / " + (s.skipped || 0);
  $("k-audit").textContent = s.audit_code ? s.audit_code + (s.seed ? " · " + s.seed : "") : (s.seed ? "seed " + s.seed : "—");

  renderTimeline(s.suite === "audit" ? s.audit_steps : null);
  renderFailures(s.failures);

  const mr = $("mail-result");
  if (s.mail) {
    mr.classList.remove("hidden");
    mr.innerHTML = (s.mail.ok ? '<span class="tag tag-green">mail sent</span> ' : '<span class="tag tag-red">mail failed</span> ') +
                   '<span class="text-slate-400">' + esc(s.mail.message) + "</span>";
  } else mr.classList.add("hidden");

  if (s.status === "done" && s.report_ready) { reportLink.href = s.report_route || "/report/"; reportLink.classList.remove("hidden"); }
  else reportLink.classList.add("hidden");

  const start = s.started_at ? s.started_at * 1000 : null;
  $("elapsed").textContent = start ? fmtElapsed((s.finished_at ? s.finished_at * 1000 : Date.now()) - start) : "";

  // refresh history + cards when a run finishes
  const key = s.status + ":" + (s.finished_at || 0);
  if (!running && key !== historyLoadedFor) { historyLoadedFor = key; loadHistory(); }
}

function appendLogLines(lines) {
  if (!lines.length) return;
  if (!logStarted) { logOutput.textContent = ""; logStarted = true; }
  for (const line of lines) {
    const div = document.createElement("div");
    const cls = classify(line);
    div.dataset.cls = cls; div.className = cls + (matchesFilter(line, cls) ? "" : " hidden");
    div.textContent = line;
    logOutput.appendChild(div);
  }
  if ($("autoscroll").checked) logOutput.scrollTop = logOutput.scrollHeight;
}

// One verdict for every kind of run. The Exe Setup chores carry no tests,
// so counting failures told us "0 failed" on a run that had gone perfectly -
// go by the exit code when there is nothing to count.
function verdictTag(r) {
  if (r.status === "stopped") return `<span class="tag tag-amber">stopped</span>`;
  const bad = (r.failed || 0) + (r.errors || 0);
  if (r.status === "done" && r.exit_code === 0) return `<span class="tag tag-green">passed</span>`;
  if (bad > 0) return `<span class="tag tag-red">${bad} failed</span>`;
  return `<span class="tag tag-red">failed</span>`;
}

// ---------- history ----------
async function loadHistory() {
  const data = await (await fetch("/api/history")).json();
  const body = $("history-body");
  if (!data.history.length) { body.innerHTML = `<tr><td colspan="7" class="td text-slate-600">No runs recorded yet.</td></tr>`; }
  else {
    body.innerHTML = data.history.slice(0, 30).map((h) => {
      const ok = h.status === "done" && h.exit_code === 0;
      const tag = verdictTag(h);
      const replay = h.suite === "audit" && h.seed ? `<button class="btn btn-ghost replay" data-seed="${h.seed}" data-tag="${(h.options || {}).env_tag || ""}">replay</button>` : "";
      return `<tr><td class="td text-slate-400">${fmtWhen(h.started_at)}</td><td class="td">${esc(h.label || h.suite)}</td><td class="td">${tag}</td>` +
             `<td class="td font-mono">${h.passed || 0}/${h.tests_total || 0}</td><td class="td font-mono">${fmtElapsed((h.duration || 0) * 1000)}</td>` +
             `<td class="td font-mono text-indigo-300">${h.audit_code || ""}</td><td class="td text-right">${replay}</td></tr>`;
    }).join("");
    body.querySelectorAll(".replay").forEach((b) => b.addEventListener("click", () => {
      openAuditModal(); $("audit-seed").value = b.dataset.seed;
      setTimeout(() => { if (b.dataset.tag) { envSelect.value = b.dataset.tag; modeRadio("reuse").checked = true; syncMode(); } }, 800);
    }));
  }
  // suite cards: last result - only for runs finished after this page loaded
  for (const [key, lr] of Object.entries(data.last || {})) {
    const el = document.querySelector(`[data-last="${key}"]`); if (!el) continue;
    if ((lr.finished_at || 0) < pageLoadedAt) continue;
    const ok = lr.status === "done" && lr.exit_code === 0;
    const tag = verdictTag(lr);
    el.innerHTML = tag + `<span class="text-slate-500">${lr.passed || 0}/${lr.tests_total || 0} · ${fmtElapsed((lr.duration || 0) * 1000)} · ${fmtWhen(lr.started_at)}</span>`;
  }
}
$("history-clear").addEventListener("click", async () => {
  if (!confirm("Clear the run history?")) return;
  await fetch("/api/history/clear", { method: "POST" }); loadHistory();
});

// ---------- polling ----------
async function pollStatus() { try { renderStatus(lastStatus = await (await fetch("/api/status")).json()); } catch (e) {} }
async function pollLogs() {
  try {
    const d = await (await fetch("/api/logs?since=" + logCursor)).json();
    if (!logPrimed) {
      // first poll after load: skip whatever an earlier run left behind,
      // unless a run is in progress right now
      logPrimed = true;
      if (!(lastStatus && lastStatus.status === "running")) { logCursor = d.next; return; }
    }
    appendLogLines(d.lines); logCursor = d.next;
  } catch (e) {}
}
async function pollApp() {
  const pill = $("pill-app"), t = pill.querySelector(".pill-text");
  try { const s = await (await fetch("/api/app-status")).json();
    pill.className = "pill " + (s.running ? "pill-ok" : "pill-bad"); t.textContent = s.running ? "POS app · PID " + s.pid : "POS app closed";
  } catch (e) { pill.className = "pill pill-unknown"; t.textContent = "POS app ?"; }
}
async function pollDb() {
  const pill = $("pill-db"), t = pill.querySelector(".pill-text");
  try { const s = await (await fetch("/api/db-status")).json();
    pill.className = "pill " + (s.ok ? "pill-ok" : "pill-bad"); t.textContent = s.ok ? "DB connected" : "DB unreachable";
    pill.title = s.reason || "";
  } catch (e) { pill.className = "pill pill-unknown"; t.textContent = "DB ?"; }
}
// ---- POS exe settings card (see exe_settings.py) ----
const groupFlag = $("exe-group-flag"), groupPin = $("exe-group-pin");
try { groupPin.checked = localStorage.getItem("exeGroupPin") !== "0"; } catch (e) { groupPin.checked = true; }
groupPin.addEventListener("change", () => { try { localStorage.setItem("exeGroupPin", groupPin.checked ? "1" : "0"); } catch (e) {} });
let exeBusy = false;
function renderExe(s) {
  const note = $("exe-flag-note");
  $("exe-pkg").textContent = (s.version ? "v" + s.version : "") + (s.package ? " · " + s.package : "");
  if (!s.ok) { groupFlag.disabled = true; note.textContent = s.error || "exe cache not readable"; note.className = "text-[11px] text-rose-400 mt-2"; return; }
  const st = s.settings;
  groupFlag.disabled = exeBusy; groupFlag.checked = !!st.IsCustomerGroupInProductDiscount;
  note.textContent = (st.IsCustomerGroupInProductDiscount ? "ON - only the assigned customer group gets the discount" : "OFF - everyone gets the discount (automation expects ON)")
    + (s.exe_running ? " · exe is running: a change applies after restart" : "");
  note.className = "text-[11px] mt-2 " + (st.IsCustomerGroupInProductDiscount ? "text-emerald-400" : "text-amber-400");
  $("exe-inv").textContent = st.strInvoiceName || "–"; $("exe-inv-re").textContent = st.strInvoiceRePrintName || "–";
  $("exe-counter").textContent = (st.StrCounterName || "–") + (st.intCounterId ? " (#" + st.intCounterId + ")" : "");
  renderInvoice(s);
}
// ---- invoice template picker ----
const invSelect = $("exe-inv-select"), invApply = $("exe-inv-apply"), invNote = $("exe-inv-note");
let invBusy = false, invUserPicked = false;
function renderInvoice(s) {
  const st = s.settings, srv = s.server_invoice, tpls = s.templates || [];
  $("exe-inv-srv").textContent = srv ? (srv.strInvoiceName || "–") : "(DB unreachable)";
  // The list is what the INSTALLED exe can actually render. A template
  // that is set but not shipped in this build has no option, and the
  // select would then silently fall back to its first entry - showing a
  // template nobody chose. So the set-but-missing one is added, marked,
  // and kept selected.
  const setSale = st.strInvoiceName || "";
  const missing = setSale && !tpls.some((t) => t.sale === setSale);
  const sig = tpls.map((t) => t.sale).join("|") + (missing ? "|missing:" + setSale : "");
  if (invSelect.dataset.sig !== sig) {
    invSelect.innerHTML = "";
    if (missing) {
      const o = document.createElement("option");
      o.value = setSale; o.dataset.reprint = st.strInvoiceRePrintName || "";
      o.textContent = "(not in this exe)  ·  " + setSale;
      invSelect.appendChild(o);
    }
    tpls.forEach((t) => { const o = document.createElement("option"); o.value = t.sale; o.dataset.reprint = t.reprint; o.textContent = t.label + "  ·  " + t.sale; invSelect.appendChild(o); });
    invSelect.dataset.sig = sig; invUserPicked = false;
  }
  if (!invUserPicked && setSale) invSelect.value = setSale;
  invSelect.disabled = invBusy || !tpls.length; invApply.disabled = invBusy || !tpls.length;
  if (!invBusy) {
    const mismatch = srv && st.strInvoiceName && srv.strInvoiceName !== st.strInvoiceName;
    let text = "", tone = "text-slate-400";
    if (missing) {
      text = setSale + " is set, but this exe (" + (s.version || "?") +
             ") does not ship it - printing will fail until it does";
      tone = "text-rose-400";
    } else if (mismatch) {
      text = "exe cache and server DIFFER - Apply to make them agree";
      tone = "text-amber-400";
    } else if (s.exe_running) {
      text = "exe is running: a change prints after restart";
    }
    invNote.textContent = text;
    invNote.className = "text-[11px] mt-2 " + tone;
  }
}
invSelect.addEventListener("change", () => { invUserPicked = true; });
invApply.addEventListener("click", async () => {
  const opt = invSelect.selectedOptions[0]; if (!opt) return;
  invBusy = true; invSelect.disabled = true; invApply.disabled = true; invNote.textContent = "writing server + exe cache…"; invNote.className = "text-[11px] mt-2 text-slate-400";
  try {
    const r = await (await fetch("/api/exe-settings/invoice", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sale: opt.value, reprint: opt.dataset.reprint }) })).json();
    invBusy = false; invUserPicked = false;
    if (r.state) renderExe(r.state);
    invNote.textContent = r.message; invNote.className = "text-[11px] mt-2 " + (r.ok ? "text-emerald-400" : "text-rose-400");
  } catch (e) { invBusy = false; invNote.textContent = "failed: " + e; invNote.className = "text-[11px] mt-2 text-rose-400"; }
  invSelect.disabled = false; invApply.disabled = false;
});
async function pollExe() { try { renderExe(await (await fetch("/api/exe-settings")).json()); } catch (e) {} }
groupFlag.addEventListener("change", async () => {
  exeBusy = true; groupFlag.disabled = true;
  try {
    const r = await (await fetch("/api/exe-settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ group_flag: groupFlag.checked }) })).json();
    if (!r.ok) alert(r.message); else if (r.state) { exeBusy = false; renderExe(r.state); $("exe-flag-note").textContent = r.message; }
  } catch (e) { alert("could not update the exe cache: " + e); }
  exeBusy = false; groupFlag.disabled = false;
});

function tickClock() { $("clock").textContent = new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }

setInterval(pollStatus, 1200); setInterval(pollLogs, 1000); setInterval(pollApp, 5000); setInterval(pollDb, 20000); setInterval(pollExe, 10000); setInterval(tickClock, 1000);
(async () => { await pollStatus(); await pollLogs(); })(); pollApp(); pollDb(); pollExe(); tickClock(); loadHistory(); loadMailStatus();

/* ============================================================
   BRANCH SETTINGS - one switch per outlet.
   Kept deliberately plain: each toggle writes one branch, waits
   for the server's answer, and re-reads the list from it. No
   optimistic flip, because a refused write would otherwise leave
   the page showing a setting the outlet does not have.
   ============================================================ */
(function () {
  var list = document.getElementById("branch-list");
  if (!list) return;
  var note = document.getElementById("branch-note");
  var refresh = document.getElementById("branch-refresh");
  var toggle = document.getElementById("branch-toggle");
  var body = document.getElementById("branch-body");
  var chevron = document.getElementById("branch-chevron");
  var summary = document.getElementById("branch-summary");
  var REMEMBER = "branch-card-open";

  function say(text, bad) {
    if (!note) return;
    note.textContent = text || "";
    note.className = "text-[11px] mt-2 " + (bad ? "text-rose-300" : "text-slate-400");
  }

  function setOpen(open) {
    body.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    chevron.classList.toggle("open", open);
    // A per-viewer convenience only; a browser that refuses storage just
    // gets the collapsed default every time, which is fine.
    try { localStorage.setItem(REMEMBER, open ? "1" : "0"); } catch (e) {}
  }

  function render(state) {
    if (state.ok) {
      var off = state.branches.filter(function (b) { return !b.vat_inclusive; }).length;
      var on = state.branches.length - off;
      summary.textContent = off + " off · " + on + " on";
    } else {
      summary.textContent = "unavailable";
    }
    if (!state.ok) {
      list.innerHTML = '<div class="text-[11px] text-rose-300">' +
        (state.message || "could not read the branches") + "</div>";
      return;
    }
    list.innerHTML = state.branches.map(function (b) {
      var id = "vatinc-" + b.id;
      return '' +
        '<div class="branch-row" data-branch="' + b.id + '">' +
          '<div class="min-w-0">' +
            '<div class="branch-name">' + b.name +
              (b.mismatch ? ' <span class="branch-mismatch">columns disagree</span>' : '') +
            '</div>' +
            '<div class="branch-meta">account ' + b.account_id + ' &middot; id ' + b.id + '</div>' +
          '</div>' +
          '<label class="switch" title="' +
            (b.vat_inclusive ? "VAT is inside the rate" : "VAT is added on top") + '">' +
            '<input type="checkbox" id="' + id + '" data-branch="' + b.id + '"' +
              (b.vat_inclusive ? " checked" : "") + ">" +
            '<span class="slider"></span>' +
          "</label>" +
        "</div>";
    }).join("");
  }

  function load() {
    return fetch("/api/branch-settings")
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function (e) { say("could not read the branches: " + e.message, true); });
  }

  list.addEventListener("change", function (e) {
    var box = e.target.closest("input[type=checkbox][data-branch]");
    if (!box) return;
    var row = box.closest(".branch-row");
    var wanted = box.checked;
    box.disabled = true;
    row.classList.add("busy");
    say("saving…");

    fetch("/api/branch-settings/vat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch_id: Number(box.dataset.branch), value: wanted })
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        say(res.message || (res.ok ? "saved" : "not saved"), !res.ok);
        if (res.state) render(res.state); else load();
      })
      .catch(function (err) {
        say("not saved: " + err.message, true);
        load();
      });
  });

  toggle.addEventListener("click", function () {
    setOpen(body.hidden);
  });

  if (refresh) refresh.addEventListener("click", function () { say(""); load(); });

  var remembered = "0";
  try { remembered = localStorage.getItem(REMEMBER) || "0"; } catch (e) {}
  setOpen(remembered === "1");
  load();
})();


// ---------- suite folders ----------
// One card that opens to show the tasks inside. The buttons within are
// ordinary .suite-card elements and were bound with the rest at load, so
// nothing here touches how a run is started.
document.querySelectorAll(".suite-folder").forEach((folder) => {
  const head = folder.querySelector(".folder-head");
  if (!head) return;
  const key = "folder:" + (folder.dataset.folder || "");
  if (localStorage.getItem(key) === "open") {
    folder.classList.add("is-open");
    head.setAttribute("aria-expanded", "true");
  }
  head.addEventListener("click", () => {
    const open = folder.classList.toggle("is-open");
    head.setAttribute("aria-expanded", open ? "true" : "false");
    try { localStorage.setItem(key, open ? "open" : "shut"); } catch (e) {}
  });
});
