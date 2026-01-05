#!/usr/bin/env node
/**
 * Render cloud-eval report JSON to standalone static HTML.
 *
 * Usage:
 *   # single report -> stdout
 *   node scripts/render_report.js path/to/report.json
 *
 *   # single report -> specific HTML file
 *   node scripts/render_report.js path/to/report.json docs/report.html
 *
 *   # entire folder of reports -> write .html for each plus index.html under output directory
 *   node scripts/render_report.js reports/2026-01-04T18-43-02Z/ docs/
 *
 * If output is omitted for a single file, HTML is written to stdout. For a folder,
 * output must be a directory (defaults to ./docs if omitted).
 */

const fs = require("fs");
const path = require("path");

function readFileSafe(p) {
  try {
    return fs.readFileSync(p, "utf8");
  } catch (err) {
    return "";
  }
}

function loadReport(reportPath) {
  const raw = fs.readFileSync(reportPath, "utf8");
  return JSON.parse(raw);
}

function findReportFiles(rootDir) {
  const results = [];
  function walk(current) {
    const entries = fs.readdirSync(current, { withFileTypes: true });
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.isFile() && entry.name.endsWith(".json")) {
        results.push(full);
      }
    }
  }
  walk(rootDir);
  return results;
}

function buildHtml(report, inlineCss) {
  const css = inlineCss || "";
  const payload = JSON.stringify(report);
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Cloud Eval Report - ${escapeHtml(report.task_name || report.task_id || "report")}</title>
  <style>
  ${css}
  /* Minimal extras for standalone rendering */
  body { background: #f8fafc; color: #0f172a; margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
  main { max-width: 1100px; margin: 1.25rem auto; padding: 0 1rem; }
  h1 { margin-bottom: 0.25rem; }
  .panel { background: #fff; border-radius: 0.5rem; padding: 1rem; box-shadow: 0 10px 25px rgba(15, 23, 42, 0.1); margin-bottom: 1rem; }
  .task-header { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
  .chip { display: inline-flex; align-items: center; padding: 0.15rem 0.55rem; border-radius: 999px; font-weight: 700; font-size: 0.8rem; letter-spacing: 0.01em; text-transform: capitalize; }
  .chip-easy { background: #ecfdf3; color: #15803d; border: 1px solid #bbf7d0; }
  .chip-medium { background: #fff7ed; color: #c2410c; border: 1px solid #fed7aa; }
  .chip-hard { background: #fef2f2; color: #b91c1c; border: 1px solid #fecdd3; }
  .metrics strong { display: inline-block; width: 110px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 0.35rem 0.5rem; border-bottom: 1px solid #e2e8f0; text-align: left; vertical-align: top; }
  .status-ok { color: #059669; }
  .status-error { color: #dc2626; }
  .note + .note { margin-top: 0.5rem; }
  .link-list { padding-left: 1.25rem; margin: 0.25rem 0 0; display: flex; flex-direction: column; gap: 0.25rem; }
  .log-block { display: block; margin: 0.25rem 0; }
  .log-block summary { cursor: pointer; color: #0f172a; font-weight: 600; list-style: none; padding: 0.25rem 0; display: flex; flex-direction: column; align-items: flex-start; gap: 0.2rem; }
  .log-block summary::-webkit-details-marker { display: none; }
  .log-summary::before { content: "▶"; display: inline-block; margin-right: 0.35rem; font-size: 0.8rem; }
  .log-block[open] .log-summary::before { content: "▼"; }
  .log-summary-label { font-weight: 700; }
  .log-summary-preview { max-width: 32ch; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; color: #475569; }
  pre { background: #f1f5f9; padding: 0.75rem; border-radius: 0.5rem; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }
  </style>
</head>
<body>
  <main>
    <h1>Cloud Eval Report</h1>
    <div id="app" class="panel">Loading report…</div>
  </main>
  <script type="application/json" id="report-data">${payload}</script>
  <script>
  const LOG_PREVIEW_LIMIT = 40;
  const report = JSON.parse(document.getElementById("report-data").textContent || "{}");

  const escapeHtml = (value) => (value ? value.toString().replace(/</g, "&lt;").replace(/>/g, "&gt;") : "");
  function formatNumber(value, digits = 2) {
    if (value == null || Number.isNaN(value)) return "-";
    return Number(value).toFixed(digits);
  }
  function prettyDuration(val) {
    if (val == null || Number.isNaN(val)) return "-";
    return Number(val).toFixed(2);
  }
  function normalizeDifficulty(raw) {
    if (!raw || typeof raw !== "string") return "";
    const val = raw.toLowerCase();
    if (val.startsWith("easy")) return "easy";
    if (val.startsWith("med")) return "medium";
    if (val.startsWith("hard")) return "hard";
    return raw;
  }
  function renderDifficultyChip(raw) {
    const difficulty = normalizeDifficulty(raw);
    if (!difficulty) return "";
    const label = difficulty.charAt(0).toUpperCase() + difficulty.slice(1);
    return \`<span class="chip chip-\${difficulty}">\${label}</span>\`;
  }
  function renderScoreComponents(components) {
    if (!components || !Object.keys(components).length) return "";
    const rows = Object.entries(components)
      .map(([key, component]) => {
        if (!component || typeof component !== "object") return "";
        const label = component.label || key;
        const formattedValue = formatNumber(component.value, 2);
        const formattedMax = formatNumber(component.max, 2);
        return \`<tr><td>\${label}</td><td>\${formattedValue}</td><td>\${formattedMax}</td></tr>\`;
      })
      .join("");
    return \`
      <div class="score-components">
        <h4>Score breakdown</h4>
        <table class="table">
          <thead><tr><th></th><th>Value</th><th>Max</th></tr></thead>
          <tbody>\${rows}</tbody>
        </table>
      </div>
    \`;
  }
  function renderNotes(notes) {
    if (!notes || !notes.length) return "";
    const items = notes.map((note) => \`<article class="note"><p>\${escapeHtml(note)}</p></article>\`).join("");
    return \`<section><h4>Notes</h4>\${items}</section>\`;
  }
  function renderLinks(links) {
    if (!links || !links.length) return "";
    const items = links
      .map((link) => {
        if (!link) return "";
        const isUrl = typeof link === "string" && link.startsWith("http");
        const escaped = escapeHtml(link);
        const body = isUrl ? \`<a href="\${escaped}" target="_blank" rel="noopener noreferrer">\${escaped}</a>\` : escaped;
        return \`<li>\${body}</li>\`;
      })
      .join("");
    if (!items) return "";
    return \`<section><h4>Links</h4><ul class="link-list">\${items}</ul></section>\`;
  }
  function renderLog(value) {
    const text = value == null ? "" : value.toString();
    if (!text) return "<pre>-</pre>";
    const escaped = escapeHtml(text);
    if (text.length <= LOG_PREVIEW_LIMIT) {
      return \`<pre class="log-inline">\${escaped}</pre>\`;
    }
    const preview = escapeHtml(text.slice(0, LOG_PREVIEW_LIMIT));
    return \`
      <details class="log-block">
        <summary class="log-summary">
          <span class="log-summary-label">Show full output (\${text.length} chars)</span>
          <span class="log-summary-preview">\${preview}…</span>
        </summary>
        <pre>\${escaped}</pre>
      </details>
    \`;
  }
  function renderActions(actions) {
    if (!actions || !actions.length) return "<p>No actions logged.</p>";
    return \`
      <h4>Actions (\${actions.length})</h4>
      <table class="table">
        <thead><tr><th>Action</th><th>Status</th><th>CLI</th><th>stdout</th><th>stderr</th></tr></thead>
        <tbody>
          \${actions.map((action) => \`
            <tr>
              <td>\${escapeHtml(action.action)}</td>
              <td class="status-\${escapeHtml(action.status)}">\${escapeHtml(action.status)}</td>
              <td>\${renderLog(action.metadata?.result?.invoked_command || action.metadata?.args?.command || "-")}</td>
              <td>\${renderLog(action.metadata?.result?.stdout)}</td>
              <td>\${renderLog(action.metadata?.result?.stderr)}</td>
            </tr>
          \`).join("")}
        </tbody>
      </table>
    \`;
  }

  function renderReport(report) {
    const metrics = report.metrics || {};
    const actions = report.actions || [];
    const baseComponents = report.verification?.score_details?.components || report.verification?.components || {};
    const taskLabel = report.task_name || report.task_id || "task";
    const difficultyChip = renderDifficultyChip(report.difficulty);
    return \`
      <div class="panel">
        <div class="task-header">
          <h2>\${escapeHtml(taskLabel)}</h2>
          \${difficultyChip}
        </div>
        <p>\${escapeHtml(report.description || "no description")}</p>
        <div class="metrics">
          <strong>Score:</strong> \${formatNumber(metrics.score)}<br>
          <strong>Duration:</strong> \${prettyDuration(metrics.duration_seconds)}s<br>
          <strong>Step count:</strong> \${metrics.step_count || 0}<br>
        </div>
        \${renderScoreComponents(baseComponents)}
      </div>
      <div class="panel">\${renderNotes(report.notes || [])}\${renderLinks(report.links || [])}</div>
      <div class="panel">\${renderActions(actions)}</div>
    \`;
  }

  document.getElementById("app").innerHTML = renderReport(report);
  </script>
</body>
</html>`;
}

function escapeHtml(str) {
  return str ? str.toString().replace(/</g, "&lt;").replace(/>/g, "&gt;") : "";
}

function main() {
  const [inputPathArg, outPathArg] = process.argv.slice(2);
  if (!inputPathArg) {
    console.error("Usage: node scripts/render_report.js <report.json|folder> [output.html|output_dir]");
    process.exit(1);
  }

  const inputPath = path.resolve(inputPathArg);
  const css = readFileSafe(path.join(__dirname, "..", "frontend", "public", "style.css"));

  if (fs.existsSync(inputPath) && fs.statSync(inputPath).isDirectory()) {
    const reports = findReportFiles(inputPath);
    if (!reports.length) {
      console.error(`No JSON reports found under ${inputPath}`);
      process.exit(1);
    }
    const outDir = outPathArg ? path.resolve(outPathArg) : path.resolve("docs");
    for (const file of reports) {
      const report = loadReport(file);
      const html = buildHtml(report, css);
      const rel = path.relative(inputPath, file);
      const outFile = path.join(outDir, rel.replace(/\.json$/i, ".html"));
      fs.mkdirSync(path.dirname(outFile), { recursive: true });
      fs.writeFileSync(outFile, html, "utf8");
      console.log(`Wrote ${outFile}`);
    }
    // Build a simple index.html
    const links = reports
      .map((file) => {
        const rel = path.relative(inputPath, file).replace(/\.json$/i, ".html");
        return `<li><a href="${rel}">${rel}</a></li>`;
      })
      .join("");
    const indexHtml = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Cloud Eval Reports</title></head><body><h1>Reports</h1><ul>${links}</ul></body></html>`;
    fs.writeFileSync(path.join(outDir, "index.html"), indexHtml, "utf8");
    console.log(`Wrote ${path.join(outDir, "index.html")}`);
    return;
  }

  // Single file path
  const report = loadReport(inputPath);
  const html = buildHtml(report, css);
  if (outPathArg) {
    fs.mkdirSync(path.dirname(path.resolve(outPathArg)), { recursive: true });
    fs.writeFileSync(outPathArg, html, "utf8");
    console.log(`Wrote ${outPathArg}`);
  } else {
    process.stdout.write(html);
  }
}

if (require.main === module) {
  main();
}
