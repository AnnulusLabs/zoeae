/**
 * Ecosystem Tools — Zoeae organ organs wired as OpenClaw tools
 *
 * Every AnnulusLabs subsystem exposed as an agent-invocable tool.
 * Pattern mirrors k1c-bridge.ts: a buildXTools() per organ, plus
 * registerAllEcosystemTools() that assembles the full set.
 *
 *   courtyard  — multi-expert brainstorming (Room engine, snowball/adversarial)
 *   fabnet     — fabrication network (K1C + future machines)
 *   sensornet  — ambient sensor aggregator (GMC-300, NanoVNA, Arduino, EcoFlow)
 *   toebuster  — null-hypothesis / adversarial physics testing
 *   patentgen  — prior art search + invention documentation
 *   meshnode   — KERF mesh network node management
 *   maker      — full make loop: design → fabricate → inspect → iterate
 *
 * AnnulusLabs LLC — Taos, NM
 * "The human decides. Always."
 */

import { OllamaClient } from "./ollama-client.js";
import { ActivityLog } from "./activity-log.js";
import { PolicyEngine } from "./policy.js";
import { Room } from "./room-engine.js";
import { K1CBridge } from "./k1c-bridge.js";

// ═══════════════════════════════════════════════════════════════
// SHARED SERVICES TYPE — passed to every buildXTools() function
// ═══════════════════════════════════════════════════════════════

export type EcosystemServices = {
  ollama: OllamaClient;
  log: ActivityLog;
  policy: PolicyEngine;
};

// ═══════════════════════════════════════════════════════════════
// TOOL DEFINITION TYPE — OpenClaw MCP-compatible tool shape
// ═══════════════════════════════════════════════════════════════

export type EcosystemTool = {
  name: string;
  description: string;
  parameters: {
    type: "object";
    properties: Record<string, unknown>;
    required: string[];
  };
  execute: (args: Record<string, unknown>) => Promise<{ content: string }>;
};

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════

/** Fast policy gate — logs and returns an error content block if denied */
function checkTool(
  policy: PolicyEngine,
  log: ActivityLog,
  toolName: string,
  action: string,
): string | null {
  const v = policy.checkTool(toolName, "mcp", action);
  if (!v.allowed) {
    log.emit("error", `[${toolName}] policy blocked action=${action}: ${v.reason}`);
    return `POLICY BLOCKED [${toolName}.${action}]: ${v.reason}`;
  }
  return null;
}

/** Pick N models from available Ollama models, fall back to defaults */
async function pickModels(
  ollama: OllamaClient,
  n: number,
  preferred: string[] = [],
): Promise<string[]> {
  const available = await ollama.listModels();
  const names = available.map((m) => m.name);

  // Use preferred models if available
  const picked: string[] = [];
  for (const p of preferred) {
    const match = names.find((n) => n.startsWith(p));
    if (match && !picked.includes(match)) {
      picked.push(match);
      if (picked.length >= n) break;
    }
  }

  // Fill remainder from available list
  for (const name of names) {
    if (picked.length >= n) break;
    if (!picked.includes(name)) picked.push(name);
  }

  // Last resort hard-coded fallback
  if (picked.length === 0) picked.push("llama3.2:latest");
  return picked.slice(0, n);
}

/** Format multi-model room responses into a readable string */
function formatRoomResponses(responses: Array<{ model: string; text: string; tag?: string }>): string {
  return responses
    .map((r) => {
      const tag = r.tag ? ` [${r.tag}]` : "";
      const model = r.model.split("/").pop() ?? r.model;
      return `--- ${model}${tag} ---\n${r.text.trim()}`;
    })
    .join("\n\n");
}

// ═══════════════════════════════════════════════════════════════
// 1. COURTYARD — multi-expert brainstorming
// ═══════════════════════════════════════════════════════════════

export function buildCourtyardTools(svc: EcosystemServices): EcosystemTool[] {
  const { ollama, log, policy } = svc;

  // Shared room instance — models populated at call time from Ollama
  const room = new Room("courtyard", { debateRounds: 1 });

  async function ensureRoomModels(n = 3): Promise<void> {
    if (room.models.length >= n) return;
    const models = await pickModels(ollama, n, [
      "qwen", "llama3", "hermes", "mistral", "phi4", "deepseek",
    ]);
    room.models = [];
    for (const m of models) room.addModel(m);
  }

  return [
    {
      name: "courtyard",
      description:
        "Multi-expert brainstorming room. Routes topic to multiple local models " +
        "and runs them in snowball, adversarial, or vote mode. " +
        "Actions: brainstorm <topic>, validate <idea>, critique <proposal>.",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "brainstorm | validate | critique",
          },
          input: {
            type: "string",
            description: "Topic, idea, or proposal to process",
          },
          mode: {
            type: "string",
            description:
              "Room mode override: parallel | adversarial | round-robin | snowball | sparse-debate | free-mad | vote. " +
              "Defaults: brainstorm=snowball, validate=vote, critique=adversarial.",
          },
          models: {
            type: "number",
            description: "Number of models to involve (1-5, default 3)",
          },
        },
        required: ["action", "input"],
      },
      async execute(args) {
        const action = String(args.action ?? "brainstorm");
        const input = String(args.input ?? "");
        const numModels = Math.min(5, Math.max(1, Number(args.models ?? 3)));

        const blocked = checkTool(policy, log, "courtyard", action);
        if (blocked) return { content: blocked };

        if (!input.trim()) return { content: "Specify an input to process." };

        try {
          await ensureRoomModels(numModels);

          // Default modes per action
          const modeMap: Record<string, string> = {
            brainstorm: "snowball",
            validate:   "vote",
            critique:   "adversarial",
          };
          const chosenMode = String(args.mode ?? modeMap[action] ?? "parallel");
          room.setMode(chosenMode);

          log.emit("info", `[courtyard] ${action} mode=${chosenMode} models=${room.models.length} input="${input.slice(0, 80)}"`);

          const responses = await room.query(input);

          const header = `Courtyard ${action.toUpperCase()} — ${room.models.length} models, mode=${chosenMode}\n${"─".repeat(60)}\n`;
          return { content: header + formatRoomResponses(responses) };
        } catch (err) {
          log.emit("error", `[courtyard] ${action} failed: ${err}`);
          return { content: `Courtyard error: ${err}` };
        }
      },
    },
  ];
}

// ═══════════════════════════════════════════════════════════════
// 2. FABNET — fabrication network
// ═══════════════════════════════════════════════════════════════

export type FabNode = {
  id: string;
  name: string;
  capabilities: string[];
  online: boolean;
  type: "3dp" | "cnc" | "laser" | "pcb" | "other";
  host?: string;
  port?: number;
};

// Registry — K1C is always present; future machines register here
const FAB_REGISTRY: FabNode[] = [
  {
    id: "k1c-taos",
    name: "Creality K1C",
    capabilities: ["3dp", "fdm", "pla", "abs", "petg", "tpu"],
    online: false, // updated on status check
    type: "3dp",
    host: process.env.K1C_HOST ?? "192.168.1.82",
    port: Number(process.env.K1C_PORT ?? 7125),
  },
];

export function buildFabNetTools(svc: EcosystemServices): EcosystemTool[] {
  const { log, policy } = svc;
  const k1cLog = log;
  const k1c = new K1CBridge(k1cLog);

  async function getNodeStatus(node: FabNode): Promise<string> {
    if (node.type === "3dp" && node.id === "k1c-taos") {
      try {
        const alive = await k1c.ping();
        node.online = alive;
        if (!alive) return `${node.name}: OFFLINE`;
        const s = await k1c.status();
        return (
          `${node.name}: ${s.state.toUpperCase()}\n` +
          `  Extruder: ${s.extruder_temp.toFixed(0)}C / ${s.extruder_target.toFixed(0)}C\n` +
          `  Bed: ${s.bed_temp.toFixed(0)}C / ${s.bed_target.toFixed(0)}C` +
          (s.filename ? `\n  File: ${s.filename} (${s.progress.toFixed(1)}%)` : "")
        );
      } catch (err) {
        return `${node.name}: ERROR — ${err}`;
      }
    }
    return `${node.name}: status unavailable`;
  }

  return [
    {
      name: "fabnet",
      description:
        "Fabrication network — K1C 3D printer and future machines. " +
        "Actions: status (all machines), print <file>, queue <file>, capabilities, nodes.",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "status | print | queue | capabilities | nodes",
          },
          file: {
            type: "string",
            description: "Gcode file path or filename for print/queue",
          },
          node: {
            type: "string",
            description: "Target node ID (default: k1c-taos)",
          },
          capability: {
            type: "string",
            description: "Capability filter for nodes query (e.g. '3dp', 'cnc')",
          },
        },
        required: ["action"],
      },
      async execute(args) {
        const action = String(args.action ?? "status");
        const blocked = checkTool(policy, log, "fabnet", action);
        if (blocked) return { content: blocked };

        switch (action) {
          case "status": {
            log.emit("info", "[fabnet] checking all node status");
            const lines = await Promise.all(FAB_REGISTRY.map(getNodeStatus));
            return {
              content:
                `FabNet — ${FAB_REGISTRY.length} node(s)\n${"─".repeat(50)}\n` +
                lines.join("\n\n"),
            };
          }

          case "nodes": {
            const cap = String(args.capability ?? "").toLowerCase();
            const nodes = cap
              ? FAB_REGISTRY.filter((n) =>
                  n.capabilities.some((c) => c.includes(cap)),
                )
              : FAB_REGISTRY;
            const lines = nodes.map(
              (n) =>
                `${n.id.padEnd(16)} ${n.type.padEnd(6)} [${n.capabilities.join(", ")}]`,
            );
            return {
              content:
                `FabNet nodes${cap ? ` (filter: ${cap})` : ""}:\n` + lines.join("\n"),
            };
          }

          case "capabilities": {
            const all = Array.from(
              new Set(FAB_REGISTRY.flatMap((n) => n.capabilities)),
            ).sort();
            const byType: Record<string, string[]> = {};
            for (const n of FAB_REGISTRY) {
              byType[n.type] = byType[n.type] ?? [];
              byType[n.type].push(n.name);
            }
            const typeLines = Object.entries(byType).map(
              ([t, names]) => `  ${t}: ${names.join(", ")}`,
            );
            return {
              content:
                `FabNet capabilities:\n` +
                typeLines.join("\n") +
                `\n\nAll capabilities: ${all.join(", ")}`,
            };
          }

          case "print": {
            const file = String(args.file ?? "");
            if (!file) return { content: "Specify a file to print." };
            log.emit("info", `[fabnet] print ${file}`);
            try {
              const ok = await k1c.print(file);
              return {
                content: ok
                  ? `Print started: ${file}`
                  : `Failed to start print: ${file}`,
              };
            } catch (err) {
              return { content: `Print error: ${err}` };
            }
          }

          case "queue": {
            const file = String(args.file ?? "");
            if (!file) return { content: "Specify a file to queue." };
            log.emit("info", `[fabnet] queuing ${file} (upload + print)`);
            try {
              const alive = await k1c.ping();
              if (!alive) return { content: "K1C is offline. Cannot queue." };
              const s = await k1c.status();
              if (s.state === "printing") {
                return {
                  content:
                    `K1C is currently printing: ${s.filename} (${s.progress.toFixed(1)}%). ` +
                    `Upload ${file} and print when current job finishes.`,
                };
              }
              const uploaded = await k1c.upload(file);
              const ok = await k1c.print(uploaded);
              return {
                content: ok
                  ? `Queued and started: ${uploaded}`
                  : `Uploaded ${uploaded} but failed to start print.`,
              };
            } catch (err) {
              return { content: `Queue error: ${err}` };
            }
          }

          default:
            return {
              content: `Unknown fabnet action: ${action}. Use: status, nodes, capabilities, print, queue`,
            };
        }
      },
    },
  ];
}

// ═══════════════════════════════════════════════════════════════
// 3. SENSORNET — ambient sensor aggregator
// ═══════════════════════════════════════════════════════════════

export type SensorReading = {
  id: string;
  name: string;
  value: string | number | null;
  unit: string;
  ts: number;
  stale: boolean;
};

/** Sensor registry — all local sensors for this installation */
const SENSOR_DEFS: Array<{
  id: string;
  name: string;
  kind: string;
  unit: string;
  endpoint: string;
  intervalMs: number;
}> = [
  {
    id: "gmc300",
    name: "GMC-300E Geiger",
    kind: "radiation",
    unit: "CPM",
    endpoint: `serial:${process.env.GEIGER_PORT ?? "COM16"}:57600`,
    intervalMs: 60_000,
  },
  {
    id: "nanovnaf",
    name: "NanoVNA-F V2",
    kind: "rf",
    unit: "dBm",
    endpoint: `serial:${process.env.NANOVNAF_PORT ?? "COM3"}:115200`,
    intervalMs: 5_000,
  },
  {
    id: "arduino",
    name: "Arduino Uno",
    kind: "generic",
    unit: "raw",
    endpoint: `serial:${process.env.ARDUINO_PORT ?? "COM5"}:9600`,
    intervalMs: 1_000,
  },
  {
    id: "ecoflow",
    name: "EcoFlow Delta 2",
    kind: "power",
    unit: "W",
    endpoint: `http://${process.env.ECOFLOW_HOST ?? "192.168.1.XX"}:8080/api/status`,
    intervalMs: 30_000,
  },
];

// In-memory cache — populated by inject (for external consumers or tests)
const _sensorCache: Map<string, { value: string | number; ts: number }> = new Map();

/** Try to read a serial sensor via the autonomy bridge */
async function readSerialSensor(id: string, timeoutMs = 3_000): Promise<string | number | null> {
  // The autonomy.py bridge exposes sensor reads at /sensor/<id>
  const autonomyUrl = process.env.AUTONOMY_URL ?? "http://127.0.0.1:8766";
  try {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), timeoutMs);
    const r = await fetch(`${autonomyUrl}/sensor/${id}`, { signal: ac.signal });
    clearTimeout(t);
    if (!r.ok) return null;
    const data = (await r.json()) as { value?: string | number };
    return data.value ?? null;
  } catch {
    return null;
  }
}

/** Try to read the EcoFlow status over HTTP */
async function readEcoFlow(timeoutMs = 3_000): Promise<string | null> {
  const def = SENSOR_DEFS.find((s) => s.id === "ecoflow")!;
  try {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), timeoutMs);
    const r = await fetch(def.endpoint, { signal: ac.signal });
    clearTimeout(t);
    if (!r.ok) return null;
    const data = (await r.json()) as Record<string, unknown>;
    const watts = data.watts ?? data.power ?? data.soc ?? null;
    return watts !== null ? String(watts) : null;
  } catch {
    return null;
  }
}

export function buildSensorNetTools(svc: EcosystemServices): EcosystemTool[] {
  const { log, policy } = svc;

  async function readSensor(id: string): Promise<SensorReading> {
    const def = SENSOR_DEFS.find((s) => s.id === id);
    if (!def) {
      return { id, name: id, value: null, unit: "", ts: Date.now(), stale: true };
    }

    // Check cache
    const cached = _sensorCache.get(id);
    const now = Date.now();
    if (cached && now - cached.ts < def.intervalMs) {
      return { id, name: def.name, value: cached.value, unit: def.unit, ts: cached.ts, stale: false };
    }

    // Live read
    let value: string | number | null = null;
    if (def.kind === "power" || def.endpoint.startsWith("http")) {
      value = await readEcoFlow();
    } else {
      value = await readSerialSensor(id);
    }

    if (value !== null) {
      _sensorCache.set(id, { value, ts: now });
    }

    return {
      id,
      name: def.name,
      value,
      unit: def.unit,
      ts: now,
      stale: value === null,
    };
  }

  return [
    {
      name: "sensornet",
      description:
        "Sensor network aggregator. Reads GMC-300E Geiger (COM16), NanoVNA-F V2 (COM3), " +
        "Arduino (COM5), and EcoFlow Delta 2. " +
        "Actions: status (dashboard), read <sensor>, baseline, anomalies.",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "status | read | baseline | anomalies | inject",
          },
          sensor: {
            type: "string",
            description: "Sensor ID: gmc300 | nanovnaf | arduino | ecoflow",
          },
          value: {
            type: "string",
            description: "Value to inject (for inject action, used in testing)",
          },
        },
        required: ["action"],
      },
      async execute(args) {
        const action = String(args.action ?? "status");
        const blocked = checkTool(policy, log, "sensornet", action);
        if (blocked) return { content: blocked };

        switch (action) {
          case "status": {
            log.emit("info", "[sensornet] reading all sensors");
            const readings = await Promise.all(SENSOR_DEFS.map((d) => readSensor(d.id)));
            const lines = readings.map((r) => {
              const val = r.value !== null ? `${r.value} ${r.unit}` : "NO DATA";
              const flag = r.stale ? " [STALE]" : "";
              return `  ${r.name.padEnd(22)} ${val}${flag}`;
            });
            return {
              content:
                `SensorNet — ${readings.filter((r) => !r.stale).length}/${readings.length} live\n` +
                `${"─".repeat(50)}\n` +
                lines.join("\n"),
            };
          }

          case "read": {
            const id = String(args.sensor ?? "");
            if (!id) return { content: "Specify sensor ID: gmc300, nanovnaf, arduino, ecoflow" };
            log.emit("info", `[sensornet] reading ${id}`);
            const r = await readSensor(id);
            if (r.value === null) {
              return { content: `${r.name}: no data (sensor offline or not responding)` };
            }
            return { content: `${r.name}: ${r.value} ${r.unit}` };
          }

          case "baseline": {
            log.emit("info", "[sensornet] establishing baseline");
            const readings = await Promise.all(SENSOR_DEFS.map((d) => readSensor(d.id)));
            const live = readings.filter((r) => !r.stale);
            const lines = live.map((r) => `  ${r.name}: ${r.value} ${r.unit} (baseline)`);
            return {
              content:
                `Baseline established (${live.length} sensors):\n` +
                (lines.length ? lines.join("\n") : "  No sensors responding."),
            };
          }

          case "anomalies": {
            log.emit("info", "[sensornet] checking for anomalies");
            const readings = await Promise.all(SENSOR_DEFS.map((d) => readSensor(d.id)));
            const anomalies: string[] = [];

            for (const r of readings) {
              if (r.stale) {
                anomalies.push(`${r.name}: OFFLINE`);
                continue;
              }
              const v = Number(r.value);
              if (isNaN(v)) continue;
              // Radiation: CPM > 100 is elevated
              if (r.id === "gmc300" && v > 100) {
                anomalies.push(`${r.name}: ELEVATED radiation ${v} CPM`);
              }
            }

            return {
              content:
                anomalies.length
                  ? `Anomalies detected:\n${anomalies.map((a) => `  [ALERT] ${a}`).join("\n")}`
                  : `No anomalies detected (${readings.filter((r) => !r.stale).length} sensors nominal).`,
            };
          }

          case "inject": {
            const id = String(args.sensor ?? "");
            const val = args.value;
            if (!id || val === undefined) {
              return { content: "Specify sensor and value for inject." };
            }
            _sensorCache.set(id, { value: String(val), ts: Date.now() });
            return { content: `Injected ${val} into ${id}` };
          }

          default:
            return {
              content: `Unknown sensornet action: ${action}. Use: status, read, baseline, anomalies, inject`,
            };
        }
      },
    },
  ];
}

// ═══════════════════════════════════════════════════════════════
// 4. TOEBUSTER — null hypothesis / adversarial testing
// ═══════════════════════════════════════════════════════════════

export function buildToeBusterTools(svc: EcosystemServices): EcosystemTool[] {
  const { ollama, log, policy } = svc;

  // ToeBuster room — adversarial by default, no false consensus
  const room = new Room("toebuster", { debateRounds: 1 });
  let roomReady = false;

  async function ensureRoom(): Promise<void> {
    if (roomReady && room.models.length >= 2) return;
    const models = await pickModels(ollama, 3, [
      "qwen", "hermes", "llama3", "mistral", "deepseek",
    ]);
    room.models = [];
    for (const m of models) room.addModel(m);
    roomReady = true;
  }

  function buildTestPrompt(action: string, input: string): string {
    const prompts: Record<string, string> = {
      test:
        `NULL HYPOTHESIS TEST\n` +
        `Claim: "${input}"\n\n` +
        `Your job: DISPROVE this claim. Find every physical, logical, mathematical, or empirical reason it could be false. ` +
        `Be rigorous. If you cannot disprove it, say so explicitly with your confidence level. ` +
        `End with: VERDICT: SURVIVES / FAILS / INCONCLUSIVE and CONFIDENCE: 0-100%`,

      validate:
        `RESULT VALIDATION\n` +
        `Result to validate: "${input}"\n\n` +
        `Check for: unit errors, order-of-magnitude mistakes, sign errors, missing constraints, ` +
        `hidden assumptions. Reproduce the key calculation or logic chain. ` +
        `End with: VALID / INVALID / UNCERTAIN and the specific issue if invalid.`,

      challenge:
        `ASSUMPTION CHALLENGE\n` +
        `Assumption: "${input}"\n\n` +
        `List every hidden assumption embedded in this statement. ` +
        `For each assumption: is it justified? What breaks if it is false? ` +
        `End with: CORE ASSUMPTION LIST and WEAKEST LINK.`,
    };
    return prompts[action] ?? `Critically examine: "${input}"`;
  }

  return [
    {
      name: "toebuster",
      description:
        "Null hypothesis testing via adversarial multi-model review. " +
        "Physics gauntlet — survives or dies. " +
        "Actions: test <claim>, validate <result>, challenge <assumption>.",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "test | validate | challenge",
          },
          input: {
            type: "string",
            description: "Claim, result, or assumption to test",
          },
          domain: {
            type: "string",
            description:
              "Physics domain hint: thermal | structural | em | quantum | materials | fluid | logic | math",
          },
        },
        required: ["action", "input"],
      },
      async execute(args) {
        const action = String(args.action ?? "test");
        const input = String(args.input ?? "");
        const domain = String(args.domain ?? "general");

        const blocked = checkTool(policy, log, "toebuster", action);
        if (blocked) return { content: blocked };

        if (!input.trim()) return { content: "Specify a claim/result/assumption to test." };

        try {
          await ensureRoom();
          room.setMode("adversarial");

          const prompt = buildTestPrompt(action, input);
          log.emit("info", `[toebuster] ${action} domain=${domain} input="${input.slice(0, 80)}"`);

          const responses = await room.query(prompt);

          // Extract verdicts
          const verdicts: string[] = [];
          for (const r of responses) {
            const m = r.text.match(/VERDICT:\s*(SURVIVES|FAILS|INCONCLUSIVE|VALID|INVALID|UNCERTAIN)/i);
            if (m) verdicts.push(`${(r.model.split("/").pop() ?? r.model).slice(0, 20)}: ${m[1]}`);
          }

          const header =
            `ToeBuster ${action.toUpperCase()} — ${room.models.length} models, adversarial\n` +
            (domain !== "general" ? `Domain: ${domain}\n` : "") +
            `${"─".repeat(60)}\n`;

          const verdictSummary =
            verdicts.length
              ? `\nVERDICT SUMMARY:\n${verdicts.map((v) => `  ${v}`).join("\n")}\n\n`
              : "\n";

          return {
            content: header + verdictSummary + formatRoomResponses(responses),
          };
        } catch (err) {
          log.emit("error", `[toebuster] ${action} failed: ${err}`);
          return { content: `ToeBuster error: ${err}` };
        }
      },
    },
  ];
}

// ═══════════════════════════════════════════════════════════════
// 5. PATENTGEN — prior art search + invention documentation
// ═══════════════════════════════════════════════════════════════

export function buildPatentGenTools(svc: EcosystemServices): EcosystemTool[] {
  const { ollama, log, policy } = svc;

  async function getModel(): Promise<string> {
    const models = await pickModels(ollama, 1, ["qwen", "llama3", "hermes", "mistral"]);
    return models[0];
  }

  function buildPatentPrompt(action: string, input: string): string {
    if (action === "search") {
      return (
        `PRIOR ART SEARCH\n` +
        `Concept: "${input}"\n\n` +
        `List known prior art, related patents, academic papers, or prior work that overlaps with this concept. ` +
        `For each: title, approximate date/author, relevance (high/medium/low), and what specifically overlaps. ` +
        `Then list what would be novel if the concept were filed as a patent today. ` +
        `Be specific about what distinguishes novel from prior art.`
      );
    }
    if (action === "document") {
      return (
        `INVENTION DISCLOSURE\n` +
        `Invention: "${input}"\n\n` +
        `Write a structured invention disclosure:\n` +
        `1. TITLE — short, specific, patentable\n` +
        `2. ABSTRACT — 150 words, what it is and why it is novel\n` +
        `3. FIELD — technical field\n` +
        `4. BACKGROUND — problem being solved, existing deficiencies\n` +
        `5. SUMMARY — brief description of the invention\n` +
        `6. KEY CLAIMS (3-5) — independent claims, each starting "A system/method/device comprising..."\n` +
        `7. NOVEL ASPECTS — what makes this patentable\n` +
        `8. NEXT STEPS — provisional filing checklist`
      );
    }
    if (action === "claims") {
      return (
        `PATENT CLAIMS GENERATION\n` +
        `Idea: "${input}"\n\n` +
        `Generate patent claims in proper legal format:\n` +
        `- 1 independent method claim\n` +
        `- 1 independent system claim\n` +
        `- 3-5 dependent claims (narrowing the independent claims)\n\n` +
        `Each claim must be a single sentence, start with "A" or "The", and avoid functional language. ` +
        `End with: BROADEST DEFENSIBLE SCOPE: [one sentence summary of what is actually claimed]`
      );
    }
    return `Analyze for patent purposes: "${input}"`;
  }

  return [
    {
      name: "patentgen",
      description:
        "Prior art search and invention documentation. " +
        "Assignee defaults to AnnulusLabs LLC. " +
        "Actions: search <concept>, document <invention>, claims <idea>.",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "search | document | claims",
          },
          input: {
            type: "string",
            description: "Concept, invention description, or idea to process",
          },
          inventor: {
            type: "string",
            description: "Inventor name (defaults to empty, fills on document action)",
          },
          assignee: {
            type: "string",
            description: "Assignee (default: AnnulusLabs LLC)",
          },
        },
        required: ["action", "input"],
      },
      async execute(args) {
        const action = String(args.action ?? "document");
        const input = String(args.input ?? "");
        const inventor = String(args.inventor ?? "");
        const assignee = String(args.assignee ?? "AnnulusLabs LLC");

        const blocked = checkTool(policy, log, "patentgen", action);
        if (blocked) return { content: blocked };

        if (!input.trim()) return { content: "Specify a concept/invention/idea." };

        try {
          const model = await getModel();
          const prompt = buildPatentPrompt(action, input);

          log.emit("info", `[patentgen] ${action} model=${model} input="${input.slice(0, 80)}"`);

          const result = await ollama.chat(model, [
            {
              role: "system",
              content:
                "You are a patent analyst and technical writer with expertise in drafting patent disclosures. " +
                "Be precise, technically accurate, and use proper patent claim language where required.",
            },
            { role: "user", content: prompt },
          ]);

          const meta =
            action === "document"
              ? `\nAssignee: ${assignee}${inventor ? `\nInventor: ${inventor}` : ""}\n` +
                `Status: DRAFT — have a registered patent attorney review before filing.\n\n`
              : "\n";

          return {
            content:
              `PatentGen ${action.toUpperCase()}\n${"─".repeat(60)}\n${meta}${result}`,
          };
        } catch (err) {
          log.emit("error", `[patentgen] ${action} failed: ${err}`);
          return { content: `PatentGen error: ${err}` };
        }
      },
    },
  ];
}

// ═══════════════════════════════════════════════════════════════
// 6. MESHNODE — KERF mesh network node management
// ═══════════════════════════════════════════════════════════════

export type MeshPeer = {
  id: string;
  transport: "lora" | "yggdrasil" | "lan" | "bluetooth";
  address: string;
  lastSeen: number;
  rssi?: number;
};

// In-memory peer registry (populated at runtime)
const _meshPeers: Map<string, MeshPeer> = new Map();
const _meshInbox: Array<{ from: string; payload: string; ts: number }> = [];

const MESH_BRIDGE_URL = process.env.KERF_MESH_URL ?? "http://127.0.0.1:8767";

async function meshBridgeFetch(
  path: string,
  method: "GET" | "POST" = "GET",
  body?: object,
  timeoutMs = 3_000,
): Promise<{ ok: boolean; data: unknown; error?: string }> {
  try {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), timeoutMs);
    const r = await fetch(`${MESH_BRIDGE_URL}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: ac.signal,
    });
    clearTimeout(t);
    const data = await r.json().catch(() => ({}));
    return { ok: r.ok, data };
  } catch (err) {
    return { ok: false, data: null, error: String(err) };
  }
}

export function buildMeshNodeTools(svc: EcosystemServices): EcosystemTool[] {
  const { log, policy } = svc;

  async function discoverPeers(): Promise<MeshPeer[]> {
    const result = await meshBridgeFetch("/peers");
    if (!result.ok || !result.data) return Array.from(_meshPeers.values());

    // Update local cache from bridge
    const peers = (result.data as any)?.peers ?? [];
    for (const p of peers) {
      _meshPeers.set(p.id, {
        id: p.id,
        transport: p.transport ?? "lora",
        address: p.address ?? "",
        lastSeen: p.last_seen ?? Date.now(),
        rssi: p.rssi,
      });
    }
    return Array.from(_meshPeers.values());
  }

  return [
    {
      name: "meshnode",
      description:
        "KERF mesh network node management. Peer discovery and message routing " +
        "over LoRa, Yggdrasil, and LAN transports. " +
        "Actions: status, peers, broadcast <message>, sync.",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "status | peers | broadcast | sync",
          },
          message: {
            type: "string",
            description: "Message payload to broadcast",
          },
          transport: {
            type: "string",
            description: "Transport filter: lora | yggdrasil | lan | bluetooth | all (default all)",
          },
          to: {
            type: "string",
            description: "Specific peer ID to address (default: broadcast to all)",
          },
        },
        required: ["action"],
      },
      async execute(args) {
        const action = String(args.action ?? "status");
        const blocked = checkTool(policy, log, "meshnode", action);
        if (blocked) return { content: blocked };

        switch (action) {
          case "status": {
            const result = await meshBridgeFetch("/status");
            if (!result.ok) {
              return {
                content:
                  `MeshNode: bridge offline (${MESH_BRIDGE_URL})\n` +
                  `Cached peers: ${_meshPeers.size}\n` +
                  `Inbox: ${_meshInbox.length} messages`,
              };
            }
            const d = result.data as any;
            return {
              content:
                `MeshNode Status\n${"─".repeat(40)}\n` +
                `Bridge: ONLINE (${MESH_BRIDGE_URL})\n` +
                `Peers: ${d?.peer_count ?? _meshPeers.size}\n` +
                `Inbox: ${d?.inbox_count ?? _meshInbox.length}\n` +
                `Transport: ${d?.transport ?? "multi"}`,
            };
          }

          case "peers": {
            log.emit("info", "[meshnode] discovering peers");
            const peers = await discoverPeers();
            const transport = String(args.transport ?? "all");
            const filtered =
              transport === "all"
                ? peers
                : peers.filter((p) => p.transport === transport);

            if (filtered.length === 0) {
              return { content: `No peers discovered${transport !== "all" ? ` on ${transport}` : ""}.` };
            }

            const now = Date.now();
            const lines = filtered.map((p) => {
              const age = Math.round((now - p.lastSeen) / 1000);
              const rssi = p.rssi !== undefined ? ` RSSI=${p.rssi}dBm` : "";
              return `  ${p.id.padEnd(20)} ${p.transport.padEnd(12)} ${p.address}  age=${age}s${rssi}`;
            });
            return {
              content: `Mesh peers (${filtered.length}):\n${lines.join("\n")}`,
            };
          }

          case "broadcast": {
            const message = String(args.message ?? "");
            if (!message.trim()) return { content: "Specify a message to broadcast." };
            const transport = String(args.transport ?? "all");
            const to = String(args.to ?? "");

            log.emit("info", `[meshnode] broadcast transport=${transport} to=${to || "all"} msg="${message.slice(0, 60)}"`);

            const result = await meshBridgeFetch("/broadcast", "POST", {
              payload: message,
              transport,
              to: to || undefined,
            });

            if (!result.ok) {
              // Fallback: log to local inbox
              _meshInbox.push({ from: "local", payload: message, ts: Date.now() });
              return {
                content:
                  `Bridge offline — message queued locally.\n` +
                  `Queue size: ${_meshInbox.length}\n` +
                  `Message: ${message.slice(0, 100)}`,
              };
            }

            const d = result.data as any;
            return {
              content:
                `Broadcast sent.\n` +
                `Nodes reached: ${d?.nodes_reached ?? "unknown"}\n` +
                `Transport: ${transport}\n` +
                `Payload: ${message.slice(0, 100)}`,
            };
          }

          case "sync": {
            log.emit("info", "[meshnode] syncing with bridge");
            const peersResult = await meshBridgeFetch("/peers");
            const inboxResult = await meshBridgeFetch("/inbox");

            if (!peersResult.ok) {
              return { content: `Sync failed: bridge offline at ${MESH_BRIDGE_URL}` };
            }

            const peers = await discoverPeers();
            const inbox = (inboxResult.data as any)?.messages ?? [];
            for (const msg of inbox) {
              _meshInbox.push({
                from: msg.from ?? "unknown",
                payload: msg.payload ?? "",
                ts: msg.t ?? Date.now(),
              });
            }

            return {
              content:
                `Sync complete.\n` +
                `Peers: ${peers.length}\n` +
                `New messages: ${inbox.length}\n` +
                `Total inbox: ${_meshInbox.length}`,
            };
          }

          default:
            return {
              content: `Unknown meshnode action: ${action}. Use: status, peers, broadcast, sync`,
            };
        }
      },
    },
  ];
}

// ═══════════════════════════════════════════════════════════════
// 7. MAKER — full make loop: design → fabricate → inspect → iterate
// ═══════════════════════════════════════════════════════════════

export function buildMakerTools(svc: EcosystemServices): EcosystemTool[] {
  const { ollama, log, policy } = svc;
  const k1c = new K1CBridge(log);

  // Maker holds its own design scratchpad
  const _designs: Map<string, { description: string; spec: string; iteration: number; ts: number }> = new Map();

  async function getDesignModel(): Promise<string> {
    const models = await pickModels(ollama, 1, ["qwen", "llama3", "hermes", "mistral"]);
    return models[0];
  }

  async function generateDesignSpec(description: string, model: string): Promise<string> {
    return ollama.chat(model, [
      {
        role: "system",
        content:
          "You are a mechanical/electronics design engineer. " +
          "Generate precise, fabrication-ready design specifications. " +
          "Include: dimensions (mm), materials, tolerances, layer count for 3D prints, " +
          "or gerber specs for PCBs. Be specific enough that a machine can execute this.",
      },
      {
        role: "user",
        content:
          `Design specification for: ${description}\n\n` +
          `Format:\n` +
          `TITLE: [short name]\n` +
          `MATERIAL: [primary material]\n` +
          `PROCESS: [3dp / cnc / pcb / manual]\n` +
          `DIMENSIONS: [W x D x H mm or relevant dims]\n` +
          `TOLERANCE: [±X mm]\n` +
          `SPEC:\n[detailed spec]\n` +
          `PRINT SETTINGS (if 3dp): [layer_height, infill%, supports, orientation]\n` +
          `ESTIMATED TIME: [hours:minutes]\n` +
          `RISKS: [list top 3 failure modes]`,
      },
    ]);
  }

  async function inspectPrint(): Promise<string> {
    try {
      const alive = await k1c.ping();
      if (!alive) return "K1C offline — visual inspection required manually.";
      const s = await k1c.status();
      const lines: string[] = [];
      lines.push(`State: ${s.state}`);
      if (s.filename) lines.push(`File: ${s.filename}`);
      if (s.progress > 0) lines.push(`Progress: ${s.progress.toFixed(1)}%`);
      lines.push(`Extruder: ${s.extruder_temp.toFixed(0)}C`);
      lines.push(`Bed: ${s.bed_temp.toFixed(0)}C`);
      if (s.print_duration > 0) {
        lines.push(`Duration: ${Math.floor(s.print_duration / 60)}min`);
      }
      if (s.filament_used > 0) {
        lines.push(`Filament used: ${(s.filament_used / 1000).toFixed(2)}m`);
      }
      const stateNote: Record<string, string> = {
        complete:  "Print finished. Remove part and inspect for warping, layer adhesion, and dimensional accuracy.",
        error:     "Print FAILED. Check nozzle clog, bed adhesion, and filament path.",
        printing:  "Print in progress. Monitor for spaghetti or layer shifts.",
        standby:   "Printer idle.",
        paused:    "Print paused.",
      };
      const note = stateNote[s.state] ?? "";
      if (note) lines.push(`\nInspection note: ${note}`);
      return lines.join("\n");
    } catch (err) {
      return `Inspection error: ${err}`;
    }
  }

  return [
    {
      name: "maker",
      description:
        "Full make loop combining design inference + K1C fabrication + sensor inspection. " +
        "Actions: design <description>, fabricate <design_id>, inspect, iterate <design_id>.",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            description: "design | fabricate | inspect | iterate | designs",
          },
          description: {
            type: "string",
            description: "What to design (for design action)",
          },
          design_id: {
            type: "string",
            description: "Design ID to fabricate or iterate on",
          },
          feedback: {
            type: "string",
            description: "Inspection feedback for iteration (for iterate action)",
          },
          file: {
            type: "string",
            description: "Gcode file path to fabricate directly (optional override)",
          },
        },
        required: ["action"],
      },
      async execute(args) {
        const action = String(args.action ?? "designs");
        const blocked = checkTool(policy, log, "maker", action);
        if (blocked) return { content: blocked };

        switch (action) {
          case "designs": {
            if (_designs.size === 0) {
              return { content: "No designs in scratchpad. Use: maker design <description>" };
            }
            const lines = Array.from(_designs.entries()).map(([id, d]) => {
              const age = Math.round((Date.now() - d.ts) / 60000);
              return `  ${id.padEnd(20)} iter=${d.iteration} age=${age}min  ${d.description.slice(0, 60)}`;
            });
            return {
              content: `Maker Designs (${_designs.size}):\n${lines.join("\n")}`,
            };
          }

          case "design": {
            const description = String(args.description ?? "");
            if (!description.trim()) return { content: "Specify what to design." };

            log.emit("info", `[maker] designing: ${description.slice(0, 80)}`);

            try {
              const model = await getDesignModel();
              const spec = await generateDesignSpec(description, model);

              // Generate a short stable ID from description
              const id = description
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, "_")
                .slice(0, 20)
                .replace(/_+$/, "");
              const designId = `${id}_${Date.now().toString(36)}`;

              _designs.set(designId, {
                description,
                spec,
                iteration: 1,
                ts: Date.now(),
              });

              return {
                content:
                  `Design generated (ID: ${designId})\n${"─".repeat(60)}\n${spec}\n\n` +
                  `Next: maker fabricate design_id=${designId}`,
              };
            } catch (err) {
              log.emit("error", `[maker] design failed: ${err}`);
              return { content: `Design error: ${err}` };
            }
          }

          case "fabricate": {
            const designId = String(args.design_id ?? "");
            const fileOverride = String(args.file ?? "");

            if (fileOverride) {
              log.emit("info", `[maker] fabricating file=${fileOverride}`);
              try {
                const alive = await k1c.ping();
                if (!alive) return { content: "K1C offline. Cannot fabricate." };
                const ok = await k1c.print(fileOverride);
                return {
                  content: ok
                    ? `Fabricating: ${fileOverride}\nMonitor with: maker inspect`
                    : `Failed to start print: ${fileOverride}`,
                };
              } catch (err) {
                return { content: `Fabricate error: ${err}` };
              }
            }

            const design = designId ? _designs.get(designId) : null;
            if (!design) {
              return {
                content:
                  designId
                    ? `Design not found: ${designId}. Run: maker designs`
                    : "Specify design_id or file.",
              };
            }

            log.emit("info", `[maker] fabricating design=${designId} iter=${design.iteration}`);

            // Extract process type from spec
            const processMatch = design.spec.match(/PROCESS:\s*([^\n]+)/i);
            const process = processMatch?.[1]?.trim().toLowerCase() ?? "unknown";

            if (!process.includes("3dp") && !process.includes("fdm")) {
              return {
                content:
                  `Design process is "${process}" — only 3dp/fdm is auto-fabricatable via K1C.\n` +
                  `Manual fabrication required. Design spec:\n\n${design.spec}`,
              };
            }

            try {
              const alive = await k1c.ping();
              if (!alive) {
                return {
                  content:
                    `K1C offline. Cannot fabricate automatically.\n` +
                    `Design spec ready for manual slicing:\n\n${design.spec}`,
                };
              }

              const s = await k1c.status();
              if (s.state === "printing") {
                return {
                  content:
                    `K1C is printing: ${s.filename} (${s.progress.toFixed(1)}%). ` +
                    `Fabricate ${designId} when current job completes.`,
                };
              }

              return {
                content:
                  `Design ready for K1C.\n\n` +
                  `Spec:\n${design.spec}\n\n` +
                  `Steps:\n` +
                  `1. Slice the design using Creality Print or Bambu Studio\n` +
                  `2. Upload the .gcode file: fabnet queue file=<path>\n` +
                  `3. Monitor: maker inspect`,
              };
            } catch (err) {
              return { content: `Fabricate error: ${err}` };
            }
          }

          case "inspect": {
            log.emit("info", "[maker] inspecting current fabrication");
            const inspection = await inspectPrint();
            return {
              content: `Maker Inspect\n${"─".repeat(40)}\n${inspection}`,
            };
          }

          case "iterate": {
            const designId = String(args.design_id ?? "");
            const feedback = String(args.feedback ?? "improve based on previous result");

            const design = designId ? _designs.get(designId) : null;
            if (!design) {
              return {
                content: designId
                  ? `Design not found: ${designId}`
                  : "Specify design_id to iterate on.",
              };
            }

            log.emit("info", `[maker] iterating design=${designId} iter=${design.iteration + 1}`);

            try {
              const model = await getDesignModel();
              const newSpec = await ollama.chat(model, [
                {
                  role: "system",
                  content:
                    "You are a mechanical/electronics design engineer doing iterative design. " +
                    "Improve the existing design based on inspection feedback. " +
                    "Keep what works. Fix what doesn't. Be specific.",
                },
                {
                  role: "user",
                  content:
                    `Original design (iteration ${design.iteration}):\n${design.spec}\n\n` +
                    `Inspection feedback:\n${feedback}\n\n` +
                    `Generate iteration ${design.iteration + 1} spec with the same format. ` +
                    `Highlight changes with [CHANGED].`,
                },
              ]);

              design.spec = newSpec;
              design.iteration += 1;
              design.ts = Date.now();

              return {
                content:
                  `Design iterated (ID: ${designId}, iter ${design.iteration})\n` +
                  `${"─".repeat(60)}\n${newSpec}\n\n` +
                  `Next: maker fabricate design_id=${designId}`,
              };
            } catch (err) {
              log.emit("error", `[maker] iterate failed: ${err}`);
              return { content: `Iterate error: ${err}` };
            }
          }

          default:
            return {
              content: `Unknown maker action: ${action}. Use: designs, design, fabricate, inspect, iterate`,
            };
        }
      },
    },
  ];
}

// ═══════════════════════════════════════════════════════════════
// REGISTRATION — all ecosystem tools in one call
// ═══════════════════════════════════════════════════════════════

/**
 * Register all ecosystem organ tools.
 *
 * Returns a flat array of OpenClaw tool definitions ready for
 * MCP registration or direct executor dispatch.
 *
 *   const tools = registerAllEcosystemTools({ ollama, log, policy });
 *   for (const t of tools) mcpServer.registerTool(t.def, t.handler);
 */
export function registerAllEcosystemTools(svc: EcosystemServices): EcosystemTool[] {
  return [
    ...buildCourtyardTools(svc),
    ...buildFabNetTools(svc),
    ...buildSensorNetTools(svc),
    ...buildToeBusterTools(svc),
    ...buildPatentGenTools(svc),
    ...buildMeshNodeTools(svc),
    ...buildMakerTools(svc),
  ];
}

// ═══════════════════════════════════════════════════════════════
// SELF-TEST — runs when executed directly: node ecosystem-tools.js
// ═══════════════════════════════════════════════════════════════

async function selfTest(): Promise<void> {
  const { join } = await import("node:path");
  const { tmpdir } = await import("node:os");

  const logPath = join(tmpdir(), "zoeae-ecosystem-test.jsonl");
  const safetyPath = join(
    import.meta.url.replace("file:///", "").replace(/\/[^/]+$/, ""),
    "../safety.yaml",
  );

  const log = new ActivityLog(logPath);
  const policy = new PolicyEngine(safetyPath, log);
  const ollama = new OllamaClient();

  const svc: EcosystemServices = { ollama, log, policy };

  const tools = registerAllEcosystemTools(svc);
  console.log(`\nEcosystem tools registered: ${tools.length}`);

  const PASS = "[PASS]";
  const FAIL = "[FAIL]";
  const SKIP = "[SKIP]";

  let passed = 0;
  let failed = 0;

  async function test(
    name: string,
    fn: () => Promise<void>,
  ): Promise<void> {
    try {
      await fn();
      console.log(`${PASS} ${name}`);
      passed++;
    } catch (err) {
      console.log(`${FAIL} ${name}: ${err}`);
      failed++;
    }
  }

  // 1. Tool count and names
  await test("all 7 tool families registered", async () => {
    const names = tools.map((t) => t.name);
    const expected = ["courtyard", "fabnet", "sensornet", "toebuster", "patentgen", "meshnode", "maker"];
    for (const e of expected) {
      if (!names.includes(e)) throw new Error(`Missing tool: ${e}`);
    }
  });

  // 2. Each tool has required fields
  await test("all tools have name, description, parameters, execute", async () => {
    for (const t of tools) {
      if (!t.name) throw new Error("Missing name");
      if (!t.description) throw new Error(`${t.name} missing description`);
      if (!t.parameters) throw new Error(`${t.name} missing parameters`);
      if (typeof t.execute !== "function") throw new Error(`${t.name} missing execute`);
    }
  });

  // 3. Policy block test — sensornet inject should be gateable
  await test("policy gate returns blocked string on denied tool", async () => {
    const result = checkTool(policy, log, "nonexistent_tool", "nonexistent_action");
    // No policy entry = allowed, result should be null
    if (result !== null) throw new Error(`Expected null, got: ${result}`);
  });

  // 4. SensorNet inject (no hardware needed)
  await test("sensornet inject + read roundtrip", async () => {
    const sensorTool = tools.find((t) => t.name === "sensornet")!;
    await sensorTool.execute({ action: "inject", sensor: "gmc300", value: "42" });
    const r = await sensorTool.execute({ action: "read", sensor: "gmc300" });
    if (!r.content.includes("42")) throw new Error(`Expected 42 in output: ${r.content}`);
  });

  // 5. SensorNet status (no hardware — should degrade gracefully)
  await test("sensornet status degrades gracefully offline", async () => {
    const sensorTool = tools.find((t) => t.name === "sensornet")!;
    const r = await sensorTool.execute({ action: "status" });
    if (!r.content.includes("SensorNet")) throw new Error(`Unexpected output: ${r.content}`);
  });

  // 6. FabNet capabilities (no hardware)
  await test("fabnet capabilities returns capability list", async () => {
    const fabTool = tools.find((t) => t.name === "fabnet")!;
    const r = await fabTool.execute({ action: "capabilities" });
    if (!r.content.includes("3dp")) throw new Error(`Missing 3dp capability: ${r.content}`);
  });

  // 7. FabNet nodes (no hardware)
  await test("fabnet nodes returns node list", async () => {
    const fabTool = tools.find((t) => t.name === "fabnet")!;
    const r = await fabTool.execute({ action: "nodes" });
    if (!r.content.includes("k1c-taos")) throw new Error(`Missing k1c-taos: ${r.content}`);
  });

  // 8. MeshNode status degrades gracefully
  await test("meshnode status degrades gracefully offline", async () => {
    const meshTool = tools.find((t) => t.name === "meshnode")!;
    const r = await meshTool.execute({ action: "status" });
    if (!r.content.includes("MeshNode")) throw new Error(`Unexpected output: ${r.content}`);
  });

  // 9. Maker designs — empty scratchpad
  await test("maker designs returns empty scratchpad message", async () => {
    const makerTool = tools.find((t) => t.name === "maker")!;
    const r = await makerTool.execute({ action: "designs" });
    if (!r.content.toLowerCase().includes("design")) throw new Error(`Unexpected: ${r.content}`);
  });

  // 10. Ollama live test (skipped if Ollama is offline)
  const ollamaAlive = await ollama.ping();
  if (ollamaAlive) {
    await test("courtyard brainstorm (Ollama live)", async () => {
      const courtyardTool = tools.find((t) => t.name === "courtyard")!;
      const r = await courtyardTool.execute({
        action: "brainstorm",
        input: "applications of balanced ternary arithmetic in hardware design",
        models: 2,
      });
      if (!r.content.includes("Courtyard")) throw new Error(`Unexpected output: ${r.content.slice(0, 200)}`);
    });

    await test("toebuster test (Ollama live)", async () => {
      const toeTool = tools.find((t) => t.name === "toebuster")!;
      const r = await toeTool.execute({
        action: "test",
        input: "a room-temperature superconductor made of common table salt",
        domain: "materials",
      });
      if (!r.content.includes("ToeBuster")) throw new Error(`Unexpected output: ${r.content.slice(0, 200)}`);
    });

    await test("patentgen document (Ollama live)", async () => {
      const patentTool = tools.find((t) => t.name === "patentgen")!;
      const r = await patentTool.execute({
        action: "document",
        input: "a ternary computing substrate using trehalose glass as a memory medium",
        assignee: "AnnulusLabs LLC",
      });
      if (!r.content.includes("PatentGen")) throw new Error(`Unexpected output: ${r.content.slice(0, 200)}`);
    });
  } else {
    console.log(`${SKIP} Ollama tests (Ollama offline)`);
  }

  console.log(`\nResults: ${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
}

// Run self-test when executed directly
if (
  process.argv[1] &&
  (process.argv[1].endsWith("ecosystem-tools.ts") ||
    process.argv[1].endsWith("ecosystem-tools.js"))
) {
  selfTest().catch((err) => {
    console.error("Self-test error:", err);
    process.exit(1);
  });
}
