/* ============================================================
   BACK OFFICE PAGE
   ------------------------------------------------------------
   Renders one environment's coverage and drives runs of it.

   Two rules this file follows:

   1. NOTHING ABOUT THE SUITE IS WRITTEN HERE. The modules, the
      tests and their titles all arrive from /api/backoffice/
      <app>/catalog, which reads them out of the test files. Add
      a test, refresh, it is on the page - in its module.

   2. A RUN IS A RUN. Whether the button pressed was "Run all",
      a module's, or one test's, the same endpoint is called with
      a different target list, and the same live panel shows it.
      There is no second code path to keep in step.
   ============================================================ */

(function () {
  "use strict";

  var APP = document.body.dataset.app;
  var SUITE = document.body.dataset.suite;

  var el = function (id) { return document.getElementById(id); };
  var catalog = null;
  var filter = "all";
  var collapsed = {};          // module key -> hidden?
  var chosen = {};          // target -> true, for "Run selected"
  var logCursor = 0;
  var running = false;
  var tickTimer = null;

  /* ---- small helpers ---------------------------------------------- */

  function escapeHtml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function duration(ms) {
    if (!ms && ms !== 0) return "";
    if (ms < 1000) return ms + "ms";
    var s = ms / 1000;
    if (s < 60) return s.toFixed(1) + "s";
    return Math.floor(s / 60) + "m " + Math.round(s % 60) + "s";
  }

  function ago(seconds) {
    if (!seconds) return "";
    var diff = Date.now() / 1000 - seconds;
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.floor(diff / 60) + " min ago";
    if (diff < 86400) return Math.floor(diff / 3600) + " h ago";
    return new Date(seconds * 1000).toLocaleString();
  }

  // One vocabulary for a verdict, used by the dot, the pill and the filter,
  // so the three can never disagree about what a test's state is.
  function verdict(test) {
    var last = test.last;
    if (!last || !last.status) return { key: "never", label: "never run", cls: "v-never" };
    var status = last.status;
    if (status === "passed") return { key: "passed", label: "passed", cls: "v-pass" };
    if (status === "failed") return { key: "failed", label: "failed", cls: "v-fail" };
    if (status === "broken") return { key: "failed", label: "error", cls: "v-fail" };
    if (status === "skipped") return { key: "skipped", label: "skipped", cls: "v-skip" };
    return { key: "unknown", label: status, cls: "v-unknown" };
  }

  function matchesFilter(test) {
    if (filter === "all") return true;
    if (filter === "client_issue") return (test.markers || []).indexOf("client_issue") >= 0;
    return verdict(test).key === filter;
  }

  /* ---- rendering --------------------------------------------------- */

  function renderTiles(data) {
    var s = data.summary;
    el("k-total").textContent = s.total;
    el("k-pass").textContent = s.passed;
    el("k-fail").textContent = s.failed + s.broken;
    el("k-skip").textContent = s.skipped;
    el("k-never").textContent = s.never;

    var note = el("last-run");
    if (data.last_run_at) {
      note.innerHTML = "Last run " + escapeHtml(ago(data.last_run_at)) +
        " · results kept per environment, so the other server's run never overwrites this one.";
    } else {
      note.textContent = "Nothing has run against this environment yet.";
    }

    var link = el("report-link");
    if (data.has_report) {
      link.href = data.app.report_route;
      link.classList.remove("hidden");
    } else {
      link.classList.add("hidden");
    }
  }

  function testRow(test) {
    var v = verdict(test);
    var last = test.last || {};
    var markers = (test.markers || []).filter(function (m) {
      return m !== "module" && m !== "parametrize";
    });

    var meta = [];
    if (last.status) {
      meta.push(escapeHtml(v.label));
      if (last.duration_ms) meta.push(escapeHtml(duration(last.duration_ms)));
      if (last.stop) meta.push(escapeHtml(ago(last.stop / 1000)));
    }

    // A skip on this suite is not noise - it names the profile keys that
    // are still missing, which is exactly the next piece of work. Show it.
    var reason = "";
    if (last.message && (v.key === "skipped" || v.key === "failed")) {
      reason = '<div class="test-reason ' + (v.key === "failed" ? "reason-fail" : "") + '">' +
        escapeHtml(last.message.trim()) + "</div>";
    }

    // A parametrised test is several runs wearing one name. Listing the
    // scenarios lets one of them be re-run on its own, which is what you
    // want when only the heavy case fails.
    var scenarios = "";
    if ((test.variants || []).length) {
      scenarios = '<div class="variants">' + test.variants.map(function (x) {
        return '<button class="variant run-one" data-target="' + escapeHtml(x.target) + '" ' +
               'title="Run only this scenario">&#9654; ' + escapeHtml(x.label) + "</button>";
      }).join("") + "</div>";
    }

    var ticked = chosen[test.id] ? " checked" : "";
    return '' +
      '<li class="test-row" data-test="' + escapeHtml(test.id) + '">' +
        '<input type="checkbox" class="pick" id="pick-' + escapeHtml(test.id) + '" ' +
               'data-target="' + escapeHtml(test.id) + '"' + ticked + ' ' +
               'aria-label="Select this test">' +
        '<span class="v-dot ' + v.cls + '" title="' + escapeHtml(v.label) + '"></span>' +
        '<div class="min-w-0 flex-1">' +
          '<div class="flex items-center gap-2 flex-wrap">' +
            '<span class="test-title">' + escapeHtml(test.title) + '</span>' +
            markers.map(function (m) {
              return '<span class="tag tag-' + (m === "client_issue" ? "red" : "slate") + '">' +
                     escapeHtml(m) + "</span>";
            }).join("") +
          '</div>' +
          '<div class="test-meta">' +
            '<span class="font-mono">' + escapeHtml(test.name) + '</span>' +
            (meta.length ? ' <span class="text-slate-600">&middot;</span> ' +
                           meta.join(' <span class="text-slate-600">&middot;</span> ') : "") +
          '</div>' +
          reason +
          scenarios +
        '</div>' +
        '<button class="btn btn-ghost btn-xs run-one" data-target="' + escapeHtml(test.id) + '" ' +
                'title="Run this test">&#9654;</button>' +
      '</li>';
  }

  function moduleCard(module) {
    var tests = module.tests.filter(matchesFilter);
    if (!tests.length && filter !== "all") return "";

    var s = module.summary;
    var isCollapsed = !!collapsed[module.key];
    var counts = [];
    if (s.passed) counts.push('<span class="count c-pass">' + s.passed + " passed</span>");
    if (s.failed + s.broken) counts.push('<span class="count c-fail">' + (s.failed + s.broken) + " failed</span>");
    if (s.skipped) counts.push('<span class="count c-skip">' + s.skipped + " skipped</span>");
    if (s.never) counts.push('<span class="count c-never">' + s.never + " never run</span>");

    return '' +
      '<div class="card p-0 overflow-hidden module-card" data-module="' + escapeHtml(module.key) + '">' +
        '<div class="module-head">' +
          '<button class="module-toggle" data-module="' + escapeHtml(module.key) + '" ' +
                  'aria-expanded="' + (!isCollapsed) + '">' +
            '<span class="chevron ' + (isCollapsed ? "" : "open") + '">›</span>' +
            '<span class="module-name">' + escapeHtml(module.label) + '</span>' +
            '<span class="module-count">' + module.count + '</span>' +
          '</button>' +
          '<div class="module-counts">' + counts.join("") + '</div>' +
          '<button class="btn btn-ghost btn-xs run-module" data-target="' +
              escapeHtml(module.key === "harness" ? "" : module.key) + '" ' +
              'title="Run every test in this module">▶ Run module</button>' +
        '</div>' +
        '<ul class="test-list ' + (isCollapsed ? "hidden" : "") + '">' +
          (tests.length ? tests.map(testRow).join("") :
            '<li class="px-4 py-3 text-[12px] text-slate-600">nothing matches this filter</li>') +
        '</ul>' +
      '</div>';
  }

  function refreshSelectionBar() {
    var picked = Object.keys(chosen);
    var bar = el("selection-bar");
    var count = el("selection-count");
    if (!bar) return;
    bar.hidden = picked.length === 0;
    if (count) count.textContent = picked.length + (picked.length === 1 ? " test" : " tests");
  }

  function render() {
    if (!catalog) return;
    renderTiles(catalog);
    var html = catalog.modules.map(moduleCard).join("");
    el("modules").innerHTML = html ||
      '<div class="card text-[13px] text-slate-500">No test matches this filter.</div>';
    refreshSelectionBar();
  }

  /* ---- data -------------------------------------------------------- */

  function loadCatalog() {
    return fetch("/api/backoffice/" + APP + "/catalog")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) throw new Error(data.message || "could not read the catalog");
        catalog = data;
        render();
      })
      .catch(function (e) {
        el("modules").innerHTML =
          '<div class="card text-[13px] text-rose-300">Could not read the test files: ' +
          escapeHtml(e.message) + "</div>";
      });
  }

  /* ---- running ----------------------------------------------------- */

  function startRun(targets, what) {
    if (running) { alert("Something is already running - wait for it or stop it."); return; }
    fetch("/api/backoffice/" + APP + "/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets: targets, headed: el("headed").checked, scope: what })
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res.ok) { alert(res.message); return; }
        logCursor = 0;
        el("log-output").textContent = "";
        el("run-panel").classList.remove("hidden");
        el("run-title").textContent = what;
        poll();
      });
  }

  function poll() {
    fetch("/api/status").then(function (r) { return r.json(); }).then(function (st) {
      // Another suite may be running - the runner allows only one at a
      // time, so say so plainly rather than showing an empty panel.
      var mine = st.suite === SUITE;
      running = st.status === "running";

      var pill = el("pill-run");
      pill.className = "pill " + (running ? (mine ? "pill-run" : "pill-warn") : "pill-unknown");
      pill.querySelector(".pill-text").textContent =
        running ? (mine ? "running" : "busy: " + (st.label || "another suite")) : "idle";

      el("run-all").disabled = running;
      el("stop-btn").disabled = !running || !mine;
      document.querySelectorAll(".run-one, .run-module").forEach(function (b) { b.disabled = running; });

      if (mine) {
        el("run-panel").classList.remove("hidden");
        var total = st.tests_total || 0;
        var pass = st.passed || 0, fail = (st.failed || 0) + (st.errors || 0), skip = st.skipped || 0;
        el("progress-text").textContent = total
          ? (pass + fail + skip) + " / " + total + " · " + pass + " passed · " + fail + " failed · " + skip + " skipped"
          : "collecting…";
        el("current-test").textContent = st.current_test || "";
        if (total) {
          el("bar-pass").style.width = (pass / total * 100) + "%";
          el("bar-fail").style.width = (fail / total * 100) + "%";
        }
        var badge = el("status-badge");
        badge.textContent = running ? "Running" : (st.status === "stopped" ? "Stopped" :
                            (st.exit_code === 0 ? "Passed" : "Finished"));
        badge.className = "badge " + (running ? "badge-running" :
                          (st.exit_code === 0 ? "badge-passed" : "badge-failed"));
        if (st.started_at) {
          var end = st.finished_at || Date.now() / 1000;
          el("elapsed").textContent = duration(Math.round((end - st.started_at) * 1000));
        }
        // After a reload the page did not start this run, so the title
        // has to come from the runner rather than from the click.
        var scope = (st.options && st.options.scope) || "whole suite";
        el("run-title").textContent = (st.label || "Back office") + " · " + scope;
        el("run-sub").textContent = st.finished_at
          ? ("finished " + ago(st.finished_at))
          : "running now";
        pullLogs();
      }

      if (running) {
        tickTimer = setTimeout(poll, 1200);
      } else if (mine && st.status !== "idle") {
        // Finished: the verdicts on the page are now out of date.
        loadCatalog();
      }
    });
  }

  function pullLogs() {
    fetch("/api/logs?since=" + logCursor).then(function (r) { return r.json(); }).then(function (data) {
      if (!data.lines || !data.lines.length) return;
      logCursor = data.next || (logCursor + data.lines.length);
      var out = el("log-output");
      out.textContent += data.lines.join("\n") + "\n";
      out.scrollTop = out.scrollHeight;
    });
  }

  /* ---- wiring ------------------------------------------------------ */

  el("run-all").addEventListener("click", function () {
    startRun([], "whole suite");
  });

  el("stop-btn").addEventListener("click", function () {
    fetch("/api/stop", { method: "POST" });
  });

  el("run-selected").addEventListener("click", function () {
    var picked = Object.keys(chosen);
    if (!picked.length) return;
    startRun(picked, picked.length + " selected test" + (picked.length === 1 ? "" : "s"));
  });

  el("clear-selection").addEventListener("click", function () {
    chosen = {};
    render();
  });

  document.getElementById("filters").addEventListener("click", function (e) {
    var chip = e.target.closest("[data-filter]");
    if (!chip) return;
    filter = chip.dataset.filter;
    this.querySelectorAll(".chip").forEach(function (c) { c.classList.remove("chip-on"); });
    chip.classList.add("chip-on");
    render();
  });

  // One delegated listener for the whole list: rows are re-rendered on
  // every refresh, so per-element listeners would be re-attached (and
  // leak) each time.
  el("modules").addEventListener("click", function (e) {
    var toggle = e.target.closest(".module-toggle");
    if (toggle) {
      var key = toggle.dataset.module;
      collapsed[key] = !collapsed[key];
      render();
      return;
    }
    var pick = e.target.closest(".pick");
    if (pick) {
      if (pick.checked) { chosen[pick.dataset.target] = true; }
      else { delete chosen[pick.dataset.target]; }
      refreshSelectionBar();
      return;
    }
    var one = e.target.closest(".run-one");
    if (one) { startRun([one.dataset.target], "one test"); return; }
    var mod = e.target.closest(".run-module");
    if (mod) {
      var target = mod.dataset.target;
      startRun(target ? [target] : [], target ? "module " + target : "whole suite");
    }
  });

  loadCatalog().then(poll);
  // Cheap and honest: if a test file changes while the page is open, the
  // next sweep picks it up. Only while nothing is running, so a live run
  // is never disturbed.
  setInterval(function () { if (!running) loadCatalog(); }, 20000);
})();
