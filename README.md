# Zoeae: Living Orchestration Runtime for OpenClaw

**Autonomous cognitive agent — genome memory, task queue, multi-model rooms, background daemon, hardware feeds**

Version 0.6.0 | MIT | AnnulusLabs LLC

---

## What This Is

Zoeae is an autonomous cognitive agent plugin for OpenClaw. It adds 21 tools, a background daemon, a multi-model room engine, goal decomposition, and persistent genome memory to the OpenClaw gateway.

There are two runtimes that coexist in this directory. The TypeScript plugin (8,852 lines across 18 files) integrates directly with OpenClaw and is what you use day-to-day. The Python framework (10,596 lines across 36 organs and 8 feeds) is a standalone orchestration library modeled on crustacean larval biology — organs, ocean, antenna, genome, molt cycles. Both are independent. Neither depends on the other at runtime.

Total: approximately 21,800 lines across both runtimes plus tests.

---

## Architecture

```
OpenClaw Gateway
       |
       v
 Zoeae TS Plugin (index.ts)
       |
   21 tools registered via api.registerTool()
   6 hooks: agent:bootstrap, message:received, message:sent,
            command:new, command:reset, gateway:startup
       |
       +---> PolicyEngine (safety.yaml) -- gates every tool call
       |
       +---> AutonomyClient ---------> AUTONOMY v3.0 (port 8766)
       |                                genome, because-chains,
       |                                StressCompiler tiers
       |
       +---> Daemon -----------------> background tick loop
       |       |                       task processing, service health,
       |       |                       genome consolidation
       |       +---> DreamEngine      idle-time fact recombination
       |       +---> Planner          goal decomposition (tree search)
       |
       +---> AgentPool --------------> N concurrent agents
       |       |                       roles: orchestrator, builder,
       |       |                       researcher, reviewer, dreamer, sentinel
       |       +---> PtyPool          tmux-backed terminal pool
       |
       +---> Room (RoomEngine) ------> multi-model Ollama queries
       |       modes: parallel, adversarial, round-robin,
       |              snowball, sparse-debate, free-mad, vote
       |
       +---> TaskEngine -------------> persistent priority queue
       +---> McpServer (port 8768) --> MCP interface for external clients
       +---> ActivityLog           --> structured JSONL audit trail
       +---> OllamaClient          --> local model inference (port 11434)

Python Framework (standalone)
       |
  36 organs: Zoeae, Ocean, Genome, Antenna, Exoskeleton, ...
  8 sensor feeds: EcoFlow, Solar, Geiger, NanoVNA, Arduino, Klipper, Look, Router
  Shared: SensorNet, Nerve (message bus), Blood (shared state), Gill (budget)
```

---

## Quick Start

### Install

Zoeae is an OpenClaw plugin. It lives at:

```
~/.openclaw/extensions/zoeae/
```

It is already installed if you are reading this file from that path.

### Enable

In your `openclaw.json` (usually `~/.openclaw/openclaw.json`):

```json
{
  "plugins": {
    "entries": {
      "zoeae": {
        "enabled": true
      }
    }
  }
}
```

OpenClaw must be version 2026.3.11 or later (`peerDependencies: openclaw >= 2026.3.11`).

### Tools

All 21 tools are available once the plugin is enabled:

| Tool | What it does |
|------|-------------|
| `shell` | Execute a shell command on the host OS (policy-gated, exit code is truth) |
| `file` | File I/O: read, write, append, list, info, delete |
| `task` | Persistent task queue: add, list, next, start, complete, fail, block, unblock, remove, stats, clear |
| `plan` | Goal decomposition via local models (tree search, breadth + depth models) |
| `delegate` | Send a prompt to a specific local Ollama model and get the response |
| `services` | Check health of local services (AUTONOMY, Ollama); restart dead ones |
| `daemon` | Start/stop/status the background daemon; set metabolic power tier |
| `genome_search` | Search the cognitive genome for facts from previous sessions |
| `genome_stats` | Show genome health: node count, edge count, because-chain coverage, domains |
| `genome_ccm` | Compute Avnir Continuous Chirality Measure on a PDB structure |
| `genome_sync` | Cross-device genome sync: export/import CRDT state |
| `room_query` | Query the multi-model room (7 modes, auto-mode selection by task type) |
| `room_manage` | Add/remove models, set mode, list available Ollama models |
| `activity` | View the real-time activity log (tool calls, shell commands, delegation) |
| `reflect` | Store a structured learning directly into the genome as a first-class fact |
| `goal` | Execute a complex goal autonomously: decompose → execute → validate → replan |
| `dream` | Control the dream engine: idle-time fact recombination across domains |
| `pool` | Spawn and manage N concurrent agents by role (orchestrator, builder, etc.) |
| `mcp` | Start/stop the MCP server so external clients can use Zoeae's tools |
| `dashboard` | Terminal telemetry: tool call frequency, model latency, task rates, uptime |

### Daemon

The daemon is off by default (`daemonAutoStart: false`). Start it:

```
# Via tool (in an OpenClaw session):
daemon action=start

# Via CLI:
openclaw daemon start
openclaw daemon status
openclaw daemon stop
```

The daemon runs a tick every 5 minutes (configurable via `daemonIntervalMs`). Each tick: checks service health, processes pending shell/prompt tasks, optionally consolidates the genome. Metabolic tiers (`thriving`, `active`, `conserving`, `encysted`) modulate behavior based on a power level you set.

### Dream Engine

```
dream action=start       # starts; fires after 10 min idle
dream action=once        # trigger one dream immediately
dream action=bridges     # show kept cross-domain connections
dream action=status      # counts, average quality, config
dream action=stop
```

The dream engine reads facts from the genome and KERF knowledge stores, asks a local Ollama model to find structural connections between unrelated domains, and writes bridges to `dreams.jsonl`. Most dreams are discarded (quality threshold: configurable). High-quality bridges can be promoted to actionable tasks.

### Agent Pool

```
pool action=start                               # spawn default agent set
pool action=spawn role=builder name=alice       # spawn a specific agent
pool action=list                                # list all live agents
pool action=route task="refactor this module"   # route work to best agent
pool action=scale-up role=researcher            # spawn another researcher
pool action=health                              # check for stalled agents
pool action=stop                                # terminate all agents
```

Roles: `orchestrator`, `builder`, `researcher`, `reviewer`, `dreamer`, `sentinel`. Each agent has its own workspace directory, PTY (tmux-backed), model assignment, and policy overrides (tighter than the base policy, never looser). Agent state persists across restarts via `agent-pool.json`.

---

## TypeScript Plugin

17 source files in `src/`, plus `index.ts` at root.

| File | Lines | Description |
|------|-------|-------------|
| `index.ts` | 1,626 | Plugin entrypoint: 21 tools, 6 hooks, CLI commands registered with OpenClaw |
| `src/agent-pool.ts` | 1,366 | Multi-agent orchestrator: AgentSession, PtyPool (tmux), AgentPool, AgentRouter, inter-agent comms, pool persistence |
| `src/autonomy.ts` | 1,398 | Genome-driven heartbeat, crash-safe cron, read-only memory compaction, append-only audit trail |
| `src/daemon.ts` | 982 | Background tick loop with 3-phase inner loop: validate → reformulate → retry, room-backed validation, adaptive thresholds |
| `src/policy.ts` | 633 | PolicyEngine: reads `safety.yaml`, gates commands, filesystem, tool dispatch, inference budget, repeat-escalation |
| `src/room-engine.ts` | 508 | Multi-model room: 7 modes including sparse-debate (ring topology) and free-mad (trajectory scoring) |
| `src/dream-engine.ts` | 384 | Creative recombination during idle time; reads KERF knowledge stores; writes bridges to `dreams.jsonl` |
| `src/k1c-bridge.ts` | 329 | Creality K1C control via Moonraker JSON-RPC: status, upload, print, cancel, pause, resume, home, heat, gcode |
| `src/dashboard.ts` | 312 | ANSI terminal telemetry: tool call frequency, delegation latency, task rates, room mode usage |
| `src/planner.ts` | 214 | Goal decomposition: tree search, best-first expansion, cheap model for breadth / expensive for depth |
| `src/task-engine.ts` | 226 | Persistent priority queue: deps, retry, status lifecycle, file-backed, zero external deps |
| `src/mcp-server.ts` | 193 | MCP (Model Context Protocol) HTTP server on port 8768; exposes tools and resources to external clients |
| `src/executor.ts` | 176 | OS-level execution: shellExec (policy-gated), readFile, writeFile, appendToFile, listDir, deleteFile |
| `src/activity-log.ts` | 123 | Structured JSONL activity log with 20+ event kinds, rolling rotation |
| `src/autonomy-client.ts` | 119 | Typed HTTP client for AUTONOMY v3.0 API: boot, record, compile, stats, writeFact, syncExport, syncImport |
| `src/services.ts` | 117 | Service health monitor: HTTP ping, restart commands for AUTONOMY and Ollama |
| `src/ollama-client.ts` | 87 | Stdlib fetch Ollama client: chat, chatResult, listModels, ping — no external dependencies |
| `src/paths.ts` | 59 | Centralized data path resolution: `ZOEAE_DATA` env var, defaults to `~/.zoeae/data/` |

**TS total: 8,852 lines**

---

## Python Framework

36 organs in `zoeae/`, 8 sensor feeds in `zoeae/feeds/`. The framework is a standalone Python library — it does not require OpenClaw. Install with `pip install -e .` from this directory.

### Organs

| Organ | Lines | Description |
|-------|-------|-------------|
| `swim.py` | 527 | Planning and navigation: Plan, Step, goal decomposition |
| `ecosystem.py` | 474 | Courtyard, ToeBuster, FabNet, SensorNet, PatentGen, MeshNode orchestration |
| `xr.py` | 428 | Extended reality interface |
| `brain.py` | 403 | LLM reasoning with backends: OllamaBackend, AnthropicBackend, HTTPBackend |
| `organism.py` | 394 | Core Zoeae class: hatch(), molt(), develop() |
| `gut.py` | 388 | Knowledge graph: Entity, Relationship, Fact extraction |
| `messenger.py` | 383 | LAN messaging: send_to_phone, get_inbox, HTTP server |
| `mouth.py` | 364 | Output: formatting, rendering, response assembly |
| `shell.py` | 353 | Defensive behavior: SpikeDecision, AttackPattern |
| `hands.py` | 338 | Action execution: ActionResult, task dispatch |
| `eye.py` | 338 | Threat/opportunity scanning: ScanResult, Threat, Opportunity, DetailedView |
| `gill.py` | 312 | Token and compute budget management: BudgetDecision, tier-aware allocation |
| `crab.py` | 306 | Post-larval settled form with hardened exoskeleton |
| `shoes.py` | 303 | Movement and locomotion primitives |
| `heart.py` | 293 | Heartbeat loop: HeartbeatEvent, periodic pulse |
| `nerve.py` | 284 | Message bus: Signal, SignalLog, pub/sub routing |
| `muscle.py` | 273 | Physical action execution: FlexResult |
| `spawn.py` | 262 | Clutch spawning: create child organisms |
| `antenna.py` | 251 | 7-channel sensory perception with gaussian developmental bleed across 5 instars |
| `pipeline.py` | 248 | DAG execution: Stage, StageStatus, dependency-ordered processing |
| `genome.py` | 246 | Hereditary memory: Chromosome, Strand, Codon, GenomeBuilder, ExpressionError |
| `blood.py` | 244 | Shared state (hemolymph): HemolymphCell, organism-wide key-value store |
| `ocean.py` | 237 | Environment: Stimulus, Reflection, ambient context |
| `tail.py` | 215 | History and trail: TailEvent, trail persistence |
| `router.py` | 212 | Capability routing: Provider, CapabilityDomain, RouteRequest, RouteResult |
| `compiler.py` | 206 | Context compilation: Budget, Tier, Skill, CompiledContext |
| `instinct.py` | 169 | Instinct graph: Belief-weighted reflexive responses |
| `accumulator.py` | 145 | Fragment accumulation: Explorer, Frontier, DiversityAnalyzer |
| `telemetry.py` | 142 | Event instrumentation: Event, EventLevel |
| `tropism.py` | 137 | Environmental response drives: Drive, default_tropisms |
| `exoskeleton.py` | 131 | Method wrapping with integrity checks: IntegrityLevel, ThreatClass, Provenance |
| `molt.py` | 105 | Developmental transitions: MoltCycle, Instar, Exuvium |
| `explorer.py` | 4 | Stub (re-exports from accumulator) |
| `diversity.py` | 4 | Stub (re-exports from accumulator) |

**Python organs total: 9,237 lines**

### Sensor Feeds (`zoeae/feeds/`)

All feeds implement `SensorFeed` and register with `SensorNet`.

| Feed | Lines | Hardware / Protocol |
|------|-------|-------------------|
| `look.py` | 337 | Auto-discovery: BLE scan, serial port enumeration, LAN device detection |
| `solar.py` | 193 | PowMr MPPT solar charge controller via Modbus RTU |
| `nanovna.py` | 179 | NanoVNA F V2 vector network analyzer via USB serial |
| `geiger.py` | 141 | GMC-300E Geiger counter via USB serial (CP2102) |
| `ecoflow.py` | 134 | EcoFlow Delta 2 battery station via BLE advertisement (manufacturer ID 0xB5B5) |
| `arduino.py` | 126 | Arduino sensor bridge via USB serial (JSON frame protocol) |
| `klipper.py` | 121 | Creality K1C 3D printer via Klipper/Moonraker HTTP API |
| `router.py` | 120 | LAN router status via HTTP (OpenWRT / generic web interface) |

**Feeds total: 1,359 lines**

Usage pattern for all feeds:

```python
from zoeae import Ecosystem, SensorNet
from zoeae.feeds import EcoFlowFeed

eco = Ecosystem("production")
feed = EcoFlowFeed()
feed.attach(eco.sensor_net)
await feed.poll()
value = eco.sensor_net.read("ecoflow:battery")
```

---

## Safety

Safety is enforced by `PolicyEngine` (`src/policy.ts`), which reads `safety.yaml` at startup.

**`safety.yaml` has four sections:**

1. **Process policy** — command denylist (17 patterns: `rm -rf /`, `dd of=`, `mkfs`, `shutdown`, fork bomb, Windows disk tools, etc.), configurable allowlist mode, timeouts (30 s default, 60 s daemon), stdout cap (2 MB), concurrent process limit (3).

2. **Inference policy** — model allowlist (`hermes3:*`, `deepseek-r1:*`, `qwen*`, `llama3*`, etc.), call cap per tick (10), session cap (500), tick time budget (120 s), room validation threshold (0.6).

3. **Tool policy matrix** — per-tool permissions across four execution contexts: `interactive`, `daemon`, `goal`, `mcp`. Permissions: `allow`, `allow_logged`, `confirm` (blocks in daemon/goal — no human present), `deny`. Action-level overrides supported (e.g., `file.delete` can have tighter policy than `file.read`).

4. **Escalation policy** — repeat violation detection over a 60 s window: `warning` (log, continue) → `blocked` (stop, notify user, record to genome) → `critical` (halt daemon, 5 min cooldown). Service restart rate limit: 5 restarts per 5 min window.

The `safety.yaml` header states explicitly: "THIS IS A CAPABILITY DECLARATION, NOT A SECURITY ENFORCEMENT MECHANISM." The tool policy matrix is enforced in-process. The infrastructure sandbox layer (NemoClaw Landlock/seccomp) is declared but not yet active.

---

## Tests

```
python -m pytest tests/
```

Three test files:

| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_zoeae.py` | 53 | Core Python framework: genome, exoskeleton, router, compiler, pipeline, antenna, organism lifecycle |
| `tests/test_full_stack.py` | 14 | Integration: ecosystem components, SensorNet, message flows |
| `tests/test_brain.py` | 10 | Brain organ with mock backend |

**77 tests total.** All pass against the current codebase (last verified 2026-03-22).

---

## Configuration

All settings live under `plugins.entries.zoeae` in `openclaw.json`. Defaults shown.

| Key | Default | Description |
|-----|---------|-------------|
| `autonomyUrl` | `http://127.0.0.1:8766` | AUTONOMY v3.0 genome service URL |
| `bootTier` | `0` | StressCompiler tier: 0=NUCLEUS, 1=CELL, 2=ORGANISM, 3=ECOSYSTEM |
| `maxTokens` | `0` | Auto-tier budget (0 = use bootTier directly) |
| `autoConsolidate` | `true` | Extract knowledge on `/new` and `/reset` |
| `recordTurns` | `true` | Record conversation turns to genome |
| `injectNucleus` | `true` | Inject compiled genome on agent bootstrap |
| `injectTasks` | `true` | Inject pending tasks on agent bootstrap |
| `injectPlan` | `true` | Inject active plan on agent bootstrap |
| `injectServices` | `true` | Inject service health alerts on agent bootstrap |
| `daemonAutoStart` | `false` | Start daemon automatically on gateway startup |
| `daemonIntervalMs` | `300000` | Daemon tick interval (5 minutes) |
| `ollamaUrl` | `http://127.0.0.1:11434` | Ollama API URL |
| `ollamaTimeoutMs` | `120000` | Ollama request timeout (2 minutes) |
| `breadthModel` | `hermes3:8b` | Cheap model for planning breadth (decomposition, voting) |
| `depthModel` | `deepseek-r1:32b` | Expensive model for step expansion and structural jumps |
| `defaultModel` | `hermes3:8b` | Default for delegation and daemon task processing |
| `activityLogEnabled` | `true` | Enable real-time JSONL activity logging |
| `mcpEnabled` | `false` | Start MCP server on gateway startup |
| `mcpPort` | `8768` | MCP server port |

---

## Hardware

Zoeae can communicate with the following hardware:

| Hardware | Interface | Module |
|----------|-----------|--------|
| Creality K1C 3D printer | Moonraker HTTP API (port 7125) | `src/k1c-bridge.ts`, `zoeae/feeds/klipper.py` |
| GMC-300E Plus Geiger counter | USB serial (CP2102) | `zoeae/feeds/geiger.py` |
| NanoVNA F V2 | USB serial (115200 baud), binary protocol | `zoeae/feeds/nanovna.py` |
| Arduino (any sensor sketch) | USB serial, JSON frame protocol | `zoeae/feeds/arduino.py` |
| EcoFlow Delta 2 | BLE advertisement, manufacturer ID 0xB5B5 | `zoeae/feeds/ecoflow.py` |
| PowMr MPPT charge controller | Modbus RTU over serial | `zoeae/feeds/solar.py` |
| LAN router (OpenWRT) | HTTP | `zoeae/feeds/router.py` |

COM ports and IP addresses are read from environment variables or passed at construction time. The K1C host defaults to the `K1C_HOST` environment variable (falls back to `192.168.1.82` if unset — override this for your network).

The `look.py` auto-discovery feed scans for BLE devices, enumerates serial ports, and pings LAN hosts, returning a structured list of found devices.

---

## Status

**What works:**

- All 21 tools register and execute correctly under OpenClaw
- PolicyEngine loads `safety.yaml`, compiles denylist regexes, gates every tool call
- TaskEngine: file-backed persistence, priority queue, dependency tracking, retry
- Planner: goal decomposition via local models, tree search, step expansion
- Daemon: tick loop, service health checks, task processing, metabolic tiers
- DreamEngine: idle-time fact recombination, quality scoring, bridge journaling
- RoomEngine: all 7 modes implemented, anti-sycophancy reasoning method injection
- AgentPool: spawn by role, tmux-backed PTY, task routing, scale up/down, health check
- ActivityLog: 20+ event kinds, rolling rotation, filter by kind
- Dashboard: ANSI terminal telemetry, reads `activity.jsonl`
- OllamaClient: chat, listModels, ping — stdlib fetch, zero dependencies
- AutonomyClient: full typed API for AUTONOMY v3.0 (boot, compile, stats, writeFact, sync)
- McpServer: HTTP server starts and accepts connections on port 8768
- Python framework: all 36 organs instantiate and pass 77 tests
- All 8 sensor feeds implement the SensorFeed interface; hardware connectivity depends on hardware being present

**What is stubbed or incomplete:**

- `src/mcp-server.ts`: The server starts, but tool registration into MCP is deferred (`TODO` at `index.ts:411`). External MCP clients can connect but will see an empty tool list until the registration pass is complete.
- `zoeae/explorer.py`, `zoeae/diversity.py`: 4-line stubs that re-export from `accumulator.py`. The full Explorer and DiversityAnalyzer implementations live in `accumulator.py`.
- AUTONOMY v3.0 (`autonomy.py`, separate process) must be running for genome tools to work. If it is not running, genome tools return a clear error message and degrade gracefully.
- NemoClaw kernel sandbox (Landlock/seccomp) is declared in `safety.yaml` but not yet active.

---

## License

MIT License — Copyright 2026 AnnulusLabs LLC

See `pyproject.toml` for Python package metadata. TypeScript package metadata in `package.json`.
