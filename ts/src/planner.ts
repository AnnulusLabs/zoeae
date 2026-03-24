/**
 * Planner — Goal decomposition via local models
 *
 * Uses tree search (not linear) per research findings:
 *   - Maintain solution tree, best-first expansion
 *   - Stateless summarization: extract metrics, don't dump raw logs
 *   - Multi-model ensemble: cheap model for breadth, expensive for depth
 *
 * Patterns pulled from:
 *   A:\claude_swarm.py       — task decomposition + resonance assignment
 *   DDL_AUTORESEARCH_SPEC.md — program.md as constraint surface
 *
 * AnnulusLabs LLC
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname } from "node:path";
import { OllamaClient } from "./ollama-client.js";

export type PlanStatus = "active" | "completed" | "abandoned";

export type PlanStep = {
  id: string;
  description: string;
  taskId?: string;           // linked task engine ID
  status: "pending" | "in_progress" | "completed" | "skipped";
  notes?: string;
  children?: string[];       // sub-step IDs for tree decomposition
  score?: number;            // quality metric for best-first expansion
};

export type Plan = {
  id: string;
  goal: string;
  steps: PlanStep[];
  status: PlanStatus;
  createdAt: string;
  updatedAt: string;
  context?: string;
  metrics?: Record<string, string>;  // extracted metrics for stateless summarization
};

export class Planner {
  private plans: Map<string, Plan> = new Map();
  private filePath: string;
  private ollama: OllamaClient;
  private breadthModel: string;    // cheap: many candidates
  private depthModel: string;      // expensive: structural jumps

  constructor(filePath: string, ollamaUrl: string, breadthModel = "hermes3:8b", depthModel = "deepseek-r1:32b") {
    this.filePath = filePath;
    this.ollama = new OllamaClient(ollamaUrl, 120_000);
    this.breadthModel = breadthModel;
    this.depthModel = depthModel;
    this.load();
  }

  private load(): void {
    try {
      if (existsSync(this.filePath)) {
        const data = JSON.parse(readFileSync(this.filePath, "utf-8"));
        for (const p of data.plans ?? []) this.plans.set(p.id, p);
      }
    } catch { /* fresh */ }
  }

  save(): void {
    try {
      mkdirSync(dirname(this.filePath), { recursive: true });
      writeFileSync(this.filePath, JSON.stringify({
        plans: Array.from(this.plans.values()),
      }, null, 2), "utf-8");
    } catch { /* silent */ }
  }

  /** Decompose a goal into steps using breadth model */
  async decompose(goal: string, context?: string): Promise<Plan> {
    const prompt = `Break this goal into 3-8 concrete, actionable steps.
Each step should be completable in one session.
Return ONLY a JSON array of strings, no explanation.
${context ? `\nContext:\n${context}\n` : ""}
Goal: ${goal}

Output: ["step 1", "step 2", ...]`;

    const raw = await this.ollama.chat(this.breadthModel, [
      { role: "system", content: "You are a task planner. Return only valid JSON arrays of step descriptions." },
      { role: "user", content: prompt },
    ]);

    let steps: string[] = [];
    try {
      const match = raw.match(/\[[\s\S]*?\]/);
      if (match) steps = JSON.parse(match[0]);
    } catch {
      steps = raw.split("\n").filter((l) => l.trim().length > 5).slice(0, 8);
    }

    const plan: Plan = {
      id: `plan_${Date.now()}`,
      goal,
      steps: steps.map((desc, i) => ({
        id: `s${i}`,
        description: typeof desc === "string" ? desc : String(desc),
        status: "pending" as const,
      })),
      status: "active",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      context,
    };

    this.plans.set(plan.id, plan);
    this.save();
    return plan;
  }

  /** Expand a step into sub-steps using depth model (tree search) */
  async expand(planId: string, stepId: string): Promise<Plan | null> {
    const plan = this.plans.get(planId);
    if (!plan) return null;
    const step = plan.steps.find((s) => s.id === stepId);
    if (!step) return null;

    const prompt = `This is one step of a larger plan.
Goal: ${plan.goal}
Step: ${step.description}

Break this step into 2-4 smaller sub-steps. Return ONLY a JSON array of strings.`;

    const raw = await this.ollama.chat(this.depthModel, [
      { role: "system", content: "Return only valid JSON arrays. Be specific and actionable." },
      { role: "user", content: prompt },
    ]);

    let subSteps: string[] = [];
    try {
      const match = raw.match(/\[[\s\S]*?\]/);
      if (match) subSteps = JSON.parse(match[0]);
    } catch {
      subSteps = raw.split("\n").filter((l) => l.trim().length > 5).slice(0, 4);
    }

    const childIds: string[] = [];
    for (let i = 0; i < subSteps.length; i++) {
      const childId = `${stepId}_${i}`;
      childIds.push(childId);
      plan.steps.push({
        id: childId,
        description: typeof subSteps[i] === "string" ? subSteps[i] : String(subSteps[i]),
        status: "pending",
      });
    }
    step.children = childIds;
    plan.updatedAt = new Date().toISOString();
    this.save();
    return plan;
  }

  get(id: string): Plan | undefined {
    return this.plans.get(id);
  }

  list(status?: PlanStatus): Plan[] {
    const plans = Array.from(this.plans.values());
    if (status) return plans.filter((p) => p.status === status);
    return plans;
  }

  active(): Plan | undefined {
    return Array.from(this.plans.values()).find((p) => p.status === "active");
  }

  updateStep(planId: string, stepId: string, update: Partial<PlanStep>): Plan | null {
    const plan = this.plans.get(planId);
    if (!plan) return null;
    const step = plan.steps.find((s) => s.id === stepId);
    if (!step) return null;
    Object.assign(step, update);
    plan.updatedAt = new Date().toISOString();
    // Auto-complete plan if all top-level steps done
    const topLevel = plan.steps.filter((s) => !s.id.includes("_"));
    if (topLevel.every((s) => s.status === "completed" || s.status === "skipped")) {
      plan.status = "completed";
    }
    this.save();
    return plan;
  }

  abandon(planId: string): boolean {
    const plan = this.plans.get(planId);
    if (!plan) return false;
    plan.status = "abandoned";
    plan.updatedAt = new Date().toISOString();
    this.save();
    return true;
  }

  /** Stateless summary: extract only metrics and status, not raw history */
  summarize(planId: string): string {
    const plan = this.plans.get(planId);
    if (!plan) return "Plan not found.";
    const total = plan.steps.length;
    const done = plan.steps.filter((s) => s.status === "completed").length;
    const inProgress = plan.steps.filter((s) => s.status === "in_progress").length;
    const nextStep = plan.steps.find((s) => s.status === "pending");
    return [
      `Plan: ${plan.goal}`,
      `Status: ${plan.status} | ${done}/${total} steps done | ${inProgress} in progress`,
      nextStep ? `Next: ${nextStep.description}` : "All steps addressed.",
      plan.metrics ? `Metrics: ${JSON.stringify(plan.metrics)}` : "",
    ].filter(Boolean).join("\n");
  }
}
