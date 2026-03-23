/**
 * Task Engine — Persistent priority queue with dependencies & retry
 *
 * Patterns pulled from:
 *   task_queue                — priority + deps + retry + status lifecycle
 *   OpenClaw autonomy         — state persistence + agent spawning
 *   OpenClaw daemon            — task execution loop with timeout
 *
 * File-backed, zero deps. Survives restarts.
 *
 * AnnulusLabs LLC
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname } from "node:path";

export type TaskStatus = "pending" | "running" | "completed" | "failed" | "blocked";
export type TaskPriority = 1 | 2 | 3 | 4 | 5; // 1=critical, 5=low

export type Task = {
  id: string;
  name: string;
  description: string;
  command?: string;
  taskType: "shell" | "prompt" | "research" | "experiment" | "delegate" | "manual";
  status: TaskStatus;
  priority: TaskPriority;
  dependsOn: string[];
  model?: string;
  retryCount: number;
  maxRetries: number;
  result?: string;
  error?: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  tags: string[];
};

export class TaskEngine {
  private tasks: Map<string, Task> = new Map();
  private filePath: string;
  private _dirty = false;
  private _saveTimer: ReturnType<typeof setTimeout> | null = null;
  private static SAVE_DEBOUNCE_MS = 2_000;

  constructor(filePath: string) {
    this.filePath = filePath;
    this.load();
  }

  private load(): void {
    try {
      if (existsSync(this.filePath)) {
        const data = JSON.parse(readFileSync(this.filePath, "utf-8"));
        for (const t of data.tasks ?? []) {
          this.tasks.set(t.id, t);
        }
      }
    } catch { /* fresh start */ }
  }

  /** Debounced save — coalesces rapid state changes into one write */
  save(): void {
    this._dirty = true;
    if (this._saveTimer) return;
    this._saveTimer = setTimeout(() => {
      this._saveTimer = null;
      if (this._dirty) this.saveNow();
    }, TaskEngine.SAVE_DEBOUNCE_MS);
  }

  /** Immediate save — use when you need guaranteed persistence */
  saveNow(): void {
    this._dirty = false;
    try {
      mkdirSync(dirname(this.filePath), { recursive: true });
      writeFileSync(this.filePath, JSON.stringify({
        version: 1,
        updatedAt: new Date().toISOString(),
        tasks: Array.from(this.tasks.values()),
      }, null, 2), "utf-8");
    } catch { /* silent */ }
  }

  add(opts: {
    name: string;
    description: string;
    command?: string;
    taskType?: Task["taskType"];
    priority?: TaskPriority;
    dependsOn?: string[];
    model?: string;
    tags?: string[];
    maxRetries?: number;
  }): Task {
    const id = `t_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const task: Task = {
      id,
      name: opts.name,
      description: opts.description,
      command: opts.command,
      taskType: opts.taskType ?? "manual",
      status: "pending",
      priority: (opts.priority ?? 3) as TaskPriority,
      dependsOn: opts.dependsOn ?? [],
      model: opts.model,
      retryCount: 0,
      maxRetries: opts.maxRetries ?? 3,
      createdAt: new Date().toISOString(),
      tags: opts.tags ?? [],
    };
    this.tasks.set(id, task);
    this.save();
    return task;
  }

  get(id: string): Task | undefined {
    return this.tasks.get(id);
  }

  list(filter?: { status?: TaskStatus; tag?: string }): Task[] {
    let tasks = Array.from(this.tasks.values());
    if (filter?.status) tasks = tasks.filter((t) => t.status === filter.status);
    if (filter?.tag) tasks = tasks.filter((t) => t.tags.includes(filter.tag));
    return tasks.sort((a, b) => a.priority - b.priority);
  }

  /** Get next ready task (deps met, sorted by priority) */
  next(): Task | null {
    const pending = this.list({ status: "pending" });
    for (const task of pending) {
      const depsMet = task.dependsOn.every((dep) => {
        const d = this.tasks.get(dep);
        return d?.status === "completed";
      });
      if (depsMet) return task;
    }
    return null;
  }

  start(id: string): Task | null {
    const task = this.tasks.get(id);
    if (!task || task.status !== "pending") return null;
    task.status = "running";
    task.startedAt = new Date().toISOString();
    this.save();
    return task;
  }

  complete(id: string, result: string): Task | null {
    const task = this.tasks.get(id);
    if (!task) return null;
    task.status = "completed";
    task.result = result.slice(0, 10_000);
    task.completedAt = new Date().toISOString();
    this.save();
    return task;
  }

  fail(id: string, error: string): Task | null {
    const task = this.tasks.get(id);
    if (!task) return null;
    task.retryCount++;
    task.status = task.retryCount >= task.maxRetries ? "failed" : "pending";
    task.error = error;
    this.save();
    return task;
  }

  block(id: string, reason: string): Task | null {
    const task = this.tasks.get(id);
    if (!task) return null;
    task.status = "blocked";
    task.error = reason;
    this.save();
    return task;
  }

  unblock(id: string): Task | null {
    const task = this.tasks.get(id);
    if (!task || task.status !== "blocked") return null;
    task.status = "pending";
    task.error = undefined;
    this.save();
    return task;
  }

  remove(id: string): boolean {
    const deleted = this.tasks.delete(id);
    if (deleted) this.save();
    return deleted;
  }

  clearCompleted(): number {
    let count = 0;
    for (const [id, task] of this.tasks) {
      if (task.status === "completed") {
        this.tasks.delete(id);
        count++;
      }
    }
    if (count > 0) this.save();
    return count;
  }

  stats(): { total: number; pending: number; running: number; completed: number; failed: number; blocked: number } {
    const s = { total: 0, pending: 0, running: 0, completed: 0, failed: 0, blocked: 0 };
    for (const t of this.tasks.values()) {
      s.total++;
      s[t.status] = (s[t.status] ?? 0) + 1;
    }
    return s;
  }

  /** Format task list as readable text */
  format(tasks?: Task[]): string {
    const list = tasks ?? this.list();
    if (list.length === 0) return "No tasks.";
    return list.map((t) => {
      const deps = t.dependsOn.length > 0 ? ` [deps: ${t.dependsOn.join(",")}]` : "";
      const tags = t.tags.length > 0 ? ` #${t.tags.join(" #")}` : "";
      return `[${t.status.toUpperCase().padEnd(9)}] P${t.priority} ${t.id} — ${t.name}${deps}${tags}`;
    }).join("\n");
  }
}
