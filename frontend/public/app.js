const reportListEl = document.getElementById("report-list");
const detailEl = document.getElementById("report-detail");
const runFilterEl = document.getElementById("run-filter");
const modelFilterEl = document.getElementById("model-filter");
const evaluateBtnEl = document.getElementById("evaluate-btn");
const evaluateStatusEl = document.getElementById("evaluate-status");
const summaryTabBtn = document.getElementById("summary-tab");
const summaryEl = document.getElementById("summary-panel");
let reports = [];
let selected = null;
let selectedRun = null;
let selectedModel = null;
let runFolders = [];
let summary = null;
let showingSummary = false;
let availableModels = [];
const LOG_PREVIEW_LIMIT = 600;

const escapeHtml = (value) => (value ? value.toString().replace(/</g, "&lt;") : "");

function normalizeDifficulty(raw) {
  if (!raw || typeof raw !== "string") return "";
  const val = raw.toLowerCase();
  if (val.startsWith("easy")) return "easy";
  if (val.startsWith("med")) return "medium";
  if (val.startsWith("hard")) return "hard";
  return raw;
}

function renderDifficultyChip(rawDifficulty) {
  const difficulty = normalizeDifficulty(rawDifficulty);
  if (!difficulty) return "";
  const label = difficulty.charAt(0).toUpperCase() + difficulty.slice(1);
  return `<span class="chip chip-${difficulty}">${label}</span>`;
}

function prettyDuration(record) {
  return record.toFixed(2);
}

function formatNumber(value, digits = 2) {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  return Number(value).toFixed(digits);
}

function withPenaltyComponent(components, metrics) {
  const result = { ...(components || {}) };
  const penalty = metrics?.error_action_penalty;
  if (penalty == null) {
    return result;
  }
  if (result.error_action_penalty) {
    return result;
  }
  result.error_action_penalty = {
    label: "Penalty (-0.02 per error action)",
    value: -Math.abs(penalty),
    max: null,
  };
  return result;
}

function formatTitleFromSlug(slug) {
  if (!slug) {
    return "Report";
  }
  const words = slug.split("-").filter(Boolean);
  if (!words.length) {
    return slug;
  }
  return words
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function renderLog(value) {
  const text = value == null ? "" : value.toString();
  if (!text) {
    return "<pre>-</pre>";
  }
  const escaped = escapeHtml(text);
  if (text.length <= LOG_PREVIEW_LIMIT) {
    return `<pre class="log-inline">${escaped}</pre>`;
  }
  const preview = escapeHtml(text.slice(0, 40));
  return `
    <details class="log-block">
      <summary class="log-summary">
        <span class="log-summary-label">Show full output (${text.length} chars)</span>
        <span class="log-summary-preview">${preview}…</span>
      </summary>
      <pre>${escaped}</pre>
    </details>
  `;
}

function parseReportMeta(report) {
  const name = report.name || "";
  const segments = name.split("/");
  const filename = segments.pop() || "";
  const run = segments.length ? segments[0] : "";

  const baseName = filename.replace(/\.json$/, "");
  const titleSlug = baseName.replace(/-\d{10,}$/, "") || baseName || "report";
  const title = formatTitleFromSlug(titleSlug);

  return { title, name, run };
}

function computeRunFolders(list) {
  const map = new Map();
  const models = new Set();
  list.forEach((report) => {
    const meta = parseReportMeta(report);
    const key = meta.run || "";
    const existing = map.get(key) || { name: key, count: 0, latest: 0 };
    const modified = report.modified_at || 0;
    existing.count += 1;
    existing.latest = Math.max(existing.latest, modified);
    map.set(key, existing);

    if (report.model) {
      models.add(report.model);
    }
  });
  return {
    runs: Array.from(map.values()).sort((a, b) => b.latest - a.latest),
    models: Array.from(models).sort(),
  };
}

function renderActions(actions) {
  if (!actions || !actions.length) {
    return "<p>No actions logged.</p>";
  }
  return `
    <table class="table">
      <thead>
        <tr><th>Action</th><th>Status</th><th>CLI</th><th>stdout</th><th>stderr</th></tr>
      </thead>
      <tbody>
        ${actions
          .map(
            (action) => `
              <tr>
                <td>${action.action}</td>
                <td class="status-${action.status}">${action.status}</td>
                <td>${renderLog(
                  action.metadata?.result?.invoked_command ||
                    action.metadata?.args?.command ||
                    "-"
                )}</td>
                <td>${renderLog(action.metadata?.result?.stdout)}</td>
                <td>${renderLog(action.metadata?.result?.stderr)}</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderReport(report) {
  if (!report) {
    detailEl.innerHTML = "<p>Select a report to inspect metrics, actions, and payloads.</p>";
    if (!showingSummary) {
      detailEl.style.display = "block";
      const heading = document.getElementById("detail-heading");
      if (heading) heading.textContent = "Details";
    }
    return;
  }

  const metrics = report.metrics || {};
  const actions = report.actions || [];
  const baseComponents =
    report.verification?.score_details?.components || report.verification?.components || {};
  const scoreComponents = withPenaltyComponent(baseComponents, metrics);

  const taskLabel = report.task_name || report.task_id || report.scenario || "task";
  const difficultyChip = renderDifficultyChip(report.difficulty);
  const modelLabel = report.model ? `<p class="muted">Model: ${escapeHtml(report.model)}</p>` : "";
  detailEl.innerHTML = `
    <section>
      <div class="task-header">
        <h3>Task: ${taskLabel}</h3>
        ${difficultyChip}
      </div>
      ${modelLabel}
      <p>${report.description || "no description"}</p>
      <div class="metrics">
        <strong>Score:</strong> ${formatNumber(metrics.score)}<br>
        <strong>Duration:</strong> ${prettyDuration(metrics.duration_seconds || 0)}s<br>
        <strong>Step count:</strong> ${metrics.step_count || 0}<br>
      </div>
      ${renderScoreComponents(scoreComponents)}
    </section>
    ${renderNotes(report.notes || [])}
    ${renderLinks(report.links || [])}
    <section>
      <h4>Actions (${actions.length})</h4>
      ${renderActions(actions)}
    </section>
    ${renderReasoning(actions)}
  `;
  detailEl.style.display = showingSummary ? "none" : "block";
}

function renderSummary(showMissing = false) {
  if (!summaryEl) return;
  if (showMissing || !summary) {
    summaryEl.innerHTML = "<p class=\"muted\">Summary unavailable.</p>";
    summaryEl.hidden = false;
    return;
  }
  const modelEntries = summary.by_model
    ? Object.entries(summary.by_model).map(([k, v]) => ({
        model: k,
        count: v.count || 0,
        passed: v.passed || 0,
        failed: v.failed || 0,
        avg: v.avg_score || 0,
        pass_rate: v.pass_rate || 0,
        difficulty: summary.by_model_difficulty && summary.by_model_difficulty[k],
      }))
    : [];
  const modelBlock = modelEntries.length
    ? `
      <div class="summary-block">
        <h4>Leaderboard</h4>
        <table class="summary-table">
          <thead>
            <tr><th>Model</th><th>Runs</th><th>Passed</th><th>Failed</th><th>Avg score</th><th>Pass rate</th><th>Difficulty mix</th></tr>
          </thead>
          <tbody>
            ${modelEntries
              .map(
                (row) => `
                <tr>
                  <td>${escapeHtml(row.model)}</td>
                  <td>${row.count}</td>
                  <td class="success">${row.passed}</td>
                  <td class="error">${row.failed}</td>
                  <td>${formatNumber(row.avg, 2)}</td>
                  <td>${formatNumber(row.pass_rate * 100, 1)}%</td>
                  <td>${renderDifficultyMix(row.difficulty)}</td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `
    : "";

  summaryEl.innerHTML = modelBlock;
}

function renderReasoning(actions) {
  const data = (actions || [])
    .map((action, index) => {
      const trace = action.metadata?.llm_trace;
      return trace ? { action: action.action, index, trace } : null;
    })
    .filter(Boolean);
  if (!data.length) {
    return "";
  }
  return `
    <section>
      <h4>LLM reasoning (${data.length} step${data.length === 1 ? "" : "s"})</h4>
      ${data
        .map(
          (entry, idx) => `
            <article class="llm-trace">
              <strong>Action ${entry.index + 1}: ${entry.action}</strong>
              <details>
                <summary>Prompt (context)</summary>
                <pre>${escapeHtml(JSON.stringify(entry.trace.prompt, null, 2))}</pre>
              </details>
              <details>
                <summary>Assistant response</summary>
                <pre>${escapeHtml(JSON.stringify(entry.trace.assistant, null, 2))}</pre>
              </details>
            </article>
          `
        )
        .join("")}
    </section>
  `;
}

async function loadReports() {
  try {
    const [reportsResp, summaryResp] = await Promise.allSettled([
      fetch("/api/reports"),
      fetch("/api/summary"),
    ]);

    if (reportsResp.status === "fulfilled") {
      const data = await reportsResp.value.json();
      reports = data.reports || [];
      const computed = computeRunFolders(reports);
      runFolders = computed.runs;
      availableModels = computed.models || [];
      ensureRunSelection();
      renderRunFilter();
      renderModelFilter();
      renderReportList();
    } else {
      detailEl.innerHTML = `<p class="error">Unable to load reports: ${reportsResp.reason?.message || reportsResp.reason}</p>`;
    }

    if (summaryResp.status === "fulfilled" && summaryResp.value.ok) {
      summary = await summaryResp.value.json();
      renderSummary();
    } else {
      summary = null;
      renderSummary(true);
    }
  } catch (err) {
    detailEl.innerHTML = `<p class="error">Unable to load reports: ${err.message}</p>`;
  }
}

function renderRunFilter() {
  if (!runFilterEl) return;
  runFilterEl.innerHTML = "";

  runFolders.forEach((folder) => {
    const opt = document.createElement("option");
    opt.value = folder.name;
    opt.textContent = folder.name || "run";
    runFilterEl.appendChild(opt);
  });

  if (selectedRun) {
    runFilterEl.value = selectedRun;
  } else if (runFolders.length) {
    runFilterEl.value = runFolders[0].name;
    selectedRun = runFolders[0].name;
  }
}

function renderModelFilter() {
  if (!modelFilterEl) return;
  modelFilterEl.innerHTML = "";
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "All models";
  modelFilterEl.appendChild(defaultOpt);
  availableModels.forEach((model) => {
    const opt = document.createElement("option");
    opt.value = model;
    opt.textContent = model;
    modelFilterEl.appendChild(opt);
  });
  modelFilterEl.value = selectedModel || "";
}

function ensureRunSelection() {
  if (!selectedRun || !runFolders.some((folder) => folder.name === selectedRun)) {
    selectedRun = runFolders.length ? runFolders[0].name : null;
  }
}

function getVisibleReports() {
  if (!selectedRun) {
    return [];
  }
  return reports.filter((report) => {
    if (!report.name || !report.name.startsWith(`${selectedRun}/`)) return false;
    if (selectedModel && report.model !== selectedModel) return false;
    return true;
  });
}

function renderReportList() {
  reportListEl.innerHTML = "";
  if (!runFolders.length) {
    detailEl.innerHTML = "<p>No reports available yet.</p>";
    return;
  }

  const visibleReports = getVisibleReports();
  if (!visibleReports.length) {
    detailEl.innerHTML = `<p>No reports for run ${selectedRun}.</p>`;
  }
  visibleReports.forEach((report) => {
    const meta = parseReportMeta(report);
    const label = report.task_label || meta.title;
    const btn = document.createElement("button");
    btn.textContent = label;
    btn.title = report.model ? `${meta.name} [${report.model}]` : meta.name;
    btn.dataset.reportName = meta.name;
    btn.addEventListener("click", () => selectReport(report.name, btn));
    if (selected === report.name) {
      btn.classList.add("selected");
    }
    reportListEl.appendChild(btn);
  });

  if (!selected && visibleReports.length) {
    const first = visibleReports[0];
    const firstButton = reportListEl.querySelector("button");
    selectReport(first.name, firstButton);
  } else if (selected && !visibleReports.some((report) => report.name === selected)) {
    detailEl.innerHTML = "<p>Select a report to inspect metrics, prompts, and actions.</p>";
  }
}

if (runFilterEl) {
  runFilterEl.addEventListener("change", () => {
    selectedRun = runFilterEl.value || null;
    selected = null;
    showingSummary = false;
    toggleSummaryPanel(false);
    renderReportList();
  });
}

if (modelFilterEl) {
  modelFilterEl.addEventListener("change", () => {
    selectedModel = modelFilterEl.value || null;
    selected = null;
    showingSummary = false;
    toggleSummaryPanel(false);
    renderReportList();
  });
}

async function selectReport(name, button) {
  showingSummary = false;
  toggleSummaryPanel(false);
  selected = name;
  document.querySelectorAll("#report-list button").forEach((btn) => {
    btn.classList.toggle("selected", btn === button);
  });
  try {
    const safePath = name
      .split("/")
      .map((segment) => encodeURIComponent(segment))
      .join("/");
    const res = await fetch(`/api/reports/${safePath}`);
    const report = await res.json();
    renderReport(report);
  } catch (err) {
    detailEl.innerHTML = `<p class="error">Unable to load ${name}: ${err.message}</p>`;
  }
}

loadReports();
setInterval(loadReports, 15000);

if (summaryTabBtn) {
  summaryTabBtn.addEventListener("click", () => {
    showingSummary = true;
    selected = null;
    document.querySelectorAll("#report-list button").forEach((btn) => btn.classList.remove("selected"));
    toggleSummaryPanel(true);
  });
}

function toggleSummaryPanel(forceShow) {
  if (forceShow === true) {
    showingSummary = true;
  } else if (forceShow === false) {
    showingSummary = false;
  }
  if (!summaryEl) return;
  summaryEl.hidden = !showingSummary;
  const heading = document.getElementById("detail-heading");
  if (showingSummary) {
    detailEl.style.display = "none";
    if (heading) {
      heading.textContent = "";
      heading.style.display = "none";
    }
  } else {
    detailEl.style.display = "block";
    if (heading) {
      heading.textContent = "Details";
      heading.style.display = "";
    }
  }
  if (summaryTabBtn) {
    summaryTabBtn.classList.toggle("active", showingSummary);
  }
}

function renderDifficultyMix(diffMap) {
  if (!diffMap || typeof diffMap !== "object") return "";
  const entries = Object.entries(diffMap)
    .map(([diff, vals]) => {
      const pct = vals.pass_rate != null ? formatNumber((vals.pass_rate || 0) * 100, 1) : "";
      const avg = vals.avg_score != null ? formatNumber(vals.avg_score, 2) : "";
      return `${escapeHtml(diff)}: ${vals.count || 0} runs, pass ${pct}%, avg ${avg}`;
    })
    .join("<br>");
  return entries || "";
}

// Evaluate button handler
if (evaluateBtnEl) {
  evaluateBtnEl.addEventListener("click", async () => {
    evaluateBtnEl.disabled = true;
    evaluateStatusEl.textContent = "Starting evaluation...";
    evaluateStatusEl.style.color = "#3b82f6";

    try {
      const response = await fetch("/api/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || "Failed to start evaluation");
      }

      const result = await response.json();
      const runId = result.run_id;
      evaluateStatusEl.textContent = `Run ${runId.substring(0, 8)}... queued`;
      evaluateStatusEl.style.color = "#10b981";

      // Poll for completion
      const pollInterval = setInterval(async () => {
        try {
          const statusResponse = await fetch(`/api/status/${runId}`);
          if (statusResponse.ok) {
            const status = await statusResponse.json();
            if (status.status === "completed") {
              clearInterval(pollInterval);
              evaluateStatusEl.textContent = "✓ Completed";
              evaluateStatusEl.style.color = "#10b981";
              evaluateBtnEl.disabled = false;
              // Reload reports after a short delay
              setTimeout(() => loadReports(), 1000);
            } else if (status.status === "failed") {
              clearInterval(pollInterval);
              evaluateStatusEl.textContent = `✗ Failed: ${status.error || "Unknown error"}`;
              evaluateStatusEl.style.color = "#ef4444";
              evaluateBtnEl.disabled = false;
            } else {
              evaluateStatusEl.textContent = `Running... (${status.status})`;
            }
          }
        } catch (err) {
          console.error("Poll error:", err);
        }
      }, 2000);

      // Timeout after 30 minutes
      setTimeout(() => {
        if (!evaluateBtnEl.disabled) return;
        clearInterval(pollInterval);
        evaluateStatusEl.textContent = "Timeout";
        evaluateStatusEl.style.color = "#ef4444";
        evaluateBtnEl.disabled = false;
      }, 30 * 60 * 1000);
    } catch (err) {
      evaluateStatusEl.textContent = `Error: ${err.message}`;
      evaluateStatusEl.style.color = "#ef4444";
      evaluateBtnEl.disabled = false;
      console.error("Evaluate error:", err);
    }
  });
}

function renderScoreComponents(components) {
  if (!components || !Object.keys(components).length) {
    return "";
  }
  const rows = Object.entries(components)
    .map(([key, component]) => {
      if (!component || typeof component !== "object") {
        return "";
      }
      const label = component.label || key;
      const formattedValue = formatNumber(component.value, 2);
      const formattedMax = formatNumber(component.max, 2);
      return `
        <tr>
          <td>${label}</td>
          <td>${formattedValue}</td>
          <td>${formattedMax}</td>
        </tr>
      `;
    })
    .join("");
  return `
    <div class="score-components">
      <h4>Score breakdown</h4>
      <table class="table">
        <thead>
          <tr><th></th><th>Value</th><th>Max</th></tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
      </table>
    </div>
  `;
}

function renderNotes(notes) {
  if (!notes || !notes.length) {
    return "";
  }
  const items = notes
    .map((note) => {
      const formatted = formatNoteBody(note);
      return `
        <article class="note">
          <p>${formatted}</p>
        </article>
      `;
    })
    .join("");
  return `
    <section>
      <h4>Notes</h4>
      ${items}
    </section>
  `;
}

function renderLinks(links) {
  if (!links || !links.length) {
    return "";
  }
  const items = links
    .map((link) => {
      if (!link) {
        return "";
      }
      const isUrl = typeof link === "string" && link.startsWith("http");
      const escaped = escapeHtml(link);
      const body = isUrl
        ? `<a href="${escaped}" target="_blank" rel="noopener noreferrer">${escaped}</a>`
        : escaped;
      return `<li>${body}</li>`;
    })
    .join("");
  if (!items) {
    return "";
  }
  return `
    <section>
      <h4>Links</h4>
      <ul class="link-list">
        ${items}
      </ul>
    </section>
  `;
}

function formatNoteBody(body) {
  if (!body) {
    return "";
  }
  if (typeof body === "string" && body.startsWith("http")) {
    const escaped = escapeHtml(body);
    return `<a href="${escaped}" target="_blank" rel="noopener noreferrer">${escaped}</a>`;
  }
  return escapeHtml(body);
}

function renderPenalty(value) {
  if (value == null) {
    return "";
  }
  const formatted =
    typeof value === "number" ? value.toFixed(3) : escapeHtml(value.toString());
  return `<strong>Penalty (error actions):</strong> ${formatted}`;
}
