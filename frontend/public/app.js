const reportListEl = document.getElementById("report-list");
const detailEl = document.getElementById("report-detail");
let reports = [];
let selected = null;

const escapeHtml = (value) => (value ? value.toString().replace(/</g, "&lt;") : "");

function prettyDuration(record) {
  return record.toFixed(2);
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
                <td><pre>${escapeHtml(
                  action.metadata?.result?.invoked_command ||
                    action.metadata?.args?.command ||
                    "-"
                )}</pre></td>
                <td><pre>${escapeHtml(action.metadata?.result?.stdout)}</pre></td>
                <td><pre>${escapeHtml(action.metadata?.result?.stderr)}</pre></td>
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
  const info = report.reports?.[0] || {};
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
    <section>
      <h4>Task validation</h4>
      <pre>${JSON.stringify(info, null, 2)}</pre>
    </section>
    ${renderNotes(report.notes || [])}
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
    reportListEl.innerHTML = "";
    reports.forEach((report) => {
      const btn = document.createElement("button");
      btn.textContent = `${report.name} (${new Date(report.modified_at).toLocaleString()})`;
      btn.dataset.reportName = report.name;
      btn.addEventListener("click", () => selectReport(report.name, btn));
      if (selected === report.name) {
        btn.classList.add("selected");
      }
      reportListEl.appendChild(btn);
    });
    if (!selected && reports.length) {
      const firstButton = reportListEl.querySelector("button");
      selectReport(reports[0].name, firstButton);
    }
  } catch (err) {
    detailEl.innerHTML = `<p class="error">Unable to load reports: ${err.message}</p>`;
  }
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
          <tr><th>Component</th><th>Value</th><th>Max</th></tr>
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
