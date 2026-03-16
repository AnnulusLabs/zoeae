/**
 * Clawtonomy — Autonomous Cognitive Agent for OpenClaw
 *
 * Full AGI toolbox: genome memory, shell execution, file I/O,
 * task queue, planning, multi-model rooms, service health,
 * background daemon, and real-time activity logging.
 *
 * Built from:
 *   AUTONOMY v3.0        — Triple-helix genome, StressCompiler, because-chains
 *   OpenClaw daemon       — Self-healing automation, task execution, agent spawning
 *   OpenClaw autonomy     — Persistent state, local AI agents, hotkey activation
 *   claude_swarm           — Multi-model coordination, hyperdimensional resonance
 *   task_queue           — Priority queues with deps, retry, status lifecycle
 *   KERF Room            — Adversarial debate, sparse-graph, Free-MAD, voting
 *   DDL_AUTORESEARCH     — Experiment runner, program.md constraints, tree search
 *
 * AnnulusLabs LLC — Taos, NM
 * "The circle must remain broken to vibrate"
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk/memory-core";
import { emptyPluginConfigSchema } from "openclaw/plugin-sdk/memory-core";
import { AutonomyClient, type GenomeStats } from "./src/autonomy-client.js";
import { OllamaClient } from "./src/ollama-client.js";
import { Room, ROOM_MODES, type RoomResponse } from "./src/room-engine.js";
import { ActivityLog } from "./src/activity-log.js";
import { shellExec, readFile, writeFile, appendToFile, listDir, fileExists, fileInfo, deleteFile } from "./src/executor.js";
import { TaskEngine, type Task } from "./src/task-engine.js";
import { Planner } from "./src/planner.js";
import { checkAllServices, restartService, formatServiceStatus } from "./src/services.js";
import { Daemon } from "./src/daemon.js";
import { McpServer } from "./src/mcp-server.js";
import { Dashboard } from "./src/dashboard.js";
import { join } from "node:path";

// ═══════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════

type ClawConfig = {
  autonomyUrl: string;
  bootTier: number;
  maxTokens: number;
  autoConsolidate: boolean;
  recordTurns: boolean;
  injectNucleus: boolean;
  injectTasks: boolean;
  injectPlan: boolean;
  injectServices: boolean;
  daemonAutoStart: boolean;
  daemonIntervalMs: number;
  ollamaUrl: string;
  ollamaTimeoutMs: number;
  breadthModel: string;
  depthModel: string;
  defaultModel: string;
  activityLogEnabled: boolean;
  mcpEnabled: boolean;
  mcpPort: number;
  dashboardEnabled: boolean;
  dashboardPort: number;
};

function resolveConfig(raw?: Record<string, unknown>): ClawConfig {
  return {
    autonomyUrl: String(raw?.autonomyUrl ?? process.env.AUTONOMY_URL ?? "http://127.0.0.1:8766"),
    bootTier: Number(raw?.bootTier ?? 0),
    maxTokens: Number(raw?.maxTokens ?? 0),
    autoConsolidate: raw?.autoConsolidate !== false,
    recordTurns: raw?.recordTurns !== false,
    injectNucleus: raw?.injectNucleus !== false,
    injectTasks: raw?.injectTasks !== false,
    injectPlan: raw?.injectPlan !== false,
    injectServices: raw?.injectServices !== false,
    daemonAutoStart: raw?.daemonAutoStart === true,
    daemonIntervalMs: Number(raw?.daemonIntervalMs ?? 300_000),
    ollamaUrl: String(raw?.ollamaUrl ?? process.env.OLLAMA_API ?? "http://127.0.0.1:11434"),
    ollamaTimeoutMs: Number(raw?.ollamaTimeoutMs ?? 120_000),
    breadthModel: String(raw?.breadthModel ?? "hermes3:8b"),
    depthModel: String(raw?.depthModel ?? "deepseek-r1:32b"),
    defaultModel: String(raw?.defaultModel ?? "hermes3:8b"),
    activityLogEnabled: raw?.activityLogEnabled !== false,
    mcpEnabled: raw?.mcpEnabled === true,
    mcpPort: Number(raw?.mcpPort ?? 8768),
    dashboardEnabled: raw?.dashboardEnabled === true,
    dashboardPort: Number(raw?.dashboardPort ?? 8769),
  };
}

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════

function formatStats(s: GenomeStats): string {
  return [
    `Nodes: ${s.total_nodes} (${s.active} active, ${s.load_bearing} LB, ${s.stale} stale)`,
    `Edges: ${s.edges} (${s.edges_with_because} because, ${s.because_coverage} coverage)`,
    `Domains: ${s.domains} [${s.domain_list.join(", ")}]`,
    `Bridges: ${s.bridges}`,
  ].join("\n");
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "..." : s;
}

function formatRoomResponse(resp: RoomResponse): string {
  const name = resp.model.split("/").pop()?.split(":")[0] ?? resp.model;
  const tag = resp.tag ? ` [${resp.tag}]` : "";
  return `**${name}${tag}**: ${resp.text}`;
}

const WORKSPACE = join(process.env.HOME ?? process.env.USERPROFILE ?? ".", ".openclaw", "workspace");

// ═══════════════════════════════════════════════════════════════
// PLUGIN REGISTRATION
// ═══════════════════════════════════════════════════════════════

const clawtonomy = {
  id: "clawtonomy",
  name: "Clawtonomy",
  description: "Autonomous cognitive agent — genome memory, shell execution, task queue, multi-model rooms, planning, service monitoring, background daemon",
  kind: "tool" as const,
  configSchema: emptyPluginConfigSchema(),

  register(api: OpenClawPluginApi) {
    // ── Lazy singletons ──────────────────────────────────
    let _cfg: ClawConfig | null = null;
    let _client: AutonomyClient | null = null;
    let _ollama: OllamaClient | null = null;
    let _room: Room | null = null;
    let _tasks: TaskEngine | null = null;
    let _planner: Planner | null = null;
    let _daemon: Daemon | null = null;
    let _log: ActivityLog | null = null;
    let _mcp: McpServer | null = null;
    let _dashboard: Dashboard | null = null;

    function getCfg(): ClawConfig {
      if (!_cfg) _cfg = resolveConfig(api.config as Record<string, unknown> | undefined);
      return _cfg;
    }
    function getClient(): AutonomyClient {
      if (!_client) _client = new AutonomyClient({ baseUrl: getCfg().autonomyUrl });
      return _client;
    }
    function getOllama(): OllamaClient {
      if (!_ollama) _ollama = new OllamaClient(getCfg().ollamaUrl, getCfg().ollamaTimeoutMs);
      return _ollama;
    }
    function getLog(): ActivityLog {
      if (!_log) _log = new ActivityLog(join(WORKSPACE, "activity.jsonl"));
      return _log;
    }
    function getTasks(): TaskEngine {
      if (!_tasks) _tasks = new TaskEngine(join(WORKSPACE, ".clawtonomy", "tasks.json"));
      return _tasks;
    }
    function getPlanner(): Planner {
      if (!_planner) _planner = new Planner(
        join(WORKSPACE, ".clawtonomy", "plans.json"),
        getCfg().ollamaUrl,
        getCfg().breadthModel,
        getCfg().depthModel,
      );
      return _planner;
    }
    function getDaemon(): Daemon {
      if (!_daemon) _daemon = new Daemon(getTasks(), getClient(), getLog(), {
        enabled: getCfg().daemonAutoStart,
        intervalMs: getCfg().daemonIntervalMs,
        ollamaUrl: getCfg().ollamaUrl,
        defaultModel: getCfg().defaultModel,
      });
      return _daemon;
    }

    async function getNucleus(): Promise<string> {
      const client = getClient();
      if (!(await client.ping())) return "";
      try {
        const { nucleus } = await client.boot(getCfg().bootTier, getCfg().maxTokens);
        return nucleus?.trim() ?? "";
      } catch { return ""; }
    }

    const ROOM_FILE = join(WORKSPACE, ".kerf", "rooms", "default.json");

    function getRoom(): Room {
      if (!_room) {
        const cfg = getCfg();
        const roomCfg = { ollamaUrl: cfg.ollamaUrl, ollamaTimeoutMs: cfg.ollamaTimeoutMs };
        _room = Room.load(ROOM_FILE, roomCfg, getNucleus) ?? new Room("default", roomCfg, getNucleus);
      }
      return _room;
    }
    function saveRoom(): void {
      if (_room) _room.save(ROOM_FILE);
    }

    // ═══════════════════════════════════════════════════════
    // HOOKS
    // ═══════════════════════════════════════════════════════

    // ─── agent:bootstrap → inject NUCLEUS + tasks + plan + service status ───
    api.registerHook("agent:bootstrap", { name: "clawtonomy:bootstrap" }, async (event) => {
      const cfg = getCfg();
      const ctx = event.context as { bootstrapFiles?: Array<{ path: string; content: string }> };
      if (!ctx.bootstrapFiles) return;
      const sections: string[] = [];

      // Genome NUCLEUS
      if (cfg.injectNucleus) {
        try {
          const client = getClient();
          if (await client.ping()) {
            const { nucleus } = await client.boot(cfg.bootTier, cfg.maxTokens);
            if (nucleus?.trim()) {
              sections.push("# Cognitive Genome (NUCLEUS)\n\nCompiled memory from previous sessions. Because-chains are load-bearing causal knowledge.\n\n```\n" + nucleus + "\n```");
            }
          }
        } catch { /* genome unavailable */ }
      }

      // Pending tasks
      if (cfg.injectTasks) {
        try {
          const tasks = getTasks();
          const pending = tasks.list({ status: "pending" });
          const running = tasks.list({ status: "running" });
          if (pending.length > 0 || running.length > 0) {
            const lines = ["# Pending Tasks\n"];
            if (running.length > 0) {
              lines.push("## In Progress");
              lines.push(tasks.format(running));
            }
            if (pending.length > 0) {
              lines.push("## Queued");
              lines.push(tasks.format(pending.slice(0, 10)));
              if (pending.length > 10) lines.push(`... and ${pending.length - 10} more`);
            }
            sections.push(lines.join("\n"));
          }
        } catch { /* silent */ }
      }

      // Active plan
      if (cfg.injectPlan) {
        try {
          const planner = getPlanner();
          const active = planner.active();
          if (active) {
            sections.push("# Active Plan\n\n" + planner.summarize(active.id));
          }
        } catch { /* silent */ }
      }

      // Service health
      if (cfg.injectServices) {
        try {
          const statuses = await checkAllServices();
          const down = statuses.filter((s) => !s.healthy);
          if (down.length > 0) {
            sections.push("# Service Alerts\n\n" + formatServiceStatus(down));
          }
        } catch { /* silent */ }
      }

      if (sections.length > 0) {
        ctx.bootstrapFiles.push({
          path: "CLAWTONOMY.md",
          content: sections.join("\n\n---\n\n"),
        });
      }

      getLog().emit("genome_event", `bootstrap injected ${sections.length} sections`);
    });

    // ─── message:received → record user turn + proactive context injection ───
    let _firstMessageInjected = false;

    api.registerHook("message:received", { name: "clawtonomy:record-user" }, async (event) => {
      const ctx = event.context as {
        content?: string;
        bootstrapFiles?: Array<{ path: string; content: string }>;
      };
      if (!ctx.content) return;

      // Record turn
      if (getCfg().recordTurns) {
        try { await getClient().record("user", truncate(ctx.content, 4000)); } catch { /* silent */ }
      }

      // Upgrade #4: Touch daemon idle tracker
      try { getDaemon().touchActivity(); } catch { /* daemon may not be started */ }

      // Upgrade #3: Proactive context injection on first message
      // On the FIRST user message of a session, extract topic keywords
      // and inject domain-specific genome facts as supplementary context
      if (!_firstMessageInjected && ctx.bootstrapFiles) {
        _firstMessageInjected = true;
        try {
          const client = getClient();
          if (!(await client.ping())) return;

          // Extract keywords from first message (simple: take significant words)
          const words = ctx.content
            .toLowerCase()
            .replace(/[^a-z0-9\s]/g, "")
            .split(/\s+/)
            .filter((w) => w.length > 3);
          const query = words.slice(0, 5).join(" ");

          if (!query) return;

          const { results } = await client.searchFacts(query, 15);
          if (results && results.length > 0) {
            const facts = results
              .map((r) => `- [${r.domain ?? "?"}${r.tier ? `/${r.tier}` : ""}] ${r.content}`)
              .join("\n");

            ctx.bootstrapFiles.push({
              path: "CONTEXT.md",
              content: [
                "# Proactive Context (genome search)",
                "",
                `Matched ${results.length} facts for: "${query}"`,
                "",
                facts,
              ].join("\n"),
            });

            getLog().emit("genome_event", `proactive inject: ${results.length} facts for "${query}"`);
          }
        } catch { /* proactive injection is best-effort */ }
      }
    });

    // ─── message:sent → record assistant turn ───
    api.registerHook("message:sent", { name: "clawtonomy:record-assistant" }, async (event) => {
      if (!getCfg().recordTurns) return;
      const ctx = event.context as { content?: string };
      if (!ctx.content) return;
      try { await getClient().record("assistant", truncate(ctx.content, 4000)); } catch { /* silent */ }
    });

    // ─── command:new / command:reset → consolidate + save state ───
    api.registerHook("command:new", { name: "clawtonomy:consolidate-new" }, async () => {
      _firstMessageInjected = false; // reset for next session
      if (!getCfg().autoConsolidate) return;
      try { await getClient().consolidate(true); } catch { /* silent */ }
      try { getTasks().save(); } catch { /* silent */ }
      try { getPlanner().save(); } catch { /* silent */ }
      getLog().emit("genome_event", "session end: consolidated + saved state");
    });

    api.registerHook("command:reset", { name: "clawtonomy:consolidate-reset" }, async () => {
      _firstMessageInjected = false; // reset for next session
      if (!getCfg().autoConsolidate) return;
      try { await getClient().consolidate(true); } catch { /* silent */ }
      try { getTasks().save(); } catch { /* silent */ }
      try { getPlanner().save(); } catch { /* silent */ }
      getLog().emit("genome_event", "session reset: consolidated + saved state");
    });

    // ─── gateway:startup → health check + daemon ───
    api.registerHook("gateway:startup", { name: "clawtonomy:startup" }, async () => {
      getLog().emit("info", "clawtonomy loaded");

      // Health check
      try {
        const statuses = await checkAllServices();
        for (const s of statuses) {
          getLog().emit("service_check", `${s.name}: ${s.healthy ? "UP" : "DOWN"} (${s.latencyMs}ms)`);
        }
      } catch { /* silent */ }

      // Auto-start daemon
      if (getCfg().daemonAutoStart) {
        getDaemon().start();
      }

      // Upgrade #5: Start MCP server
      if (getCfg().mcpEnabled) {
        try {
          _mcp = new McpServer({ port: getCfg().mcpPort });
          // TODO: register all tools into MCP after they're defined
          // For now, MCP starts and tools are registered below in a deferred init
          _mcp.start();
          getLog().emit("info", `MCP server started on port ${getCfg().mcpPort}`);
        } catch (e) { getLog().emit("error", `MCP start failed: ${e}`); }
      }

      // Upgrade #8: Start telemetry dashboard
      if (getCfg().dashboardEnabled) {
        try {
          _dashboard = new Dashboard({
            port: getCfg().dashboardPort,
            host: "127.0.0.1",
            activityLogPath: join(WORKSPACE, "activity.jsonl"),
          });
          _dashboard.start();
          getLog().emit("info", `Dashboard started at http://127.0.0.1:${getCfg().dashboardPort}/`);
        } catch (e) { getLog().emit("error", `Dashboard start failed: ${e}`); }
      }
    });

    // ═══════════════════════════════════════════════════════
    // TOOLS — Shell & Files
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "shell",
        description:
          "Execute a shell command on the host OS. Returns stdout, stderr, exit code. " +
          "Uses PowerShell on Windows, bash on Linux. Timeout default 30s.",
        parameters: {
          type: "object" as const,
          properties: {
            command: { type: "string", description: "Shell command to execute" },
            cwd: { type: "string", description: "Working directory (optional)" },
            timeout_ms: { type: "number", description: "Timeout in ms (default 30000)" },
          },
          required: ["command"],
        },
        async execute(args: { command: string; cwd?: string; timeout_ms?: number }) {
          const result = await shellExec(args.command, {
            timeoutMs: args.timeout_ms,
            cwd: args.cwd,
            log: getLog(),
          });
          return {
            content: [
              `Exit: ${result.exitCode}${result.timedOut ? " (TIMEOUT)" : ""} | ${result.durationMs}ms`,
              result.stdout ? `\nSTDOUT:\n${result.stdout}` : "",
              result.stderr ? `\nSTDERR:\n${result.stderr}` : "",
            ].filter(Boolean).join(""),
          };
        },
      }),
      { names: ["shell"] },
    );

    api.registerTool(
      () => ({
        name: "file",
        description:
          "File operations: read, write, append, list, info, delete. " +
          "Use this for all file I/O on the host filesystem.",
        parameters: {
          type: "object" as const,
          properties: {
            action: { type: "string", description: "read|write|append|list|info|delete" },
            path: { type: "string", description: "File or directory path" },
            content: { type: "string", description: "Content for write/append" },
          },
          required: ["action", "path"],
        },
        async execute(args: { action: string; path: string; content?: string }) {
          try {
            switch (args.action) {
              case "read":
                return { content: readFile(args.path, getLog()) };
              case "write":
                writeFile(args.path, args.content ?? "", getLog());
                return { content: `Written ${(args.content ?? "").length} chars to ${args.path}` };
              case "append":
                appendToFile(args.path, args.content ?? "", getLog());
                return { content: `Appended ${(args.content ?? "").length} chars to ${args.path}` };
              case "list": {
                const entries = listDir(args.path);
                return { content: entries.map((e) => `${e.isDir ? "[DIR]" : `${e.size}B`} ${e.name}`).join("\n") || "Empty directory." };
              }
              case "info": {
                const info = fileInfo(args.path);
                return { content: info ? `${info.isDir ? "DIR" : "FILE"} | ${info.size}B | Modified: ${info.modified}` : "Not found." };
              }
              case "delete":
                return { content: deleteFile(args.path, getLog()) ? `Deleted ${args.path}` : `Not found: ${args.path}` };
              default:
                return { content: `Unknown action: ${args.action}. Use: read, write, append, list, info, delete` };
            }
          } catch (err) { return { content: `File error: ${err}` }; }
        },
      }),
      { names: ["file"] },
    );

    // ═══════════════════════════════════════════════════════
    // TOOLS — Task Queue
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "task",
        description:
          "Persistent task queue with priorities and dependencies. " +
          "Actions: add, list, next, start, complete, fail, block, unblock, remove, stats, clear. " +
          "Tasks persist across sessions. The daemon can auto-process shell and prompt tasks.",
        parameters: {
          type: "object" as const,
          properties: {
            action: { type: "string", description: "add|list|next|start|complete|fail|block|unblock|remove|stats|clear" },
            id: { type: "string", description: "Task ID (for start/complete/fail/block/unblock/remove)" },
            name: { type: "string", description: "Task name (for add)" },
            description: { type: "string", description: "Task description (for add)" },
            command: { type: "string", description: "Shell command (for add, type=shell)" },
            type: { type: "string", description: "shell|prompt|research|experiment|delegate|manual (for add)" },
            priority: { type: "number", description: "1-5, 1=critical (for add)" },
            depends_on: { type: "string", description: "Comma-separated task IDs this depends on (for add)" },
            model: { type: "string", description: "Preferred model (for add, type=prompt|research)" },
            tags: { type: "string", description: "Comma-separated tags (for add)" },
            result: { type: "string", description: "Result text (for complete)" },
            error: { type: "string", description: "Error text (for fail)" },
            status: { type: "string", description: "Filter by status (for list)" },
          },
          required: ["action"],
        },
        async execute(args: Record<string, string | number | undefined>) {
          const tasks = getTasks();
          const log = getLog();

          switch (args.action) {
            case "add": {
              if (!args.name || !args.description) return { content: "Need name and description." };
              const task = tasks.add({
                name: String(args.name),
                description: String(args.description),
                command: args.command ? String(args.command) : undefined,
                taskType: (args.type as Task["taskType"]) ?? "manual",
                priority: args.priority ? Number(args.priority) as 1|2|3|4|5 : undefined,
                dependsOn: args.depends_on ? String(args.depends_on).split(",").map((s) => s.trim()) : undefined,
                model: args.model ? String(args.model) : undefined,
                tags: args.tags ? String(args.tags).split(",").map((s) => s.trim()) : undefined,
              });
              log.emit("task_event", `added: ${task.name} (${task.id})`);
              return { content: `Added: ${task.id} — ${task.name} (P${task.priority} ${task.taskType})` };
            }
            case "list": {
              const filter = args.status ? { status: String(args.status) as any } : undefined;
              return { content: tasks.format(tasks.list(filter)) };
            }
            case "next": {
              const next = tasks.next();
              return { content: next ? `Next: ${next.id} — ${next.name} (P${next.priority} ${next.taskType})` : "No ready tasks." };
            }
            case "start":
              return { content: tasks.start(String(args.id)) ? `Started: ${args.id}` : `Can't start: ${args.id}` };
            case "complete":
              return { content: tasks.complete(String(args.id), String(args.result ?? "Done")) ? `Completed: ${args.id}` : `Not found: ${args.id}` };
            case "fail":
              return { content: tasks.fail(String(args.id), String(args.error ?? "Unknown error")) ? `Failed: ${args.id}` : `Not found: ${args.id}` };
            case "block":
              return { content: tasks.block(String(args.id), String(args.error ?? "Blocked")) ? `Blocked: ${args.id}` : `Not found: ${args.id}` };
            case "unblock":
              return { content: tasks.unblock(String(args.id)) ? `Unblocked: ${args.id}` : `Not found: ${args.id}` };
            case "remove":
              return { content: tasks.remove(String(args.id)) ? `Removed: ${args.id}` : `Not found: ${args.id}` };
            case "stats": {
              const s = tasks.stats();
              return { content: `Tasks: ${s.total} total | ${s.pending} pending | ${s.running} running | ${s.completed} done | ${s.failed} failed | ${s.blocked} blocked` };
            }
            case "clear":
              return { content: `Cleared ${tasks.clearCompleted()} completed tasks.` };
            default:
              return { content: `Unknown action: ${args.action}` };
          }
        },
      }),
      { names: ["task"] },
    );

    // ═══════════════════════════════════════════════════════
    // TOOLS — Planning
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "plan",
        description:
          "Goal decomposition and tracking. Uses local models (breadth model for decomposition, " +
          "depth model for expansion). Tree search: steps can be expanded into sub-steps. " +
          "Actions: create, list, active, get, expand, update, abandon, summarize.",
        parameters: {
          type: "object" as const,
          properties: {
            action: { type: "string", description: "create|list|active|get|expand|update|abandon|summarize" },
            goal: { type: "string", description: "Goal to decompose (for create)" },
            context: { type: "string", description: "Additional context (for create)" },
            plan_id: { type: "string", description: "Plan ID" },
            step_id: { type: "string", description: "Step ID (for update/expand)" },
            status: { type: "string", description: "pending|in_progress|completed|skipped (for update)" },
            notes: { type: "string", description: "Notes for step (for update)" },
          },
          required: ["action"],
        },
        async execute(args: Record<string, string | undefined>) {
          const planner = getPlanner();
          const log = getLog();

          switch (args.action) {
            case "create": {
              if (!args.goal) return { content: "Need a goal." };
              log.emit("plan_event", `decomposing: ${args.goal.slice(0, 80)}`);
              const plan = await planner.decompose(String(args.goal), args.context);
              log.emit("plan_event", `plan created: ${plan.id} with ${plan.steps.length} steps`);
              return {
                content: [
                  `Plan: ${plan.id}`,
                  `Goal: ${plan.goal}`,
                  "",
                  ...plan.steps.map((s, i) => `  ${i + 1}. [${s.status}] ${s.description}`),
                ].join("\n"),
              };
            }
            case "list": {
              const plans = planner.list(args.status as any);
              if (plans.length === 0) return { content: "No plans." };
              return { content: plans.map((p) => `${p.id} [${p.status}] ${p.goal.slice(0, 60)} (${p.steps.length} steps)`).join("\n") };
            }
            case "active": {
              const active = planner.active();
              return { content: active ? planner.summarize(active.id) : "No active plan." };
            }
            case "get": {
              const plan = planner.get(String(args.plan_id));
              if (!plan) return { content: "Not found." };
              return {
                content: [
                  `Plan: ${plan.id} [${plan.status}]`,
                  `Goal: ${plan.goal}`,
                  "",
                  ...plan.steps.map((s) => {
                    const children = s.children ? ` → [${s.children.join(",")}]` : "";
                    return `  ${s.id} [${s.status}] ${s.description}${children}`;
                  }),
                ].join("\n"),
              };
            }
            case "expand": {
              if (!args.plan_id || !args.step_id) return { content: "Need plan_id and step_id." };
              log.emit("plan_event", `expanding step ${args.step_id}`);
              const plan = await planner.expand(String(args.plan_id), String(args.step_id));
              if (!plan) return { content: "Not found." };
              return { content: `Expanded. Steps now: ${plan.steps.length}\n${plan.steps.filter((s) => s.id.startsWith(args.step_id!)).map((s) => `  ${s.id} ${s.description}`).join("\n")}` };
            }
            case "update": {
              if (!args.plan_id || !args.step_id) return { content: "Need plan_id and step_id." };
              const update: any = {};
              if (args.status) update.status = args.status;
              if (args.notes) update.notes = args.notes;
              const plan = planner.updateStep(String(args.plan_id), String(args.step_id), update);
              return { content: plan ? `Updated ${args.step_id} → ${args.status ?? "noted"}` : "Not found." };
            }
            case "abandon":
              return { content: planner.abandon(String(args.plan_id)) ? `Abandoned ${args.plan_id}` : "Not found." };
            case "summarize":
              return { content: planner.summarize(String(args.plan_id)) };
            default:
              return { content: `Unknown action: ${args.action}` };
          }
        },
      }),
      { names: ["plan"] },
    );

    // ═══════════════════════════════════════════════════════
    // TOOLS — Delegation (send work to local models)
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "delegate",
        description:
          "Send a task to a specific local Ollama model. Use this to offload work " +
          "to the local bot army instead of using your own tokens. " +
          "Good for: research, code review, summarization, translation, analysis.",
        parameters: {
          type: "object" as const,
          properties: {
            prompt: { type: "string", description: "The prompt to send" },
            model: { type: "string", description: "Model name (default: hermes3:8b)" },
            system: { type: "string", description: "Optional system prompt" },
          },
          required: ["prompt"],
        },
        async execute(args: { prompt: string; model?: string; system?: string }) {
          const model = args.model ?? getCfg().defaultModel;
          const log = getLog();
          log.emit("delegate", `→ ${model}: ${args.prompt.slice(0, 80)}...`);

          const messages: Array<{ role: "system" | "user"; content: string }> = [];
          if (args.system) messages.push({ role: "system", content: args.system });
          messages.push({ role: "user", content: args.prompt });

          const result = await getOllama().chat(model, messages);
          log.emit("delegate_result", `← ${model}: ${result.slice(0, 80)}...`, { durationMs: 0 });
          return { content: `[${model}]: ${result}` };
        },
      }),
      { names: ["delegate"] },
    );

    // ═══════════════════════════════════════════════════════
    // TOOLS — Services
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "services",
        description:
          "Check health of local services (AUTONOMY, Ollama, etc.) and restart them. " +
          "Actions: status, restart.",
        parameters: {
          type: "object" as const,
          properties: {
            action: { type: "string", description: "status|restart" },
            name: { type: "string", description: "Service name (for restart)" },
          },
          required: ["action"],
        },
        async execute(args: { action: string; name?: string }) {
          switch (args.action) {
            case "status": {
              const statuses = await checkAllServices();
              getLog().emit("service_check", `checked ${statuses.length} services`);
              return { content: formatServiceStatus(statuses) };
            }
            case "restart": {
              if (!args.name) return { content: "Need service name." };
              const result = await restartService(args.name, getLog());
              return { content: result };
            }
            default:
              return { content: `Unknown action: ${args.action}. Use: status, restart` };
          }
        },
      }),
      { names: ["services"] },
    );

    // ═══════════════════════════════════════════════════════
    // TOOLS — Daemon
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "daemon",
        description:
          "Control the autonomous background daemon. " +
          "When running, it processes the task queue, monitors service health, " +
          "auto-restarts dead services, and periodically consolidates the genome. " +
          "Actions: start, stop, status, tick (run one cycle manually).",
        parameters: {
          type: "object" as const,
          properties: {
            action: { type: "string", description: "start|stop|status|tick" },
          },
          required: ["action"],
        },
        async execute(args: { action: string }) {
          const daemon = getDaemon();
          switch (args.action) {
            case "start":
              return { content: daemon.start() ? "Daemon started." : "Daemon already running." };
            case "stop":
              return { content: daemon.stop() ? "Daemon stopped." : "Daemon not running." };
            case "status": {
              const s = daemon.status();
              return { content: `Daemon: ${s.running ? "RUNNING" : "STOPPED"} | Ticks: ${s.tickCount} | Interval: ${s.config.intervalMs / 1000}s` };
            }
            case "tick": {
              const result = await daemon.tick();
              return { content: `Tick: ${result.health} services healthy, ${result.tasksProcessed} tasks processed${result.consolidated ? ", genome consolidated" : ""}` };
            }
            default:
              return { content: `Unknown action: ${args.action}. Use: start, stop, status, tick` };
          }
        },
      }),
      { names: ["daemon"] },
    );

    // ═══════════════════════════════════════════════════════
    // TOOLS — Genome (from original)
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "genome_search",
        description:
          "Search the persistent cognitive genome for knowledge from previous sessions. " +
          "Returns nodes with because-chain relationships. Use when user references past work.",
        parameters: {
          type: "object" as const,
          properties: {
            query: { type: "string", description: "Search term" },
            tier: { type: "number", description: "0=NUCLEUS 1=CELL 2=ORGANISM 3=ECOSYSTEM", default: 0 },
          },
          required: ["query"],
        },
        async execute(args: { query: string; tier?: number }) {
          try {
            const client = getClient();
            if (!(await client.ping())) return { content: "AUTONOMY not running. Use: services restart autonomy" };
            const { compiled } = await client.compile(args.tier ?? 0);
            const stats = await client.stats();
            const q = args.query.toLowerCase();
            const lines = compiled.split("\n");
            const matched = lines.filter((l) => l.toLowerCase().includes(q) || l.includes("\u2235"));
            getLog().emit("genome_event", `search "${args.query}" → ${matched.length} hits`);
            return {
              content: [
                `Genome: ${stats.total_nodes}N ${stats.edges}E ${stats.because_coverage} because`,
                `Query: "${args.query}" (tier ${args.tier ?? 0})`,
                "",
                matched.length > 0 ? matched.join("\n") : compiled,
              ].join("\n"),
            };
          } catch (err) { return { content: `Genome search failed: ${err}` }; }
        },
      }),
      { names: ["genome_search"] },
    );

    api.registerTool(
      () => ({
        name: "genome_stats",
        description: "Show cognitive genome health: nodes, edges, because coverage, domains, bridges.",
        parameters: { type: "object" as const, properties: {} },
        async execute() {
          try {
            const client = getClient();
            if (!(await client.ping())) return { content: "AUTONOMY not running." };
            return { content: formatStats(await client.stats()) };
          } catch (err) { return { content: `Stats failed: ${err}` }; }
        },
      }),
      { names: ["genome_stats"] },
    );

    api.registerTool(
      () => ({
        name: "genome_ccm",
        description:
          "Compute Avnir Continuous Chirality Measure on a PDB structure. Provide 4-char PDB ID.",
        parameters: {
          type: "object" as const,
          properties: {
            pdb_id: { type: "string", description: "4-character PDB ID (e.g. 1MUC, 3NJP)" },
          },
          required: ["pdb_id"],
        },
        async execute(args: { pdb_id: string }) {
          try {
            const r = await getClient().computeCcm(args.pdb_id);
            return { content: r.success ? `PDB ${args.pdb_id}: CCM = ${r.ccm}` : `CCM failed: ${r.error}` };
          } catch (err) { return { content: `CCM failed: ${err}` }; }
        },
      }),
      { names: ["genome_ccm"] },
    );

    // ═══════════════════════════════════════════════════════
    // TOOLS — Room (enhanced with new modes)
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "room_query",
        description:
          "Send a prompt to the multi-model room. Modes: " +
          "parallel (all at once), adversarial (answer → critique → rebuttal), " +
          "round-robin (sequential), snowball (each builds on previous), " +
          "sparse-debate (ring topology, 41% cheaper, same accuracy), " +
          "free-mad (no forced consensus, trajectory scoring, 13-16% better), " +
          "vote (majority wins, best for reasoning). " +
          "Anti-sycophancy: each model gets a different reasoning method.",
        parameters: {
          type: "object" as const,
          properties: {
            prompt: { type: "string", description: "The prompt to send to all room models" },
            mode: { type: "string", description: "Override mode for this query, or 'auto' for auto-selection" },
            task_type: { type: "string", description: "Task type for auto-mode: reasoning, creative, review, research, validation, general" },
          },
          required: ["prompt"],
        },
        async execute(args: { prompt: string; mode?: string; task_type?: string }) {
          try {
            const room = getRoom();
            if (room.models.length === 0) return { content: "No models in room. Use room_manage to add models." };
            const prevMode = room.mode;

            // Upgrade #6: Auto-select mode based on task type
            if (args.mode === "auto" && args.task_type) {
              const autoMode = Room.autoMode(args.task_type);
              room.setMode(autoMode);
              getLog().emit("info", `room auto-mode: ${args.task_type} → ${autoMode}`);
            } else if (args.mode && ROOM_MODES.includes(args.mode as any)) {
              room.setMode(args.mode);
            }
            getLog().emit("delegate", `room query [${args.mode ?? room.mode}] → ${room.models.length} models`);
            const responses = await room.query(args.prompt);
            if (args.mode) room.mode = prevMode;
            saveRoom();
            getLog().emit("delegate_result", `room returned ${responses.length} responses`);
            return {
              content: [
                `Room "${room.name}" | Mode: ${args.mode ?? room.mode} | Models: ${room.models.length}`,
                "",
                ...responses.map(formatRoomResponse),
              ].join("\n\n"),
            };
          } catch (err) { return { content: `Room query failed: ${err}` }; }
        },
      }),
      { names: ["room_query"] },
    );

    api.registerTool(
      () => ({
        name: "room_manage",
        description:
          "Manage the multi-model room: add/remove models, set mode, list models, show status. " +
          "Actions: add, remove, mode, list, models, status.",
        parameters: {
          type: "object" as const,
          properties: {
            action: { type: "string", description: "add|remove|mode|list|models|status" },
            value: { type: "string", description: "Model name or mode name" },
          },
          required: ["action"],
        },
        async execute(args: { action: string; value?: string }) {
          try {
            const room = getRoom();
            const ollama = getOllama();

            switch (args.action) {
              case "add": {
                if (!args.value) return { content: "Specify model name." };
                const available = await ollama.listModels();
                const match = available.find((m) => m.name.includes(args.value!) || args.value!.includes(m.name));
                if (match) {
                  room.addModel(match.name);
                  saveRoom();
                  return { content: `Added ${match.name}. Models: [${room.models.join(", ")}]` };
                }
                room.addModel(args.value);
                saveRoom();
                return { content: `Added ${args.value}. Models: [${room.models.join(", ")}]` };
              }
              case "remove": {
                if (!args.value) return { content: "Specify model." };
                const removed = room.removeModel(args.value);
                if (removed) saveRoom();
                return { content: removed ? `Removed ${removed}. Models: [${room.models.join(", ")}]` : `Not found: ${args.value}` };
              }
              case "mode": {
                if (!args.value) return { content: `Mode: ${room.mode}. Options: ${ROOM_MODES.join(", ")}` };
                if (room.setMode(args.value)) { saveRoom(); return { content: `Mode: ${room.mode}` }; }
                return { content: `Invalid. Options: ${ROOM_MODES.join(", ")}` };
              }
              case "list":
              case "active":
                return { content: room.models.length > 0 ? `Models: [${room.models.join(", ")}]\nMode: ${room.mode}` : "Room empty. Add models with action=add." };
              case "models": {
                const available = await ollama.listModels();
                const lines = available.map((m) => {
                  const inRoom = room.models.includes(m.name) ? " [IN ROOM]" : "";
                  return `  ${m.name} (${m.parameter_size ?? "?"})${inRoom}`;
                });
                return { content: `Available:\n${lines.join("\n")}\n\n${available.length} models` };
              }
              case "status":
                return {
                  content: [
                    `Room: ${room.name}`,
                    `Mode: ${room.mode}`,
                    `Models: [${room.models.join(", ")}]`,
                    `History: ${room.history.length} entries`,
                    `Nucleus: ${room.nucleus ? `${room.nucleus.length} chars` : "not loaded"}`,
                  ].join("\n"),
                };
              default:
                return { content: `Unknown: ${args.action}. Use: add, remove, mode, list, models, status` };
            }
          } catch (err) { return { content: `Room error: ${err}` }; }
        },
      }),
      { names: ["room_manage"] },
    );

    // ═══════════════════════════════════════════════════════
    // TOOLS — Activity & Reflection
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "activity",
        description:
          "View the real-time activity log — what you've been doing, tool calls, " +
          "file reads, shell commands, delegation results. Like Claude Code's terminal output.",
        parameters: {
          type: "object" as const,
          properties: {
            lines: { type: "number", description: "Number of recent entries (default 20)" },
            kind: { type: "string", description: "Filter by kind: tool_call, shell_exec, delegate, task_event, etc." },
          },
        },
        async execute(args: { lines?: number; kind?: string }) {
          try {
            const logPath = join(WORKSPACE, "activity.jsonl");
            const content = readFile(logPath);
            let entries = content.trim().split("\n").filter(Boolean).map((l) => {
              try { return JSON.parse(l); } catch { return null; }
            }).filter(Boolean);
            if (args.kind) entries = entries.filter((e: any) => e.kind === args.kind);
            const recent = entries.slice(-(args.lines ?? 20));
            return {
              content: recent.map((e: any) => {
                const ts = e.ts?.slice(11, 19) ?? "??:??:??";
                const dur = e.durationMs ? ` (${e.durationMs}ms)` : "";
                return `${ts} [${e.kind}] ${e.summary}${dur}`;
              }).join("\n") || "No activity yet.",
            };
          } catch { return { content: "No activity log yet." }; }
        },
      }),
      { names: ["activity"] },
    );

    api.registerTool(
      () => ({
        name: "reflect",
        description:
          "Store a structured learning directly into the cognitive genome as a first-class fact " +
          "with because-chain, domain tag, and confidence score. Not a conversation turn — " +
          "a real genome node. Use after completing work to record what worked/failed and why.",
        parameters: {
          type: "object" as const,
          properties: {
            observation: { type: "string", description: "What happened — becomes genome fact content" },
            because: { type: "string", description: "Why it matters — becomes because-chain edge" },
            domain: { type: "string", description: "Knowledge domain (code, ml, infra, research, multi-agent, etc.)" },
            confidence: { type: "number", description: "0.0-1.0 confidence score (default 0.8, decays via pit crew)" },
          },
          required: ["observation"],
        },
        async execute(args: { observation: string; because?: string; domain?: string; confidence?: number }) {
          const log = getLog();
          const entry = args.because
            ? `${args.observation} ∵ ${args.because}`
            : args.observation;

          log.emit("genome_event", `reflect: ${entry.slice(0, 80)}`);

          try {
            const client = getClient();
            if (!(await client.ping())) return { content: "AUTONOMY not running. Reflection not stored." };

            // Try structured writeFact first (direct genome node injection)
            try {
              const result = await client.writeFact(
                args.observation,
                args.domain ?? "general",
                args.because ?? "",
                args.confidence ?? 0.8,
              );
              if (result.written) {
                return { content: `Genome fact stored${result.node_id ? ` (${result.node_id})` : ""}: ${entry.slice(0, 200)}` };
              }
            } catch {
              // writeFact endpoint may not exist yet — fall back to record
            }

            // Fallback: record as conversation turn (still gets extracted by pit crew)
            await client.record("assistant", `[REFLECTION${args.domain ? `:${args.domain}` : ""}] ${entry}`);
            return { content: `Stored reflection (via record): ${entry.slice(0, 200)}` };
          } catch (err) {
            return { content: `Reflection failed: ${err}` };
          }
        },
      }),
      { names: ["reflect"] },
    );

    // ═══════════════════════════════════════════════════════
    // TOOLS — Cross-Device Sync (Upgrade #7)
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "genome_sync",
        description:
          "Cross-device genome synchronization. Export encrypted CRDT state, " +
          "import from remote nodes, check sync status. " +
          "The genome follows you across devices via KERF tunnel.",
        parameters: {
          type: "object" as const,
          properties: {
            action: { type: "string", description: "export|import|status" },
            state: { type: "string", description: "Encrypted CRDT state string (for import)" },
          },
          required: ["action"],
        },
        async execute(args: { action: string; state?: string }) {
          try {
            const client = getClient();
            if (!(await client.ping())) return { content: "AUTONOMY not running." };

            switch (args.action) {
              case "export": {
                const result = await client.syncExport();
                getLog().emit("genome_event", `sync export: ${result.nodes} nodes, ${result.edges} edges`);
                return { content: `Exported: ${result.nodes} nodes, ${result.edges} edges at ${result.exportedAt}\n\nState (pass to import on remote):\n${result.state.slice(0, 500)}${result.state.length > 500 ? "..." : ""}` };
              }
              case "import": {
                if (!args.state) return { content: "Need state string from export." };
                const result = await client.syncImport(args.state);
                getLog().emit("genome_event", `sync import: +${result.nodesAdded} nodes, ${result.conflicts} conflicts`);
                return { content: `Merged: +${result.nodesAdded} nodes added, ${result.conflicts} conflicts resolved` };
              }
              case "status": {
                const result = await client.syncStatus();
                return { content: `Local: ${result.localNodes} nodes | Last sync: ${result.lastSync ?? "never"} | Pending exports: ${result.pendingExports}` };
              }
              default:
                return { content: `Unknown action: ${args.action}. Use: export, import, status` };
            }
          } catch (err) { return { content: `Sync failed: ${err}` }; }
        },
      }),
      { names: ["genome_sync"] },
    );

    // ═══════════════════════════════════════════════════════
    // TOOLS — MCP & Dashboard Control (Upgrades #5, #8)
    // ═══════════════════════════════════════════════════════

    api.registerTool(
      () => ({
        name: "mcp",
        description:
          "Control the MCP (Model Context Protocol) server. When running, any MCP client " +
          "(Claude Code, Cursor, Windsurf, custom agents) can use Clawtonomy's tools. " +
          "Actions: start, stop, status.",
        parameters: {
          type: "object" as const,
          properties: {
            action: { type: "string", description: "start|stop|status" },
          },
          required: ["action"],
        },
        async execute(args: { action: string }) {
          switch (args.action) {
            case "start": {
              if (_mcp?.isRunning()) return { content: "MCP server already running." };
              _mcp = new McpServer({ port: getCfg().mcpPort });
              const ok = _mcp.start();
              if (ok) getLog().emit("info", `MCP server started on port ${getCfg().mcpPort}`);
              return { content: ok ? `MCP server started at http://127.0.0.1:${getCfg().mcpPort}/` : "Failed to start." };
            }
            case "stop":
              return { content: _mcp?.stop() ? "MCP server stopped." : "Not running." };
            case "status":
              return { content: _mcp?.isRunning() ? `MCP running on port ${getCfg().mcpPort}` : "MCP not running." };
            default:
              return { content: `Unknown: ${args.action}. Use: start, stop, status` };
          }
        },
      }),
      { names: ["mcp"] },
    );

    api.registerTool(
      () => ({
        name: "dashboard",
        description:
          "Control the telemetry dashboard. Shows tool call frequency, model latency, " +
          "task completion rates, room mode usage, service uptime. " +
          "Actions: start, stop, status.",
        parameters: {
          type: "object" as const,
          properties: {
            action: { type: "string", description: "start|stop|status" },
          },
          required: ["action"],
        },
        async execute(args: { action: string }) {
          switch (args.action) {
            case "start": {
              if (_dashboard?.isRunning()) return { content: "Dashboard already running." };
              _dashboard = new Dashboard({
                port: getCfg().dashboardPort,
                host: "127.0.0.1",
                activityLogPath: join(WORKSPACE, "activity.jsonl"),
              });
              const ok = _dashboard.start();
              if (ok) getLog().emit("info", `Dashboard started at http://127.0.0.1:${getCfg().dashboardPort}/`);
              return { content: ok ? `Dashboard at http://127.0.0.1:${getCfg().dashboardPort}/` : "Failed to start." };
            }
            case "stop":
              return { content: _dashboard?.stop() ? "Dashboard stopped." : "Not running." };
            case "status":
              return { content: _dashboard?.isRunning() ? `Dashboard running at http://127.0.0.1:${getCfg().dashboardPort}/` : "Dashboard not running." };
            default:
              return { content: `Unknown: ${args.action}. Use: start, stop, status` };
          }
        },
      }),
      { names: ["dashboard"] },
    );

    // ═══════════════════════════════════════════════════════
    // CLI
    // ═══════════════════════════════════════════════════════

    api.registerCli(
      ({ program }) => {
        // ─── openclaw genome ───
        const g = program.command("genome").description("Persistent cognitive genome (AUTONOMY v3.0)");

        g.command("stats").description("Genome statistics").action(async () => {
          try {
            console.log("\n  CLAWTONOMY — Genome\n");
            console.log("  " + formatStats(await getClient().stats()).split("\n").join("\n  "));
            console.log();
          } catch (e) { console.error(`  Error: ${e}\n  Is AUTONOMY running?`); }
        });

        g.command("boot").description("Boot and print NUCLEUS")
          .option("-t, --tier <n>", "Tier 0-3", "0")
          .action(async (opts: { tier: string }) => {
            try {
              const { nucleus, tier } = await getClient().boot(parseInt(opts.tier, 10));
              const names = ["NUCLEUS", "CELL", "ORGANISM", "ECOSYSTEM"];
              console.log(`\n  CLAWTONOMY — ${names[tier]}\n`);
              console.log(nucleus);
              console.log();
            } catch (e) { console.error(`  Error: ${e}`); }
          });

        g.command("consolidate").description("Extract knowledge into genome").action(async () => {
          try {
            const s = await getClient().consolidate(true);
            console.log("\n  Consolidated. " + formatStats(s).split("\n").join("\n  ") + "\n");
          } catch (e) { console.error(`  Error: ${e}`); }
        });

        // ─── openclaw room ───
        const rm = program.command("room").description("Multi-model room (KERF engine)");

        rm.command("status").description("Show room status").action(async () => {
          const room = getRoom();
          console.log(`\n  CLAWTONOMY — Room\n`);
          console.log(`  Name:    ${room.name}`);
          console.log(`  Mode:    ${room.mode}`);
          console.log(`  Models:  [${room.models.join(", ") || "none"}]`);
          console.log(`  History: ${room.history.length} entries`);
          console.log(`  Modes:   ${ROOM_MODES.join(", ")}`);
          console.log();
        });

        rm.command("models").description("List available Ollama models").action(async () => {
          const models = await getOllama().listModels();
          const room = getRoom();
          console.log(`\n  CLAWTONOMY — Available Models\n`);
          for (const m of models) {
            const inRoom = room.models.includes(m.name) ? " [IN ROOM]" : "";
            console.log(`  ${m.name} (${m.parameter_size ?? "?"})${inRoom}`);
          }
          console.log(`\n  ${models.length} models\n`);
        });

        // ─── openclaw tasks ───
        const t = program.command("tasks").description("Task queue management");

        t.command("list").description("List all tasks").action(async () => {
          console.log("\n  CLAWTONOMY — Tasks\n");
          console.log("  " + getTasks().format().split("\n").join("\n  "));
          console.log();
        });

        t.command("stats").description("Task queue stats").action(async () => {
          const s = getTasks().stats();
          console.log(`\n  Tasks: ${s.total} | Pending: ${s.pending} | Running: ${s.running} | Done: ${s.completed} | Failed: ${s.failed}\n`);
        });

        // ─── openclaw daemon ───
        const d = program.command("daemon").description("Autonomous background daemon");

        d.command("start").description("Start daemon").action(async () => {
          console.log(getDaemon().start() ? "  Daemon started." : "  Already running.");
        });

        d.command("stop").description("Stop daemon").action(async () => {
          console.log(getDaemon().stop() ? "  Daemon stopped." : "  Not running.");
        });

        d.command("status").description("Daemon status").action(async () => {
          const s = getDaemon().status();
          console.log(`\n  Daemon: ${s.running ? "RUNNING" : "STOPPED"} | Ticks: ${s.tickCount} | Interval: ${s.config.intervalMs / 1000}s\n`);
        });

        // ─── openclaw services ───
        program.command("services").description("Service health check").action(async () => {
          console.log("\n  CLAWTONOMY — Services\n");
          const statuses = await checkAllServices();
          console.log("  " + formatServiceStatus(statuses).split("\n").join("\n  "));
          console.log();
        });
      },
      { commands: ["genome", "room", "tasks", "daemon", "services"] },
    );
  },
};

export default clawtonomy;
