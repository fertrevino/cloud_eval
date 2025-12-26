const reportListEl = document.getElementById("report-list");
const detailEl = document.getElementById("report-detail");
const runFilterEl = document.getElementById("run-filter");
let reports = [];
let selected = null;
let selectedRun = null;
let runFolders = [];
const LOG_PREVIEW_LIMIT = 600;

const escapeHtml = (value) => (value ? value.toString().replace(/</g, "&lt;") : "");

function prettyDuration(record) {
  return record.toFixed(2);
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
    return `<pre>${escaped}</pre>`;
  }
  const preview = escapeHtml(text.slice(0, LOG_PREVIEW_LIMIT));
  return `
    <div class="log-block">
      <pre class="log-preview">${preview}…</pre>
      <details class="log-full">
        <summary>Show full output (${text.length} chars)</summary>
        <pre>${escaped}</pre>
      </details>
    </div>
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
  list.forEach((report) => {
    const meta = parseReportMeta(report);
    const key = meta.run || "";
    const existing = map.get(key) || { name: key, count: 0, latest: 0 };
    const modified = report.modified_at || 0;
    existing.count += 1;
    existing.latest = Math.max(existing.latest, modified);
    map.set(key, existing);
  });
  return Array.from(map.values()).sort((a, b) => b.latest - a.latest);
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
    return;
  }

  const metrics = report.metrics || {};
  const actions = report.actions || [];
  const scoreComponents = report.verification?.score_details?.components || {};

  const taskLabel = report.task_name || report.task_id || report.scenario || "task";
  detailEl.innerHTML = `
    <section>
      <h3>Task: ${taskLabel}</h3>
      <p>${report.description || "no description"}</p>
      <div class="metrics">
        <strong>Score:</strong> ${metrics.score?.toFixed(3) || "-"}<br>
        <strong>Duration:</strong> ${prettyDuration(metrics.duration_seconds || 0)}s<br>
        <strong>Step count:</strong> ${metrics.step_count || 0}<br>
        ${renderPenalty(metrics.error_action_penalty)}
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
    const response = await fetch("/api/reports");
    const data = await response.json();
    reports = data.reports || [];
    runFolders = computeRunFolders(reports);
    ensureRunSelection();
    renderRunFilter();
    renderReportList();
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

function ensureRunSelection() {
  if (!selectedRun || !runFolders.some((folder) => folder.name === selectedRun)) {
    selectedRun = runFolders.length ? runFolders[0].name : null;
  }
}

function getVisibleReports() {
  if (!selectedRun) {
    return [];
  }
  return reports.filter((report) => report.name && report.name.startsWith(`${selectedRun}/`));
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
    const btn = document.createElement("button");
    btn.textContent = meta.title;
    btn.title = meta.name;
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
    renderReportList();
  });
}

async function selectReport(name, button) {
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
      const formattedValue =
        typeof component.value === "number" ? component.value.toFixed(3) : "-";
      const formattedMax =
        typeof component.max === "number" ? component.max.toFixed(3) : "-";
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
