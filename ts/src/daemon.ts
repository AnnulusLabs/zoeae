/**
 * Autonomous Daemon — Background loop that runs between conversations
 *
 * Phase 1: validate → reformulate → retry (single replan max)
 * Phase 2: room-backed validation, genome-informed reformulation
 * Phase 3: executeGoal() with StepContext, plan-aware validation,
 *          adaptive thresholds, compression pipeline
 *
 * Safeguards: tick mutex, exit-code-is-truth, command denylist,
 *             Ollama call cap, replan depth limit, step cap.
 *
 * AnnulusLabs LLC
 */

import { TaskEngine, type Task } from "./task-engine.js";
import { Planner, type Plan, type PlanStep } from "./planner.js";
import { checkAllServices, restartService } from "./services.js";
import { shellExec } from "./executor.js";
import { OllamaClient, type ChatResult } from "./ollama-client.js";
import { AutonomyClient } from "./autonomy-client.js";
import { ActivityLog } from "./activity-log.js";
import { DreamEngine, type DreamConfig } from "./dream-engine.js";
import { PolicyEngine, type ExecutionContext, type EscalationLevel } from "./policy.js";
import { join } from "node:path";

// ═══════════════════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════════════════

/** Metabolic tier — maps power state to daemon behavior */
export type MetabolicTier = "thriving" | "active" | "conserving" | "encysted";

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
  evalModel: string;
  maxOllamaCallsPerTick: number;
  tickTimeBudgetMs: number;
  // Phase 2
  roomValidationModels: string[];
  roomValidationThreshold: number;   // 0-1, fraction of models that must pass
  genomeSearchOnReplan: boolean;
  // Phase 3
  maxGoalSteps: number;
  maxGoalReplans: number;
  adaptiveThresholds: boolean;
};

const DEFAULTS: DaemonConfig = {
  enabled: false,
  intervalMs: 300_000,
  taskProcessing: true,
  healthMonitoring: true,
  autoRestart: true,
  maxTasksPerTick: 3,
  consolidateEveryNTicks: 6,
  ollamaUrl: "http://127.0.0.1:11434",
  defaultModel: "hermes3:8b",
  evalModel: "phi4-mini-reasoning",
  maxOllamaCallsPerTick: 10,
  tickTimeBudgetMs: 120_000,
  // Phase 2
  roomValidationModels: ["hermes3:8b", "mistral:latest", "phi4-mini-reasoning"],
  roomValidationThreshold: 0.6,
  genomeSearchOnReplan: true,
  // Phase 3
  maxGoalSteps: 20,
  maxGoalReplans: 2,
  adaptiveThresholds: true,
};

// ═══════════════════════════════════════════════════════════════════════
// SAFEGUARDS — enforced by PolicyEngine (loaded from safety.yaml)
// ═══════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════

type ValidationResult = {
  pass: boolean;
  confidence: number;
  critique: string;
  suggestion: string;
};

/** Phase 3: Compressed state carried through multi-step goal execution */
type StepContext = {
  goalId: string;
  goal: string;
  planId: string;
  stepIndex: number;
  totalSteps: number;
  completedSteps: string[];       // compressed: "step N: outcome (Xms)"
  failedSteps: string[];          // compressed: "step N: reason"
  cumulativeMetrics: Record<string, number>;  // running tallies
  genomeFacts: string[];          // relevant facts pulled at goal start
  adaptedThreshold: number;       // validation threshold, adjusted per-step
};

/** Phase 3: Goal execution result */
export type GoalResult = {
  goalId: string;
  goal: string;
  planId: string;
  status: "completed" | "partial" | "failed" | "aborted";
  stepsCompleted: number;
  stepsTotal: number;
  replans: number;
  results: Array<{ step: string; status: string; result: string }>;
  durationMs: number;
};

// ═══════════════════════════════════════════════════════════════════════
// DAEMON
// ═══════════════════════════════════════════════════════════════════════

export class Daemon {
  private timer: ReturnType<typeof setInterval> | null = null;
  private cfg: DaemonConfig;
  private tasks: TaskEngine;
  private planner: Planner | null = null;
  private dreamer: DreamEngine | null = null;
  private ollama: OllamaClient;
  private autonomy: AutonomyClient;
  private log: ActivityLog;
  private policy: PolicyEngine;
  private running = false;
  private tickCount = 0;
  private _lastMessageAt = 0;
  private _deepConsolidated = false;
  private _ticking = false;
  private _ollamaCallsThisTick = 0;
  private _replanCounts = new Map<string, number>(); // task ID → replan count
  // Phase 3: genome-learned validation stats
  private _validationStats = { passed: 0, failed: 0, avgConfidence: 0.7 };
  // Metabolic awareness — energy-gated behavior
  private _metabolicTier: MetabolicTier = "active";
  private _powerLevel = 1.0; // 0.0-1.0, externally set

  constructor(
    tasks: TaskEngine,
    autonomy: AutonomyClient,
    log: ActivityLog,
    config?: Partial<DaemonConfig>,
    policy?: PolicyEngine,
  ) {
    this.cfg = { ...DEFAULTS, ...config };
    this.tasks = tasks;
    this.autonomy = autonomy;
    this.log = log;
    this.ollama = new OllamaClient(this.cfg.ollamaUrl, 120_000);

    // Load policy — override budgets from safety.yaml
    if (policy) {
      this.policy = policy;
    } else {
      const pluginDir = join(process.env.HOME ?? process.env.USERPROFILE ?? ".", ".openclaw", "extensions", "zoeae");
      this.policy = new PolicyEngine(join(pluginDir, "safety.yaml"), log);
    }
    const budgets = this.policy.getBudgets();
    this.cfg.maxOllamaCallsPerTick = config?.maxOllamaCallsPerTick ?? budgets.maxOllamaCallsPerTick;
    this.cfg.tickTimeBudgetMs = config?.tickTimeBudgetMs ?? budgets.tickTimeBudgetMs;
    this.cfg.maxGoalSteps = config?.maxGoalSteps ?? budgets.maxGoalSteps;
    this.cfg.maxGoalReplans = config?.maxGoalReplans ?? budgets.maxGoalReplans;
    this.cfg.roomValidationThreshold = config?.roomValidationThreshold ?? budgets.roomValidationThreshold;
  }

  getPolicy(): PolicyEngine { return this.policy; }

  // ═══════════════════════════════════════════════════════════════════
  // METABOLIC AWARENESS — energy-gated behavior tiers
  // ═══════════════════════════════════════════════════════════════════
  //
  // Thriving  (>0.75): full daemon, dreams active, all task priorities, room validation
  // Active   (0.40-0.75): normal daemon, dreams paused, P1-P3 tasks only
  // Conserving (0.15-0.40): slow ticks, no dreams, P1-P2 only, no room validation
  // Encysted  (<0.15): serialize state, stop daemon, hibernate until power recovers

  setPowerLevel(level: number): MetabolicTier {
    this._powerLevel = Math.min(1, Math.max(0, level));
    const prev = this._metabolicTier;

    if (this._powerLevel > 0.75) {
      this._metabolicTier = "thriving";
    } else if (this._powerLevel > 0.40) {
      this._metabolicTier = "active";
    } else if (this._powerLevel > 0.15) {
      this._metabolicTier = "conserving";
    } else {
      this._metabolicTier = "encysted";
    }

    if (this._metabolicTier !== prev) {
      this.log.emit("metabolic", `tier change: ${prev} → ${this._metabolicTier} (power=${(this._powerLevel * 100).toFixed(0)}%)`);

      // Encyst: stop everything, serialize state
      if (this._metabolicTier === "encysted" && this.running) {
        this.log.emit("metabolic", "encysting: serializing state and hibernating");
        if (this.dreamer) this.dreamer.stop();
        this.stop();
      }

      // Wake from encystment
      if (prev === "encysted" && this._metabolicTier !== "encysted" && !this.running) {
        this.log.emit("metabolic", "waking from encystment");
        this.start();
      }

      // Dream control
      if (this.dreamer) {
        if (this._metabolicTier === "thriving" && !this.dreamer.isRunning()) {
          this.dreamer.start();
          this.log.emit("metabolic", "dreams resumed (thriving)");
        } else if (this._metabolicTier !== "thriving" && this.dreamer.isRunning()) {
          this.dreamer.stop();
          this.log.emit("metabolic", "dreams paused (conserving energy)");
        }
      }
    }

    return this._metabolicTier;
  }

  getPowerLevel(): number { return this._powerLevel; }
  getMetabolicTier(): MetabolicTier { return this._metabolicTier; }

  /** Get effective config modulated by metabolic tier */
  private metabolicTasksPerTick(): number {
    switch (this._metabolicTier) {
      case "thriving": return this.cfg.maxTasksPerTick;
      case "active": return Math.min(this.cfg.maxTasksPerTick, 2);
      case "conserving": return 1;
      case "encysted": return 0;
    }
  }

  /** Get max task priority allowed in current tier (lower = higher priority) */
  private metabolicMaxPriority(): number {
    switch (this._metabolicTier) {
      case "thriving": return 5;  // all priorities
      case "active": return 3;    // P1-P3 only
      case "conserving": return 2; // P1-P2 only
      case "encysted": return 0;  // nothing
    }
  }

  /** Whether room validation is allowed in current tier */
  private metabolicAllowRoom(): boolean {
    return this._metabolicTier === "thriving";
  }

  /** Inject planner for Phase 3 goal execution */
  setPlanner(planner: Planner): void {
    this.planner = planner;
  }

  /** Initialize and start dream engine */
  enableDreaming(config?: Partial<DreamConfig>): DreamEngine {
    if (!this.dreamer) {
      this.dreamer = new DreamEngine(
        this.ollama, this.log,
        () => this.idleMs(),
        {
          resourceGated: true,
          onPromote: (dream, actionPlan) => {
            const domains = dream.facts.map((f) => f.domain).join(" ↔ ");
            this.tasks.add({
              name: `[dream] ${domains}: ${dream.bridge.slice(0, 50)}`,
              description: `Dream bridge (q=${dream.quality.toFixed(2)}):\n${dream.bridge}\n\nAction plan:\n${actionPlan}`,
              taskType: "research",
              priority: 3,
              tags: ["dream", "promoted", ...dream.facts.map((f) => f.domain)],
            });
            this.log.emit("genome_event", `dream → task: [${domains}] ${actionPlan.slice(0, 80)}`);
          },
          ...config,
        },
      );
    }
    this.dreamer.start();
    return this.dreamer;
  }

  getDreamer(): DreamEngine | null { return this.dreamer; }

  start(): boolean {
    if (this.running) return false;
    this.running = true;
    this.tickCount = 0;
    this.log.emit("daemon_tick", "daemon started", { meta: { intervalMs: this.cfg.intervalMs } });
    this.timer = setInterval(() => {
      this.tick().catch((e) => this.log.emit("error", `daemon tick failed: ${e}`));
    }, this.cfg.intervalMs);
    // Auto-enable dreaming — the organism dreams when idle
    if (!this.dreamer) {
      this.enableDreaming();
      this.log.emit("info", "dream engine auto-enabled on daemon start");
    }
    return true;
  }

  stop(): boolean {
    if (!this.running) return false;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.running = false;
    if (this.dreamer) this.dreamer.stop();
    this.log.emit("daemon_tick", "daemon stopped");
    return true;
  }

  isRunning(): boolean { return this.running; }

  touchActivity(): void {
    this._lastMessageAt = Date.now();
    this._deepConsolidated = false;
  }

  idleMs(): number {
    return this._lastMessageAt > 0 ? Date.now() - this._lastMessageAt : Infinity;
  }

  // ═══════════════════════════════════════════════════════════════════
  // GUARDED OLLAMA
  // ═══════════════════════════════════════════════════════════════════

  private async guardedChat(model: string, messages: Array<{ role: "system" | "user" | "assistant"; content: string }>): Promise<ChatResult> {
    if (this._ollamaCallsThisTick >= this.cfg.maxOllamaCallsPerTick) {
      return { ok: false, content: "", error: "Ollama call cap reached for this tick" };
    }

    // Policy: check model allowlist
    const modelVerdict = this.policy.checkModel(model);
    if (!modelVerdict.allowed) {
      this.log.emit("policy_violation", `Model blocked: ${modelVerdict.reason}`);
      return { ok: false, content: "", error: `POLICY: ${modelVerdict.reason}` };
    }

    // Policy: check session inference budget
    const budgetVerdict = this.policy.checkInferenceBudget();
    if (!budgetVerdict.allowed) {
      this.log.emit("policy_violation", `Inference budget: ${budgetVerdict.reason}`);
      return { ok: false, content: "", error: `POLICY: ${budgetVerdict.reason}` };
    }

    this._ollamaCallsThisTick++;
    return this.ollama.chatResult(model, messages);
  }

  // ═══════════════════════════════════════════════════════════════════
  // PHASE 1: VALIDATION GATE
  // ═══════════════════════════════════════════════════════════════════

  private async validateResult(task: Task, result: string, exitCode?: number): Promise<ValidationResult> {
    if (task.taskType === "shell" && exitCode === 0) {
      const evalResult = await this.guardedChat(this.cfg.evalModel, [
        { role: "system", content: 'You evaluate task results. Output ONLY valid JSON: {"confidence":0.0-1.0,"critique":"...","suggestion":"..."}' },
        { role: "user", content: `Task: ${task.name}\nDescription: ${task.description.slice(0, 500)}\nResult (exit 0):\n${result.slice(0, 1000)}` },
      ]);
      if (evalResult.ok) {
        try {
          const parsed = JSON.parse(evalResult.content.match(/\{[\s\S]*\}/)?.[0] ?? "{}");
          return { pass: true, confidence: parsed.confidence ?? 1.0, critique: parsed.critique ?? "", suggestion: parsed.suggestion ?? "" };
        } catch { /* parse fail, still pass */ }
      }
      return { pass: true, confidence: 1.0, critique: "", suggestion: "" };
    }

    const evalResult = await this.guardedChat(this.cfg.evalModel, [
      { role: "system", content: 'You evaluate whether a task completed successfully. Output ONLY valid JSON: {"pass":true/false,"confidence":0.0-1.0,"critique":"one sentence","suggestion":"how to fix if failed"}' },
      { role: "user", content: `Task: ${task.name}\nType: ${task.taskType}\nDescription: ${task.description.slice(0, 500)}\nResult:\n${result.slice(0, 1000)}` },
    ]);

    if (!evalResult.ok) {
      this.log.emit("inner_loop", `eval failed for ${task.id}: ${evalResult.error}`);
      return { pass: true, confidence: 0.5, critique: "evaluation unavailable", suggestion: "" };
    }

    try {
      const parsed = JSON.parse(evalResult.content.match(/\{[\s\S]*\}/)?.[0] ?? "{}");
      const v: ValidationResult = {
        pass: Boolean(parsed.pass),
        confidence: Math.min(1, Math.max(0, Number(parsed.confidence) || 0.5)),
        critique: String(parsed.critique ?? "").slice(0, 300),
        suggestion: String(parsed.suggestion ?? "").slice(0, 300),
      };
      // Phase 3: Update adaptive stats
      this._validationStats[v.pass ? "passed" : "failed"]++;
      const total = this._validationStats.passed + this._validationStats.failed;
      this._validationStats.avgConfidence = (this._validationStats.avgConfidence * (total - 1) + v.confidence) / total;
      return v;
    } catch {
      this.log.emit("inner_loop", `eval parse failed for ${task.id}, passing through`);
      return { pass: true, confidence: 0.5, critique: "parse error", suggestion: "" };
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  // PHASE 2: ROOM-BACKED VALIDATION
  // ═══════════════════════════════════════════════════════════════════

  /** Multi-model adversarial validation for high-priority tasks */
  private async validateWithRoom(task: Task, result: string): Promise<ValidationResult> {
    const models = this.cfg.roomValidationModels;
    if (models.length < 2) return this.validateResult(task, result);

    this.log.emit("inner_room", `room validation for ${task.id}: ${models.length} models`);

    const prompt = `Task: ${task.name}\nDescription: ${task.description.slice(0, 400)}\nResult:\n${result.slice(0, 800)}\n\nDid this task succeed? Output ONLY valid JSON: {"pass":true/false,"confidence":0.0-1.0,"critique":"one sentence"}`;

    const responses = await Promise.all(
      models.map((m) => this.guardedChat(m, [
        { role: "system", content: "You are a critical evaluator. Judge whether a task result is correct and complete. Be harsh but fair." },
        { role: "user", content: prompt },
      ])),
    );

    let passes = 0;
    let totalConf = 0;
    const critiques: string[] = [];
    const suggestions: string[] = [];

    for (let i = 0; i < responses.length; i++) {
      const r = responses[i];
      if (!r.ok) continue;
      try {
        const parsed = JSON.parse(r.content.match(/\{[\s\S]*\}/)?.[0] ?? "{}");
        if (parsed.pass) passes++;
        totalConf += Number(parsed.confidence) || 0.5;
        if (parsed.critique) critiques.push(`[${models[i].split(":")[0]}] ${parsed.critique}`);
        if (parsed.suggestion) suggestions.push(String(parsed.suggestion));
      } catch { /* skip unparseable */ }
    }

    const validResponses = responses.filter((r) => r.ok).length || 1;
    const passRate = passes / validResponses;
    const pass = passRate >= this.cfg.roomValidationThreshold;
    const confidence = totalConf / validResponses;

    this.log.emit("inner_room", `${task.id} room verdict: ${passes}/${validResponses} pass (${(passRate * 100).toFixed(0)}%), conf=${confidence.toFixed(2)}`);

    return {
      pass,
      confidence,
      critique: critiques.join("; ").slice(0, 500),
      suggestion: suggestions[0]?.slice(0, 300) ?? "",
    };
  }

  // ═══════════════════════════════════════════════════════════════════
  // PHASE 2: GENOME-INFORMED REFORMULATION
  // ═══════════════════════════════════════════════════════════════════

  /** Search genome for past failures before reformulating */
  private async reformulateWithGenome(task: Task, critique: string, suggestion: string): Promise<string> {
    let genomeContext = "";

    if (this.cfg.genomeSearchOnReplan) {
      try {
        if (await this.autonomy.ping()) {
          const keywords = task.name.toLowerCase().split(/\s+/).slice(0, 3).join(" ");
          const { results } = await this.autonomy.searchFacts(`TASK_FAILURE ${keywords}`, 5);
          if (results && results.length > 0) {
            genomeContext = "\n\nPast failures (from genome):\n" +
              results.map((r) => `- ${r.content.slice(0, 150)}`).join("\n");
            this.log.emit("inner_genome", `found ${results.length} past failures for "${keywords}"`);
          }
        }
      } catch (e) { this.log.emit("error", `genome search failed: ${e}`); }
    }

    const r = await this.guardedChat(this.cfg.evalModel, [
      { role: "system", content: "Rewrite this task description to address the critique and avoid past mistakes. Output ONLY the improved task description." },
      { role: "user", content: `Original: ${task.description.slice(0, 500)}\nCritique: ${critique}\nSuggestion: ${suggestion}${genomeContext}\n\nImproved task description:` },
    ]);
    if (!r.ok || r.content.length < 10) {
      this.log.emit("inner_replan", `reformulation failed for ${task.id}, keeping original`);
      return task.description;
    }
    this.log.emit("inner_replan", `${task.id} reformulated${genomeContext ? " (genome-informed)" : ""}`);
    return r.content.slice(0, 2000);
  }

  // ═══════════════════════════════════════════════════════════════════
  // PHASE 3: PLAN-AWARE VALIDATION
  // ═══════════════════════════════════════════════════════════════════

  /** Validates whether a result advances the current plan step */
  private async validateForGoal(task: Task, result: string, ctx: StepContext, step: PlanStep): Promise<ValidationResult> {
    const compressed = this.compressContext(ctx);
    const r = await this.guardedChat(this.cfg.evalModel, [
      { role: "system", content: 'You evaluate whether a task result advances a specific plan step toward a larger goal. Output ONLY valid JSON: {"pass":true/false,"confidence":0.0-1.0,"critique":"one sentence","suggestion":"...","advances_goal":true/false}' },
      { role: "user", content: `Goal: ${ctx.goal}\nCurrent step: ${step.description}\nTask: ${task.name}\nResult:\n${result.slice(0, 600)}\n\nPrior progress:\n${compressed}` },
    ]);

    if (!r.ok) return { pass: true, confidence: 0.5, critique: "eval unavailable", suggestion: "" };

    try {
      const parsed = JSON.parse(r.content.match(/\{[\s\S]*\}/)?.[0] ?? "{}");
      return {
        pass: Boolean(parsed.pass && parsed.advances_goal !== false),
        confidence: Math.min(1, Math.max(0, Number(parsed.confidence) || 0.5)),
        critique: String(parsed.critique ?? "").slice(0, 300),
        suggestion: String(parsed.suggestion ?? "").slice(0, 300),
      };
    } catch {
      return { pass: true, confidence: 0.5, critique: "parse error", suggestion: "" };
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  // PHASE 3: ADAPTIVE THRESHOLDS
  // ═══════════════════════════════════════════════════════════════════

  /** Returns validation threshold adjusted by historical success rate */
  private adaptiveThreshold(): number {
    if (!this.cfg.adaptiveThresholds) return 0.5;
    const total = this._validationStats.passed + this._validationStats.failed;
    if (total < 10) return 0.5; // not enough data
    const successRate = this._validationStats.passed / total;
    // If most tasks pass, we can afford to be stricter
    // If most fail, loosen up to avoid blocking everything
    return Math.min(0.8, Math.max(0.3, successRate * 0.7 + 0.15));
  }

  // ═══════════════════════════════════════════════════════════════════
  // PHASE 3: CONTEXT COMPRESSION
  // ═══════════════════════════════════════════════════════════════════

  /** Compress StepContext into a string that fits in 4k model context */
  private compressContext(ctx: StepContext): string {
    const lines: string[] = [
      `Goal: ${ctx.goal.slice(0, 100)}`,
      `Progress: ${ctx.stepIndex}/${ctx.totalSteps} steps`,
    ];
    if (ctx.completedSteps.length > 0) {
      lines.push("Done: " + ctx.completedSteps.slice(-5).join(", "));
    }
    if (ctx.failedSteps.length > 0) {
      lines.push("Failed: " + ctx.failedSteps.slice(-3).join(", "));
    }
    if (ctx.genomeFacts.length > 0) {
      lines.push("Relevant knowledge: " + ctx.genomeFacts.slice(0, 3).join("; "));
    }
    const metrics = Object.entries(ctx.cumulativeMetrics)
      .map(([k, v]) => `${k}=${typeof v === "number" ? v.toFixed(2) : v}`)
      .join(", ");
    if (metrics) lines.push(`Metrics: ${metrics}`);
    return lines.join("\n").slice(0, 1500);
  }

  // ═══════════════════════════════════════════════════════════════════
  // PHASE 3: executeGoal() — THE FULL LOOP
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Decompose a goal into a plan, execute each step with inner loop,
   * replan on failure, carry compressed state through.
   */
  async executeGoal(goal: string, context?: string): Promise<GoalResult> {
    if (!this.planner) {
      return { goalId: "", goal, planId: "", status: "aborted", stepsCompleted: 0, stepsTotal: 0, replans: 0, results: [], durationMs: 0 };
    }

    const startMs = Date.now();
    const goalId = `g_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`;
    this.log.emit("goal_start", `${goalId}: ${goal.slice(0, 80)}`, { meta: { context: context?.slice(0, 200) } });

    // Decompose goal into plan
    const plan = await this.planner.decompose(goal, context);
    this.log.emit("goal_step", `${goalId}: decomposed into ${plan.steps.length} steps`);

    // Pull relevant genome facts for context
    let genomeFacts: string[] = [];
    try {
      if (await this.autonomy.ping()) {
        const keywords = goal.toLowerCase().split(/\s+/).filter((w) => w.length > 3).slice(0, 4).join(" ");
        const { results } = await this.autonomy.searchFacts(keywords, 8);
        if (results) genomeFacts = results.map((r) => r.content.slice(0, 100));
      }
    } catch { /* genome search is best-effort */ }

    // Initialize StepContext
    const ctx: StepContext = {
      goalId,
      goal,
      planId: plan.id,
      stepIndex: 0,
      totalSteps: plan.steps.length,
      completedSteps: [],
      failedSteps: [],
      cumulativeMetrics: {},
      genomeFacts,
      adaptedThreshold: this.adaptiveThreshold(),
    };

    const results: GoalResult["results"] = [];
    let replans = 0;
    let currentPlan = plan;

    for (let i = 0; i < currentPlan.steps.length && i < this.cfg.maxGoalSteps; i++) {
      const step = currentPlan.steps[i];
      if (step.children && step.children.length > 0) continue; // skip parent steps
      if (step.status === "completed" || step.status === "skipped") continue;

      ctx.stepIndex = i;
      this.log.emit("goal_step", `${goalId} step ${i}: ${step.description.slice(0, 80)}`);
      this.planner.updateStep(currentPlan.id, step.id, { status: "in_progress" });

      // Create and execute a task for this step
      const task = this.tasks.add({
        name: `[${goalId}] Step ${i}: ${step.description.slice(0, 50)}`,
        description: step.description,
        taskType: this.inferTaskType(step.description),
        priority: 2,
        tags: ["goal", goalId],
      });

      this.tasks.start(task.id);
      const { result, exitCode } = await this.executeTask(task);

      if (result === null) {
        // Task blocked/failed at execution level
        ctx.failedSteps.push(`step ${i}: execution blocked`);
        results.push({ step: step.description, status: "blocked", result: task.error ?? "blocked" });
        this.planner.updateStep(currentPlan.id, step.id, { status: "skipped", notes: "execution blocked" });
        continue;
      }

      // Validate with plan awareness
      const validation = await this.validateForGoal(task, result, ctx, step);
      this.log.emit("goal_step", `${goalId} step ${i} validated: pass=${validation.pass} conf=${validation.confidence.toFixed(2)}`);

      if (validation.pass) {
        this.tasks.complete(task.id, result);
        this.planner.updateStep(currentPlan.id, step.id, { status: "completed", notes: result.slice(0, 200) });
        ctx.completedSteps.push(`step ${i}: ${step.description.slice(0, 30)} (${validation.confidence.toFixed(1)})`);
        results.push({ step: step.description, status: "completed", result: result.slice(0, 300) });
        await this.recordGenome(task, result, true);
      } else {
        // Step failed — try reformulation with genome
        const newDesc = await this.reformulateWithGenome(task, validation.critique, validation.suggestion);

        // Re-execute once with reformulated description
        task.description = newDesc;
        this.tasks.fail(task.id, `validation failed: ${validation.critique}`);

        // Can we replan the remaining steps?
        if (replans < this.cfg.maxGoalReplans) {
          replans++;
          this.log.emit("goal_replan", `${goalId}: replanning after step ${i} failure (replan ${replans}/${this.cfg.maxGoalReplans})`);

          // Feed failure into planner for remaining steps
          const remainingSteps = currentPlan.steps.slice(i + 1).filter((s) => s.status === "pending");
          if (remainingSteps.length > 0 && this.planner) {
            const replanContext = `Original goal: ${goal}\nCompleted: ${ctx.completedSteps.join("; ")}\nFailed at step ${i}: ${validation.critique}\nRemaining steps need adjustment.`;
            const newPlan = await this.planner.decompose(
              `Continue: ${goal} (after step ${i} failed: ${validation.critique})`,
              replanContext,
            );
            // Replace remaining steps
            for (const ns of newPlan.steps) {
              currentPlan.steps.push({ ...ns, id: `replan${replans}_${ns.id}` });
            }
            this.log.emit("goal_replan", `${goalId}: added ${newPlan.steps.length} replanned steps`);
          }
        }

        ctx.failedSteps.push(`step ${i}: ${validation.critique.slice(0, 50)}`);
        results.push({ step: step.description, status: "failed", result: validation.critique });
        this.planner.updateStep(currentPlan.id, step.id, { status: "skipped", notes: `failed: ${validation.critique.slice(0, 100)}` });
        await this.recordGenome(task, result, false, validation.critique);
      }
    }

    // Determine overall status
    const completed = results.filter((r) => r.status === "completed").length;
    const total = results.length;
    const status: GoalResult["status"] =
      completed === total && total > 0 ? "completed" :
      completed > 0 ? "partial" :
      "failed";

    const durationMs = Date.now() - startMs;
    this.log.emit("goal_complete", `${goalId}: ${status} (${completed}/${total} steps, ${replans} replans, ${durationMs}ms)`);

    // Record goal outcome to genome
    try {
      if (await this.autonomy.ping()) {
        await this.autonomy.record("system",
          `[GOAL:${goalId}] "${goal.slice(0, 80)}" ${status}: ${completed}/${total} steps, ${replans} replans ∵ ${ctx.completedSteps.slice(-3).join("; ")}`,
        );
      }
    } catch { /* best-effort */ }

    return { goalId, goal, planId: plan.id, status, stepsCompleted: completed, stepsTotal: total, replans, results, durationMs };
  }

  /** Infer task type from step description */
  private inferTaskType(desc: string): Task["taskType"] {
    const lower = desc.toLowerCase();
    if (lower.includes("run ") || lower.includes("execute") || lower.includes("install") || lower.includes("build")) return "shell";
    if (lower.includes("research") || lower.includes("investigate") || lower.includes("find out")) return "research";
    if (lower.includes("review") || lower.includes("compare") || lower.includes("evaluate")) return "delegate";
    return "prompt";
  }

  // ═══════════════════════════════════════════════════════════════════
  // TICK LOOP
  // ═══════════════════════════════════════════════════════════════════

  async tick(): Promise<{ health: number; tasksProcessed: number; consolidated: boolean }> {
    if (this._ticking) {
      this.log.emit("daemon_tick", "tick skipped: previous tick still running");
      return { health: 0, tasksProcessed: 0, consolidated: false };
    }
    this._ticking = true;
    this._ollamaCallsThisTick = 0;
    const tickStart = Date.now();

    try {
      return await this._tickInner(tickStart);
    } finally {
      this._ticking = false;
    }
  }

  private async _tickInner(tickStart: number): Promise<{ health: number; tasksProcessed: number; consolidated: boolean }> {
    // Metabolic gate: don't tick if encysted
    if (this._metabolicTier === "encysted") {
      this.log.emit("metabolic", "tick skipped: encysted");
      return { health: 0, tasksProcessed: 0, consolidated: false };
    }

    this.tickCount++;
    this.log.emit("daemon_tick", `tick #${this.tickCount} start [${this._metabolicTier}]`);
    let healthUp = 0;
    let tasksProcessed = 0;
    let consolidated = false;

    // Reset stale running tasks (>10 min)
    for (const t of this.tasks.list({ status: "running" })) {
      if (t.startedAt) {
        const elapsed = Date.now() - new Date(t.startedAt).getTime();
        if (elapsed > 600_000) {
          this.tasks.fail(t.id, "stale: stuck running >10min, reset by daemon");
          this.log.emit("inner_loop", `reset stale task ${t.id} (${t.name})`);
        }
      }
    }

    // Health monitoring
    if (this.cfg.healthMonitoring) {
      const statuses = await checkAllServices();
      for (const s of statuses) {
        if (s.healthy) {
          healthUp++;
        } else {
          this.log.emit("service_check", `${s.name} DOWN: ${s.error?.slice(0, 100)}`);
          if (this.cfg.autoRestart) {
            const restartVerdict = this.policy.checkServiceRestart(s.name);
            if (restartVerdict.allowed) {
              await restartService(s.name, this.log);
            } else {
              this.log.emit("policy_violation", `Service restart throttled: ${restartVerdict.reason}`);
            }
          }
        }
      }
    }

    // Task processing with inner loop (metabolic-gated)
    const maxTasks = this.metabolicTasksPerTick();
    const maxPriority = this.metabolicMaxPriority();
    if (this.cfg.taskProcessing && maxTasks > 0) {
      let processed = 0;
      while (processed < maxTasks) {
        if (Date.now() - tickStart > this.cfg.tickTimeBudgetMs) {
          this.log.emit("daemon_tick", `tick time budget exhausted`);
          break;
        }

        const task = this.tasks.next();
        if (!task) break;

        // Metabolic filter: skip tasks below our energy tier
        if (task.priority > maxPriority) {
          this.log.emit("metabolic", `skipping ${task.id} (P${task.priority}) — tier ${this._metabolicTier} only runs P1-P${maxPriority}`);
          processed++;
          continue;
        }

        this.tasks.start(task.id);
        this.log.emit("task_event", `processing: ${task.name} (${task.taskType}) [${this._metabolicTier}]`);

        try {
          const { result, exitCode } = await this.executeTask(task);

          if (result === null) {
            processed++;
            continue;
          }

          // Phase 2: Use room validation for P1-P2 priority tasks (if metabolically allowed)
          const isHighPriority = task.priority <= 2;
          const useRoom = isHighPriority && this.metabolicAllowRoom();
          const validation = useRoom
            ? await this.validateWithRoom(task, result)
            : await this.validateResult(task, result, exitCode);

          this.log.emit("inner_loop", `${task.id} validated: pass=${validation.pass} conf=${validation.confidence.toFixed(2)}${useRoom ? " [room]" : ""}${validation.critique ? ` "${validation.critique.slice(0, 60)}"` : ""}`);

          if (validation.pass) {
            this.tasks.complete(task.id, result);
            this._replanCounts.delete(task.id);
            this.log.emit("task_event", `completed: ${task.name}`);
            await this.recordGenome(task, result, true);
          } else {
            // Phase 2: Genome-informed reformulation
            const replanCount = this._replanCounts.get(task.id) ?? 0;
            if (task.retryCount < task.maxRetries && replanCount === 0) {
              this._replanCounts.set(task.id, replanCount + 1);
              const newDesc = await this.reformulateWithGenome(task, validation.critique, validation.suggestion);
              task.description = newDesc;
              this.tasks.fail(task.id, `validation failed: ${validation.critique}`);
            } else {
              this.tasks.block(task.id, `validation failed after replan: ${validation.critique}`);
              this.log.emit("inner_loop", `${task.id} blocked: replan limit reached`);
              await this.recordGenome(task, result, false, validation.critique);
            }
          }

        } catch (err) {
          this.tasks.fail(task.id, String(err));
          this.log.emit("task_event", `failed: ${task.name}: ${err}`);
          await this.recordGenome(task, String(err), false);
        }
        processed++;
      }
      tasksProcessed = processed;
    }

    // Genome consolidation
    const IDLE_THRESHOLD_MS = 300_000;
    const isIdle = this.idleMs() > IDLE_THRESHOLD_MS;

    if (isIdle && !this._deepConsolidated) {
      try {
        if (await this.autonomy.ping()) {
          await this.autonomy.consolidateDeep();
          consolidated = true;
          this._deepConsolidated = true;
          this.log.emit("genome_event", "deep sleep-time consolidation (idle >5min)");
        }
      } catch (e) { this.log.emit("error", `deep consolidation failed: ${e}`); }
    } else if (this.tickCount % this.cfg.consolidateEveryNTicks === 0) {
      try {
        if (await this.autonomy.ping()) {
          await this.autonomy.consolidate(true);
          consolidated = true;
          this.log.emit("genome_event", "genome consolidated (daemon periodic)");
        }
      } catch (e) { this.log.emit("error", `periodic consolidation failed: ${e}`); }
    }

    this.log.emit("daemon_tick", `tick #${this.tickCount} done: ${healthUp} healthy, ${tasksProcessed} tasks, ${this._ollamaCallsThisTick} ollama calls${consolidated ? ", consolidated" : ""}`);
    return { health: healthUp, tasksProcessed, consolidated };
  }

  // ═══════════════════════════════════════════════════════════════════
  // TASK EXECUTION
  // ═══════════════════════════════════════════════════════════════════

  private async executeTask(task: Task): Promise<{ result: string | null; exitCode?: number }> {
    if (task.taskType === "shell" && task.command) {
      const verdict = this.policy.checkCommand(task.command);
      if (!verdict.allowed) {
        this.tasks.block(task.id, `POLICY BLOCKED: ${verdict.reason}`);
        this.log.emit("policy_violation", `${task.id} BLOCKED: ${verdict.reason} (rule: ${verdict.rule})`);
        this.policy.recordViolation(verdict.level as EscalationLevel);
        return { result: null };
      }

      // Check tool policy for shell in daemon context
      const toolVerdict = this.policy.checkTool("shell", "daemon");
      if (!toolVerdict.allowed) {
        this.tasks.block(task.id, `TOOL POLICY: ${toolVerdict.reason}`);
        return { result: null };
      }

      const exec = await shellExec(task.command, { timeoutMs: 60_000, log: this.log, policy: this.policy });
      const result = exec.exitCode === 0
        ? exec.stdout || "OK"
        : `EXIT ${exec.exitCode}: ${exec.stderr}`;

      if (exec.exitCode !== 0 && !exec.timedOut) {
        this.tasks.fail(task.id, result);
        return { result: null };
      }
      return { result, exitCode: exec.exitCode };

    } else if (task.taskType === "prompt" || task.taskType === "research") {
      const systemPrompt = task.taskType === "research"
        ? "You are a research assistant. Be thorough. Cite sources when possible."
        : "You are a helpful assistant. Be concise and actionable.";
      const r = await this.guardedChat(task.model ?? this.cfg.defaultModel, [
        { role: "system", content: systemPrompt },
        { role: "user", content: task.description },
      ]);
      if (!r.ok) {
        this.tasks.fail(task.id, `Ollama error: ${r.error}`);
        return { result: null };
      }
      return { result: r.content };

    } else if (task.taskType === "delegate") {
      const models = this.cfg.roomValidationModels.length >= 2
        ? this.cfg.roomValidationModels.slice(0, 2)
        : [this.cfg.defaultModel];
      const responses = await Promise.all(
        models.map((m) => this.guardedChat(m, [
          { role: "user", content: task.description },
        ])),
      );
      const results = responses.map((r, i) =>
        r.ok ? `[${models[i]}]: ${r.content}` : `[${models[i]}]: ERROR: ${r.error}`
      );
      return { result: results.join("\n\n") };

    } else {
      this.tasks.block(task.id, "Requires manual execution or unsupported task type");
      return { result: null };
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  // GENOME RECORDING
  // ═══════════════════════════════════════════════════════════════════

  private async recordGenome(task: Task, result: string, success: boolean, critique?: string): Promise<void> {
    try {
      if (!(await this.autonomy.ping())) return;
      const tag = success ? "TASK_RESULT" : "TASK_FAILURE";
      const body = success
        ? `[${tag}:${task.id}] ${task.name} completed: ${result.slice(0, 500)} ∵ executed via ${task.taskType} on ${task.model ?? "shell"}`
        : `[${tag}:${task.id}] ${task.name} failed: ${result.slice(0, 300)}${critique ? ` ∵ ${critique}` : ""} ∵ ${task.retryCount}/${task.maxRetries} retries`;
      await this.autonomy.record("system", body);
    } catch (e) {
      this.log.emit("error", `genome record failed: ${e}`);
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  // STATUS
  // ═══════════════════════════════════════════════════════════════════

  status(): {
    running: boolean; tickCount: number; config: DaemonConfig;
    ticking: boolean; ollamaCallsLastTick: number;
    validationStats: typeof this._validationStats;
    adaptiveThreshold: number;
    metabolicTier: MetabolicTier;
    powerLevel: number;
  } {
    return {
      running: this.running, tickCount: this.tickCount, config: this.cfg,
      ticking: this._ticking, ollamaCallsLastTick: this._ollamaCallsThisTick,
      validationStats: { ...this._validationStats },
      adaptiveThreshold: this.adaptiveThreshold(),
      metabolicTier: this._metabolicTier,
      powerLevel: this._powerLevel,
    };
  }
}
