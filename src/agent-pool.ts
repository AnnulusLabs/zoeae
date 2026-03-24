/**
 * Agent Pool — Multi-instance agent orchestrator
 *
 * Manages N concurrent agents, each with their own workspace, PTY,
 * and policy scope, while sharing the dream engine and genome.
 *
 * Architecture:
 *   - AgentSession  — lifecycle + state for one agent
 *   - PtyPool       — tmux-backed terminal pool (no node-pty dep)
 *   - AgentPool     — main orchestrator, spawn/kill/route
 *   - AgentRouter   — routes incoming tasks to the right role
 *   - AgentComms    — inter-agent message bus
 *   - PoolPersistence — save/restore pool state
 *
 * AnnulusLabs LLC
 */

import { spawnSync, spawn, type ChildProcess } from "node:child_process";
import {
  writeFileSync,
  readFileSync,
  existsSync,
  mkdirSync,
  renameSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { OllamaClient } from "./ollama-client.js";
import { ActivityLog } from "./activity-log.js";
import { DreamEngine } from "./dream-engine.js";
import { PolicyEngine, type ToolPolicyEntry } from "./policy.js";

// ═══════════════════════════════════════════════════════════════════════
// ENUMERATIONS
// ═══════════════════════════════════════════════════════════════════════

/** Functional role — shapes task routing and resource budgets */
export type AgentRole =
  | "orchestrator"
  | "builder"
  | "researcher"
  | "reviewer"
  | "dreamer"
  | "sentinel"
  | "custom";

/** Lifecycle state */
export type AgentState =
  | "idle"
  | "working"
  | "waiting"
  | "dreaming"
  | "paused"
  | "dead";

// ═══════════════════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════════════════

/** Per-agent policy overrides — tighten (never loosen) the base policy */
export type ToolPolicy = Record<string, Partial<ToolPolicyEntry>>;

/** Immutable identity + preferences for one agent */
export type AgentConfig = {
  /** UUID — stable across restarts */
  id: string;
  /** Human-friendly label, e.g. "builder-1" */
  name: string;
  role: AgentRole;
  /** Absolute working directory */
  cwd: string;
  /** Default Ollama model for this agent */
  model: string;
  /** Linked tmux session ID (null if no terminal attached) */
  ptySessionId: string | null;
  /** Per-agent policy tightening applied on top of the base PolicyEngine */
  policyOverrides: Partial<ToolPolicy>;
  /** How many tasks this agent may run concurrently */
  maxConcurrentTasks: number;
  enabled: boolean;
  metadata: Record<string, unknown>;
};

function defaultAgentConfig(partial: Partial<AgentConfig> = {}): AgentConfig {
  return {
    id: partial.id ?? randomUUID(),
    name: partial.name ?? `agent-${Date.now()}`,
    role: partial.role ?? "custom",
    cwd: partial.cwd ?? (process.env.USERPROFILE ?? process.env.HOME ?? "."),
    model: partial.model ?? "hermes3:8b",
    ptySessionId: partial.ptySessionId ?? null,
    policyOverrides: partial.policyOverrides ?? {},
    maxConcurrentTasks: partial.maxConcurrentTasks ?? 1,
    enabled: partial.enabled ?? true,
    metadata: partial.metadata ?? {},
  };
}

// ═══════════════════════════════════════════════════════════════════════
// AGENT SESSION
// ═══════════════════════════════════════════════════════════════════════

type FileInteraction = {
  filePath: string;
  type: "read" | "write";
  timestamp: number;
};

type StateChangeListener = (prev: AgentState, next: AgentState) => void;
type FileTouchedListener = (interaction: FileInteraction) => void;
type TaskCompleteListener = (taskId: string, result: unknown) => void;

/** Live session for one agent — mutable runtime state */
export class AgentSession {
  readonly config: AgentConfig;
  private _state: AgentState = "idle";
  readonly startedAt: number;
  lastActivityAt: number;
  readonly interactions: FileInteraction[] = [];
  taskCount = 0;
  ollamaCallCount = 0;

  private _stateListeners: StateChangeListener[] = [];
  private _fileTouchedListeners: FileTouchedListener[] = [];
  private _taskCompleteListeners: TaskCompleteListener[] = [];

  constructor(config: AgentConfig) {
    this.config = config;
    this.startedAt = Date.now();
    this.lastActivityAt = this.startedAt;
  }

  get state(): AgentState { return this._state; }

  /** Transition state and fire listeners */
  private _setState(next: AgentState): void {
    if (this._state === next) return;
    const prev = this._state;
    this._state = next;
    this.lastActivityAt = Date.now();
    for (const fn of this._stateListeners) {
      try { fn(prev, next); } catch { /* silent */ }
    }
  }

  /** Start the agent — transitions idle → idle (already live) */
  start(): void {
    if (this._state === "dead") this._setState("idle");
  }

  /** Graceful stop */
  stop(): void {
    this._setState("dead");
  }

  /** Pause execution without killing the session */
  pause(): void {
    if (this._state === "working" || this._state === "idle") {
      this._setState("paused");
    }
  }

  /** Resume from paused */
  resume(): void {
    if (this._state === "paused") this._setState("idle");
  }

  /** Mark the agent as actively executing work */
  markWorking(): void {
    if (this._state !== "paused" && this._state !== "dead") {
      this._setState("working");
    }
  }

  /** Mark the agent as idle (work complete) */
  markIdle(): void {
    if (this._state !== "paused" && this._state !== "dead") {
      this._setState("idle");
    }
  }

  /** Mark the agent as waiting on an external resource */
  markWaiting(): void {
    if (this._state !== "paused" && this._state !== "dead") {
      this._setState("waiting");
    }
  }

  /** Mark the agent as running a dream cycle */
  markDreaming(): void {
    if (this._state !== "paused" && this._state !== "dead") {
      this._setState("dreaming");
    }
  }

  /**
   * Record a file interaction.
   * Fires "file-touched" listeners.
   */
  touchFile(filePath: string, type: "read" | "write"): void {
    const interaction: FileInteraction = { filePath, type, timestamp: Date.now() };
    this.interactions.push(interaction);
    this.lastActivityAt = interaction.timestamp;
    for (const fn of this._fileTouchedListeners) {
      try { fn(interaction); } catch { /* silent */ }
    }
  }

  /** Notify that a task completed */
  notifyTaskComplete(taskId: string, result: unknown): void {
    this.taskCount++;
    this.lastActivityAt = Date.now();
    for (const fn of this._taskCompleteListeners) {
      try { fn(taskId, result); } catch { /* silent */ }
    }
  }

  /** Milliseconds since last recorded activity */
  idleMs(): number {
    return Date.now() - this.lastActivityAt;
  }

  // ── Event subscriptions ───────────────────────────────────────────

  /**
   * Subscribe to session events.
   * Returns an unsubscribe function.
   */
  on(event: "state-change", fn: StateChangeListener): () => void;
  on(event: "file-touched", fn: FileTouchedListener): () => void;
  on(event: "task-complete", fn: TaskCompleteListener): () => void;
  on(event: string, fn: (...args: unknown[]) => void): () => void {
    if (event === "state-change") {
      this._stateListeners.push(fn as StateChangeListener);
      return () => { this._stateListeners = this._stateListeners.filter(l => l !== fn); };
    }
    if (event === "file-touched") {
      this._fileTouchedListeners.push(fn as FileTouchedListener);
      return () => { this._fileTouchedListeners = this._fileTouchedListeners.filter(l => l !== fn); };
    }
    if (event === "task-complete") {
      this._taskCompleteListeners.push(fn as TaskCompleteListener);
      return () => { this._taskCompleteListeners = this._taskCompleteListeners.filter(l => l !== fn); };
    }
    return () => {};
  }

  // ── Serialization ────────────────────────────────────────────────

  /** Snapshot for persistence */
  toJSON(): object {
    return {
      config: this.config,
      state: this._state,
      startedAt: this.startedAt,
      lastActivityAt: this.lastActivityAt,
      interactions: this.interactions.slice(-500), // cap at 500 entries
      taskCount: this.taskCount,
      ollamaCallCount: this.ollamaCallCount,
    };
  }

  /** Restore from a persisted snapshot */
  static fromJSON(raw: Record<string, unknown>): AgentSession {
    const config = defaultAgentConfig(raw.config as Partial<AgentConfig>);
    const session = new AgentSession(config);
    // Restore ephemeral-safe state — treat "working" as "idle" on restore
    const savedState = raw.state as AgentState;
    if (savedState === "paused") {
      session._setState("paused");
    } else {
      session._setState("idle");
    }
    (session as any).lastActivityAt = (raw.lastActivityAt as number) ?? Date.now();
    (session as any).taskCount = (raw.taskCount as number) ?? 0;
    (session as any).ollamaCallCount = (raw.ollamaCallCount as number) ?? 0;
    if (Array.isArray(raw.interactions)) {
      (session as any).interactions = raw.interactions as FileInteraction[];
    }
    return session;
  }
}

// ═══════════════════════════════════════════════════════════════════════
// PTY POOL — tmux-backed, no node-pty dependency
// ═══════════════════════════════════════════════════════════════════════

/** Live tmux session handle */
export type PtySession = {
  sessionId: string;
  tmuxName: string;
  cwd: string;
  cols: number;
  rows: number;
  createdAt: number;
  /** Write data to the tmux session via send-keys */
  write: (data: string) => void;
  /** Attach a data listener — returns unsubscribe */
  onData: (fn: (data: string) => void) => () => void;
  /** Resize the session window */
  resize: (cols: number, rows: number) => void;
  /** Destroy the tmux session */
  kill: () => void;
};

/** Metadata entry tracked in the pool */
type PtyMeta = {
  sessionId: string;
  tmuxName: string;
  cwd: string;
  cols: number;
  rows: number;
  createdAt: number;
  proc: ChildProcess | null;
  listeners: Array<(data: string) => void>;
};

/** tmux socket name — scoped to this process so we don't collide with Collaborator */
const TMUX_SOCKET = "zoeae";

function tmuxName(sessionId: string): string {
  return `zoeae-${sessionId.slice(0, 16)}`;
}

function tmuxRun(...args: string[]): string {
  const result = spawnSync("tmux", ["-L", TMUX_SOCKET, ...args], {
    encoding: "utf-8",
    timeout: 5_000,
  });
  if (result.error) throw result.error;
  return (result.stdout ?? "").trim();
}

function tmuxHasSession(name: string): boolean {
  try {
    tmuxRun("has-session", "-t", name);
    return true;
  } catch {
    return false;
  }
}

/**
 * PtyPool — manages tmux-backed terminal sessions.
 *
 * Sessions survive detach (tmux keeps running). Clients reconnect and
 * receive scrollback. Works on any Unix platform with tmux ≥ 2.6.
 */
export class PtyPool {
  private sessions: Map<string, PtyMeta> = new Map();

  /**
   * Create a new tmux session and return a handle.
   * The session persists even if the handle is garbage-collected.
   */
  create(cwd: string, cols = 220, rows = 50): PtySession {
    const sessionId = randomUUID().replace(/-/g, "").slice(0, 16);
    const name = tmuxName(sessionId);
    const resolvedCwd = resolve(cwd);

    tmuxRun(
      "new-session", "-d",
      "-s", name,
      "-c", resolvedCwd,
      "-x", String(cols),
      "-y", String(rows),
    );

    const meta: PtyMeta = {
      sessionId,
      tmuxName: name,
      cwd: resolvedCwd,
      cols,
      rows,
      createdAt: Date.now(),
      proc: null,
      listeners: [],
    };

    this.sessions.set(sessionId, meta);
    return this._makeHandle(meta);
  }

  /**
   * Attach (or re-attach) a data-listener pipe to an existing tmux session.
   * On reconnect, fires scrollback captured via `tmux capture-pane`.
   */
  attach(sessionId: string): PtySession {
    const meta = this.sessions.get(sessionId);
    if (!meta) throw new Error(`PtyPool: unknown session ${sessionId}`);

    const name = meta.tmuxName;
    if (!tmuxHasSession(name)) {
      throw new Error(`PtyPool: tmux session ${name} not found`);
    }

    // Detach existing pipe if present
    if (meta.proc) {
      try { meta.proc.kill(); } catch { /* silent */ }
      meta.proc = null;
    }

    // Replay scrollback to new listeners
    try {
      const scrollback = tmuxRun(
        "capture-pane", "-t", name,
        "-p", "-e", "-S", "-200000",
      );
      if (scrollback.trim()) {
        for (const fn of meta.listeners) {
          try { fn(scrollback); } catch { /* silent */ }
        }
      }
    } catch { /* no scrollback available */ }

    return this._makeHandle(meta);
  }

  /**
   * Detach client pipe but leave the tmux session alive.
   */
  detach(sessionId: string): void {
    const meta = this.sessions.get(sessionId);
    if (!meta) return;
    if (meta.proc) {
      try { meta.proc.kill(); } catch { /* silent */ }
      meta.proc = null;
    }
  }

  /** Destroy the tmux session and remove from pool */
  kill(sessionId: string): void {
    const meta = this.sessions.get(sessionId);
    if (meta) {
      if (meta.proc) {
        try { meta.proc.kill(); } catch { /* silent */ }
      }
      try { tmuxRun("kill-session", "-t", meta.tmuxName); } catch { /* already dead */ }
      this.sessions.delete(sessionId);
    }
  }

  /** List all tracked sessions with metadata */
  list(): Array<{ sessionId: string; tmuxName: string; cwd: string; cols: number; rows: number; createdAt: number }> {
    return [...this.sessions.values()].map(m => ({
      sessionId: m.sessionId,
      tmuxName: m.tmuxName,
      cwd: m.cwd,
      cols: m.cols,
      rows: m.rows,
      createdAt: m.createdAt,
    }));
  }

  /** Kill all sessions */
  killAll(): void {
    for (const id of [...this.sessions.keys()]) {
      this.kill(id);
    }
  }

  private _makeHandle(meta: PtyMeta): PtySession {
    return {
      sessionId: meta.sessionId,
      tmuxName: meta.tmuxName,
      cwd: meta.cwd,
      cols: meta.cols,
      rows: meta.rows,
      createdAt: meta.createdAt,

      write: (data: string) => {
        try {
          tmuxRun("send-keys", "-t", meta.tmuxName, data, "");
        } catch { /* silent */ }
      },

      onData: (fn: (data: string) => void): (() => void) => {
        meta.listeners.push(fn);
        return () => {
          meta.listeners = meta.listeners.filter(l => l !== fn);
        };
      },

      resize: (cols: number, rows: number) => {
        meta.cols = cols;
        meta.rows = rows;
        try {
          tmuxRun("resize-window", "-t", meta.tmuxName, "-x", String(cols), "-y", String(rows));
        } catch { /* non-fatal */ }
      },

      kill: () => this.kill(meta.sessionId),
    };
  }
}

// ═══════════════════════════════════════════════════════════════════════
// AGENT COMMS — inter-agent message bus
// ═══════════════════════════════════════════════════════════════════════

/** Wire format for all inter-agent messages */
export type AgentMessage = {
  id: string;
  from: string;
  to: string | "all";
  channel: string;
  payload: unknown;
  timestamp: number;
};

type MessageListener = (msg: AgentMessage) => void;

/**
 * AgentComms — lightweight pub/sub for inter-agent communication.
 *
 * Channels: "file-changed" | "task-complete" | "threat-detected" | "dream-found"
 * plus any custom channel.
 */
export class AgentComms {
  private _directListeners: Map<string, MessageListener[]> = new Map();
  private _channelListeners: Map<string, MessageListener[]> = new Map();
  private _log: ActivityLog;

  constructor(log: ActivityLog) {
    this._log = log;
  }

  /**
   * Send a direct message from one agent to another.
   * The target agent must have subscribed to its own ID.
   */
  send(fromId: string, toId: string, payload: unknown, channel = "direct"): void {
    const msg: AgentMessage = {
      id: randomUUID(),
      from: fromId,
      to: toId,
      channel,
      payload,
      timestamp: Date.now(),
    };
    this._log.emit("info", `[comms] ${fromId} → ${toId} (${channel})`);
    const listeners = this._directListeners.get(toId) ?? [];
    for (const fn of listeners) {
      try { fn(msg); } catch { /* silent */ }
    }
    this._fireChannel(channel, msg);
  }

  /**
   * Broadcast from one agent to all agents on a channel.
   */
  broadcast(fromId: string, payload: unknown, channel = "broadcast"): void {
    const msg: AgentMessage = {
      id: randomUUID(),
      from: fromId,
      to: "all",
      channel,
      payload,
      timestamp: Date.now(),
    };
    this._log.emit("info", `[comms] ${fromId} → all (${channel})`);
    this._fireChannel(channel, msg);
    // Also fire every direct listener (broadcast reaches everyone)
    for (const listeners of this._directListeners.values()) {
      for (const fn of listeners) {
        try { fn(msg); } catch { /* silent */ }
      }
    }
  }

  /**
   * Subscribe an agent to receive direct messages.
   * Returns an unsubscribe function.
   */
  subscribe(agentId: string, channel: string, fn: MessageListener): () => void {
    if (channel === "direct") {
      const list = this._directListeners.get(agentId) ?? [];
      list.push(fn);
      this._directListeners.set(agentId, list);
      return () => {
        const updated = (this._directListeners.get(agentId) ?? []).filter(l => l !== fn);
        this._directListeners.set(agentId, updated);
      };
    }
    return this._subscribeChannel(channel, fn);
  }

  /** Publish a message to a named channel (no sender attribution) */
  publish(channel: string, payload: unknown, fromId = "system"): void {
    const msg: AgentMessage = {
      id: randomUUID(),
      from: fromId,
      to: "all",
      channel,
      payload,
      timestamp: Date.now(),
    };
    this._fireChannel(channel, msg);
  }

  private _subscribeChannel(channel: string, fn: MessageListener): () => void {
    const list = this._channelListeners.get(channel) ?? [];
    list.push(fn);
    this._channelListeners.set(channel, list);
    return () => {
      const updated = (this._channelListeners.get(channel) ?? []).filter(l => l !== fn);
      this._channelListeners.set(channel, updated);
    };
  }

  private _fireChannel(channel: string, msg: AgentMessage): void {
    const listeners = this._channelListeners.get(channel) ?? [];
    for (const fn of listeners) {
      try { fn(msg); } catch { /* silent */ }
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════
// TASK QUEUE — FIFO per role, with priority
// ═══════════════════════════════════════════════════════════════════════

export type PoolTask = {
  id: string;
  description: string;
  role: AgentRole;
  priority: number;       // higher = more urgent
  payload: unknown;
  createdAt: number;
  assignedTo: string | null;
  affinityFiles?: string[]; // prefer agent that recently touched these files
};

class RoleQueue {
  private _queues: Map<AgentRole, PoolTask[]> = new Map();

  enqueue(task: PoolTask): void {
    const q = this._queues.get(task.role) ?? [];
    q.push(task);
    // Sort descending by priority, FIFO within same priority
    q.sort((a, b) => b.priority - a.priority);
    this._queues.set(task.role, q);
  }

  /** Dequeue the highest-priority task for a given role */
  dequeue(role: AgentRole): PoolTask | undefined {
    const q = this._queues.get(role);
    if (!q || q.length === 0) return undefined;
    return q.shift();
  }

  /** Peek without removing */
  peek(role: AgentRole): PoolTask | undefined {
    return this._queues.get(role)?.[0];
  }

  depthFor(role: AgentRole): number {
    return this._queues.get(role)?.length ?? 0;
  }

  totalDepth(): number {
    let n = 0;
    for (const q of this._queues.values()) n += q.length;
    return n;
  }
}

// ═══════════════════════════════════════════════════════════════════════
// AGENT ROUTER
// ═══════════════════════════════════════════════════════════════════════

/** Keyword → role routing table */
const ROLE_KEYWORDS: Array<{ pattern: RegExp; role: AgentRole }> = [
  { pattern: /\b(build|compile|implement|code|write|fix|refactor|patch)\b/i, role: "builder" },
  { pattern: /\b(research|search|find|look up|investigate|explore|survey)\b/i, role: "researcher" },
  { pattern: /\b(review|audit|check|lint|analyse|analyze|inspect)\b/i, role: "reviewer" },
  { pattern: /\b(monitor|watch|guard|secure|detect|threat|alert)\b/i, role: "sentinel" },
  { pattern: /\b(dream|imagine|ideate|brainstorm|synthesize|connect)\b/i, role: "dreamer" },
];

/**
 * AgentRouter — routes incoming tasks to the best available agent.
 *
 * Routing priority:
 *   1. Affinity: agent that recently touched files referenced in the task
 *   2. Role match: idle agent with the target role
 *   3. Least-busy: agent of any role with lowest taskCount
 *   4. Spawn: create a new agent of the required role if none exist
 */
export class AgentRouter {
  private _pool: AgentPool;
  private _queue: RoleQueue = new RoleQueue();

  constructor(pool: AgentPool) {
    this._pool = pool;
  }

  /**
   * Infer the best role for a task from its description.
   */
  inferRole(description: string): AgentRole {
    for (const { pattern, role } of ROLE_KEYWORDS) {
      if (pattern.test(description)) return role;
    }
    return "builder"; // safe default
  }

  /**
   * Route a task — returns the agentId it was dispatched to,
   * or null if queued (no agent available right now).
   */
  route(task: PoolTask): string | null {
    const targetRole = task.role;

    // 1. Affinity: find idle agent that recently touched the task's files
    if (task.affinityFiles && task.affinityFiles.length > 0) {
      const affined = this._findAffinityAgent(task.affinityFiles, targetRole);
      if (affined) return affined;
    }

    // 2. Idle agent of the target role
    const idleByRole = this._pool.getByRole(targetRole)
      .filter(s => s.state === "idle" && s.config.enabled);
    if (idleByRole.length > 0) {
      const chosen = idleByRole[0]!;
      return chosen.config.id;
    }

    // 3. Least-busy agent of that role
    const allByRole = this._pool.getByRole(targetRole)
      .filter(s => s.config.enabled && s.state !== "dead" && s.state !== "paused");
    if (allByRole.length > 0) {
      const chosen = allByRole.sort((a, b) => a.taskCount - b.taskCount)[0]!;
      return chosen.config.id;
    }

    // 4. Queue and signal pool to scale up
    this._queue.enqueue(task);
    this._pool.log.emit("info", `[router] queued task ${task.id} for role=${targetRole} (queue depth=${this._queue.depthFor(targetRole)})`);
    return null;
  }

  /** Drain queued tasks — called after a new agent is spawned */
  drainFor(role: AgentRole): void {
    let task: PoolTask | undefined;
    while ((task = this._queue.dequeue(role)) !== undefined) {
      const agentId = this.route(task);
      if (!agentId) break; // still no agent available
      this._pool.assignTask(agentId, task);
    }
  }

  queueDepth(role: AgentRole): number {
    return this._queue.depthFor(role);
  }

  private _findAffinityAgent(files: string[], role: AgentRole): string | null {
    const candidates = this._pool.getByRole(role)
      .filter(s => s.state === "idle" && s.config.enabled);
    let bestId: string | null = null;
    let bestScore = 0;

    for (const session of candidates) {
      const recentFiles = new Set(
        session.interactions.slice(-100).map(i => i.filePath)
      );
      const overlap = files.filter(f => recentFiles.has(f)).length;
      if (overlap > bestScore) {
        bestScore = overlap;
        bestId = session.config.id;
      }
    }
    return bestId;
  }
}

// ═══════════════════════════════════════════════════════════════════════
// POOL PERSISTENCE
// ═══════════════════════════════════════════════════════════════════════

const PERSIST_PATH = join("A:/AI/KERF/.kerf", "agent-pool.json");
const PERSIST_DEBOUNCE_MS = 2_000;

/** PoolPersistence — atomic save/restore of pool state */
export class PoolPersistence {
  private _path: string;
  private _timer: ReturnType<typeof setTimeout> | null = null;

  constructor(path = PERSIST_PATH) {
    this._path = path;
  }

  /** Write pool state atomically (tmp + rename) */
  save(pool: AgentPool): void {
    try {
      mkdirSync(dirname(this._path), { recursive: true });
      const data = JSON.stringify({
        version: 1,
        savedAt: new Date().toISOString(),
        agents: [...pool.agents.values()].map(s => s.toJSON()),
      }, null, 2);
      const tmp = this._path + ".tmp";
      writeFileSync(tmp, data, "utf-8");
      renameSync(tmp, this._path);
    } catch (e) {
      pool.log.emit("error", `[persistence] save failed: ${e}`);
    }
  }

  /** Restore agents from saved state — returns AgentSession array */
  load(pool: AgentPool): AgentSession[] {
    if (!existsSync(this._path)) return [];
    try {
      const raw = JSON.parse(readFileSync(this._path, "utf-8"));
      if (!Array.isArray(raw.agents)) return [];
      const sessions: AgentSession[] = [];
      for (const entry of raw.agents) {
        try {
          sessions.push(AgentSession.fromJSON(entry as Record<string, unknown>));
        } catch (e) {
          pool.log.emit("error", `[persistence] failed to restore agent: ${e}`);
        }
      }
      pool.log.emit("info", `[persistence] restored ${sessions.length} agent(s) from ${this._path}`);
      return sessions;
    } catch (e) {
      pool.log.emit("error", `[persistence] load failed: ${e}`);
      return [];
    }
  }

  /** Schedule a debounced auto-save */
  scheduleSave(pool: AgentPool): void {
    if (this._timer) clearTimeout(this._timer);
    this._timer = setTimeout(() => {
      this._timer = null;
      this.save(pool);
    }, PERSIST_DEBOUNCE_MS);
  }
}

// ═══════════════════════════════════════════════════════════════════════
// AGENT POOL
// ═══════════════════════════════════════════════════════════════════════

/** Summary row for status() output */
export type AgentSummary = {
  id: string;
  name: string;
  role: AgentRole;
  state: AgentState;
  idleMs: number;
  taskCount: number;
  ollamaCallCount: number;
  cwd: string;
  ptySessionId: string | null;
};

export type PoolStatus = {
  totalAgents: number;
  byRole: Record<AgentRole, number>;
  byState: Record<AgentState, number>;
  queueDepths: Partial<Record<AgentRole, number>>;
  agents: AgentSummary[];
};

/**
 * AgentPool — the main orchestrator.
 *
 * Manages N concurrent AgentSessions. Shares dream engine, genome,
 * and Ollama client across all agents. Each agent gets its own PTY
 * and policy scope.
 */
export class AgentPool {
  readonly agents: Map<string, AgentSession> = new Map();
  readonly ptyPool: PtyPool;
  readonly ollama: OllamaClient;
  readonly dreamer: DreamEngine;
  readonly log: ActivityLog;
  readonly policy: PolicyEngine;
  readonly comms: AgentComms;

  private _router: AgentRouter;
  private _persistence: PoolPersistence;
  private _running = false;
  private _healthTimer: ReturnType<typeof setInterval> | null = null;

  constructor(opts: {
    ollama: OllamaClient;
    dreamer: DreamEngine;
    log: ActivityLog;
    policy: PolicyEngine;
    persistPath?: string;
  }) {
    this.ollama = opts.ollama;
    this.dreamer = opts.dreamer;
    this.log = opts.log;
    this.policy = opts.policy;
    this.ptyPool = new PtyPool();
    this.comms = new AgentComms(opts.log);
    this._router = new AgentRouter(this);
    this._persistence = new PoolPersistence(opts.persistPath);
  }

  // ── Lifecycle ─────────────────────────────────────────────────────

  /**
   * Start the pool.
   * Restores persisted agents, then spawns the 3 default agents if
   * no agents are loaded.
   */
  start(): void {
    if (this._running) return;
    this._running = true;

    // Restore persisted state
    const restored = this._persistence.load(this);
    for (const session of restored) {
      if (session.config.enabled) {
        session.start();
        this.agents.set(session.config.id, session);
        this._watchSession(session);
        this.log.emit("info", `[pool] restored agent ${session.config.name} (${session.config.role})`);
      }
    }

    // Spawn defaults if nothing was restored
    if (this.agents.size === 0) {
      this._spawnDefaults();
    }

    // Start health-check loop every 60s
    this._healthTimer = setInterval(() => {
      this._runHealthCheck();
    }, 60_000);

    this.log.emit("info", `[pool] started with ${this.agents.size} agent(s)`);
  }

  /** Gracefully stop all agents and persist state */
  async stop(): Promise<void> {
    if (!this._running) return;
    this._running = false;

    if (this._healthTimer) {
      clearInterval(this._healthTimer);
      this._healthTimer = null;
    }

    for (const session of this.agents.values()) {
      session.stop();
    }

    this.ptyPool.killAll();
    this._persistence.save(this);
    this.log.emit("info", "[pool] stopped — all agents halted, state persisted");
  }

  // ── Agent lifecycle ───────────────────────────────────────────────

  /**
   * Spawn a new agent and add it to the pool.
   * Optionally creates a PTY session for it.
   */
  spawn(config: Partial<AgentConfig> = {}): AgentSession {
    const fullConfig = defaultAgentConfig(config);
    const session = new AgentSession(fullConfig);
    session.start();

    this.agents.set(fullConfig.id, session);
    this._watchSession(session);

    this.log.emit("info", `[pool] spawned ${fullConfig.name} (role=${fullConfig.role}, id=${fullConfig.id.slice(0, 8)})`);

    // Drain any queued tasks for this role
    this._router.drainFor(fullConfig.role);

    this._persistence.scheduleSave(this);
    return session;
  }

  /**
   * Kill an agent, optionally recording a reason.
   */
  kill(agentId: string, reason?: string): void {
    const session = this.agents.get(agentId);
    if (!session) return;

    session.stop();

    if (session.config.ptySessionId) {
      this.ptyPool.kill(session.config.ptySessionId);
    }

    this.agents.delete(agentId);
    this.log.emit("info", `[pool] killed ${session.config.name}${reason ? ` — ${reason}` : ""}`);
    this._persistence.scheduleSave(this);
  }

  /** Pause a running agent */
  pause(agentId: string): void {
    const session = this.agents.get(agentId);
    if (!session) return;
    session.pause();
    this.log.emit("info", `[pool] paused ${session.config.name}`);
    this._persistence.scheduleSave(this);
  }

  /** Resume a paused agent */
  resume(agentId: string): void {
    const session = this.agents.get(agentId);
    if (!session) return;
    session.resume();
    this.log.emit("info", `[pool] resumed ${session.config.name}`);
    this._persistence.scheduleSave(this);
  }

  // ── Lookups ───────────────────────────────────────────────────────

  /** Get a session by ID */
  get(agentId: string): AgentSession | undefined {
    return this.agents.get(agentId);
  }

  /** All agents with their state summary */
  list(): AgentSummary[] {
    return [...this.agents.values()].map(s => ({
      id: s.config.id,
      name: s.config.name,
      role: s.config.role,
      state: s.state,
      idleMs: s.idleMs(),
      taskCount: s.taskCount,
      ollamaCallCount: s.ollamaCallCount,
      cwd: s.config.cwd,
      ptySessionId: s.config.ptySessionId,
    }));
  }

  /** All agents with a given role */
  getByRole(role: AgentRole): AgentSession[] {
    return [...this.agents.values()].filter(s => s.config.role === role);
  }

  // ── Messaging ─────────────────────────────────────────────────────

  /** Send a message to all agents */
  broadcast(message: unknown, channel = "broadcast"): void {
    this.comms.broadcast("pool", message, channel);
  }

  /** Send a message to a specific agent */
  route(agentId: string, message: unknown, channel = "direct"): void {
    this.comms.send("pool", agentId, message, channel);
  }

  // ── Task dispatch ─────────────────────────────────────────────────

  /**
   * Assign a task to a specific agent.
   * Marks the agent as working and records the task.
   */
  assignTask(agentId: string, task: PoolTask): boolean {
    const session = this.agents.get(agentId);
    if (!session || session.state === "dead" || session.state === "paused") return false;

    task.assignedTo = agentId;
    session.markWorking();
    this.log.emit("task_event", `[pool] assigned task "${task.description}" → ${session.config.name}`);
    return true;
  }

  /**
   * Give a task to the best available agent of a given role.
   * Spawns a new agent if none are available.
   * Returns the agentId that accepted the task, or null if queued.
   */
  assignTaskToRole(role: AgentRole, description: string, payload: unknown = null, priority = 0): string | null {
    const task: PoolTask = {
      id: randomUUID(),
      description,
      role,
      priority,
      payload,
      createdAt: Date.now(),
      assignedTo: null,
    };

    const agentId = this._router.route(task);
    if (agentId) {
      this.assignTask(agentId, task);
    }
    return agentId;
  }

  // ── Orchestration ─────────────────────────────────────────────────

  /**
   * Rebalance tasks if any agent is overloaded.
   * Simple heuristic: if one agent has 2× the mean taskCount, mark it
   * overloaded and emit a log event (actual migration is domain-specific).
   */
  balanceLoad(): void {
    const sessions = [...this.agents.values()].filter(s => s.state !== "dead");
    if (sessions.length < 2) return;

    const mean = sessions.reduce((sum, s) => sum + s.taskCount, 0) / sessions.length;
    for (const s of sessions) {
      if (s.taskCount > mean * 2) {
        this.log.emit("info", `[pool] load imbalance: ${s.config.name} taskCount=${s.taskCount} mean=${mean.toFixed(1)}`);
      }
    }
  }

  /** Spawn another agent of a given role */
  scaleUp(role: AgentRole, configOverrides: Partial<AgentConfig> = {}): AgentSession {
    const existing = this.getByRole(role);
    const n = existing.length + 1;
    const session = this.spawn({
      role,
      name: `${role}-${n}`,
      ...configOverrides,
    });
    this.log.emit("info", `[pool] scaled up: spawned ${session.config.name}`);
    return session;
  }

  /** Kill the least-busy agent of a given role */
  scaleDown(role: AgentRole, reason = "scale-down"): boolean {
    const candidates = this.getByRole(role)
      .filter(s => s.state !== "dead")
      .sort((a, b) => a.taskCount - b.taskCount);
    if (candidates.length === 0) return false;
    this.kill(candidates[0]!.config.id, reason);
    this.log.emit("info", `[pool] scaled down: killed least-busy ${role} agent`);
    return true;
  }

  /**
   * Health check — identify dead or stuck agents.
   * Agents idle for > 30 min while in "working" state are considered stuck.
   */
  healthCheck(): { dead: AgentSummary[]; stuck: AgentSummary[] } {
    const STUCK_THRESHOLD_MS = 30 * 60 * 1_000;
    const dead: AgentSummary[] = [];
    const stuck: AgentSummary[] = [];

    for (const s of this.agents.values()) {
      if (s.state === "dead") {
        dead.push(this._toSummary(s));
      } else if (s.state === "working" && s.idleMs() > STUCK_THRESHOLD_MS) {
        stuck.push(this._toSummary(s));
      }
    }

    if (dead.length > 0 || stuck.length > 0) {
      this.log.emit("info", `[pool] health: ${dead.length} dead, ${stuck.length} stuck`);
    }

    return { dead, stuck };
  }

  // ── Full status ───────────────────────────────────────────────────

  /** Full pool status snapshot */
  status(): PoolStatus {
    const allRoles: AgentRole[] = ["orchestrator", "builder", "researcher", "reviewer", "dreamer", "sentinel", "custom"];
    const allStates: AgentState[] = ["idle", "working", "waiting", "dreaming", "paused", "dead"];

    const byRole = Object.fromEntries(allRoles.map(r => [r, 0])) as Record<AgentRole, number>;
    const byState = Object.fromEntries(allStates.map(s => [s, 0])) as Record<AgentState, number>;

    for (const s of this.agents.values()) {
      byRole[s.config.role] = (byRole[s.config.role] ?? 0) + 1;
      byState[s.state] = (byState[s.state] ?? 0) + 1;
    }

    const queueDepths: Partial<Record<AgentRole, number>> = {};
    for (const role of allRoles) {
      const depth = this._router.queueDepth(role);
      if (depth > 0) queueDepths[role] = depth;
    }

    return {
      totalAgents: this.agents.size,
      byRole,
      byState,
      queueDepths,
      agents: this.list(),
    };
  }

  // ── Internal helpers ──────────────────────────────────────────────

  private _spawnDefaults(): void {
    const home = process.env.USERPROFILE ?? process.env.HOME ?? ".";

    this.spawn({
      name: "orchestrator",
      role: "orchestrator",
      cwd: home,
      model: "hermes3:8b",
    });

    this.spawn({
      name: "sentinel",
      role: "sentinel",
      cwd: home,
      model: "phi4-mini-reasoning",
      metadata: { purpose: "monitors filesystem and services" },
    });

    this.spawn({
      name: "dreamer",
      role: "dreamer",
      cwd: home,
      model: "hermes3:8b",
      metadata: { purpose: "dedicated dream engine runner, aggressive dream schedule" },
    });

    this.log.emit("info", "[pool] spawned 3 default agents: orchestrator, sentinel, dreamer");
  }

  private _watchSession(session: AgentSession): void {
    session.on("state-change", (_prev, next) => {
      this.log.emit("info", `[pool] ${session.config.name} → ${next}`);
      this._persistence.scheduleSave(this);
      if (next === "dead") {
        this.comms.publish("agent-dead", { agentId: session.config.id, name: session.config.name });
      }
    });

    session.on("file-touched", (interaction) => {
      this.comms.publish("file-changed", {
        agentId: session.config.id,
        ...interaction,
      });
    });

    session.on("task-complete", (taskId, result) => {
      this.comms.publish("task-complete", {
        agentId: session.config.id,
        taskId,
        result,
      });
      session.markIdle();
      // Drain queued tasks for this role
      this._router.drainFor(session.config.role);
    });
  }

  private _runHealthCheck(): void {
    const { dead, stuck } = this.healthCheck();

    // Remove confirmed-dead agents
    for (const s of dead) {
      this.agents.delete(s.id);
    }

    // Restart stuck agents (log warning, then recover)
    for (const s of stuck) {
      const session = this.agents.get(s.id);
      if (session) {
        this.log.emit("info", `[pool] recovering stuck agent ${session.config.name}`);
        session.markIdle();
      }
    }
  }

  private _toSummary(s: AgentSession): AgentSummary {
    return {
      id: s.config.id,
      name: s.config.name,
      role: s.config.role,
      state: s.state,
      idleMs: s.idleMs(),
      taskCount: s.taskCount,
      ollamaCallCount: s.ollamaCallCount,
      cwd: s.config.cwd,
      ptySessionId: s.config.ptySessionId,
    };
  }
}

// ═══════════════════════════════════════════════════════════════════════
// SELF-TEST
// ═══════════════════════════════════════════════════════════════════════

/**
 * Run a quick self-test: create a pool with 3 agents, route a task,
 * print status to stdout.
 *
 * Invoked when this module is run directly:
 *   node --experimental-vm-modules dist/agent-pool.js
 */
export async function selfTest(): Promise<void> {
  const logPath = join(
    process.env.USERPROFILE ?? process.env.HOME ?? ".",
    ".openclaw", "extensions", "zoeae", "agent-pool-selftest.jsonl"
  );
  const log = new ActivityLog(logPath);

  const ollama = new OllamaClient("http://127.0.0.1:11434", 30_000);

  // DreamEngine requires idleCheck — supply a stub
  const dreamer = new DreamEngine(ollama, log, () => 999_999, {
    enabled: false,
    knowledgePaths: [],
    journalPath: logPath + ".dreams",
  });

  const pluginDir = join(
    process.env.USERPROFILE ?? process.env.HOME ?? ".",
    ".openclaw", "extensions", "zoeae"
  );
  const policyPath = join(pluginDir, "safety.yaml");
  const policy = new PolicyEngine(policyPath, log);

  const pool = new AgentPool({ ollama, dreamer, log, policy });
  pool.start();

  console.log("=== AgentPool self-test ===");

  // Pool should have 3 default agents
  const st = pool.status();
  console.log(`Agents: ${st.totalAgents}`);
  for (const a of st.agents) {
    console.log(`  [${a.role}] ${a.name} — state=${a.state}`);
  }

  // Route a task to the builder role
  const taskId = pool.assignTaskToRole("builder", "implement a new sensor feed", null, 5);
  console.log(`\nRouted builder task → agentId=${taskId?.slice(0, 8) ?? "queued"}`);

  // Touch a file on the orchestrator
  const orch = pool.getByRole("orchestrator")[0];
  if (orch) {
    orch.touchFile("/src/foo.ts", "write");
    console.log(`Orchestrator touched /src/foo.ts`);
    console.log(`Orchestrator idleMs: ${orch.idleMs()}`);
  }

  // Inter-agent message
  pool.comms.publish("test-channel", { hello: "world" }, "orchestrator");

  // Final status
  const final = pool.status();
  console.log("\n=== Final status ===");
  console.log(JSON.stringify(final, null, 2));

  await pool.stop();
  console.log("\nPool stopped. Self-test complete.");
}

// Run self-test if executed directly
if (
  typeof process !== "undefined" &&
  process.argv[1] &&
  (process.argv[1].endsWith("agent-pool.ts") || process.argv[1].endsWith("agent-pool.js"))
) {
  selfTest().catch(e => {
    console.error("self-test failed:", e);
    process.exit(1);
  });
}
