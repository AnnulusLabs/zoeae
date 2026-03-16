/**
 * Telemetry Dashboard — Real-time HTML dashboard for activity observability
 *
 * Upgrade #8: Aggregates activity.jsonl into tool call frequency,
 * delegation latency per model, task completion rates, genome growth,
 * room mode usage, service uptime.
 *
 * Served as a single-page HTML — no dependencies, no React, just template literals.
 *
 * AnnulusLabs LLC
 */

import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";

export type DashboardConfig = {
  port: number;
  host: string;
  activityLogPath: string;
};

type AggregatedStats = {
  totalEntries: number;
  byKind: Record<string, number>;
  avgLatencyByModel: Record<string, { total: number; count: number; avg: number }>;
  taskStats: { completed: number; failed: number; blocked: number };
  roomModeUsage: Record<string, number>;
  serviceHealth: Record<string, { checks: number; failures: number; uptime: string }>;
  recentEntries: Array<{ ts: string; kind: string; summary: string; durationMs?: number }>;
  timeRange: { first: string; last: string };
};

function aggregate(logPath: string): AggregatedStats {
  const stats: AggregatedStats = {
    totalEntries: 0,
    byKind: {},
    avgLatencyByModel: {},
    taskStats: { completed: 0, failed: 0, blocked: 0 },
    roomModeUsage: {},
    serviceHealth: {},
    recentEntries: [],
    timeRange: { first: "", last: "" },
  };

  if (!existsSync(logPath)) return stats;

  let lines: string[];
  try {
    lines = readFileSync(logPath, "utf-8").trim().split("\n").filter(Boolean);
  } catch { return stats; }

  const entries = lines.map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  stats.totalEntries = entries.length;
  if (entries.length > 0) {
    stats.timeRange.first = entries[0].ts ?? "";
    stats.timeRange.last = entries[entries.length - 1].ts ?? "";
  }

  for (const e of entries) {
    // By kind
    stats.byKind[e.kind] = (stats.byKind[e.kind] ?? 0) + 1;

    // Delegation latency
    if (e.kind === "delegate_result" && e.durationMs && e.meta?.model) {
      const model = String(e.meta.model);
      if (!stats.avgLatencyByModel[model]) stats.avgLatencyByModel[model] = { total: 0, count: 0, avg: 0 };
      stats.avgLatencyByModel[model].total += e.durationMs;
      stats.avgLatencyByModel[model].count++;
    }

    // Task stats
    if (e.kind === "task_event") {
      if (e.summary?.includes("completed")) stats.taskStats.completed++;
      if (e.summary?.includes("failed")) stats.taskStats.failed++;
      if (e.summary?.includes("blocked")) stats.taskStats.blocked++;
    }

    // Room mode usage
    if (e.kind === "delegate" && e.summary?.includes("room query")) {
      const modeMatch = e.summary.match(/\[(\w[\w-]*)\]/);
      if (modeMatch) stats.roomModeUsage[modeMatch[1]] = (stats.roomModeUsage[modeMatch[1]] ?? 0) + 1;
    }

    // Service health
    if (e.kind === "service_check") {
      const nameMatch = e.summary?.match(/^(\w+)/);
      if (nameMatch) {
        const name = nameMatch[1];
        if (!stats.serviceHealth[name]) stats.serviceHealth[name] = { checks: 0, failures: 0, uptime: "0%" };
        stats.serviceHealth[name].checks++;
        if (e.summary.includes("DOWN")) stats.serviceHealth[name].failures++;
      }
    }
  }

  // Compute averages
  for (const m of Object.values(stats.avgLatencyByModel)) {
    m.avg = m.count > 0 ? Math.round(m.total / m.count) : 0;
  }
  for (const s of Object.values(stats.serviceHealth)) {
    const upPct = s.checks > 0 ? Math.round(((s.checks - s.failures) / s.checks) * 100) : 0;
    s.uptime = `${upPct}%`;
  }

  // Recent entries (last 30)
  stats.recentEntries = entries.slice(-30).reverse().map((e) => ({
    ts: e.ts?.slice(11, 19) ?? "??:??:??",
    kind: e.kind,
    summary: (e.summary ?? "").slice(0, 120),
    durationMs: e.durationMs,
  }));

  return stats;
}

function renderHtml(stats: AggregatedStats): string {
  const kindRows = Object.entries(stats.byKind)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`)
    .join("");

  const latencyRows = Object.entries(stats.avgLatencyByModel)
    .sort((a, b) => b[1].avg - a[1].avg)
    .map(([m, v]) => `<tr><td>${m}</td><td>${v.avg}ms</td><td>${v.count}</td></tr>`)
    .join("");

  const serviceRows = Object.entries(stats.serviceHealth)
    .map(([n, v]) => `<tr><td>${n}</td><td>${v.uptime}</td><td>${v.checks}</td><td>${v.failures}</td></tr>`)
    .join("");

  const modeRows = Object.entries(stats.roomModeUsage)
    .sort((a, b) => b[1] - a[1])
    .map(([m, v]) => `<tr><td>${m}</td><td>${v}</td></tr>`)
    .join("");

  const activityRows = stats.recentEntries
    .map((e) => {
      const dur = e.durationMs ? ` <span style="color:#888">(${e.durationMs}ms)</span>` : "";
      return `<tr><td style="white-space:nowrap">${e.ts}</td><td><code>${e.kind}</code></td><td>${e.summary}${dur}</td></tr>`;
    }).join("");

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clawtonomy — Telemetry</title>
<meta http-equiv="refresh" content="10">
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:#0d1117;color:#c9d1d9;font:13px/1.5 'Cascadia Code','Fira Code',monospace;padding:20px}
  h1{color:#58a6ff;font-size:18px;margin-bottom:16px}
  h2{color:#8b949e;font-size:14px;margin:16px 0 8px;border-bottom:1px solid #21262d;padding-bottom:4px}
  .grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px}
  .stat{font-size:24px;color:#58a6ff;font-weight:bold}
  .label{color:#8b949e;font-size:11px;text-transform:uppercase}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th{text-align:left;color:#8b949e;border-bottom:1px solid #21262d;padding:4px 8px}
  td{padding:4px 8px;border-bottom:1px solid #161b22}
  code{background:#1f2937;padding:2px 4px;border-radius:3px;color:#7ee787;font-size:11px}
  .ok{color:#3fb950} .err{color:#f85149}
</style>
</head>
<body>
<h1>CLAWTONOMY — Telemetry Dashboard</h1>
<div style="color:#8b949e;margin-bottom:16px;font-size:11px">
  ${stats.timeRange.first ? `Range: ${stats.timeRange.first.slice(0,19)} → ${stats.timeRange.last.slice(0,19)}` : "No data yet"}
  &nbsp;|&nbsp; Auto-refreshes every 10s
</div>
<div class="grid">
  <div class="card"><div class="stat">${stats.totalEntries}</div><div class="label">Total Events</div></div>
  <div class="card"><div class="stat">${stats.taskStats.completed} <span class="ok">✓</span> / ${stats.taskStats.failed} <span class="err">✗</span></div><div class="label">Tasks Completed / Failed</div></div>
  <div class="card"><div class="stat">${Object.keys(stats.roomModeUsage).length}</div><div class="label">Room Modes Used</div></div>
</div>

<div class="grid">
  <div class="card">
    <h2>Events by Type</h2>
    <table><tr><th>Kind</th><th>Count</th></tr>${kindRows || "<tr><td colspan=2>No data</td></tr>"}</table>
  </div>
  <div class="card">
    <h2>Model Latency</h2>
    <table><tr><th>Model</th><th>Avg</th><th>Calls</th></tr>${latencyRows || "<tr><td colspan=3>No data</td></tr>"}</table>
  </div>
  <div class="card">
    <h2>Services</h2>
    <table><tr><th>Name</th><th>Uptime</th><th>Checks</th><th>Fails</th></tr>${serviceRows || "<tr><td colspan=4>No data</td></tr>"}</table>
  </div>
</div>

<div class="card" style="margin-bottom:16px">
  <h2>Room Mode Usage</h2>
  <table><tr><th>Mode</th><th>Queries</th></tr>${modeRows || "<tr><td colspan=2>No data</td></tr>"}</table>
</div>

<div class="card">
  <h2>Recent Activity</h2>
  <table><tr><th>Time</th><th>Kind</th><th>Summary</th></tr>${activityRows || "<tr><td colspan=3>No data</td></tr>"}</table>
</div>
</body></html>`;
}

export class Dashboard {
  private server: ReturnType<typeof createServer> | null = null;
  private cfg: DashboardConfig;
  private running = false;

  constructor(config: DashboardConfig) {
    this.cfg = config;
  }

  start(): boolean {
    if (this.running) return false;
    this.server = createServer((req, res) => {
      if (req.url === "/api/stats") {
        const stats = aggregate(this.cfg.activityLogPath);
        res.writeHead(200, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" });
        res.end(JSON.stringify(stats));
        return;
      }
      const stats = aggregate(this.cfg.activityLogPath);
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(renderHtml(stats));
    });
    this.server.listen(this.cfg.port, this.cfg.host);
    this.running = true;
    return true;
  }

  stop(): boolean {
    if (!this.running || !this.server) return false;
    this.server.close();
    this.server = null;
    this.running = false;
    return true;
  }

  isRunning(): boolean { return this.running; }
}
