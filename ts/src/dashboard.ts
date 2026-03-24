/**
 * Telemetry Dashboard — Terminal readout for activity observability
 *
 * Aggregates activity.jsonl into tool call frequency, delegation latency
 * per model, task completion rates, genome growth, room mode usage,
 * service uptime.
 *
 * Pure ANSI output. No webapp. No browser. No dependencies.
 *
 * AnnulusLabs LLC
 */

import { readFileSync, existsSync } from "node:fs";

// ── ANSI NOX palette ──────────────────────────────────────────────
const RST = "\x1b[0m";
const BLD = "\x1b[1m";
const DIM = "\x1b[2m";
const INV = "\x1b[7m";

const GREEN  = "\x1b[38;2;0;255;136m";
const RED    = "\x1b[38;2;255;51;102m";
const BLUE   = "\x1b[38;2;102;119;170m";
const GREY   = "\x1b[38;2;100;100;100m";
const WHITE  = "\x1b[38;2;255;255;255m";
const GOLD   = "\x1b[38;2;255;204;0m";
const CYAN   = "\x1b[38;2;51;204;255m";
const ORANGE = "\x1b[38;2;255;153;51m";
const PURPLE = "\x1b[38;2;204;102;255m";
const MINT   = "\x1b[38;2;102;255;204m";

const BG_BAR = "\x1b[48;2;20;20;35m";

// ── Types ─────────────────────────────────────────────────────────
export type DashboardConfig = {
  activityLogPath: string;
};

type AggregatedStats = {
  totalEntries: number;
  byKind: Record<string, number>;
  avgLatencyByModel: Record<string, { total: number; count: number; avg: number }>;
  taskStats: { completed: number; failed: number; blocked: number };
  roomModeUsage: Record<string, number>;
  serviceHealth: Record<string, { checks: number; failures: number; uptime: string }>;
  policyStats: { violations: number; warnings: number; blocks: number; toolInvocations: number; recentViolations: string[] };
  recentEntries: Array<{ ts: string; kind: string; summary: string; durationMs?: number }>;
  timeRange: { first: string; last: string };
};

// ── Aggregation (unchanged) ───────────────────────────────────────
function aggregate(logPath: string): AggregatedStats {
  const stats: AggregatedStats = {
    totalEntries: 0,
    byKind: {},
    avgLatencyByModel: {},
    taskStats: { completed: 0, failed: 0, blocked: 0 },
    roomModeUsage: {},
    serviceHealth: {},
    policyStats: { violations: 0, warnings: 0, blocks: 0, toolInvocations: 0, recentViolations: [] },
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
    stats.byKind[e.kind] = (stats.byKind[e.kind] ?? 0) + 1;

    if (e.kind === "delegate_result" && e.durationMs && e.meta?.model) {
      const model = String(e.meta.model);
      if (!stats.avgLatencyByModel[model]) stats.avgLatencyByModel[model] = { total: 0, count: 0, avg: 0 };
      stats.avgLatencyByModel[model].total += e.durationMs;
      stats.avgLatencyByModel[model].count++;
    }

    if (e.kind === "task_event") {
      if (e.summary?.includes("completed")) stats.taskStats.completed++;
      if (e.summary?.includes("failed")) stats.taskStats.failed++;
      if (e.summary?.includes("blocked")) stats.taskStats.blocked++;
    }

    if (e.kind === "delegate" && e.summary?.includes("room query")) {
      const modeMatch = e.summary.match(/\[(\w[\w-]*)\]/);
      if (modeMatch) stats.roomModeUsage[modeMatch[1]] = (stats.roomModeUsage[modeMatch[1]] ?? 0) + 1;
    }

    if (e.kind === "service_check") {
      const nameMatch = e.summary?.match(/^(\w+)/);
      if (nameMatch) {
        const name = nameMatch[1];
        if (!stats.serviceHealth[name]) stats.serviceHealth[name] = { checks: 0, failures: 0, uptime: "0%" };
        stats.serviceHealth[name].checks++;
        if (e.summary.includes("DOWN")) stats.serviceHealth[name].failures++;
      }
    }

    if (e.kind === "policy_violation") {
      stats.policyStats.violations++;
      stats.policyStats.blocks++;
      stats.policyStats.recentViolations.push(`${e.ts?.slice(11, 19) ?? "?"} ${(e.summary ?? "").slice(0, 80)}`);
    }
    if (e.kind === "policy_warning") {
      stats.policyStats.warnings++;
    }
    if (e.kind === "policy_block") {
      stats.policyStats.blocks++;
    }
    if (e.kind === "tool_invocation") {
      stats.policyStats.toolInvocations++;
    }
    if (e.kind === "policy_escalation") {
      stats.policyStats.violations++;
      stats.policyStats.recentViolations.push(`${e.ts?.slice(11, 19) ?? "?"} ESCALATION: ${(e.summary ?? "").slice(0, 70)}`);
    }
  }

  for (const m of Object.values(stats.avgLatencyByModel)) {
    m.avg = m.count > 0 ? Math.round(m.total / m.count) : 0;
  }
  for (const s of Object.values(stats.serviceHealth)) {
    const upPct = s.checks > 0 ? Math.round(((s.checks - s.failures) / s.checks) * 100) : 0;
    s.uptime = `${upPct}%`;
  }

  stats.recentEntries = entries.slice(-20).reverse().map((e) => ({
    ts: e.ts?.slice(11, 19) ?? "??:??:??",
    kind: e.kind,
    summary: (e.summary ?? "").slice(0, 90),
    durationMs: e.durationMs,
  }));

  return stats;
}

// ── ANSI rendering helpers ────────────────────────────────────────
function bar(text: string, width = 80): string {
  const padded = ` ${text} `.padEnd(width);
  return `${BG_BAR}${WHITE}${BLD}${padded}${RST}`;
}

function sectionHeader(title: string): string {
  return `${GREEN}${BLD}${title}${RST}`;
}

function tableRow(cols: string[], widths: number[]): string {
  return cols.map((c, i) => c.padEnd(widths[i])).join("  ");
}

function sparkBar(value: number, max: number, width = 20): string {
  if (max === 0) return GREY + "░".repeat(width) + RST;
  const filled = Math.round((value / max) * width);
  return GREEN + "█".repeat(filled) + GREY + "░".repeat(width - filled) + RST;
}

function modelColor(model: string): string {
  const m = model.toLowerCase();
  if (m.includes("qwen")) return GOLD;
  if (m.includes("llama")) return CYAN;
  if (m.includes("hermes") || m.includes("phi")) return ORANGE;
  if (m.includes("deepseek")) return PURPLE;
  if (m.includes("mistral") || m.includes("codestral") || m.includes("devstral")) return MINT;
  if (m.includes("gemma")) return "\x1b[38;2;255;102;153m";
  return WHITE;
}

function kindColor(kind: string): string {
  if (kind.includes("error") || kind.includes("fail")) return RED;
  if (kind.includes("complete") || kind.includes("success")) return GREEN;
  if (kind.includes("delegate")) return CYAN;
  if (kind.includes("task")) return ORANGE;
  if (kind.includes("service")) return BLUE;
  return GREY;
}

// ── Main render ───────────────────────────────────────────────────
export function renderDashboard(logPath: string): string {
  const s = aggregate(logPath);
  const W = 80;
  const lines: string[] = [];

  // ── Header bar ──
  lines.push("");
  lines.push(bar("ZOEAE  TELEMETRY", W));
  if (s.timeRange.first) {
    lines.push(`${DIM}  ${s.timeRange.first.slice(0, 19)} -> ${s.timeRange.last.slice(0, 19)}  |  ${s.totalEntries} events${RST}`);
  } else {
    lines.push(`${DIM}  No data yet${RST}`);
  }
  lines.push("");

  // ── Summary stats ──
  const completed = `${GREEN}${s.taskStats.completed}${RST}`;
  const failed = `${RED}${s.taskStats.failed}${RST}`;
  const blocked = `${ORANGE}${s.taskStats.blocked}${RST}`;
  const modes = Object.keys(s.roomModeUsage).length;
  lines.push(`  ${BLD}Tasks${RST}  ${completed} done  ${failed} failed  ${blocked} blocked    ${BLD}Room Modes${RST}  ${CYAN}${modes}${RST}`);
  lines.push("");

  // ── Events by type ──
  const kindEntries = Object.entries(s.byKind).sort((a, b) => b[1] - a[1]);
  if (kindEntries.length > 0) {
    lines.push(sectionHeader("  EVENTS"));
    const maxKind = Math.max(...kindEntries.map(([, v]) => v));
    for (const [kind, count] of kindEntries) {
      const label = kind.padEnd(22);
      const num = String(count).padStart(5);
      lines.push(`  ${GREY}${label}${RST} ${num}  ${sparkBar(count, maxKind, 30)}`);
    }
    lines.push("");
  }

  // ── Model latency ──
  const latencyEntries = Object.entries(s.avgLatencyByModel).sort((a, b) => b[1].avg - a[1].avg);
  if (latencyEntries.length > 0) {
    lines.push(sectionHeader("  MODEL LATENCY"));
    lines.push(`  ${DIM}${tableRow(["Model", "Avg", "Calls"], [28, 10, 6])}${RST}`);
    for (const [model, v] of latencyEntries) {
      const mc = modelColor(model);
      const name = model.length > 26 ? model.slice(0, 24) + ".." : model;
      lines.push(`  ${mc}${name.padEnd(28)}${RST} ${WHITE}${(v.avg + "ms").padStart(10)}${RST} ${DIM}${String(v.count).padStart(6)}${RST}`);
    }
    lines.push("");
  }

  // ── Services ──
  const svcEntries = Object.entries(s.serviceHealth);
  if (svcEntries.length > 0) {
    lines.push(sectionHeader("  SERVICES"));
    for (const [name, v] of svcEntries) {
      const pct = parseInt(v.uptime);
      const color = pct >= 95 ? GREEN : pct >= 70 ? ORANGE : RED;
      lines.push(`  ${WHITE}${name.padEnd(16)}${RST} ${color}${v.uptime.padStart(5)}${RST}  ${DIM}${v.checks} checks  ${v.failures} fails${RST}`);
    }
    lines.push("");
  }

  // ── Policy ──
  const ps = s.policyStats;
  if (ps.violations > 0 || ps.warnings > 0 || ps.toolInvocations > 0) {
    lines.push(sectionHeader("  POLICY"));
    const vColor = ps.violations > 0 ? RED : GREEN;
    const wColor = ps.warnings > 0 ? ORANGE : GREEN;
    lines.push(`  ${BLD}Violations${RST} ${vColor}${ps.violations}${RST}    ${BLD}Warnings${RST} ${wColor}${ps.warnings}${RST}    ${BLD}Blocks${RST} ${RED}${ps.blocks}${RST}    ${BLD}Tool Audit${RST} ${DIM}${ps.toolInvocations}${RST}`);
    if (ps.recentViolations.length > 0) {
      const recent = ps.recentViolations.slice(-5);
      for (const v of recent) {
        lines.push(`  ${RED}!${RST} ${DIM}${v}${RST}`);
      }
    }
    if (ps.violations === 0 && ps.blocks === 0) {
      lines.push(`  ${GREEN}clean — no violations${RST}`);
    }
    lines.push("");
  }

  // ── Room mode usage ──
  const modeEntries = Object.entries(s.roomModeUsage).sort((a, b) => b[1] - a[1]);
  if (modeEntries.length > 0) {
    lines.push(sectionHeader("  ROOM MODES"));
    const maxMode = Math.max(...modeEntries.map(([, v]) => v));
    for (const [mode, count] of modeEntries) {
      lines.push(`  ${CYAN}${mode.padEnd(16)}${RST} ${String(count).padStart(4)}  ${sparkBar(count, maxMode, 20)}`);
    }
    lines.push("");
  }

  // ── Recent activity ──
  if (s.recentEntries.length > 0) {
    lines.push(sectionHeader("  RECENT ACTIVITY"));
    for (const e of s.recentEntries) {
      const dur = e.durationMs ? `${DIM}(${e.durationMs}ms)${RST}` : "";
      const kc = kindColor(e.kind);
      const kindTag = e.kind.padEnd(18);
      lines.push(`  ${DIM}${e.ts}${RST}  ${kc}${kindTag}${RST} ${e.summary.slice(0, 60)} ${dur}`);
    }
    lines.push("");
  }

  lines.push(`${DIM}${"─".repeat(W)}${RST}`);
  return lines.join("\n");
}

// ── Legacy compat: Dashboard class now just wraps renderDashboard ──
export class Dashboard {
  private cfg: DashboardConfig & { port?: number; host?: string };

  constructor(config: DashboardConfig & { port?: number; host?: string }) {
    this.cfg = config;
  }

  render(): string {
    return renderDashboard(this.cfg.activityLogPath);
  }

  // Stubs for backward compat — no-op since we killed the server
  start(): boolean { return true; }
  stop(): boolean { return true; }
  isRunning(): boolean { return false; }
}
