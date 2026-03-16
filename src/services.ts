/**
 * Service Health Monitor — Watch and auto-restart local infrastructure
 *
 * Patterns pulled from:
 *   OpenClaw daemon          — self-healing service mesh
 *   OpenClaw bridge          — service endpoint registry
 *
 * AnnulusLabs LLC
 */

import { shellExec } from "./executor.js";
import type { ActivityLog } from "./activity-log.js";

export type ServiceStatus = {
  name: string;
  url: string;
  healthy: boolean;
  latencyMs: number;
  error?: string;
  lastCheck: string;
};

export type ServiceDef = {
  name: string;
  url: string;
  healthPath?: string;
  startCommand?: string;
};

const BUILTIN_SERVICES: ServiceDef[] = [
  {
    name: "autonomy",
    url: "http://127.0.0.1:8766",
    healthPath: "/status",
    startCommand: process.platform === "win32"
      ? 'Start-Process -FilePath "C:/Users/slows/AppData/Local/Programs/Python/Python312/python.exe" -ArgumentList "C:/Users/slows/.openclaw/workspace/autonomy.py","--serve" -WindowStyle Hidden'
      : "nohup python ~/.openclaw/workspace/autonomy.py --serve &",
  },
  {
    name: "ollama",
    url: "http://127.0.0.1:11434",
    healthPath: "/api/tags",
  },
];

async function checkOne(svc: ServiceDef, timeoutMs = 5_000): Promise<ServiceStatus> {
  const start = Date.now();
  try {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), timeoutMs);
    const r = await fetch(`${svc.url}${svc.healthPath ?? "/"}`, { signal: ac.signal });
    clearTimeout(t);
    return {
      name: svc.name,
      url: svc.url,
      healthy: r.ok,
      latencyMs: Date.now() - start,
      lastCheck: new Date().toISOString(),
    };
  } catch (err) {
    return {
      name: svc.name,
      url: svc.url,
      healthy: false,
      latencyMs: Date.now() - start,
      error: String(err).slice(0, 200),
      lastCheck: new Date().toISOString(),
    };
  }
}

export async function checkAllServices(extra?: ServiceDef[]): Promise<ServiceStatus[]> {
  const all = [...BUILTIN_SERVICES, ...(extra ?? [])];
  return Promise.all(all.map((s) => checkOne(s)));
}

export async function restartService(name: string, log?: ActivityLog, extra?: ServiceDef[]): Promise<string> {
  const all = [...BUILTIN_SERVICES, ...(extra ?? [])];
  const svc = all.find((s) => s.name === name);
  if (!svc) return `Unknown service: ${name}. Known: ${all.map((s) => s.name).join(", ")}`;
  if (!svc.startCommand) return `No start command configured for ${name}`;

  log?.emit("service_check", `restarting ${name}...`);
  const result = await shellExec(svc.startCommand, { timeoutMs: 15_000, log });

  if (result.exitCode === 0) {
    // Wait a beat then verify
    await new Promise((r) => setTimeout(r, 2_000));
    const status = await checkOne(svc);
    log?.emit("service_check", `${name}: ${status.healthy ? "UP" : "still down"} (${status.latencyMs}ms)`);
    return status.healthy
      ? `${name} restarted successfully (${status.latencyMs}ms)`
      : `${name} started but health check failed: ${status.error}`;
  }
  return `Failed to start ${name}: ${result.stderr.slice(0, 300)}`;
}

export function formatServiceStatus(statuses: ServiceStatus[]): string {
  return statuses.map((s) => {
    const icon = s.healthy ? "OK" : "DOWN";
    const latency = s.healthy ? ` ${s.latencyMs}ms` : "";
    const err = s.error ? ` — ${s.error.slice(0, 100)}` : "";
    return `[${icon.padEnd(4)}] ${s.name.padEnd(12)} ${s.url}${latency}${err}`;
  }).join("\n");
}

export { BUILTIN_SERVICES };
