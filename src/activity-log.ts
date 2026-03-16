/**
 * Activity Log — Real-time execution transparency
 *
 * The thing Claude Code's terminal does that OpenClaw TUI doesn't:
 * live streaming of what the agent is doing, thinking, reading, writing.
 *
 * Writes structured JSONL to a rolling log file.
 * OpenClaw hooks can tail this for TUI display.
 *
 * AnnulusLabs LLC
 */

import { appendFileSync, mkdirSync, statSync, renameSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";

export type ActivityKind =
  | "tool_call"      // agent invoked a tool
  | "tool_result"    // tool returned
  | "shell_exec"     // ran a command
  | "file_read"      // read a file
  | "file_write"     // wrote a file
  | "delegate"       // sent to local model
  | "delegate_result"// local model responded
  | "service_check"  // health check
  | "daemon_tick"    // daemon heartbeat
  | "task_event"     // task started/completed/failed
  | "plan_event"     // plan created/updated
  | "genome_event"   // genome consolidate/boot/record
  | "error"          // something went wrong
  | "info";          // general info

export type ActivityEntry = {
  ts: string;
  kind: ActivityKind;
  summary: string;        // one-line human-readable
  detail?: string;        // optional expanded detail
  durationMs?: number;    // how long it took
  meta?: Record<string, unknown>;
};

const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB before rotation

export class ActivityLog {
  private logPath: string;
  private listeners: Array<(entry: ActivityEntry) => void> = [];

  constructor(logPath: string) {
    this.logPath = logPath;
    mkdirSync(dirname(logPath), { recursive: true });
  }

  emit(kind: ActivityKind, summary: string, opts?: {
    detail?: string;
    durationMs?: number;
    meta?: Record<string, unknown>;
  }): ActivityEntry {
    const entry: ActivityEntry = {
      ts: new Date().toISOString(),
      kind,
      summary,
      ...opts,
    };
    this.write(entry);
    for (const fn of this.listeners) {
      try { fn(entry); } catch { /* silent */ }
    }
    return entry;
  }

  /** Subscribe to live entries */
  on(fn: (entry: ActivityEntry) => void): () => void {
    this.listeners.push(fn);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== fn);
    };
  }

  /** Timed execution wrapper — logs start + result + duration */
  async timed<T>(kind: ActivityKind, summary: string, fn: () => Promise<T>, meta?: Record<string, unknown>): Promise<T> {
    const start = Date.now();
    this.emit(kind, summary, { meta });
    try {
      const result = await fn();
      const durationMs = Date.now() - start;
      const detail = typeof result === "string" ? result.slice(0, 500) : undefined;
      this.emit(kind, `${summary} [done ${durationMs}ms]`, { durationMs, detail, meta });
      return result;
    } catch (err) {
      const durationMs = Date.now() - start;
      this.emit("error", `${summary} [failed ${durationMs}ms]: ${err}`, { durationMs, meta });
      throw err;
    }
  }

  private write(entry: ActivityEntry): void {
    try {
      this.rotate();
      appendFileSync(this.logPath, JSON.stringify(entry) + "\n");
    } catch { /* silent */ }
  }

  private rotate(): void {
    try {
      if (!existsSync(this.logPath)) return;
      const stat = statSync(this.logPath);
      if (stat.size > MAX_FILE_SIZE) {
        const prev = this.logPath + ".prev";
        try { renameSync(prev, prev + ".old"); } catch { /* no prev */ }
        renameSync(this.logPath, prev);
      }
    } catch { /* silent */ }
  }
}
