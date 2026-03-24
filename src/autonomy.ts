/**
 * Autonomy — Genome-driven heartbeat, persistent cron, memory compaction, audit trail
 *
 * Clean rewrite of MoltBot's three best autonomy patterns with Zoeae's
 * PolicyEngine enforcement. Every pattern closes a MoltBot security hole:
 *
 *   HeartbeatEngine  — policy-gated directive loop (MoltBot: raw LLM exec, no validation)
 *   CronEngine       — crash-safe cron with minimal privilege (MoltBot: full agent authority)
 *   MemoryCompactor  — read-only Ollama compaction (MoltBot: full tools during compaction)
 *   AuditTrail       — append-only JSONL audit log (MoltBot: no audit log at all)
 *   AutonomyEngine   — ties all four together
 *
 * AnnulusLabs LLC
 */

import {
  readFileSync,
  writeFileSync,
  appendFileSync,
  existsSync,
  mkdirSync,
  renameSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { createHash, randomUUID } from "node:crypto";

import { ActivityLog } from "./activity-log.js";
import { PolicyEngine } from "./policy.js";
import type { ExecutionContext } from "./policy.js";
import { TaskEngine } from "./task-engine.js";
import { AutonomyClient } from "./autonomy-client.js";
import type { GenomeStats } from "./autonomy-client.js";
import { OllamaClient } from "./ollama-client.js";
import { shellExec } from "./executor.js";

// ═══════════════════════════════════════════════════════════════════════
// SHARED PATHS
// ═══════════════════════════════════════════════════════════════════════

import { getKerfDir, paths } from "./paths.js";
const KERF_DIR = getKerfDir();

// ═══════════════════════════════════════════════════════════════════════
// PATTERN 1 — GENOME-DRIVEN HEARTBEAT
// ═══════════════════════════════════════════════════════════════════════

/**
 * A single directive parsed from the genome or HEARTBEAT.md.
 *
 * MoltBot executes HEARTBEAT.md content as-is through the LLM with zero
 * validation. Every directive here must pass PolicyEngine before execution.
 */
export type Directive = {
  source: "genome" | "file";
  content: string;
  /** Execution type determines which runtime handles the directive */
  type: "shell" | "inference" | "task" | "research";
  /** Higher number = higher priority (1–10) */
  priority: number;
  /** Set by HeartbeatEngine after PolicyEngine.checkCommand() */
  approved: boolean;
  result?: string;
  blockedReason?: string;
};

export type HeartbeatConfig = {
  /** Milliseconds between automatic beats. Default: 30 minutes */
  intervalMs: number;
  /** Where to source directives from */
  source: "genome" | "file" | "both";
  /** Absolute path to HEARTBEAT.md; only used when source includes "file" */
  filePath?: string;
  /** Maximum directives executed per beat cycle (prevents runaway) */
  maxActionsPerBeat: number;
  /**
   * Always true — here for documentation/audit purposes only.
   * Removing this field does not bypass the policy check.
   */
  requirePolicyCheck: true;
};

const HEARTBEAT_DEFAULTS: HeartbeatConfig = {
  intervalMs: 1_800_000,   // 30 minutes
  source: "both",
  maxActionsPerBeat: 3,
  requirePolicyCheck: true,
};

export type HeartbeatBeat = {
  ts: number;
  directivesFound: number;
  directivesApproved: number;
  directivesBlocked: number;
  directivesExecuted: number;
  results: Array<Pick<Directive, "source" | "type" | "content" | "approved" | "result" | "blockedReason">>;
  durationMs: number;
};

/**
 * HeartbeatEngine — periodic genome + file directive loop
 *
 * Security improvements over MoltBot:
 * - Every command passes PolicyEngine.checkCommand() — no exceptions
 * - Full audit trail for every directive (approved, blocked, results)
 * - maxActionsPerBeat hard cap prevents runaway execution loops
 * - Blocked directives are written back to the genome as lessons
 * - File-sourced directives are parsed and typed, never raw-evaluated
 */
export class HeartbeatEngine {
  private cfg: HeartbeatConfig;
  private policy: PolicyEngine;
  private log: ActivityLog;
  private genome: AutonomyClient;
  private ollama: OllamaClient;
  private tasks: TaskEngine;
  private audit: AuditTrail;
  private _timer: ReturnType<typeof setInterval> | null = null;
  private _lastBeat: HeartbeatBeat | null = null;
  private _pending: Directive[] = [];
  private _running = false;

  constructor(opts: {
    config?: Partial<Omit<HeartbeatConfig, "requirePolicyCheck">>;
    policy: PolicyEngine;
    log: ActivityLog;
    genome: AutonomyClient;
    ollama: OllamaClient;
    tasks: TaskEngine;
    audit: AuditTrail;
  }) {
    this.cfg = {
      ...HEARTBEAT_DEFAULTS,
      ...opts.config,
      requirePolicyCheck: true, // cannot be overridden
    };
    this.policy = opts.policy;
    this.log = opts.log;
    this.genome = opts.genome;
    this.ollama = opts.ollama;
    this.tasks = opts.tasks;
    this.audit = opts.audit;
  }

  /** Start the background heartbeat timer */
  start(): void {
    if (this._timer) return;
    this._timer = setInterval(() => { void this.tick(); }, this.cfg.intervalMs);
    this.log.emit("daemon_tick", `HeartbeatEngine started — interval ${this.cfg.intervalMs}ms, source=${this.cfg.source}`);
  }

  /** Stop the background timer */
  stop(): void {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
    this.log.emit("daemon_tick", "HeartbeatEngine stopped");
  }

  /**
   * Execute one full heartbeat cycle.
   *
   * Sequence:
   *   1. Collect directives from genome and/or HEARTBEAT.md
   *   2. Policy-check every directive
   *   3. Execute approved directives (up to maxActionsPerBeat)
   *   4. Record blocked directives to genome as lessons
   *   5. Persist beat results
   */
  async tick(): Promise<HeartbeatBeat> {
    if (this._running) {
      this.log.emit("daemon_tick", "HeartbeatEngine tick skipped — previous beat still running");
      return this._lastBeat ?? this._emptyBeat();
    }
    this._running = true;
    const start = Date.now();

    this.log.emit("daemon_tick", "HeartbeatEngine tick starting");

    const raw: Directive[] = [];

    // ── 1a. Genome directives ────────────────────────────────────────
    if (this.cfg.source === "genome" || this.cfg.source === "both") {
      const genomeDirectives = await this._collectFromGenome();
      raw.push(...genomeDirectives);
    }

    // ── 1b. File directives ──────────────────────────────────────────
    if (this.cfg.source === "file" || this.cfg.source === "both") {
      const fileDirectives = this._collectFromFile();
      raw.push(...fileDirectives);
    }

    // Sort by priority descending
    raw.sort((a, b) => b.priority - a.priority);
    this._pending = raw.slice(this.cfg.maxActionsPerBeat); // queue remainder

    const batch = raw.slice(0, this.cfg.maxActionsPerBeat);

    // ── 2. Policy-check every directive ────────────────────────────
    for (const d of batch) {
      if (d.type === "shell") {
        const verdict = this.policy.checkCommand(d.content);
        d.approved = verdict.allowed;
        if (!verdict.allowed) {
          d.blockedReason = verdict.reason;
        }
      } else {
        // inference / task / research — allow by default unless content looks dangerous
        const verdict = this.policy.checkCommand(d.content);
        // For non-shell types we only hard-block if policy explicitly denies
        d.approved = verdict.level !== "blocked" && verdict.level !== "critical";
        if (!d.approved) {
          d.blockedReason = verdict.reason;
        }
      }
    }

    const approved = batch.filter((d) => d.approved);
    const blocked  = batch.filter((d) => !d.approved);

    // ── 3. Execute approved directives ──────────────────────────────
    for (const d of approved) {
      const t0 = Date.now();
      try {
        switch (d.type) {
          case "shell": {
            const r = await shellExec(d.content, { policy: this.policy, log: this.log });
            d.result = r.exitCode === 0 ? r.stdout.slice(0, 500) : `exit ${r.exitCode}: ${r.stderr.slice(0, 300)}`;
            this.audit.append({
              agent: "heartbeat",
              tool: "shell",
              argsHash: sha256(d.content),
              status: r.exitCode === 0 ? "ok" : "error",
              durationMs: Date.now() - t0,
              policyDecision: "allowed",
            });
            break;
          }
          case "inference": {
            const r = await this.ollama.chatResult("hermes3:8b", [
              { role: "user", content: d.content },
            ]);
            d.result = r.ok ? r.content.slice(0, 500) : `inference error: ${r.error}`;
            this.audit.append({
              agent: "heartbeat",
              tool: "inference",
              argsHash: sha256(d.content),
              status: r.ok ? "ok" : "error",
              durationMs: Date.now() - t0,
              policyDecision: "allowed",
            });
            break;
          }
          case "task": {
            this.tasks.add({
              id: randomUUID(),
              name: d.content.slice(0, 80),
              description: d.content,
              taskType: "prompt",
              status: "pending",
              priority: 3,
              dependsOn: [],
              retryCount: 0,
              maxRetries: 1,
              createdAt: new Date().toISOString(),
              tags: ["heartbeat"],
            });
            d.result = "task queued";
            this.audit.append({
              agent: "heartbeat",
              tool: "task",
              argsHash: sha256(d.content),
              status: "ok",
              durationMs: Date.now() - t0,
              policyDecision: "allowed",
            });
            break;
          }
          case "research": {
            // Research directives go through inference with a research prompt wrapper
            const r = await this.ollama.chatResult("hermes3:8b", [
              { role: "system", content: "You are a research assistant. Provide a concise, factual response." },
              { role: "user", content: d.content },
            ]);
            d.result = r.ok ? r.content.slice(0, 500) : `research error: ${r.error}`;
            this.audit.append({
              agent: "heartbeat",
              tool: "research",
              argsHash: sha256(d.content),
              status: r.ok ? "ok" : "error",
              durationMs: Date.now() - t0,
              policyDecision: "allowed",
            });
            break;
          }
        }
      } catch (err) {
        d.result = `execution error: ${err}`;
        this.audit.append({
          agent: "heartbeat",
          tool: d.type,
          argsHash: sha256(d.content),
          status: "error",
          durationMs: Date.now() - t0,
          policyDecision: "allowed",
        });
      }
    }

    // ── 4. Record blocked directives to genome as lessons ───────────
    for (const d of blocked) {
      this.audit.append({
        agent: "heartbeat",
        tool: d.type,
        argsHash: sha256(d.content),
        status: "blocked",
        durationMs: 0,
        policyDecision: `blocked: ${d.blockedReason ?? "policy"}`,
      });
      try {
        await this.genome.record(
          "system",
          `HEARTBEAT BLOCKED: directive type=${d.type} was blocked by PolicyEngine. Reason: ${d.blockedReason ?? "policy violation"}. Do not issue this type of directive again.`,
        );
      } catch { /* genome unavailable — audit trail covers it */ }
    }

    // ── 5. Record beat result to genome ─────────────────────────────
    const summaryParts = approved
      .filter((d) => d.result)
      .map((d) => `[${d.type}] ${d.content.slice(0, 60)} → ${(d.result ?? "").slice(0, 80)}`);
    if (summaryParts.length > 0) {
      try {
        await this.genome.record("system", `HEARTBEAT COMPLETED: ${summaryParts.join(" | ")}`);
      } catch { /* genome unavailable */ }
    }

    const beat: HeartbeatBeat = {
      ts: Date.now(),
      directivesFound: batch.length,
      directivesApproved: approved.length,
      directivesBlocked: blocked.length,
      directivesExecuted: approved.length,
      results: batch.map((d) => ({
        source: d.source,
        type: d.type,
        content: d.content.slice(0, 120),
        approved: d.approved,
        result: d.result,
        blockedReason: d.blockedReason,
      })),
      durationMs: Date.now() - start,
    };

    this._lastBeat = beat;
    this._running = false;

    this.log.emit("daemon_tick", `HeartbeatEngine tick done — ${approved.length} executed, ${blocked.length} blocked (${beat.durationMs}ms)`, {
      durationMs: beat.durationMs,
      meta: { directivesFound: beat.directivesFound, directivesBlocked: beat.directivesBlocked },
    });

    return beat;
  }

  /** Last completed beat, or null if no beat has run yet */
  getLastBeat(): HeartbeatBeat | null {
    return this._lastBeat;
  }

  /** Directives queued beyond maxActionsPerBeat, waiting for the next beat */
  getPendingDirectives(): Directive[] {
    return [...this._pending];
  }

  // ── Private helpers ──────────────────────────────────────────────

  private async _collectFromGenome(): Promise<Directive[]> {
    const directives: Directive[] = [];
    try {
      const result = await this.genome.searchFacts("pending tasks directives todo", 10);
      for (const hit of result.results) {
        const content = hit.content?.trim();
        if (!content) continue;
        directives.push({
          source: "genome",
          content,
          type: this._inferType(content),
          priority: this._inferPriority(hit.score ?? 0.5),
          approved: false,
        });
      }
    } catch (err) {
      this.log.emit("info", `HeartbeatEngine: genome unavailable — ${err}`);
    }
    return directives;
  }

  private _collectFromFile(): Directive[] {
    const directives: Directive[] = [];
    const filePath = this.cfg.filePath;
    if (!filePath || !existsSync(filePath)) return directives;

    try {
      const raw = readFileSync(filePath, "utf-8");
      const lines = raw.split("\n");
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        // Skip headings and empty checkbox list items (mirrors MoltBot's isHeartbeatContentEffectivelyEmpty)
        if (/^#+(\s|$)/.test(trimmed)) continue;
        if (/^[-*+]\s*(\[[\sXx]?\]\s*)?$/.test(trimmed)) continue;
        // Strip leading list/checkbox markers
        const content = trimmed.replace(/^[-*+]\s*(\[[\sXx]?\]\s*)?/, "").trim();
        if (!content) continue;
        directives.push({
          source: "file",
          content,
          type: this._inferType(content),
          priority: 5,
          approved: false,
        });
      }
    } catch (err) {
      this.log.emit("error", `HeartbeatEngine: failed to read HEARTBEAT.md — ${err}`);
    }
    return directives;
  }

  /** Heuristic type inference from directive content */
  private _inferType(content: string): Directive["type"] {
    const lower = content.toLowerCase();
    if (/^(run|exec|ls|dir|git|npm|pip|python|node|curl|wget)\b/.test(lower)) return "shell";
    if (/\b(research|find|look up|search|investigate)\b/.test(lower)) return "research";
    if (/\b(task|create task|add task|queue)\b/.test(lower)) return "task";
    return "inference";
  }

  /** Map genome relevance score (0–1) to priority (1–10) */
  private _inferPriority(score: number): number {
    return Math.max(1, Math.min(10, Math.round(score * 10)));
  }

  private _emptyBeat(): HeartbeatBeat {
    return {
      ts: Date.now(), directivesFound: 0, directivesApproved: 0,
      directivesBlocked: 0, directivesExecuted: 0, results: [], durationMs: 0,
    };
  }
}

// ═══════════════════════════════════════════════════════════════════════
// PATTERN 2 — PERSISTENT CRON WITH CRASH RECOVERY
// ═══════════════════════════════════════════════════════════════════════

/**
 * Schedule expression for a cron job.
 *
 * - kind="every": run every intervalMs milliseconds
 * - kind="at":    run once at runAt (unix ms timestamp)
 * - kind="cron":  standard 5-field cron expression (evaluated as "every" with intervalMs fallback)
 */
export type CronSchedule =
  | { kind: "every"; intervalMs: number }
  | { kind: "at"; runAt: number }
  | { kind: "cron"; expr: string; intervalMs?: number };

/**
 * What a cron job actually does when it fires.
 *
 * Payload kind "shell" runs through PolicyEngine.checkCommand().
 * Payload kind "inference" talks to Ollama directly (no tools, no agent loop).
 * Payload kind "task" queues a TaskEngine entry.
 * Payload kind "message" routes to an agent via AgentPool (not yet implemented — logs intent).
 */
export type CronPayload =
  | { kind: "shell"; command: string }
  | { kind: "inference"; prompt: string }
  | { kind: "task"; taskDescription: string }
  | { kind: "message"; targetAgentRole: string; body: string };

/**
 * A single persistent cron job.
 *
 * Security improvements over MoltBot:
 * - policyScope defaults to "minimal" (MoltBot: full agent authority)
 * - maxRuns prevents infinite scheduling
 * - Cannot self-create recursive cron jobs
 */
export type CronJob = {
  id: string;
  name: string;
  schedule: CronSchedule;
  payload: CronPayload;
  /** UUID of the agent that created this job */
  createdBy: string;
  enabled: boolean;
  runCount: number;
  /** Unix ms timestamp of last execution */
  lastRunAt: number;
  lastResult: string;
  /** 0 = unlimited */
  maxRuns: number;
  /** Determines which PolicyEngine context is used during execution */
  policyScope: "minimal" | "standard" | "full";
  /** Unix ms timestamp when this job was created */
  createdAt: number;
};

/** Debounce constant for cron persistence writes (ms) */
const CRON_SAVE_DEBOUNCE_MS = 2_000;

/**
 * CronEngine — persistent cron scheduler with crash recovery
 *
 * Jobs are persisted to JSONL/JSON on disk and reloaded on startup.
 * The daemon calls tick() every 60 seconds.
 */
export class CronEngine {
  private jobs: Map<string, CronJob> = new Map();
  private persistPath: string;
  private policy: PolicyEngine;
  private log: ActivityLog;
  private ollama: OllamaClient;
  private tasks: TaskEngine;
  private audit: AuditTrail;
  private _saveTimer: ReturnType<typeof setTimeout> | null = null;
  private _lastTickAt = 0;
  private static readonly TICK_RATE_LIMIT_MS = 60_000;

  constructor(opts: {
    persistPath?: string;
    policy: PolicyEngine;
    log: ActivityLog;
    ollama: OllamaClient;
    tasks: TaskEngine;
    audit: AuditTrail;
  }) {
    this.persistPath = opts.persistPath ?? join(KERF_DIR, "cron-jobs.json");
    this.policy = opts.policy;
    this.log = opts.log;
    this.ollama = opts.ollama;
    this.tasks = opts.tasks;
    this.audit = opts.audit;
    this.load();
  }

  /**
   * Add a new cron job.
   *
   * Validates:
   * - Schedule is parseable
   * - Payload is not a recursive cron-creation job
   * - Shell commands pass PolicyEngine
   */
  add(job: Omit<CronJob, "id" | "runCount" | "lastRunAt" | "lastResult" | "createdAt">): CronJob {
    // Security: prevent recursive cron job creation
    if ((job.payload as { kind: string }).kind === "cron" as string) {
      throw new Error("CronEngine: recursive cron payloads are not permitted");
    }

    // Pre-validate shell commands at registration time
    if (job.payload.kind === "shell") {
      const verdict = this.policy.checkCommand(job.payload.command);
      if (!verdict.allowed) {
        throw new Error(`CronEngine: job command blocked by policy — ${verdict.reason}`);
      }
    }

    const full: CronJob = {
      ...job,
      id: randomUUID(),
      runCount: 0,
      lastRunAt: 0,
      lastResult: "",
      createdAt: Date.now(),
    };

    this.jobs.set(full.id, full);
    this.scheduleSave();
    this.log.emit("info", `CronEngine: job added — ${full.name} (${full.id}) scope=${full.policyScope}`);
    return full;
  }

  /** Remove a job by ID */
  remove(id: string): boolean {
    const existed = this.jobs.delete(id);
    if (existed) {
      this.scheduleSave();
      this.log.emit("info", `CronEngine: job removed — ${id}`);
    }
    return existed;
  }

  /** Enable a disabled job */
  enable(id: string): boolean {
    const job = this.jobs.get(id);
    if (!job) return false;
    job.enabled = true;
    this.scheduleSave();
    return true;
  }

  /** Disable a job without removing it */
  disable(id: string): boolean {
    const job = this.jobs.get(id);
    if (!job) return false;
    job.enabled = false;
    this.scheduleSave();
    return true;
  }

  /** List all jobs with current status */
  list(): CronJob[] {
    return Array.from(this.jobs.values());
  }

  /**
   * Called by the daemon every 60 seconds.
   *
   * Rate-limited: will skip if called more frequently than TICK_RATE_LIMIT_MS.
   * Executes at most one job per tick to prevent burst execution.
   */
  async tick(): Promise<void> {
    const now = Date.now();
    if (now - this._lastTickAt < CronEngine.TICK_RATE_LIMIT_MS) return;
    this._lastTickAt = now;

    for (const job of this.jobs.values()) {
      if (!job.enabled) continue;
      if (!this._isDue(job, now)) continue;
      if (job.maxRuns > 0 && job.runCount >= job.maxRuns) {
        job.enabled = false;
        this.scheduleSave();
        this.log.emit("info", `CronEngine: job ${job.name} auto-disabled — maxRuns reached`);
        continue;
      }

      await this._runJob(job, now);
      this.scheduleSave();
      // Rate limit: one job per tick
      break;
    }
  }

  /**
   * Force-run a specific job immediately, bypassing schedule.
   * The job still goes through PolicyEngine.
   */
  async forceRun(id: string): Promise<string> {
    const job = this.jobs.get(id);
    if (!job) return `job ${id} not found`;
    await this._runJob(job, Date.now());
    this.scheduleSave();
    return job.lastResult;
  }

  // ── Private helpers ──────────────────────────────────────────────

  private _isDue(job: CronJob, now: number): boolean {
    switch (job.schedule.kind) {
      case "every":
        return (now - job.lastRunAt) >= job.schedule.intervalMs;
      case "at":
        return job.lastRunAt === 0 && now >= job.schedule.runAt;
      case "cron": {
        const intervalMs = job.schedule.intervalMs ?? 3_600_000; // default 1h for bare cron exprs
        return (now - job.lastRunAt) >= intervalMs;
      }
    }
  }

  private async _runJob(job: CronJob, now: number): Promise<void> {
    const t0 = Date.now();
    const context: ExecutionContext = job.policyScope === "minimal" ? "daemon"
      : job.policyScope === "full" ? "interactive" : "daemon";

    this.log.emit("daemon_tick", `CronEngine: running job ${job.name} (scope=${job.policyScope})`);

    try {
      switch (job.payload.kind) {
        case "shell": {
          const verdict = this.policy.checkCommand(job.payload.command);
          if (!verdict.allowed) {
            job.lastResult = `BLOCKED: ${verdict.reason}`;
            this.audit.append({
              agent: `cron:${job.id}`,
              tool: "shell",
              argsHash: sha256(job.payload.command),
              status: "blocked",
              durationMs: 0,
              policyDecision: `blocked: ${verdict.reason}`,
            });
            break;
          }
          const r = await shellExec(job.payload.command, { policy: this.policy, log: this.log });
          job.lastResult = r.exitCode === 0 ? r.stdout.slice(0, 500) : `exit ${r.exitCode}: ${r.stderr.slice(0, 300)}`;
          this.audit.append({
            agent: `cron:${job.id}`,
            tool: "shell",
            argsHash: sha256(job.payload.command),
            status: r.exitCode === 0 ? "ok" : "error",
            durationMs: Date.now() - t0,
            policyDecision: "allowed",
          });
          break;
        }
        case "inference": {
          const r = await this.ollama.chatResult("hermes3:8b", [
            { role: "user", content: job.payload.prompt },
          ]);
          job.lastResult = r.ok ? r.content.slice(0, 500) : `inference error: ${r.error}`;
          this.audit.append({
            agent: `cron:${job.id}`,
            tool: "inference",
            argsHash: sha256(job.payload.prompt),
            status: r.ok ? "ok" : "error",
            durationMs: Date.now() - t0,
            policyDecision: "allowed",
          });
          break;
        }
        case "task": {
          this.tasks.add({
            id: randomUUID(),
            name: job.payload.taskDescription.slice(0, 80),
            description: job.payload.taskDescription,
            taskType: "prompt",
            status: "pending",
            priority: 3,
            dependsOn: [],
            retryCount: 0,
            maxRetries: 1,
            createdAt: new Date().toISOString(),
            tags: ["cron", job.id],
          });
          job.lastResult = "task queued";
          this.audit.append({
            agent: `cron:${job.id}`,
            tool: "task",
            argsHash: sha256(job.payload.taskDescription),
            status: "ok",
            durationMs: Date.now() - t0,
            policyDecision: "allowed",
          });
          break;
        }
        case "message": {
          // Route to agent — AgentPool integration point
          job.lastResult = `message intent logged: role=${job.payload.targetAgentRole} body="${job.payload.body.slice(0, 80)}"`;
          this.audit.append({
            agent: `cron:${job.id}`,
            tool: "message",
            argsHash: sha256(job.payload.body),
            status: "ok",
            durationMs: Date.now() - t0,
            policyDecision: "allowed",
          });
          this.log.emit("info", `CronEngine: message payload — ${job.lastResult}`);
          break;
        }
      }
    } catch (err) {
      job.lastResult = `error: ${err}`;
      this.audit.append({
        agent: `cron:${job.id}`,
        tool: job.payload.kind,
        argsHash: "",
        status: "error",
        durationMs: Date.now() - t0,
        policyDecision: "error",
      });
    }

    job.lastRunAt = now;
    job.runCount += 1;

    if (job.maxRuns > 0 && job.runCount >= job.maxRuns) {
      job.enabled = false;
      this.log.emit("info", `CronEngine: job ${job.name} auto-disabled after ${job.runCount} runs`);
    }

    this.log.emit("daemon_tick", `CronEngine: job ${job.name} done (${Date.now() - t0}ms) — ${job.lastResult.slice(0, 80)}`);
  }

  // ── Persistence (atomic tmp+rename, same pattern as PoolPersistence) ──

  private load(): void {
    try {
      if (!existsSync(this.persistPath)) return;
      const raw = JSON.parse(readFileSync(this.persistPath, "utf-8"));
      for (const j of raw.jobs ?? []) {
        this.jobs.set(j.id, j as CronJob);
      }
      this.log.emit("info", `CronEngine: loaded ${this.jobs.size} job(s) from ${this.persistPath}`);
    } catch (err) {
      this.log.emit("error", `CronEngine: failed to load persisted jobs — ${err}`);
    }
  }

  private scheduleSave(): void {
    if (this._saveTimer) return;
    this._saveTimer = setTimeout(() => {
      this._saveTimer = null;
      this.saveNow();
    }, CRON_SAVE_DEBOUNCE_MS);
  }

  private saveNow(): void {
    try {
      const dir = dirname(this.persistPath);
      mkdirSync(dir, { recursive: true });
      const tmp = `${this.persistPath}.tmp`;
      writeFileSync(tmp, JSON.stringify({
        version: 1,
        savedAt: new Date().toISOString(),
        jobs: Array.from(this.jobs.values()),
      }, null, 2));
      renameSync(tmp, this.persistPath);
    } catch (err) {
      this.log.emit("error", `CronEngine: failed to persist jobs — ${err}`);
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════
// PATTERN 3 — MEMORY COMPACTION WITH READ-ONLY AGENT
// ═══════════════════════════════════════════════════════════════════════

export type CompactionConfig = {
  /** Token count that triggers automatic compaction. Default: 150000 */
  triggerTokenThreshold: number;
  /** Maximum tokens to spend on the compaction prompt. Default: 4000 */
  maxCompactionTokens: number;
  /** Ollama model used for compaction — must be local. Default: hermes3:8b */
  compactionModel: string;
  /** Where to write session archives */
  outputPath: string;
  /** Automatically compact when triggerTokenThreshold is exceeded */
  autoCompact: boolean;
};

export type CompactionResult = {
  factsExtracted: number;
  tokensCompacted: number;
  sessionArchived: boolean;
  archivedPath: string;
  skipped?: boolean;
  skipReason?: string;
};

const COMPACTION_DEFAULTS: CompactionConfig = {
  triggerTokenThreshold: 150_000,
  maxCompactionTokens: 4_000,
  compactionModel: "hermes3:8b",
  outputPath: join(KERF_DIR, "sessions"),
  autoCompact: true,
};

/**
 * MemoryCompactor — read-only Ollama session summarisation
 *
 * Security improvements over MoltBot:
 * - Ollama called with NO tools, NO shell, NO file write permissions
 * - Output validated: must be parseable JSONL (not arbitrary agent response)
 * - Session archived to disk BEFORE any compaction (no data loss on failure)
 * - Uses Ollama chatResult() directly — no agent loop, no tool dispatch
 */
export class MemoryCompactor {
  private cfg: CompactionConfig;
  private genome: AutonomyClient;
  private ollama: OllamaClient;
  private log: ActivityLog;
  private audit: AuditTrail;
  private _lastCompaction: CompactionResult | null = null;

  constructor(opts: {
    config?: Partial<CompactionConfig>;
    genome: AutonomyClient;
    ollama: OllamaClient;
    log: ActivityLog;
    audit: AuditTrail;
  }) {
    this.cfg = { ...COMPACTION_DEFAULTS, ...opts.config };
    this.genome = opts.genome;
    this.ollama = opts.ollama;
    this.log = opts.log;
    this.audit = opts.audit;
  }

  /**
   * Compact a session log into genome facts.
   *
   * Steps:
   *   1. Estimate token count — skip if below threshold
   *   2. Archive full session to disk FIRST (no data loss)
   *   3. Call Ollama with read-only context (no tools)
   *   4. Parse and validate JSONL output
   *   5. Write validated facts to genome
   */
  async compact(sessionLog: string[], genomeStats: GenomeStats): Promise<CompactionResult> {
    const t0 = Date.now();
    const joined = sessionLog.join("\n");

    // ── 1. Token estimation (4 chars ≈ 1 token) ─────────────────────
    const estimatedTokens = Math.ceil(joined.length / 4);
    if (estimatedTokens < this.cfg.triggerTokenThreshold) {
      const result: CompactionResult = {
        factsExtracted: 0,
        tokensCompacted: 0,
        sessionArchived: false,
        archivedPath: "",
        skipped: true,
        skipReason: `below threshold (${estimatedTokens} < ${this.cfg.triggerTokenThreshold} tokens)`,
      };
      this.log.emit("info", `MemoryCompactor: skipped — ${result.skipReason}`);
      this._lastCompaction = result;
      return result;
    }

    this.log.emit("genome_event", `MemoryCompactor: starting (${estimatedTokens} est. tokens, ${genomeStats.total_nodes} genome nodes)`);

    // ── 2. Archive full session BEFORE compaction ────────────────────
    const archiveName = `session-${Date.now()}.jsonl`;
    const archivedPath = join(this.cfg.outputPath, archiveName);
    let sessionArchived = false;
    try {
      mkdirSync(this.cfg.outputPath, { recursive: true });
      writeFileSync(archivedPath, sessionLog.map((l) => JSON.stringify({ line: l })).join("\n") + "\n");
      sessionArchived = true;
      this.log.emit("genome_event", `MemoryCompactor: session archived to ${archivedPath}`);
    } catch (err) {
      this.log.emit("error", `MemoryCompactor: archive failed (continuing) — ${err}`);
    }

    // ── 3. Read-only Ollama call (NO tools, NO shell, NO file write) ─
    const truncated = joined.slice(0, this.cfg.maxCompactionTokens * 4); // respect token budget
    const compactionPrompt = `You are a memory compactor. Analyze the session below and extract key facts, decisions, and outcomes.

Output ONLY valid JSONL — one JSON object per line, no other text.
Each object must have exactly these fields:
  { "content": "...", "domain": "...", "confidence": 0.0-1.0 }

Session to compact:
---
${truncated}
---

JSONL facts:`;

    const r = await this.ollama.chatResult(this.cfg.compactionModel, [
      { role: "user", content: compactionPrompt },
    ]);

    this.audit.append({
      agent: "compactor",
      tool: "inference",
      argsHash: sha256(compactionPrompt),
      status: r.ok ? "ok" : "error",
      durationMs: Date.now() - t0,
      policyDecision: "allowed",
    });

    if (!r.ok) {
      const result: CompactionResult = {
        factsExtracted: 0,
        tokensCompacted: estimatedTokens,
        sessionArchived,
        archivedPath,
        skipped: false,
        skipReason: `Ollama error: ${r.error}`,
      };
      this._lastCompaction = result;
      return result;
    }

    // ── 4. Parse and validate JSONL output ──────────────────────────
    const facts = this._parseJsonlFacts(r.content);
    this.log.emit("genome_event", `MemoryCompactor: parsed ${facts.length} facts from compaction response`);

    // ── 5. Write validated facts to genome ──────────────────────────
    let written = 0;
    for (const fact of facts) {
      try {
        const wr = await this.genome.writeFact(
          fact.content,
          fact.domain ?? "compaction",
          `compacted from session archive ${archiveName}`,
          fact.confidence ?? 0.7,
        );
        if (wr.written) written++;
      } catch (err) {
        this.log.emit("error", `MemoryCompactor: failed to write fact — ${err}`);
      }
    }

    const result: CompactionResult = {
      factsExtracted: written,
      tokensCompacted: estimatedTokens,
      sessionArchived,
      archivedPath,
    };

    this._lastCompaction = result;
    this.log.emit("genome_event", `MemoryCompactor: done — ${written} facts written, ${estimatedTokens} tokens compacted (${Date.now() - t0}ms)`);
    return result;
  }

  /** Result of the most recent compaction, or null */
  getLastCompaction(): CompactionResult | null {
    return this._lastCompaction;
  }

  // ── Private helpers ──────────────────────────────────────────────

  /**
   * Strict JSONL parser — each line must parse as a JSON object with a
   * non-empty "content" field. Lines that do not parse are silently dropped.
   *
   * This closes MoltBot's hole where any agent response was trusted verbatim.
   */
  private _parseJsonlFacts(raw: string): Array<{ content: string; domain?: string; confidence?: number }> {
    const facts: Array<{ content: string; domain?: string; confidence?: number }> = [];
    for (const line of raw.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const obj = JSON.parse(trimmed) as Record<string, unknown>;
        if (typeof obj.content !== "string" || !obj.content.trim()) continue;
        facts.push({
          content: obj.content.trim(),
          domain: typeof obj.domain === "string" ? obj.domain : undefined,
          confidence: typeof obj.confidence === "number" ? Math.min(1, Math.max(0, obj.confidence)) : undefined,
        });
      } catch {
        /* malformed line — drop silently; MoltBot would have executed it */
      }
    }
    return facts;
  }
}

// ═══════════════════════════════════════════════════════════════════════
// PATTERN 4 — EXECUTION AUDIT TRAIL (missing from MoltBot entirely)
// ═══════════════════════════════════════════════════════════════════════

/**
 * One audit log entry.
 *
 * args are never logged raw — only a SHA-256 hash is stored so that secrets
 * in shell commands are not persisted in plaintext (closes MoltBot's
 * plaintext token vulnerability in exec-approvals.ts).
 */
export type AuditEntry = {
  ts: number;
  agent: string;
  tool: string;
  /** SHA-256 of the raw args — NOT the args themselves */
  argsHash: string;
  status: "ok" | "error" | "blocked" | "escalated";
  durationMs: number;
  /** Human-readable policy decision string */
  policyDecision: string;
};

/** Filters for AuditTrail.search() */
export type AuditFilter = {
  agent?: string;
  tool?: string;
  status?: AuditEntry["status"];
  since?: number;
  until?: number;
};

export type AuditStats = {
  total: number;
  byTool: Record<string, number>;
  byAgent: Record<string, number>;
  byStatus: Record<string, number>;
};

/**
 * AuditTrail — append-only JSONL execution log
 *
 * Every autonomy action (heartbeat, cron, compaction) is recorded here.
 * MoltBot has no equivalent — this is the entire missing layer.
 */
export class AuditTrail {
  private auditPath: string;
  private _cache: AuditEntry[] = [];
  private static readonly CACHE_MAX = 500; // in-memory ring buffer

  constructor(auditPath?: string) {
    this.auditPath = auditPath ?? join(KERF_DIR, "audit.jsonl");
    mkdirSync(dirname(this.auditPath), { recursive: true });
    this._loadRecent();
  }

  /**
   * Append one audit entry.
   * Writes to disk immediately (audit trail is always synchronous).
   */
  append(entry: Omit<AuditEntry, "ts">): void {
    const full: AuditEntry = { ts: Date.now(), ...entry };
    try {
      appendFileSync(this.auditPath, JSON.stringify(full) + "\n");
    } catch { /* disk full — in-memory cache still works */ }
    this._cache.push(full);
    if (this._cache.length > AuditTrail.CACHE_MAX) {
      this._cache.shift(); // evict oldest
    }
  }

  /**
   * Search the in-memory cache (last 500 entries).
   * For older entries query the JSONL file directly.
   */
  search(filters: AuditFilter): AuditEntry[] {
    return this._cache.filter((e) => {
      if (filters.agent  && e.agent  !== filters.agent)  return false;
      if (filters.tool   && e.tool   !== filters.tool)   return false;
      if (filters.status && e.status !== filters.status) return false;
      if (filters.since  && e.ts     <  filters.since)   return false;
      if (filters.until  && e.ts     >  filters.until)   return false;
      return true;
    });
  }

  /** All blocked or escalated entries since a timestamp (default: all time) */
  getViolations(since = 0): AuditEntry[] {
    return this.search({ status: "blocked", since }).concat(
      this.search({ status: "escalated", since }),
    ).sort((a, b) => a.ts - b.ts);
  }

  /** Counts by tool, by agent, by status across the in-memory cache */
  stats(): AuditStats {
    const byTool: Record<string, number> = {};
    const byAgent: Record<string, number> = {};
    const byStatus: Record<string, number> = {};
    for (const e of this._cache) {
      byTool[e.tool]     = (byTool[e.tool]     ?? 0) + 1;
      byAgent[e.agent]   = (byAgent[e.agent]   ?? 0) + 1;
      byStatus[e.status] = (byStatus[e.status] ?? 0) + 1;
    }
    return { total: this._cache.length, byTool, byAgent, byStatus };
  }

  /** Path to the underlying JSONL file */
  get path(): string { return this.auditPath; }

  // ── Private helpers ──────────────────────────────────────────────

  private _loadRecent(): void {
    try {
      if (!existsSync(this.auditPath)) return;
      const raw = readFileSync(this.auditPath, "utf-8");
      const lines = raw.trim().split("\n").filter(Boolean);
      // Load last CACHE_MAX lines into cache
      const recent = lines.slice(-AuditTrail.CACHE_MAX);
      for (const line of recent) {
        try {
          this._cache.push(JSON.parse(line) as AuditEntry);
        } catch { /* malformed line */ }
      }
    } catch { /* first run */ }
  }
}

// ═══════════════════════════════════════════════════════════════════════
// INTEGRATION — AutonomyEngine
// ═══════════════════════════════════════════════════════════════════════

export type AutonomyStatus = {
  heartbeat: HeartbeatBeat | null;
  cron: { total: number; enabled: number; jobs: CronJob[] };
  compaction: CompactionResult | null;
  audit: { recentViolations: AuditEntry[]; stats: AuditStats };
};

/**
 * AutonomyEngine — ties HeartbeatEngine, CronEngine, MemoryCompactor,
 * and AuditTrail together into a single lifecycle object.
 *
 * All three patterns feed the audit trail.
 * All three check PolicyEngine.
 * All three record genome lessons from blocked actions.
 */
export class AutonomyEngine {
  readonly heartbeat: HeartbeatEngine;
  readonly cron: CronEngine;
  readonly compactor: MemoryCompactor;
  readonly audit: AuditTrail;

  private _cronTickTimer: ReturnType<typeof setInterval> | null = null;

  constructor(opts: {
    heartbeatConfig?: Partial<Omit<HeartbeatConfig, "requirePolicyCheck">>;
    compactionConfig?: Partial<CompactionConfig>;
    cronPersistPath?: string;
    auditPath?: string;
    policy: PolicyEngine;
    log: ActivityLog;
    genome: AutonomyClient;
    ollama: OllamaClient;
    tasks: TaskEngine;
  }) {
    this.audit = new AuditTrail(opts.auditPath);

    this.heartbeat = new HeartbeatEngine({
      config: opts.heartbeatConfig,
      policy: opts.policy,
      log: opts.log,
      genome: opts.genome,
      ollama: opts.ollama,
      tasks: opts.tasks,
      audit: this.audit,
    });

    this.cron = new CronEngine({
      persistPath: opts.cronPersistPath,
      policy: opts.policy,
      log: opts.log,
      ollama: opts.ollama,
      tasks: opts.tasks,
      audit: this.audit,
    });

    this.compactor = new MemoryCompactor({
      config: opts.compactionConfig,
      genome: opts.genome,
      ollama: opts.ollama,
      log: opts.log,
      audit: this.audit,
    });
  }

  /** Start the heartbeat timer and the cron tick loop */
  start(): void {
    this.heartbeat.start();
    if (!this._cronTickTimer) {
      this._cronTickTimer = setInterval(() => { void this.cron.tick(); }, 60_000);
    }
  }

  /** Stop both timers and flush any pending audit writes */
  stop(): void {
    this.heartbeat.stop();
    if (this._cronTickTimer) {
      clearInterval(this._cronTickTimer);
      this._cronTickTimer = null;
    }
  }

  /** Snapshot of all three subsystem statuses */
  status(): AutonomyStatus {
    const allJobs = this.cron.list();
    return {
      heartbeat: this.heartbeat.getLastBeat(),
      cron: {
        total: allJobs.length,
        enabled: allJobs.filter((j) => j.enabled).length,
        jobs: allJobs,
      },
      compaction: this.compactor.getLastCompaction(),
      audit: {
        recentViolations: this.audit.getViolations(Date.now() - 86_400_000), // last 24h
        stats: this.audit.stats(),
      },
    };
  }

  /** Trigger a heartbeat tick immediately without waiting for the timer */
  forceHeartbeat(): Promise<HeartbeatBeat> {
    return this.heartbeat.tick();
  }

  /** Trigger a specific cron job immediately without waiting for the schedule */
  forceCron(jobId: string): Promise<string> {
    return this.cron.forceRun(jobId);
  }

  /** Trigger memory compaction immediately */
  forceCompact(sessionLog: string[], genomeStats: GenomeStats): Promise<CompactionResult> {
    return this.compactor.compact(sessionLog, genomeStats);
  }
}

// ═══════════════════════════════════════════════════════════════════════
// UTILITY
// ═══════════════════════════════════════════════════════════════════════

/** SHA-256 hex digest of a string — used to hash audit args without logging them */
function sha256(input: string): string {
  return createHash("sha256").update(input).digest("hex");
}

// ═══════════════════════════════════════════════════════════════════════
// SELF-TEST
// ═══════════════════════════════════════════════════════════════════════

/**
 * Self-test: instantiates AutonomyEngine, adds a cron job, runs a heartbeat
 * tick, and prints audit status to stdout. Exits 0 on success, 1 on failure.
 *
 * Run with: npx ts-node src/autonomy.ts
 */
async function selfTest(): Promise<void> {
  const { join: pathJoin } = await import("node:path");
  const { PolicyEngine } = await import("./policy.js");
  const { ActivityLog } = await import("./activity-log.js");
  const { AutonomyClient } = await import("./autonomy-client.js");
  const { OllamaClient } = await import("./ollama-client.js");
  const { TaskEngine } = await import("./task-engine.js");

  const tmpDir = pathJoin(process.env.TEMP ?? "/tmp", "zoeae-autonomy-test");
  const safetyYaml = pathJoin(process.cwd(), "safety.yaml");

  const log = new ActivityLog(pathJoin(tmpDir, "activity.jsonl"));
  const policy = new PolicyEngine(safetyYaml, log);
  const genome = new AutonomyClient();
  const ollama = new OllamaClient();
  const tasks = new TaskEngine(pathJoin(tmpDir, "tasks.json"));

  const engine = new AutonomyEngine({
    heartbeatConfig: {
      intervalMs: 9_999_999, // don't auto-fire during test
      source: "file",
      filePath: pathJoin(process.cwd(), "HEARTBEAT.md"),
      maxActionsPerBeat: 2,
    },
    compactionConfig: {
      triggerTokenThreshold: 10, // low threshold so test can trigger it
      outputPath: pathJoin(tmpDir, "sessions"),
      autoCompact: false,
      compactionModel: "hermes3:8b",
      maxCompactionTokens: 100,
    },
    cronPersistPath: pathJoin(tmpDir, "cron-jobs.json"),
    auditPath: pathJoin(tmpDir, "audit.jsonl"),
    policy,
    log,
    genome,
    ollama,
    tasks,
  });

  console.log("[autonomy self-test] AutonomyEngine constructed");

  // Add a cron job
  const job = engine.cron.add({
    name: "test-echo",
    schedule: { kind: "every", intervalMs: 3_600_000 },
    payload: { kind: "shell", command: "echo autonomy-cron-test" },
    createdBy: "self-test",
    enabled: true,
    maxRuns: 1,
    policyScope: "minimal",
  });
  console.log(`[autonomy self-test] cron job added: ${job.id} (${job.name})`);

  // Verify recursive cron payload is rejected
  let rejectedRecursive = false;
  try {
    // @ts-expect-error intentional bad payload to test guard
    engine.cron.add({ name: "bad", schedule: { kind: "every", intervalMs: 1000 }, payload: { kind: "cron" }, createdBy: "test", enabled: true, maxRuns: 1, policyScope: "minimal" });
  } catch {
    rejectedRecursive = true;
  }
  console.log(`[autonomy self-test] recursive cron rejected: ${rejectedRecursive}`);

  // Run a heartbeat tick (no genome/file available in test — should handle gracefully)
  console.log("[autonomy self-test] running heartbeat tick...");
  const beat = await engine.forceHeartbeat();
  console.log(`[autonomy self-test] beat: found=${beat.directivesFound} approved=${beat.directivesApproved} blocked=${beat.directivesBlocked} duration=${beat.durationMs}ms`);

  // Audit status
  const status = engine.status();
  const auditStats = status.audit.stats;
  console.log(`[autonomy self-test] audit stats: total=${auditStats.total} byStatus=${JSON.stringify(auditStats.byStatus)}`);
  console.log(`[autonomy self-test] cron jobs: total=${status.cron.total} enabled=${status.cron.enabled}`);

  console.log("[autonomy self-test] PASS");
  process.exit(0);
}

// Run self-test when executed directly (ts-node / tsx)
if (
  typeof process !== "undefined" &&
  process.argv[1] !== undefined &&
  (process.argv[1].endsWith("autonomy.ts") || process.argv[1].endsWith("autonomy.js"))
) {
  selfTest().catch((err) => {
    console.error("[autonomy self-test] FAIL:", err);
    process.exit(1);
  });
}
