/**
 * Autonomous Daemon — Background loop that runs between conversations
 *
 * Patterns pulled from:
 *   OpenClaw daemon            — self-healing automation loop
 *   OpenClaw autonomy          — agent spawning + task processing
 *   DDL_AUTORESEARCH_SPEC.md  — overnight experiment pattern
 *
 * Processes task queue, monitors service health, auto-restarts,
 * consolidates genome. The thing that makes it autonomous.
 *
 * AnnulusLabs LLC
 */

import { TaskEngine } from "./task-engine.js";
import { checkAllServices, restartService } from "./services.js";
import { shellExec } from "./executor.js";
import { OllamaClient } from "./ollama-client.js";
import { AutonomyClient } from "./autonomy-client.js";
import { ActivityLog } from "./activity-log.js";
import { join } from "node:path";

export type DaemonConfig = {
  enabled: boolean;
  intervalMs: number;
  taskProcessing: boolean;
  healthMonitoring: boolean;
  autoRestart: boolean;
  maxTasksPerTick: number;
  consolidateEveryNTicks: number;
  ollamaUrl: string;
  defaultModel: string;
};

const DEFAULTS: DaemonConfig = {
  enabled: false,
  intervalMs: 300_000,       // 5 minutes
  taskProcessing: true,
  healthMonitoring: true,
  autoRestart: true,
  maxTasksPerTick: 3,
  consolidateEveryNTicks: 6, // every 30 min
  ollamaUrl: "http://127.0.0.1:11434",
  defaultModel: "hermes3:8b",
};

export class Daemon {
  private timer: ReturnType<typeof setInterval> | null = null;
  private cfg: DaemonConfig;
  private tasks: TaskEngine;
  private ollama: OllamaClient;
  private autonomy: AutonomyClient;
  private log: ActivityLog;
  private running = false;
  private tickCount = 0;
  private _lastMessageAt = 0;       // Upgrade #4: idle tracking
  private _deepConsolidated = false; // Upgrade #4: once per idle period

  constructor(
    tasks: TaskEngine,
    autonomy: AutonomyClient,
    log: ActivityLog,
    config?: Partial<DaemonConfig>,
  ) {
    this.cfg = { ...DEFAULTS, ...config };
    this.tasks = tasks;
    this.autonomy = autonomy;
    this.log = log;
    this.ollama = new OllamaClient(this.cfg.ollamaUrl, 120_000);
  }

  start(): boolean {
    if (this.running) return false;
    this.running = true;
    this.tickCount = 0;
    this.log.emit("daemon_tick", "daemon started", { meta: { intervalMs: this.cfg.intervalMs } });
    this.timer = setInterval(() => {
      this.tick().catch((e) => this.log.emit("error", `daemon tick failed: ${e}`));
    }, this.cfg.intervalMs);
    return true;
  }

  stop(): boolean {
    if (!this.running) return false;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.running = false;
    this.log.emit("daemon_tick", "daemon stopped");
    return true;
  }

  isRunning(): boolean { return this.running; }

  /** Upgrade #4: Call from message:received hook to track activity */
  touchActivity(): void {
    this._lastMessageAt = Date.now();
    this._deepConsolidated = false; // new activity resets deep consolidation
  }

  /** Upgrade #4: Idle time in ms since last message */
  idleMs(): number {
    return this._lastMessageAt > 0 ? Date.now() - this._lastMessageAt : Infinity;
  }

  /** Run one tick manually (also called by timer) */
  async tick(): Promise<{ health: number; tasksProcessed: number; consolidated: boolean }> {
    this.tickCount++;
    this.log.emit("daemon_tick", `tick #${this.tickCount} start`);
    let healthUp = 0;
    let tasksProcessed = 0;
    let consolidated = false;

    // ── Health monitoring ────────────────────────────────
    if (this.cfg.healthMonitoring) {
      const statuses = await checkAllServices();
      for (const s of statuses) {
        if (s.healthy) {
          healthUp++;
        } else {
          this.log.emit("service_check", `${s.name} DOWN: ${s.error?.slice(0, 100)}`);
          if (this.cfg.autoRestart) {
            await restartService(s.name, this.log);
          }
        }
      }
    }

    // ── Task processing ──────────────────────────────────
    if (this.cfg.taskProcessing) {
      let processed = 0;
      while (processed < this.cfg.maxTasksPerTick) {
        const task = this.tasks.next();
        if (!task) break;
        this.tasks.start(task.id);
        this.log.emit("task_event", `processing: ${task.name} (${task.taskType})`);

        try {
          let result: string;

          if (task.taskType === "shell" && task.command) {
            const exec = await shellExec(task.command, { timeoutMs: 60_000, log: this.log });
            result = exec.exitCode === 0
              ? exec.stdout || "OK"
              : `EXIT ${exec.exitCode}: ${exec.stderr}`;
            if (exec.exitCode !== 0 && !exec.timedOut) {
              this.tasks.fail(task.id, result);
              processed++;
              continue;
            }

          } else if (task.taskType === "prompt" || task.taskType === "research") {
            const systemPrompt = task.taskType === "research"
              ? "You are a research assistant. Be thorough. Cite sources when possible."
              : "You are a helpful assistant. Be concise and actionable.";
            result = await this.ollama.chat(task.model ?? this.cfg.defaultModel, [
              { role: "system", content: systemPrompt },
              { role: "user", content: task.description },
            ]);

          } else if (task.taskType === "delegate") {
            // Multi-model: get consensus from 2 models
            const models = [this.cfg.defaultModel, "mistral:latest"];
            const responses = await Promise.all(
              models.map((m) => this.ollama.chat(m, [
                { role: "user", content: task.description },
              ])),
            );
            result = responses.map((r, i) => `[${models[i]}]: ${r}`).join("\n\n");

          } else {
            this.tasks.block(task.id, "Requires manual execution or unsupported task type");
            processed++;
            continue;
          }

          this.tasks.complete(task.id, result);
          this.log.emit("task_event", `completed: ${task.name}`);

          // Upgrade #1: Feed task outcome into genome as because-chain
          try {
            if (await this.autonomy.ping()) {
              await this.autonomy.record("system",
                `[TASK_RESULT:${task.id}] ${task.name} completed: ${result.slice(0, 500)} ∵ executed via ${task.taskType} on ${task.model ?? "shell"}`,
              );
            }
          } catch { /* genome recording is best-effort */ }

        } catch (err) {
          this.tasks.fail(task.id, String(err));
          this.log.emit("task_event", `failed: ${task.name}: ${err}`);

          // Upgrade #1: Feed failure into genome so it doesn't repeat
          try {
            if (await this.autonomy.ping()) {
              await this.autonomy.record("system",
                `[TASK_FAILURE:${task.id}] ${task.name} failed: ${String(err).slice(0, 500)} ∵ ${task.retryCount}/${task.maxRetries} retries exhausted`,
              );
            }
          } catch { /* genome recording is best-effort */ }
        }
        processed++;
      }
      tasksProcessed = processed;
    }

    // ── Genome consolidation ────────────────────────────
    // Upgrade #4: Sleep-time deep consolidation when idle > 5 min
    const IDLE_THRESHOLD_MS = 300_000; // 5 minutes
    const isIdle = this.idleMs() > IDLE_THRESHOLD_MS;

    if (isIdle && !this._deepConsolidated) {
      // Deep consolidation: topic-segmented, deduplication, contradiction resolution
      try {
        if (await this.autonomy.ping()) {
          await this.autonomy.consolidateDeep();
          consolidated = true;
          this._deepConsolidated = true;
          this.log.emit("genome_event", "deep sleep-time consolidation (idle >5min)");
        }
      } catch { /* silent */ }
    } else if (this.tickCount % this.cfg.consolidateEveryNTicks === 0) {
      // Standard periodic consolidation
      try {
        if (await this.autonomy.ping()) {
          await this.autonomy.consolidate(true);
          consolidated = true;
          this.log.emit("genome_event", "genome consolidated (daemon periodic)");
        }
      } catch { /* silent */ }
    }

    this.log.emit("daemon_tick", `tick #${this.tickCount} done: ${healthUp} healthy, ${tasksProcessed} tasks${consolidated ? ", consolidated" : ""}`);
    return { health: healthUp, tasksProcessed, consolidated };
  }

  status(): { running: boolean; tickCount: number; config: DaemonConfig } {
    return { running: this.running, tickCount: this.tickCount, config: this.cfg };
  }
}
