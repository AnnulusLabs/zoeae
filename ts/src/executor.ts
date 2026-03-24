/**
 * Executor — OS-level execution bridge
 * Gives the agent hands: shell commands, file I/O, process management.
 *
 * Patterns pulled from:
 *   OpenClaw daemon     — subprocess + psutil execution
 *   task_queue           — shell/python/admin task types
 *   OpenClaw autonomy   — agent spawn + result capture
 *
 * AnnulusLabs LLC
 */

import { exec as nodeExec } from "node:child_process";
import {
  readFileSync, writeFileSync, mkdirSync, existsSync,
  readdirSync, statSync, unlinkSync, appendFileSync,
} from "node:fs";
import { dirname, resolve, join, basename } from "node:path";
import { ActivityLog } from "./activity-log.js";
import type { PolicyEngine } from "./policy.js";

export type ExecResult = {
  stdout: string;
  stderr: string;
  exitCode: number;
  timedOut: boolean;
  durationMs: number;
};

// ── Shell Execution ──────────────────────────────────────────────────

export async function shellExec(
  command: string,
  opts?: {
    timeoutMs?: number;
    cwd?: string;
    shell?: string;
    log?: ActivityLog;
    policy?: PolicyEngine;
  },
): Promise<ExecResult> {
  // Policy: check command before execution
  if (opts?.policy) {
    const v = opts.policy.checkCommand(command);
    if (!v.allowed) {
      opts?.log?.emit("policy_block", `shellExec blocked: ${v.reason}`);
      return { stdout: "", stderr: `POLICY BLOCKED: ${v.reason}`, exitCode: 126, timedOut: false, durationMs: 0 };
    }
  }

  const timeoutMs = opts?.timeoutMs ?? 30_000;
  const cwd = opts?.cwd ?? process.env.HOME ?? process.env.USERPROFILE ?? ".";
  const shell = opts?.shell ?? (process.platform === "win32" ? "powershell.exe" : "/bin/bash");
  const start = Date.now();

  opts?.log?.emit("shell_exec", `$ ${command.slice(0, 200)}`, { meta: { cwd, timeoutMs } });

  return new Promise((res) => {
    nodeExec(command, {
      timeout: timeoutMs,
      cwd,
      shell,
      maxBuffer: 2 * 1024 * 1024, // 2MB
      env: { ...process.env },
    }, (err, stdout, stderr) => {
      const durationMs = Date.now() - start;
      const result: ExecResult = {
        stdout: (stdout ?? "").slice(0, 20_000),
        stderr: (stderr ?? "").slice(0, 10_000),
        exitCode: err?.code ?? (err ? 1 : 0),
        timedOut: err?.killed ?? false,
        durationMs,
      };

      opts?.log?.emit("shell_exec", `$ ${command.slice(0, 80)} → exit ${result.exitCode} (${durationMs}ms)`, {
        durationMs,
        detail: result.stdout.slice(0, 300) || result.stderr.slice(0, 300),
      });

      res(result);
    });
  });
}

// ── File Operations ──────────────────────────────────────────────────

export function readFile(path: string, log?: ActivityLog, policy?: PolicyEngine): string {
  const resolved = resolve(path);
  if (policy) {
    const v = policy.checkPathRead(resolved);
    if (!v.allowed) {
      log?.emit("policy_block", `readFile blocked: ${v.reason}`);
      throw new Error(`POLICY BLOCKED: ${v.reason}`);
    }
  }
  log?.emit("file_read", `read ${basename(resolved)}`, { meta: { path: resolved } });
  return readFileSync(resolved, "utf-8");
}

export function writeFile(path: string, content: string, log?: ActivityLog, policy?: PolicyEngine): void {
  const resolved = resolve(path);
  if (policy) {
    const v = policy.checkPathWrite(resolved);
    if (!v.allowed) {
      log?.emit("policy_block", `writeFile blocked: ${v.reason}`);
      throw new Error(`POLICY BLOCKED: ${v.reason}`);
    }
  }
  mkdirSync(dirname(resolved), { recursive: true });
  writeFileSync(resolved, content, "utf-8");
  log?.emit("file_write", `write ${basename(resolved)} (${content.length} chars)`, { meta: { path: resolved } });
}

export function appendToFile(path: string, content: string, log?: ActivityLog, policy?: PolicyEngine): void {
  const resolved = resolve(path);
  if (policy) {
    const v = policy.checkPathWrite(resolved);
    if (!v.allowed) {
      log?.emit("policy_block", `appendToFile blocked: ${v.reason}`);
      throw new Error(`POLICY BLOCKED: ${v.reason}`);
    }
  }
  mkdirSync(dirname(resolved), { recursive: true });
  appendFileSync(resolved, content, "utf-8");
  log?.emit("file_write", `append ${basename(resolved)} (+${content.length} chars)`, { meta: { path: resolved } });
}

export function listDir(path: string): Array<{ name: string; isDir: boolean; size: number }> {
  const resolved = resolve(path);
  if (!existsSync(resolved)) return [];
  return readdirSync(resolved).map((name) => {
    try {
      const full = join(resolved, name);
      const stat = statSync(full);
      return { name, isDir: stat.isDirectory(), size: stat.size };
    } catch {
      return { name, isDir: false, size: 0 };
    }
  });
}

export function fileExists(path: string): boolean {
  return existsSync(resolve(path));
}

export function deleteFile(path: string, log?: ActivityLog, policy?: PolicyEngine): boolean {
  const resolved = resolve(path);
  if (policy) {
    const v = policy.checkPathWrite(resolved);
    if (!v.allowed) {
      log?.emit("policy_block", `deleteFile blocked: ${v.reason}`);
      return false;
    }
  }
  try {
    unlinkSync(resolved);
    log?.emit("file_write", `delete ${basename(resolved)}`, { meta: { path: resolved } });
    return true;
  } catch {
    return false;
  }
}

export function fileInfo(path: string): { exists: boolean; size: number; isDir: boolean; modified: string } | null {
  try {
    const stat = statSync(resolve(path));
    return {
      exists: true,
      size: stat.size,
      isDir: stat.isDirectory(),
      modified: stat.mtime.toISOString(),
    };
  } catch {
    return null;
  }
}
