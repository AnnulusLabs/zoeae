/**
 * Dream Engine — Creative recombination during idle time
 *
 * File-backed. No external API. Reads knowledge directly from:
 *   - claude_session_log.jsonl (session facts)
 *   - KERF .kerf/*.jsonl (domain knowledge stores)
 *   - Zoeae activity.jsonl (tool call history)
 *
 * Pulls random facts from unrelated domains, asks a local Ollama
 * model to find structural connections. Most dreams are garbage —
 * discarded. Real bridges get written as rhymes_with entries to
 * a dream journal (dreams.jsonl).
 *
 * AnnulusLabs LLC — Taos, NM
 * "The circle must remain broken to vibrate"
 */

import { readFileSync, writeFileSync, appendFileSync, existsSync, readdirSync, mkdirSync } from "node:fs";
import { join, basename } from "node:path";
import { OllamaClient } from "./ollama-client.js";
import { ActivityLog } from "./activity-log.js";

// ── Config ───────────────────────────────────────────────────────

export type DreamConfig = {
  enabled: boolean;
  model: string;
  minIdleMs: number;
  dreamIntervalMs: number;
  maxDreamsPerSession: number;
  minBridgeQuality: number;
  factsPerDream: number;
  /** Paths to scan for knowledge */
  knowledgePaths: string[];
  /** Where to write dreams */
  journalPath: string;
  /** Resource-gated mode: dream whenever Ollama is available, not just idle */
  resourceGated: boolean;
  /** Quality threshold to expand a bridge into an actionable task */
  expandThreshold: number;
  /** Callback when a dream is promoted to actionable */
  onPromote?: (dream: Dream, actionPlan: string) => void;
};

const DEFAULTS: DreamConfig = {
  enabled: true,
  model: "hermes3:8b",
  minIdleMs: 600_000,
  dreamIntervalMs: 300_000,
  maxDreamsPerSession: 50,
  minBridgeQuality: 0.6,
  factsPerDream: 2,
  knowledgePaths: ((): string[] => {
    try { const { paths } = require("./paths.js"); return paths.knowledgePaths(); }
    catch { return [process.env.ZOEAE_DATA ?? join(process.env.HOME ?? ".", ".zoeae", "data")]; }
  })(),
  journalPath: ((): string => {
    try { const { paths } = require("./paths.js"); return paths.dreamJournal(); }
    catch { return join(process.env.ZOEAE_DATA ?? join(process.env.HOME ?? ".", ".zoeae", "data"), "dreams.jsonl"); }
  })(),
  resourceGated: true,
  expandThreshold: 0.8,
};

export type Dream = {
  id: string;
  ts: string;
  facts: Array<{ content: string; domain: string; source: string }>;
  bridge: string;
  quality: number;
  kept: boolean;
};

// ── Fact pool — reads local files ────────────────────────────────

type RawFact = { content: string; domain: string; source: string };

function loadFactPool(paths: string[]): RawFact[] {
  const facts: RawFact[] = [];

  for (const p of paths) {
    try {
      if (!existsSync(p)) continue;

      // If it's a directory, scan all .jsonl files in it
      const files = p.endsWith("/") || !p.includes(".")
        ? readdirSync(p).filter((f) => f.endsWith(".jsonl")).map((f) => join(p, f))
        : [p];

      for (const file of files) {
        if (!existsSync(file)) continue;
        const domain = basename(file, ".jsonl");
        const lines = readFileSync(file, "utf-8").trim().split("\n").filter(Boolean);

        for (const line of lines) {
          try {
            const entry = JSON.parse(line);
            // Extract readable content from various JSONL formats
            const content =
              entry.fact ?? entry.summary ?? entry.text ?? entry.content ??
              entry.observation ?? entry.message ?? entry.description ??
              (typeof entry.action === "string" && entry.path ? `${entry.action}: ${entry.path}` : null);
            if (content && typeof content === "string" && content.length > 20) {
              facts.push({
                content: content.slice(0, 300),
                domain: entry.category ?? entry.domain ?? entry.kind ?? domain,
                source: basename(file),
              });
            }
          } catch { /* skip unparseable lines */ }
        }
      }
    } catch { /* skip inaccessible paths */ }
  }

  return facts;
}

// ── Dream Engine ─────────────────────────────────────────────────

export class DreamEngine {
  private cfg: DreamConfig;
  private ollama: OllamaClient;
  private log: ActivityLog;
  private dreamCount = 0;
  private dreams: Dream[] = [];
  private _timer: ReturnType<typeof setInterval> | null = null;
  private _idleCheck: () => number;
  private _factPool: RawFact[] = [];
  private _poolLoadedAt = 0;

  constructor(
    ollama: OllamaClient,
    log: ActivityLog,
    idleCheck: () => number,
    config?: Partial<DreamConfig>,
  ) {
    this.cfg = { ...DEFAULTS, ...config };
    this.ollama = ollama;
    this.log = log;
    this._idleCheck = idleCheck;
  }

  start(): boolean {
    if (this._timer) return false;
    this._timer = setInterval(() => {
      this._maybeDream().catch((e) =>
        this.log.emit("error", `dream engine error: ${e}`)
      );
    }, this.cfg.dreamIntervalMs);
    this.log.emit("info", "dream engine started");
    return true;
  }

  stop(): boolean {
    if (!this._timer) return false;
    clearInterval(this._timer);
    this._timer = null;
    this.log.emit("info", `dream engine stopped (${this.dreamCount} dreams, ${this.dreams.filter(d => d.kept).length} kept)`);
    return true;
  }

  isRunning(): boolean { return this._timer !== null; }

  async dreamOnce(): Promise<Dream | null> {
    return this._dream();
  }

  history(limit = 20): Dream[] {
    return this.dreams.slice(-limit);
  }

  bridges(): Dream[] {
    return this.dreams.filter((d) => d.kept);
  }

  status(): {
    running: boolean;
    dreamCount: number;
    keptCount: number;
    avgQuality: number;
    factPoolSize: number;
    config: DreamConfig;
  } {
    const kept = this.dreams.filter((d) => d.kept);
    const avgQ = this.dreams.length > 0
      ? this.dreams.reduce((s, d) => s + d.quality, 0) / this.dreams.length
      : 0;
    return {
      running: this.isRunning(),
      dreamCount: this.dreamCount,
      keptCount: kept.length,
      avgQuality: avgQ,
      factPoolSize: this._factPool.length,
      config: this.cfg,
    };
  }

  // ── Internal ────────────────────────────────────────────────

  private refreshPool(): void {
    const now = Date.now();
    // Reload pool every 10 minutes
    if (now - this._poolLoadedAt < 600_000 && this._factPool.length > 0) return;
    this._factPool = loadFactPool(this.cfg.knowledgePaths);
    this._poolLoadedAt = now;
    this.log.emit("info", `dream pool refreshed: ${this._factPool.length} facts`);
  }

  private async _maybeDream(): Promise<void> {
    if (!this.cfg.enabled) return;
    if (this.dreamCount >= this.cfg.maxDreamsPerSession) return;

    // Resource-gated: dream whenever Ollama responds (system has spare capacity)
    // Idle-gated (legacy): dream only after minIdleMs of inactivity
    if (!this.cfg.resourceGated && this._idleCheck() < this.cfg.minIdleMs) return;

    if (!(await this.ollama.ping())) return;
    await this._dream();
  }

  private async _dream(): Promise<Dream | null> {
    this.dreamCount++;
    const dreamId = `dream_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`;

    this.refreshPool();
    if (this._factPool.length < 10) {
      this.log.emit("info", `${dreamId}: not enough facts to dream (${this._factPool.length})`);
      return null;
    }

    // Pick N random facts from DIFFERENT domains
    const picked = this._pickDiverseFacts(this.cfg.factsPerDream);
    if (picked.length < 2) return null;

    this.log.emit("info", `${dreamId}: dreaming across [${picked.map(f => f.domain).join(", ")}]`);

    // Ask the model to find connections
    const bridge = await this._findBridge(picked);
    if (!bridge) {
      this.log.emit("info", `${dreamId}: no bridge found`);
      return null;
    }

    const quality = await this._scoreBridge(bridge, picked);

    const dream: Dream = {
      id: dreamId,
      ts: new Date().toISOString(),
      facts: picked,
      bridge,
      quality,
      kept: quality >= this.cfg.minBridgeQuality,
    };

    this.dreams.push(dream);

    if (dream.kept) {
      this._writeDream(dream);
      this.log.emit("genome_event",
        `${dreamId} KEPT (q=${quality.toFixed(2)}): [${picked.map(f => f.domain).join("↔")}] ${bridge.slice(0, 100)}`
      );

      // Promote high-quality dreams: expand into actionable plan
      if (quality >= this.cfg.expandThreshold && this.cfg.onPromote) {
        const actionPlan = await this._expandBridge(bridge, picked);
        if (actionPlan) {
          this.log.emit("genome_event", `${dreamId} PROMOTED: ${actionPlan.slice(0, 100)}`);
          this.cfg.onPromote(dream, actionPlan);
        }
      }
    } else {
      this.log.emit("info",
        `${dreamId} discarded (q=${quality.toFixed(2)}): ${bridge.slice(0, 80)}`
      );
    }

    return dream;
  }

  private async _expandBridge(bridge: string, facts: RawFact[]): Promise<string | null> {
    const prompt = [
      "A creative recombination engine found this cross-domain connection:",
      "",
      `Domains: ${facts.map(f => f.domain).join(" ↔ ")}`,
      `Facts: ${facts.map(f => `[${f.domain}] ${f.content.slice(0, 150)}`).join("\n")}`,
      `Bridge: ${bridge}`,
      "",
      "Turn this into a concrete, actionable research task or experiment.",
      "What specific thing should be built, tested, or investigated?",
      "Be specific: name tools, methods, data sources, expected outcomes.",
      "One paragraph, max 4 sentences. Start with a verb.",
    ].join("\n");

    const r = await this.ollama.chatResult(this.cfg.model, [
      { role: "user", content: prompt },
    ]);

    if (!r.ok || r.content.length < 30) return null;
    return r.content.trim().slice(0, 600);
  }

  private _pickDiverseFacts(n: number): RawFact[] {
    const pool = this._factPool;
    const domains = [...new Set(pool.map((f) => f.domain))];
    if (domains.length < 2) return [];

    // Shuffle domains, pick one fact from each
    const shuffled = domains.sort(() => Math.random() - 0.5);
    const picked: RawFact[] = [];

    for (const domain of shuffled) {
      if (picked.length >= n) break;
      // Skip if we already have a fact from this domain
      if (picked.some((f) => f.domain === domain)) continue;
      const domainFacts = pool.filter((f) => f.domain === domain);
      const fact = domainFacts[Math.floor(Math.random() * domainFacts.length)];
      picked.push(fact);
    }

    return picked;
  }

  private async _findBridge(facts: RawFact[]): Promise<string | null> {
    const prompt = [
      "You find unexpected connections between ideas from different fields.",
      "",
      ...facts.map((f, i) => `Fact ${i + 1} [${f.domain}]: ${f.content}`),
      "",
      "What is the deepest structural connection between these facts?",
      "Not surface similarity — a shared pattern, principle, or mechanism.",
      "If there is no real connection, say NONE.",
      "",
      "Connection (one paragraph, max 3 sentences):",
    ].join("\n");

    const r = await this.ollama.chatResult(this.cfg.model, [
      { role: "user", content: prompt },
    ]);

    if (!r.ok) return null;
    const text = r.content.trim();
    if (text.length < 20 || text.toUpperCase().includes("NONE")) return null;
    return text.slice(0, 500);
  }

  private async _scoreBridge(bridge: string, facts: RawFact[]): Promise<number> {
    const prompt = [
      "Rate this connection between facts. Output ONLY a number 0.0-1.0.",
      "0.0=trivial/wrong, 0.5=plausible, 0.8=genuine insight, 1.0=profound",
      "",
      `Facts: ${facts.map((f) => `[${f.domain}] ${f.content.slice(0, 100)}`).join(" | ")}`,
      `Connection: ${bridge}`,
      "",
      "Score:",
    ].join("\n");

    const r = await this.ollama.chatResult(this.cfg.model, [
      { role: "user", content: prompt },
    ]);

    if (!r.ok) return 0.3;
    const match = r.content.match(/(\d+\.?\d*)/);
    if (!match) return 0.3;
    const score = parseFloat(match[1]);
    return Number.isFinite(score) ? Math.min(1, Math.max(0, score)) : 0.3;
  }

  private _writeDream(dream: Dream): void {
    try {
      const dir = join(this.cfg.journalPath, "..");
      mkdirSync(dir, { recursive: true });
      appendFileSync(this.cfg.journalPath, JSON.stringify({
        id: dream.id,
        ts: dream.ts,
        domains: dream.facts.map((f) => f.domain),
        sources: dream.facts.map((f) => f.source),
        facts: dream.facts.map((f) => f.content.slice(0, 150)),
        bridge: dream.bridge,
        quality: dream.quality,
      }) + "\n");
    } catch { /* best-effort */ }
  }
}
