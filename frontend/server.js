const express = require("express");
const path = require("path");
const fs = require("fs/promises");
const cors = require("cors");

const app = express();
const port = Number(process.env.PORT || 3000);
const reportsDir = path.resolve(process.env.REPORTS_DIR || path.join(__dirname, "reports"));

app.use(cors());

app.get("/", async (req, res, next) => {
  const wantsJson =
    req.query.format === "json" || (req.accepts("json") && !req.accepts("html"));
  if (!wantsJson) {
    return next();
  }

  try {
    const files = await listReports();
    return res.json({ reports: files });
  } catch (err) {
    return res.status(500).json({ error: "unable to list reports" });
  }
});

app.use(express.static(path.join(__dirname, "public")));

async function listReports() {
  async function walk(dir, prefix = "") {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    const files = [];
    for (const entry of entries) {
      const resolved = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        const nested = await walk(resolved, prefix ? `${prefix}/${entry.name}` : entry.name);
        files.push(...nested);
        continue;
      }
      if (!entry.name.endsWith(".json")) {
        continue;
      }
      let taskLabel = null;
      try {
        const raw = await fs.readFile(resolved, "utf-8");
        const parsed = JSON.parse(raw);
        taskLabel = parsed.task_name || parsed.task_id || parsed.scenario || null;
      } catch (err) {
        if (err.code !== "ENOENT") {
          console.debug("Unable to read report metadata", resolved, err.message);
        }
      }
      try {
        const stats = await fs.stat(resolved);
        files.push({
          name: prefix ? `${prefix}/${entry.name}` : entry.name,
          modified_at: stats.mtimeMs,
          task_label: taskLabel,
        });
      } catch (err) {
        if (err.code === "ENOENT") {
          continue;
        }
        throw err;
      }
    }
    return files;
  }

  try {
    await fs.access(reportsDir);
  } catch (err) {
    if (err.code === "ENOENT") {
      return [];
    }
    throw err;
  }
  const files = await walk(reportsDir);
  return files.sort((a, b) => b.modified_at - a.modified_at);
}

app.get("/api/reports", async (req, res) => {
  try {
    const files = await listReports();
    res.json({ reports: files });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "unable to list reports" });
  }
});

app.get("/api/reports/*", async (req, res) => {
  const name = req.params[0];
  if (!name.endsWith(".json")) {
    return res.status(400).json({ error: "reports must end with .json" });
  }

  const resolved = path.join(reportsDir, name);
  if (!resolved.startsWith(reportsDir)) {
    return res.status(400).json({ error: "invalid report name" });
  }

  try {
    const data = await fs.readFile(resolved, "utf-8");
    res.json(JSON.parse(data));
  } catch (err) {
    if (err.code === "ENOENT") {
      console.debug("Report not found (stale reference):", name);
      return res.status(404).json({ error: "report not found" });
    }
    console.error(err);
    res.status(500).json({ error: "unable to load report" });
  }
});

app.get("/*", (req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

app.listen(port, () => {
  console.log(`Frontend dashboard listening on port ${port}, serving ${reportsDir}`);
});
