/**
 * Policy Engine — Reads safety.yaml and enforces it in-process
 *
 * Replaces hardcoded COMMAND_DENYLIST with declarative, regex-based matching.
 * Gates filesystem operations, tool dispatch, and budget enforcement.
 *
 * Two enforcement layers:
 *   1. THIS — in-process, fast path, covers everything
 *   2. NemoClaw — kernel-level (Landlock/seccomp), when it stabilizes
 *
 * AnnulusLabs LLC
 */

import { readFileSync, existsSync } from "node:fs";
import { resolve, join, normalize, sep } from "node:path";
import { ActivityLog } from "./activity-log.js";

// ═══════════════════════════════════════════════════════════════════════
// TYPES — mirror safety.yaml schema
// ═══════════════════════════════════════════════════════════════════════

export type CommandRule = {
  pattern: string;
  reason: string;
  _regex?: RegExp;
};

export type ProcessPolicy = {
  spawn_allowed: boolean;
  command_denylist: CommandRule[];
  command_allowlist?: string[];
  default_timeout_ms: number;
  daemon_timeout_ms: number;
  max_concurrent: number;
  max_stdout_bytes: number;
  allowed_shells: string[];
};

export type InferencePolicy = {
  allowed_models: string[];
  max_calls_per_tick: number;
  max_calls_per_session: number;
  tick_time_budget_ms: number;
  rate_limit_per_minute: number;
  room: {
    max_models_per_query: number;
    validation_threshold: number;
  };
};

export type ToolPermission = "allow" | "allow_logged" | "confirm" | "deny";
export type ExecutionContext = "interactive" | "daemon" | "goal" | "mcp";

export type ToolPolicyEntry = {
  interactive: ToolPermission;
  daemon: ToolPermission;
  goal: ToolPermission;
  mcp: ToolPermission;
  actions?: Record<string, Partial<Record<ExecutionContext, ToolPermission>>>;
};

export type EscalationLevel = "warning" | "blocked" | "critical";

export type EscalationPolicy = {
  on_violation: {
    warning: { action: string; continue_execution: boolean };
    blocked: { action: string; notify_user: boolean; continue_execution: boolean; record_to_genome: boolean };
    critical: { action: string; notify_user: boolean; halt_daemon: boolean; cooldown_ms: number };
  };
  repeat_detection: {
    window_ms: number;
    max_violations_before_escalate: number;
    chain: EscalationLevel[];
  };
  degradation: Record<string, string>;
};

export type SafetyPolicy = {
  spec_version: string;
  plugin: { id: string; name: string; version: string; publisher: string; capabilities: string[] };
  process: ProcessPolicy;
  inference: InferencePolicy;
  tool_policy: Record<string, ToolPolicyEntry>;
  escalation: EscalationPolicy;
};

// ═══════════════════════════════════════════════════════════════════════
// VERDICT TYPES
// ═══════════════════════════════════════════════════════════════════════

export type PolicyVerdict = {
  allowed: boolean;
  level: EscalationLevel | "ok";
  reason: string;
  rule?: string;
};

// ═══════════════════════════════════════════════════════════════════════
// POLICY ENGINE
// ═══════════════════════════════════════════════════════════════════════

export class PolicyEngine {
  private policy: SafetyPolicy;
  private log: ActivityLog | null;
  private home: string;
  private _sessionInferenceCalls = 0;
  private _violations: Array<{ ts: number; level: EscalationLevel }> = [];
  private _restartLog: Array<{ service: string; ts: number }> = [];
  private _denyRegexes: RegExp[] = [];
  private _warnRegexes: Array<{ regex: RegExp; pattern: string }> = [];
  private _fsWritable: string[] = [];
  private _fsReadable: string[] = [];
  private _fsDeny: string[] = [];

  constructor(yamlPath: string, log?: ActivityLog) {
    this.log = log ?? null;
    this.home = process.env.HOME ?? process.env.USERPROFILE ?? "/";
    this.policy = this.loadYaml(yamlPath);
    this.compileDenylist();
    this.compileFilesystemPaths();
  }

  // ── YAML Loading ─────────────────────────────────────────────────

  private loadYaml(yamlPath: string): SafetyPolicy {
    const resolved = resolve(yamlPath);
    if (!existsSync(resolved)) {
      this.log?.emit("policy", `safety.yaml not found at ${resolved}, using hardcoded defaults`);
      return this.defaults();
    }

    try {
      const raw = readFileSync(resolved, "utf-8");
      const parsed = this.parseSimpleYaml(raw);
      this.log?.emit("policy", `loaded safety.yaml v${parsed.spec_version ?? "?"} from ${resolved}`);
      return this.mergeDefaults(parsed);
    } catch (e) {
      this.log?.emit("policy", `failed to parse safety.yaml: ${e}, using defaults`);
      return this.defaults();
    }
  }

  /**
   * Minimal YAML parser for safety.yaml — handles the subset we use:
   * scalars, lists, nested objects. No anchors, no multi-doc, no flow style.
   */
  private parseSimpleYaml(raw: string): any {
    const lines = raw.split("\n");
    const result: any = {};
    const stack: Array<{ obj: any; indent: number }> = [{ obj: result, indent: -1 }];

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      // Skip comments and blank lines
      if (/^\s*(#|$)/.test(line)) continue;

      const match = line.match(/^(\s*)(- )?(.+)/);
      if (!match) continue;

      const indent = match[1].length;
      const isList = !!match[2];
      const content = match[3].trim();

      // Pop stack to correct level
      while (stack.length > 1 && stack[stack.length - 1].indent >= indent) {
        stack.pop();
      }

      const parent = stack[stack.length - 1].obj;

      if (isList) {
        // List item
        const keyMatch = content.match(/^(\w+):\s*(.+)/);
        if (keyMatch) {
          // List of objects: - key: value
          const listItem: any = {};
          listItem[keyMatch[1]] = this.parseValue(keyMatch[2]);
          // Look ahead for more keys at same object level
          const nextIndent = indent + 2;
          while (i + 1 < lines.length) {
            const nextLine = lines[i + 1];
            const nextMatch = nextLine.match(/^(\s+)(\w+):\s*(.+)/);
            if (nextMatch && nextMatch[1].length === nextIndent) {
              listItem[nextMatch[2]] = this.parseValue(nextMatch[3]);
              i++;
            } else {
              break;
            }
          }
          if (Array.isArray(parent)) {
            parent.push(listItem);
          }
        } else {
          // Simple list item: - "value"
          const val = this.parseValue(content);
          if (Array.isArray(parent)) {
            parent.push(val);
          }
        }
      } else {
        // Key: value pair
        const kvMatch = content.match(/^(\w[\w_.-]*):\s*(.*)/);
        if (!kvMatch) continue;

        const key = kvMatch[1];
        const rawVal = kvMatch[2].trim();

        if (rawVal === "" || rawVal === "|") {
          // Check if next line is a list or nested object
          const nextLine = lines[i + 1];
          if (nextLine && /^\s+- /.test(nextLine)) {
            parent[key] = [];
            stack.push({ obj: parent[key], indent });
          } else {
            parent[key] = {};
            stack.push({ obj: parent[key], indent });
          }
        } else {
          parent[key] = this.parseValue(rawVal);
        }
      }
    }

    return result;
  }

  private parseValue(raw: string): any {
    const trimmed = raw.replace(/#.*$/, "").trim();
    if (trimmed === "true") return true;
    if (trimmed === "false") return false;
    if (trimmed === "null") return null;
    if (/^\d+$/.test(trimmed)) return parseInt(trimmed, 10);
    if (/^\d+\.\d+$/.test(trimmed)) return parseFloat(trimmed);
    // Strip quotes
    if ((trimmed.startsWith('"') && trimmed.endsWith('"')) ||
        (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
      return trimmed.slice(1, -1);
    }
    return trimmed;
  }

  // ── Compilation ──────────────────────────────────────────────────

  private compileDenylist(): void {
    const denylist = this.policy.process?.command_denylist ?? [];
    this._denyRegexes = denylist.map((r) => {
      try {
        return new RegExp(r.pattern, "i");
      } catch {
        // Fall back to escaped literal match
        return new RegExp(r.pattern.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
      }
    });
  }

  private expandHome(p: string): string {
    if (p.startsWith("~/") || p === "~") {
      return join(this.home, p.slice(1));
    }
    return p;
  }

  private compileFilesystemPaths(): void {
    // We don't have a filesystem section in the existing safety.yaml,
    // but we can derive writable/readable paths from the process and plugin config.
    // For now, use sensible defaults based on the plugin capabilities.
    const homeNorm = normalize(this.home);
    const openclawDir = join(homeNorm, ".openclaw");

    this._fsWritable = [
      openclawDir,
      join(homeNorm, "tmp"),
      normalize("/tmp/zoeae"),
      normalize("/tmp"),
    ];

    this._fsReadable = [
      homeNorm,
      normalize("/etc"),
      normalize("/usr/share"),
    ];

    this._fsDeny = [
      join(homeNorm, ".ssh"),
      join(homeNorm, ".gnupg"),
      join(homeNorm, ".aws", "credentials"),
      join(homeNorm, ".config", "gcloud"),
      normalize("/dev"),
      normalize("/proc"),
      normalize("/sys"),
    ];
  }

  // ── Defaults ─────────────────────────────────────────────────────

  private defaults(): SafetyPolicy {
    return {
      spec_version: "0.1.0",
      plugin: { id: "zoeae", name: "Zoeae", version: "3.0.0", publisher: "annuluslabs", capabilities: [] },
      process: {
        spawn_allowed: true,
        command_denylist: [
          { pattern: "rm -rf /", reason: "Recursive root deletion" },
          { pattern: "rm -rf ~", reason: "Recursive home deletion" },
          { pattern: "rm -rf .", reason: "Recursive cwd deletion" },
          { pattern: "dd if=", reason: "Raw disk read" },
          { pattern: "dd of=", reason: "Raw disk write" },
          { pattern: "mkfs", reason: "Filesystem format" },
          { pattern: "diskpart", reason: "Windows disk partition tool" },
          { pattern: ":()", reason: "Fork bomb" },
          { pattern: "chmod -R 777 /", reason: "Global permission strip" },
          { pattern: "Clear-Disk", reason: "Windows disk wipe" },
          { pattern: "Disable-PnpDevice", reason: "Hardware device disable" },
          { pattern: "Format-Volume", reason: "Windows volume format" },
          { pattern: "> /dev/sda", reason: "Direct disk write" },
          { pattern: "shutdown", reason: "System shutdown" },
          { pattern: "reboot", reason: "System reboot" },
          { pattern: "init 0", reason: "System halt" },
          { pattern: "init 6", reason: "System reboot (init)" },
        ],
        default_timeout_ms: 30000,
        daemon_timeout_ms: 60000,
        max_concurrent: 3,
        max_stdout_bytes: 2097152,
        allowed_shells: ["/bin/bash", "/bin/sh", "powershell.exe"],
      },
      inference: {
        allowed_models: ["hermes3:*", "phi4-mini-reasoning", "mistral:*", "deepseek-r1:*", "llama3*", "qwen*", "devstral*", "glm*", "smollm3:*"],
        max_calls_per_tick: 10,
        max_calls_per_session: 500,
        tick_time_budget_ms: 120000,
        rate_limit_per_minute: 30,
        room: { max_models_per_query: 5, validation_threshold: 0.6 },
      },
      tool_policy: {},
      escalation: {
        on_violation: {
          warning: { action: "log", continue_execution: true },
          blocked: { action: "block_and_log", notify_user: true, continue_execution: false, record_to_genome: true },
          critical: { action: "block_log_and_halt", notify_user: true, halt_daemon: true, cooldown_ms: 300000 },
        },
        repeat_detection: { window_ms: 60000, max_violations_before_escalate: 3, chain: ["warning", "blocked", "critical"] },
        degradation: {},
      },
    };
  }

  private mergeDefaults(parsed: any): SafetyPolicy {
    const d = this.defaults();
    return {
      spec_version: parsed.spec_version ?? d.spec_version,
      plugin: { ...d.plugin, ...parsed.plugin },
      process: {
        ...d.process,
        ...parsed.process,
        command_denylist: parsed.process?.command_denylist ?? d.process.command_denylist,
      },
      inference: {
        ...d.inference,
        ...parsed.inference,
        room: { ...d.inference.room, ...parsed.inference?.room },
      },
      tool_policy: parsed.tool_policy ?? d.tool_policy,
      escalation: {
        ...d.escalation,
        ...parsed.escalation,
        on_violation: { ...d.escalation.on_violation, ...parsed.escalation?.on_violation },
        repeat_detection: { ...d.escalation.repeat_detection, ...parsed.escalation?.repeat_detection },
      },
    };
  }

  // ═══════════════════════════════════════════════════════════════════
  // COMMAND CHECKING — replaces isCommandBlocked()
  // ═══════════════════════════════════════════════════════════════════

  checkCommand(cmd: string): PolicyVerdict {
    if (!this.policy.process.spawn_allowed) {
      return this.verdict(false, "blocked", "Process spawning disabled by policy", "spawn_allowed=false");
    }

    // Allowlist mode: if configured, only allow listed prefixes
    const allowlist = this.policy.process.command_allowlist;
    if (allowlist && allowlist.length > 0) {
      const cmdBase = cmd.trim().split(/\s+/)[0].toLowerCase();
      const allowed = allowlist.some((a) => cmdBase === a.toLowerCase() || cmdBase.endsWith("/" + a.toLowerCase()));
      if (!allowed) {
        return this.verdict(false, "blocked", `Command "${cmdBase}" not in allowlist`, "command_allowlist");
      }
    }

    // Denylist: regex match against full command
    const denylist = this.policy.process.command_denylist;
    for (let i = 0; i < this._denyRegexes.length; i++) {
      if (this._denyRegexes[i].test(cmd)) {
        const rule = denylist[i];
        return this.verdict(false, "blocked", rule?.reason ?? "Denied by command policy", rule?.pattern ?? "denylist");
      }
    }

    return this.verdict(true, "ok", "");
  }

  // ═══════════════════════════════════════════════════════════════════
  // FILESYSTEM CHECKING — gates readFile/writeFile/deleteFile
  // ═══════════════════════════════════════════════════════════════════

  checkPathRead(path: string): PolicyVerdict {
    const norm = normalize(resolve(path));

    // Deny takes precedence
    for (const denied of this._fsDeny) {
      if (norm.startsWith(denied + sep) || norm === denied) {
        return this.verdict(false, "blocked", `Read denied: ${denied}`, "filesystem.deny");
      }
    }

    // Any readable path is allowed
    for (const readable of this._fsReadable) {
      if (norm.startsWith(readable + sep) || norm === readable) {
        return this.verdict(true, "ok", "");
      }
    }

    // Writable paths are also readable
    for (const writable of this._fsWritable) {
      if (norm.startsWith(writable + sep) || norm === writable) {
        return this.verdict(true, "ok", "");
      }
    }

    // Default: allow reads (restrictive mode would deny here)
    return this.verdict(true, "ok", "");
  }

  checkPathWrite(path: string): PolicyVerdict {
    const norm = normalize(resolve(path));

    // Deny takes precedence
    for (const denied of this._fsDeny) {
      if (norm.startsWith(denied + sep) || norm === denied) {
        return this.verdict(false, "blocked", `Write denied: ${denied}`, "filesystem.deny");
      }
    }

    // Must be under a writable path
    for (const writable of this._fsWritable) {
      if (norm.startsWith(writable + sep) || norm === writable) {
        return this.verdict(true, "ok", "");
      }
    }

    // Not under any writable path — block in daemon context, warn in interactive
    return this.verdict(false, "warning",
      `Write to ${norm} outside writable paths: ${this._fsWritable.join(", ")}`,
      "filesystem.writable");
  }

  // ═══════════════════════════════════════════════════════════════════
  // TOOL POLICY — context-aware dispatch gating
  // ═══════════════════════════════════════════════════════════════════

  checkTool(toolName: string, context: ExecutionContext, action?: string): PolicyVerdict {
    const entry = this.policy.tool_policy[toolName];
    if (!entry) return this.verdict(true, "ok", ""); // No policy = allow

    // Check action-specific override first
    if (action && entry.actions?.[action]?.[context]) {
      const perm = entry.actions[action][context]!;
      return this.permissionToVerdict(perm, toolName, context, action);
    }

    const perm = entry[context] ?? "allow";
    return this.permissionToVerdict(perm, toolName, context);
  }

  private permissionToVerdict(perm: ToolPermission, tool: string, ctx: ExecutionContext, action?: string): PolicyVerdict {
    const label = action ? `${tool}.${action}` : tool;
    switch (perm) {
      case "allow":
        return this.verdict(true, "ok", "");
      case "allow_logged":
        this.log?.emit("tool_invocation", `[policy] ${label} invoked in ${ctx} context`);
        return this.verdict(true, "ok", "");
      case "confirm":
        // In autonomous contexts, treat confirm as deny (no human to confirm)
        if (ctx === "daemon" || ctx === "goal") {
          return this.verdict(false, "blocked", `${label} requires confirmation in ${ctx} context (no human present)`, `tool_policy.${label}`);
        }
        return this.verdict(true, "ok", `${label} requires confirmation`, `tool_policy.${label}`);
      case "deny":
        return this.verdict(false, "blocked", `${label} denied in ${ctx} context`, `tool_policy.${label}`);
      default:
        return this.verdict(true, "ok", "");
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  // INFERENCE CHECKING — model allowlist, session budget
  // ═══════════════════════════════════════════════════════════════════

  checkModel(model: string): PolicyVerdict {
    const allowed = this.policy.inference.allowed_models;
    if (!allowed || allowed.length === 0) return this.verdict(true, "ok", "");

    const modelLower = model.toLowerCase();
    const isAllowed = allowed.some((pattern) => {
      const patLower = pattern.toLowerCase();
      if (patLower.endsWith("*")) {
        return modelLower.startsWith(patLower.slice(0, -1));
      }
      return modelLower === patLower;
    });

    if (!isAllowed) {
      return this.verdict(false, "blocked", `Model "${model}" not in allowed list`, "inference.allowed_models");
    }

    return this.verdict(true, "ok", "");
  }

  checkInferenceBudget(): PolicyVerdict {
    this._sessionInferenceCalls++;
    if (this._sessionInferenceCalls > this.policy.inference.max_calls_per_session) {
      return this.verdict(false, "blocked",
        `Session inference cap reached (${this.policy.inference.max_calls_per_session})`,
        "inference.max_calls_per_session");
    }
    return this.verdict(true, "ok", "");
  }

  // ═══════════════════════════════════════════════════════════════════
  // SERVICE RESTART RATE LIMITING
  // ═══════════════════════════════════════════════════════════════════

  checkServiceRestart(serviceName: string): PolicyVerdict {
    const now = Date.now();
    const esc = this.policy.escalation;
    const windowMs = esc?.repeat_detection?.window_ms ?? 300000;
    const limit = 5; // service_restart_limit from budgets concept

    // Prune old entries
    this._restartLog = this._restartLog.filter((r) => now - r.ts < windowMs);

    // Count restarts for this service in window
    const count = this._restartLog.filter((r) => r.service === serviceName).length;
    if (count >= limit) {
      return this.verdict(false, "blocked",
        `Service "${serviceName}" restarted ${count} times in ${windowMs / 1000}s window (limit: ${limit})`,
        "service_restart_limit");
    }

    this._restartLog.push({ service: serviceName, ts: now });
    return this.verdict(true, "ok", "");
  }

  // ═══════════════════════════════════════════════════════════════════
  // ESCALATION — repeat detection + level escalation
  // ═══════════════════════════════════════════════════════════════════

  recordViolation(level: EscalationLevel): EscalationLevel {
    const now = Date.now();
    this._violations.push({ ts: now, level });

    const esc = this.policy.escalation.repeat_detection;
    const windowMs = esc?.window_ms ?? 60000;
    const maxBefore = esc?.max_violations_before_escalate ?? 3;
    const chain = esc?.chain ?? ["warning", "blocked", "critical"];

    // Count recent violations
    const recent = this._violations.filter((v) => now - v.ts < windowMs);
    if (recent.length >= maxBefore) {
      // Escalate: find current level in chain, move up
      const currentIdx = chain.indexOf(level);
      const nextIdx = Math.min(currentIdx + 1, chain.length - 1);
      const escalated = chain[nextIdx] as EscalationLevel;

      this.log?.emit("policy_escalation",
        `Escalating from ${level} to ${escalated}: ${recent.length} violations in ${windowMs / 1000}s`);

      // Clear window after escalation
      this._violations = [];
      return escalated;
    }

    return level;
  }

  // ═══════════════════════════════════════════════════════════════════
  // ACCESSORS
  // ═══════════════════════════════════════════════════════════════════

  getProcessPolicy(): ProcessPolicy { return this.policy.process; }
  getInferencePolicy(): InferencePolicy { return this.policy.inference; }
  getEscalationPolicy(): EscalationPolicy { return this.policy.escalation; }
  getToolPolicy(): Record<string, ToolPolicyEntry> { return this.policy.tool_policy; }

  /** Get budget values for DaemonConfig overrides */
  getBudgets(): {
    maxOllamaCallsPerTick: number;
    tickTimeBudgetMs: number;
    maxTasksPerTick: number;
    maxGoalSteps: number;
    maxGoalReplans: number;
    roomValidationThreshold: number;
    defaultTimeoutMs: number;
    daemonTimeoutMs: number;
  } {
    return {
      maxOllamaCallsPerTick: this.policy.inference.max_calls_per_tick,
      tickTimeBudgetMs: this.policy.inference.tick_time_budget_ms,
      maxTasksPerTick: this.policy.process.max_concurrent,
      maxGoalSteps: 20,   // Not in current yaml, use default
      maxGoalReplans: 2,   // Not in current yaml, use default
      roomValidationThreshold: this.policy.inference.room.validation_threshold,
      defaultTimeoutMs: this.policy.process.default_timeout_ms,
      daemonTimeoutMs: this.policy.process.daemon_timeout_ms,
    };
  }

  // ═══════════════════════════════════════════════════════════════════
  // INTERNAL
  // ═══════════════════════════════════════════════════════════════════

  private verdict(allowed: boolean, level: EscalationLevel | "ok", reason: string, rule?: string): PolicyVerdict {
    if (level !== "ok" && level !== "warning") {
      this.log?.emit("policy_violation", `[${level}] ${reason}${rule ? ` (rule: ${rule})` : ""}`);
    } else if (level === "warning" && reason) {
      this.log?.emit("policy_warning", reason);
    }
    return { allowed, level, reason, rule };
  }
}
