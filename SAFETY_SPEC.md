# OpenClaw Plugin Safety Policy Specification v1.0.0

## Enforcement Mapping Table

Every field in `safety.yaml` maps to enforcement in two independent layers. A
violation at either layer is sufficient to block. Infrastructure enforcement is
the hard floor; in-process enforcement is the fast path.

### 1. Filesystem Policy

| safety.yaml field | Zoeae In-Process Enforcement | NemoClaw Infrastructure Enforcement |
|---|---|---|
| `filesystem.read.allow` | Path validation in `executor.ts` `readFile()` before `readFileSync()` | Landlock `LANDLOCK_ACCESS_FS_READ_FILE` ruleset on allowed paths |
| `filesystem.read.deny` | Denylist check in `executor.ts` `readFile()` — reject before syscall | Landlock: paths not in allow ruleset are denied by default; explicit deny removes from parent allow |
| `filesystem.write.allow` | Path validation in `executor.ts` `writeFile()` / `appendToFile()` / `deleteFile()` | Landlock `LANDLOCK_ACCESS_FS_WRITE_FILE` + `LANDLOCK_ACCESS_FS_MAKE_REG` |
| `filesystem.write.deny` | Denylist check rejects `.git/`, self-modification paths, system dirs | Landlock: excluded from write ruleset; `LANDLOCK_ACCESS_FS_REMOVE_FILE` restricted |
| `filesystem.max_write_bytes_per_session` | Session-scoped byte counter in executor, checked on each write | cgroup v2 `io.max` writeback limit + disk quota (`quota(8)`) |
| `filesystem.max_single_file_bytes` | Content length check before `writeFileSync()` | Landlock cannot enforce this; enforced via `RLIMIT_FSIZE` in seccomp |

### 2. Network Policy

| safety.yaml field | Zoeae In-Process Enforcement | NemoClaw Infrastructure Enforcement |
|---|---|---|
| `network.egress.allow` | URL validation in `OllamaClient` / `AutonomyClient` constructors; reject non-allowed hosts | Network namespace (`netns`) with `iptables`/`nftables` OUTPUT rules allowing only listed host:port pairs |
| `network.ingress.allow` | `McpServer` binds only to `127.0.0.1:8768` | `nftables` INPUT rules in netns; only listed ports accepted |
| `network.deny_wildcard_bind` | `McpServer` constructor rejects `0.0.0.0` bind | seccomp filter on `bind(2)`: reject `INADDR_ANY` |
| `network.max_concurrent_connections` | Connection counter in HTTP clients | `conntrack` limit in netns |
| `network.max_egress_bytes_per_session` | Byte counter on HTTP response bodies | `tc` (traffic control) bandwidth cap in netns |
| `network.max_ingress_bytes_per_session` | Byte counter on incoming MCP request bodies | `tc` ingress cap |

### 3. Process Policy

| safety.yaml field | Zoeae In-Process Enforcement | NemoClaw Infrastructure Enforcement |
|---|---|---|
| `process.spawn_allowed` | Gate in `shellExec()` — if false, return error immediately | seccomp filter: deny `execve(2)` entirely |
| `process.command_denylist[*].pattern` | `isCommandBlocked()` in `daemon.ts` lines 78-91 — substring match, case-insensitive | seccomp cannot inspect execve arguments; this is in-process only. NemoClaw compensates with Landlock path restrictions on destructive targets. |
| `process.command_allowlist` | (Optional) Prefix-match allowlist in `shellExec()` | seccomp allowlist on `execve(2)` binary paths |
| `process.default_timeout_ms` | `shellExec()` `timeoutMs` parameter (default 30s) in `executor.ts` line 40 | `RLIMIT_CPU` per-process via `prlimit(2)` in pid namespace |
| `process.daemon_timeout_ms` | `executeTask()` override: 60s timeout in `daemon.ts` line 722 | Same as above, longer limit for daemon context |
| `process.max_concurrent` | Semaphore around `shellExec()` calls | pid namespace `pid.max` cgroup controller |
| `process.max_stdout_bytes` | `maxBuffer: 2MB` in `executor.ts` `nodeExec()` line 52 | Pipe buffer limits in kernel (`/proc/sys/fs/pipe-max-size`) |
| `process.max_stderr_bytes` | Stderr truncation in `executor.ts` line 58 | Same pipe buffer mechanism |
| `process.allowed_shells` | Shell selection in `executor.ts` line 42 | seccomp filter: only allow `execve(2)` for listed interpreter paths |

### 4. Inference Policy

| safety.yaml field | Zoeae In-Process Enforcement | NemoClaw Infrastructure Enforcement |
|---|---|---|
| `inference.allowed_models` | Model name validation before `ollama.chatResult()` call | NemoClaw: HTTP proxy in front of Ollama inspects `/api/chat` body for model field |
| `inference.max_calls_per_tick` | `guardedChat()` in `daemon.ts` line 206: `_ollamaCallsThisTick >= maxOllamaCallsPerTick` | Rate limiter proxy: per-minute token bucket per source pid |
| `inference.max_calls_per_session` | Session-scoped counter wrapping all Ollama calls | Proxy-level cumulative counter per session ID |
| `inference.tick_time_budget_ms` | `tickTimeBudgetMs` check in `daemon.ts` `_tickInner()` line 628 | cgroup `cpu.max` bandwidth for daemon tick context |
| `inference.max_tokens_per_call` | `num_predict` parameter in Ollama request body | Proxy rewrites/caps `num_predict` in request body |
| `inference.rate_limit_per_minute` | Token bucket in OllamaClient wrapper | `tc` rate limiting on Ollama port traffic |
| `inference.room.max_models_per_query` | Check in `Room.query()` before dispatching | Proxy: reject batch if model count exceeds limit |
| `inference.room.validation_threshold` | `roomValidationThreshold` in `daemon.ts` line 43, checked line 300 | In-process only (semantic, not enforceable at infra level) |

### 5. Tool Policy

| safety.yaml field | Zoeae In-Process Enforcement | NemoClaw Infrastructure Enforcement |
|---|---|---|
| `tool_policy.<tool>.<context>` | Context-aware wrapper around each `api.registerTool()` handler: checks execution mode before dispatch | NemoClaw cannot distinguish tool-level dispatch. Enforcement is through the underlying syscalls each tool triggers (e.g., `shell` tool triggers `execve`, `file` tool triggers `open/write`). |
| `"allow"` | Execute, no logging overhead | No additional restriction |
| `"allow_logged"` | Execute + `ActivityLog.emit("tool_invocation", ...)` | Kernel audit subsystem logs syscall |
| `"confirm"` | Emit confirmation request to user via `api.requestConfirmation()`, block until approved | NemoClaw: action queued in sandbox control plane; user approval gate in orchestrator |
| `"deny"` | Return error immediately, never reach tool handler | Underlying syscalls denied by Landlock/seccomp rules for that context |

### 6. Escalation Policy

| safety.yaml field | Zoeae In-Process Enforcement | NemoClaw Infrastructure Enforcement |
|---|---|---|
| `escalation.on_violation.warning` | `ActivityLog.emit("policy_warning", ...)` | Sandbox audit log entry at INFO level |
| `escalation.on_violation.blocked` | `tasks.block()` or `tasks.fail()` in daemon; `ActivityLog.emit("policy_violation", ...)`; notification queued | Landlock/seccomp returns `EPERM`; auditd logs at ERR level |
| `escalation.on_violation.critical` | `daemon.stop()`; cooldown timer; genome record | NemoClaw kills sandbox, logs to orchestrator, triggers alert webhook |
| `escalation.repeat_detection` | Sliding window counter in policy enforcement layer | NemoClaw: rate-based alert rule in audit pipeline |
| `escalation.degradation.*` | Conditional logic in daemon tick loop (e.g., skip validation when budget exhausted — already implemented in `_tickInner()` fallthrough) | cgroup notifications trigger mode switches in sandbox control plane |

### 7. Resource Limits

| safety.yaml field | Zoeae In-Process Enforcement | NemoClaw Infrastructure Enforcement |
|---|---|---|
| `resources.max_memory_bytes` | `process.memoryUsage()` check in daemon tick | cgroup v2 `memory.max = 2147483648` |
| `resources.max_cpu_time_seconds` | Cumulative `durationMs` tracking across tick loop | cgroup v2 `cpu.max` with period-based bandwidth limit |
| `resources.max_pids` | Not enforced in-process (OS-level only) | pid cgroup `pids.max = 50` |
| `resources.max_disk_io_bps` | Not enforced in-process (OS-level only) | cgroup v2 `io.max` with `rbps`/`wbps` limits |
| `resources.max_disk_usage_bytes` | Cumulative write byte counter | Disk quota via `quota(8)` or cgroup `io` accounting |
| `resources.max_open_files` | Not enforced in-process (OS-level only) | `RLIMIT_NOFILE = 256` via `prlimit(2)` |
| `resources.daemon.max_tasks_per_tick` | `maxTasksPerTick` in `daemon.ts` line 627 | In-process only (semantic) |
| `resources.daemon.tick_time_budget_ms` | `tickTimeBudgetMs` check in `daemon.ts` line 628 | cgroup cpu budget per tick interval |
| `resources.daemon.max_goal_steps` | `maxGoalSteps` loop bound in `daemon.ts` line 464 | In-process only (semantic) |
| `resources.daemon.max_goal_replans` | `maxGoalReplans` check in `daemon.ts` line 512 | In-process only (semantic) |
| `resources.daemon.stale_task_timeout_ms` | 600s stale check in `_tickInner()` lines 599-607 | Process-level timeout via pid cgroup watchdog |

---

## Zoeae Existing Safeguard Inventory

Cross-reference of every safeguard currently implemented in Zoeae and where it
appears in `safety.yaml`:

| Safeguard | Source Location | safety.yaml Section |
|---|---|---|
| Command denylist (16 patterns) | `daemon.ts` lines 78-83, `isCommandBlocked()` | `process.command_denylist` |
| Ollama call cap per tick (10) | `daemon.ts` line 39, `guardedChat()` line 206 | `inference.max_calls_per_tick` |
| Tick mutex (no concurrent ticks) | `daemon.ts` `_ticking` flag, line 576 | Implicit in `resources.daemon` (structural, not configurable) |
| Exit-code-is-truth | `daemon.ts` `validateResult()` line 218 | `inference.room.validation_threshold` (validation semantics) |
| Replan depth limit (1 replan) | `daemon.ts` line 660 `_replanCount` | `resources.daemon.max_goal_replans` |
| Goal step cap (20) | `daemon.ts` line 464 | `resources.daemon.max_goal_steps` |
| Goal replan cap (2) | `daemon.ts` line 512 | `resources.daemon.max_goal_replans` |
| Tick time budget (120s) | `daemon.ts` line 628 | `resources.daemon.tick_time_budget_ms` |
| Shell timeout (30s default, 60s daemon) | `executor.ts` line 40, `daemon.ts` line 722 | `process.default_timeout_ms`, `process.daemon_timeout_ms` |
| Stdout buffer cap (2MB) | `executor.ts` line 52 | `process.max_stdout_bytes` |
| Stale task reset (10 min) | `daemon.ts` lines 599-607 | `resources.daemon.stale_task_timeout_ms` |
| Max tasks per tick (3) | `daemon.ts` line 627 | `resources.daemon.max_tasks_per_tick` |
| Room validation threshold (0.6) | `daemon.ts` line 43 | `inference.room.validation_threshold` |
| Adaptive validation thresholds | `daemon.ts` `adaptiveThreshold()` line 379 | `inference.room.validation_threshold` (base; adaptive adjustment is in-process logic) |

---

## Design Decisions

### Why denylist + allowlist coexist in process policy

The `command_denylist` is the current Zoeae implementation and catches
catastrophic commands. The `command_allowlist` (commented out by default) is
the stricter alternative for locked-down deployments. When both are present,
the allowlist takes precedence and the denylist becomes a secondary safety net.

### Why tool policy cannot be fully enforced at infrastructure level

NemoClaw's Landlock/seccomp operates at the syscall boundary. It cannot
distinguish between a `shell` tool invocation and a `file` tool invocation
because both ultimately call the same kernel interfaces (`execve`, `open`,
`write`). Tool-level policy is inherently an in-process concern. Infrastructure
enforcement compensates by restricting the *effects* of each tool category
(filesystem paths, network hosts, process spawning rights).

### Why inference policy needs a proxy layer in NemoClaw

Landlock and seccomp cannot inspect HTTP request bodies. To enforce
`allowed_models` and `max_tokens_per_call` at the infrastructure level,
NemoClaw must run an HTTP proxy (e.g., nginx + lua, envoy with ext_authz, or a
purpose-built sidecar) in the network namespace between the plugin and Ollama.
This proxy inspects the `/api/chat` and `/api/generate` request bodies.

### Inheritance model

```
openclaw/default          (platform base: conservative defaults)
  └── openclaw/daemon     (base for all plugins that run a daemon)
       └── zoeae          (this file: plugin-specific overrides)
```

A field present in `zoeae/safety.yaml` overrides the same field in
`openclaw/daemon`, which overrides `openclaw/default`. Use `_inherit: false`
on any section to suppress parent defaults entirely and start from a blank slate.
