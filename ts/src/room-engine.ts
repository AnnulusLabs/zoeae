/**
 * Room Engine — Multi-model conversation rooms
 * Ported from KERF nerve/gtui.py Room class
 *
 * Core modes (original):
 *   parallel    — all models queried concurrently
 *   adversarial — first answers, others critique, first rebuts
 *   round-robin — sequential, one at a time
 *   snowball    — each model builds on previous output
 *
 * New modes (from multi-agent debate research):
 *   sparse-debate  — sparse communication topology: each model sees only 1-2 others,
 *                     not all. Cuts cost 41% while maintaining accuracy.
 *   free-mad       — Free-form Multi-Agent Debate: no forced consensus, score full
 *                     trajectory. 13-16% improvement at lower cost.
 *   vote           — Each model answers independently, majority vote wins.
 *                     Better than consensus for reasoning tasks.
 *
 * Anti-sycophancy: force diverse reasoning methods per agent (DMAD pattern).
 * Heterogeneous models > homogeneous. 3 diverse 7Bs beat GPT-4 on GSM-8K.
 *
 * AnnulusLabs LLC
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { OllamaClient, type OllamaChatMessage } from "./ollama-client.js";

export type RoomMode = "parallel" | "adversarial" | "round-robin" | "snowball" | "sparse-debate" | "free-mad" | "vote";
export const ROOM_MODES: RoomMode[] = ["parallel", "adversarial", "round-robin", "snowball", "sparse-debate", "free-mad", "vote"];

export type RoomEntry = {
  model: string;
  role: "user" | "assistant";
  text: string;
  ts: number;
  tag?: string;
};

export type RoomResponse = {
  model: string;
  text: string;
  tag?: string;
  score?: number;   // for vote/free-mad scoring
};

export type RoomConfig = {
  ollamaUrl: string;
  ollamaTimeoutMs: number;
  maxHistory: number;
  contextWindowEntries: number;
  debateRounds: number;        // for sparse-debate and free-mad
  votingThreshold: number;     // majority threshold for vote mode
};

const DEFAULTS: RoomConfig = {
  ollamaUrl: "http://127.0.0.1:11434",
  ollamaTimeoutMs: 120_000,
  maxHistory: 200,
  contextWindowEntries: 15,
  debateRounds: 2,
  votingThreshold: 0.5,
};

// Anti-sycophancy: diverse reasoning prompts per model slot (DMAD pattern)
const REASONING_METHODS = [
  "Think step-by-step, showing your work.",
  "Start with your conclusion, then justify it. Play devil's advocate against yourself.",
  "List 3 possible answers, evaluate each, pick the strongest.",
  "Identify the key constraint first, then solve from that constraint outward.",
  "Solve this using first principles. Question every assumption.",
  "Think about what could go wrong. What are the failure modes? Then construct the safest answer.",
  "Consider the opposite of the obvious answer. Is it actually better?",
];

function shortName(modelId: string): string {
  const n = modelId.split("/").pop() ?? modelId;
  if (n.includes(":")) {
    const [base, tag] = n.split(":", 2);
    return ["latest", "8b", "7b", "3b", "1b"].includes(tag) ? base : `${base}:${tag.slice(0, 3)}`;
  }
  return n;
}

export class Room {
  name: string;
  models: string[] = [];
  mode: RoomMode = "parallel";
  history: RoomEntry[] = [];
  nucleus = "";

  private ollama: OllamaClient;
  private cfg: RoomConfig;
  private getNucleus: (() => Promise<string>) | null = null;

  constructor(name = "default", config?: Partial<RoomConfig>, nucleusFn?: () => Promise<string>) {
    this.name = name;
    this.cfg = { ...DEFAULTS, ...config };
    this.ollama = new OllamaClient(this.cfg.ollamaUrl, this.cfg.ollamaTimeoutMs);
    this.getNucleus = nucleusFn ?? null;
  }

  addModel(model: string): boolean {
    if (this.models.includes(model)) return false;
    this.models.push(model);
    return true;
  }

  removeModel(query: string): string | null {
    const match = this.models.find((m) => m.includes(query));
    if (match) this.models = this.models.filter((m) => m !== match);
    return match ?? null;
  }

  setMode(mode: string): boolean {
    if (!ROOM_MODES.includes(mode as RoomMode)) return false;
    this.mode = mode as RoomMode;
    return true;
  }

  /**
   * Upgrade #6: Auto-select the best room mode for a task type.
   * Defaults based on research findings; overridden by genome-learned preferences.
   */
  static autoMode(taskType: string, genomeHints?: Array<{ mode: string; taskType: string; worked: boolean }>): RoomMode {
    // Check genome-learned preferences first
    if (genomeHints && genomeHints.length > 0) {
      const relevant = genomeHints.filter((h) => h.taskType === taskType);
      if (relevant.length > 0) {
        // Count successes per mode
        const scores = new Map<string, number>();
        for (const h of relevant) {
          const key = h.mode;
          scores.set(key, (scores.get(key) ?? 0) + (h.worked ? 1 : -1));
        }
        let best = "";
        let bestScore = -Infinity;
        for (const [mode, score] of scores) {
          if (score > bestScore) { best = mode; bestScore = score; }
        }
        if (best && ROOM_MODES.includes(best as RoomMode)) return best as RoomMode;
      }
    }

    // Research-backed defaults
    const TASK_MODE_MAP: Record<string, RoomMode> = {
      reasoning: "vote",          // majority wins, best for reasoning
      math: "vote",
      logic: "vote",
      creative: "snowball",       // each builds on previous
      brainstorm: "snowball",
      writing: "snowball",
      review: "adversarial",      // answer → critique → rebuttal
      audit: "adversarial",
      debug: "adversarial",
      research: "sparse-debate",  // ring topology, 41% cheaper
      analysis: "sparse-debate",
      validation: "free-mad",     // no forced consensus, trajectory scoring
      verify: "free-mad",
      general: "parallel",
      quick: "parallel",
    };

    const lower = taskType.toLowerCase();
    for (const [key, mode] of Object.entries(TASK_MODE_MAP)) {
      if (lower.includes(key)) return mode;
    }
    return "parallel"; // safe default
  }

  private buildMessages(forModel: string, extraSystem?: string): OllamaChatMessage[] {
    const others = this.models.filter((m) => m !== forModel).map(shortName).join(", ");
    let system = `You are ${shortName(forModel)} in a multi-AI room. Others: ${others}. Be direct, disagree when warranted.`;
    if (extraSystem) system += `\n${extraSystem}`;
    if (this.nucleus) system += `\n\n[SHARED CONTEXT]\n${this.nucleus}`;

    const msgs: OllamaChatMessage[] = [{ role: "system", content: system }];
    const recent = this.history.slice(-this.cfg.contextWindowEntries);
    for (const e of recent) {
      if (e.role === "user") {
        msgs.push({ role: "user", content: e.text });
      } else if (e.model === forModel) {
        msgs.push({ role: "assistant", content: e.text });
      } else {
        msgs.push({ role: "user", content: `[${shortName(e.model)}]: ${e.text.slice(0, 300)}` });
      }
    }
    return msgs;
  }

  private log(model: string, text: string, role: "user" | "assistant" = "assistant", tag?: string): void {
    this.history.push({ model, role, text, ts: Date.now(), tag });
    if (this.history.length > this.cfg.maxHistory) {
      this.history = this.history.slice(-Math.floor(this.cfg.maxHistory / 2));
    }
  }

  async query(prompt: string, onResponse?: (resp: RoomResponse) => void): Promise<RoomResponse[]> {
    // Refresh nucleus
    if (this.getNucleus) {
      try { this.nucleus = await this.getNucleus(); } catch { /* silent */ }
    }

    this.log("human", prompt, "user");
    const results: RoomResponse[] = [];

    switch (this.mode) {
      case "parallel":
        results.push(...await this.runParallel(prompt, onResponse));
        break;
      case "round-robin":
        results.push(...await this.runRoundRobin(prompt, onResponse));
        break;
      case "adversarial":
        results.push(...await this.runAdversarial(prompt, onResponse));
        break;
      case "snowball":
        results.push(...await this.runSnowball(prompt, onResponse));
        break;
      case "sparse-debate":
        results.push(...await this.runSparseDebate(prompt, onResponse));
        break;
      case "free-mad":
        results.push(...await this.runFreeMad(prompt, onResponse));
        break;
      case "vote":
        results.push(...await this.runVote(prompt, onResponse));
        break;
    }

    return results;
  }

  // ── Original modes ─────────────────────────────────────

  private async runParallel(prompt: string, onResponse?: (r: RoomResponse) => void): Promise<RoomResponse[]> {
    const promises = this.models.map(async (m, i) => {
      const method = REASONING_METHODS[i % REASONING_METHODS.length];
      const msgs = this.buildMessages(m, method);
      msgs.push({ role: "user", content: prompt });
      const text = await this.ollama.chat(m, msgs);
      const resp: RoomResponse = { model: m, text };
      this.log(m, text);
      onResponse?.(resp);
      return resp;
    });
    return Promise.all(promises);
  }

  private async runRoundRobin(prompt: string, onResponse?: (r: RoomResponse) => void): Promise<RoomResponse[]> {
    const results: RoomResponse[] = [];
    for (const m of this.models) {
      const msgs = this.buildMessages(m);
      msgs.push({ role: "user", content: prompt });
      const text = await this.ollama.chat(m, msgs);
      const resp: RoomResponse = { model: m, text };
      this.log(m, text);
      onResponse?.(resp);
      results.push(resp);
    }
    return results;
  }

  private async runAdversarial(prompt: string, onResponse?: (r: RoomResponse) => void): Promise<RoomResponse[]> {
    const results: RoomResponse[] = [];
    if (this.models.length < 2) return results;

    // Initial
    const first = this.models[0];
    const firstMsgs = this.buildMessages(first);
    firstMsgs.push({ role: "user", content: prompt });
    const initial = await this.ollama.chat(first, firstMsgs);
    this.log(first, initial);
    const r1: RoomResponse = { model: first, text: initial };
    onResponse?.(r1);
    results.push(r1);

    // Critics
    for (const critic of this.models.slice(1)) {
      const criticMsgs = this.buildMessages(critic, "Your job is to find errors, gaps, and weaknesses. Be harsh but constructive.");
      criticMsgs.push({ role: "user", content: `Review critically:\n\n${initial}` });
      const crit = await this.ollama.chat(critic, criticMsgs);
      this.log(critic, crit, "assistant", "REVIEW");
      const rc: RoomResponse = { model: critic, text: crit, tag: "REVIEW" };
      onResponse?.(rc);
      results.push(rc);
    }

    // Rebuttal
    const critSummary = results.filter((r) => r.tag === "REVIEW").map((r) => `${shortName(r.model)}: ${r.text.slice(0, 200)}`).join("\n");
    const rebutMsgs = this.buildMessages(first);
    rebutMsgs.push({ role: "user", content: `Address these critiques and give your final answer:\n\nOriginal: ${initial.slice(0, 300)}\n\nCritiques:\n${critSummary}` });
    const final = await this.ollama.chat(first, rebutMsgs);
    this.log(first, final, "assistant", "FINAL");
    const rf: RoomResponse = { model: first, text: final, tag: "FINAL" };
    onResponse?.(rf);
    results.push(rf);

    return results;
  }

  private async runSnowball(prompt: string, onResponse?: (r: RoomResponse) => void): Promise<RoomResponse[]> {
    const results: RoomResponse[] = [];
    let acc = prompt;
    for (const m of this.models) {
      const msgs = this.buildMessages(m);
      msgs.push({ role: "user", content: `Build on this:\n\n${acc}` });
      const text = await this.ollama.chat(m, msgs);
      this.log(m, text);
      const resp: RoomResponse = { model: m, text };
      onResponse?.(resp);
      results.push(resp);
      acc = text;
    }
    return results;
  }

  // ── New modes (research-backed) ────────────────────────

  /**
   * Sparse-debate: each model sees only 1-2 neighbors, not all.
   * Sparse communication topology cuts cost 41% while maintaining accuracy.
   * Models are arranged in a ring; each sees only the previous model's output.
   */
  private async runSparseDebate(prompt: string, onResponse?: (r: RoomResponse) => void): Promise<RoomResponse[]> {
    const results: RoomResponse[] = [];
    if (this.models.length < 2) return this.runParallel(prompt, onResponse);

    // Round 0: all models answer independently with diverse reasoning
    const initial = await Promise.all(
      this.models.map(async (m, i) => {
        const method = REASONING_METHODS[i % REASONING_METHODS.length];
        const msgs = this.buildMessages(m, method);
        msgs.push({ role: "user", content: prompt });
        const text = await this.ollama.chat(m, msgs);
        this.log(m, text);
        return { model: m, text };
      }),
    );
    for (const r of initial) {
      const resp: RoomResponse = { ...r, tag: "R0" };
      onResponse?.(resp);
      results.push(resp);
    }

    // Subsequent rounds: ring topology, each sees only previous neighbor
    let prev = initial;
    for (let round = 1; round <= this.cfg.debateRounds; round++) {
      const next = await Promise.all(
        this.models.map(async (m, i) => {
          const neighborIdx = (i - 1 + this.models.length) % this.models.length;
          const neighbor = prev[neighborIdx];
          const msgs = this.buildMessages(m, REASONING_METHODS[(i + round) % REASONING_METHODS.length]);
          msgs.push({
            role: "user",
            content: `Question: ${prompt}\n\nYour previous answer: ${prev[i].text.slice(0, 300)}\n\n${shortName(neighbor.model)} said: ${neighbor.text.slice(0, 300)}\n\nUpdate your answer if warranted. If you disagree, explain why.`,
          });
          const text = await this.ollama.chat(m, msgs);
          this.log(m, text, "assistant", `R${round}`);
          return { model: m, text };
        }),
      );
      for (const r of next) {
        const resp: RoomResponse = { ...r, tag: `R${round}` };
        onResponse?.(resp);
        results.push(resp);
      }
      prev = next;
    }

    return results;
  }

  /**
   * Free-MAD: Free-form Multi-Agent Debate.
   * No forced consensus. Each model debates freely.
   * Final scoring selects the best trajectory (not just final answer).
   * 13-16% improvement with less cost than forced consensus.
   */
  private async runFreeMad(prompt: string, onResponse?: (r: RoomResponse) => void): Promise<RoomResponse[]> {
    const results: RoomResponse[] = [];
    if (this.models.length < 2) return this.runParallel(prompt, onResponse);

    // All models answer with diverse reasoning methods
    const answers = await Promise.all(
      this.models.map(async (m, i) => {
        const method = REASONING_METHODS[i % REASONING_METHODS.length];
        const msgs = this.buildMessages(m, method);
        msgs.push({ role: "user", content: prompt });
        const text = await this.ollama.chat(m, msgs);
        this.log(m, text, "assistant", "ANSWER");
        const resp: RoomResponse = { model: m, text, tag: "ANSWER" };
        onResponse?.(resp);
        results.push(resp);
        return { model: m, text };
      }),
    );

    // Each model critiques all others (free-form, no forced agreement)
    for (let i = 0; i < this.models.length; i++) {
      const m = this.models[i];
      const othersText = answers
        .filter((_, j) => j !== i)
        .map((a) => `${shortName(a.model)}: ${a.text.slice(0, 200)}`)
        .join("\n\n");

      const msgs = this.buildMessages(m, "You are evaluating other models' answers. Be critical. Do NOT agree just to be agreeable.");
      msgs.push({
        role: "user",
        content: `Question: ${prompt}\n\nYour answer: ${answers[i].text.slice(0, 300)}\n\nOther answers:\n${othersText}\n\nCritique the others. If your answer was wrong, correct it. If it was right, defend it.`,
      });
      const text = await this.ollama.chat(m, msgs);
      this.log(m, text, "assistant", "CRITIQUE");
      const resp: RoomResponse = { model: m, text, tag: "CRITIQUE" };
      onResponse?.(resp);
      results.push(resp);
    }

    // Scoring: use first model as judge (or cheapest available)
    const judge = this.models[0];
    const allAnswers = results.filter((r) => r.tag === "CRITIQUE").map((r) => `${shortName(r.model)}: ${r.text.slice(0, 300)}`).join("\n---\n");
    const scoreMsgs: OllamaChatMessage[] = [
      { role: "system", content: "You are a fair judge. Pick the best answer based on accuracy, reasoning quality, and completeness. Output ONLY the model name of the winner." },
      { role: "user", content: `Question: ${prompt}\n\nFinal answers:\n${allAnswers}\n\nWinner:` },
    ];
    const winner = await this.ollama.chat(judge, scoreMsgs);
    this.log(judge, winner, "assistant", "JUDGE");
    const jr: RoomResponse = { model: judge, text: `WINNER: ${winner.trim()}`, tag: "JUDGE" };
    onResponse?.(jr);
    results.push(jr);

    return results;
  }

  /**
   * Vote: each model answers independently, majority wins.
   * Better than consensus for reasoning tasks (per research).
   * For open-ended/generation tasks, use adversarial or snowball instead.
   */
  private async runVote(prompt: string, onResponse?: (r: RoomResponse) => void): Promise<RoomResponse[]> {
    const results: RoomResponse[] = [];

    // All models answer with diverse reasoning
    const answers = await Promise.all(
      this.models.map(async (m, i) => {
        const method = REASONING_METHODS[i % REASONING_METHODS.length];
        const msgs = this.buildMessages(m, method);
        msgs.push({ role: "user", content: `${prompt}\n\nGive a clear, concise answer. End with "ANSWER: [your final answer]"` });
        const text = await this.ollama.chat(m, msgs);
        this.log(m, text, "assistant", "VOTE");
        const resp: RoomResponse = { model: m, text, tag: "VOTE" };
        onResponse?.(resp);
        results.push(resp);
        return { model: m, text };
      }),
    );

    // Tally: use first model to identify consensus
    const tally = answers.map((a) => `${shortName(a.model)}: ${a.text.slice(0, 200)}`).join("\n\n");
    const tallyMsgs: OllamaChatMessage[] = [
      { role: "system", content: "Identify the majority answer from these responses. Output: 'MAJORITY: [the answer]' followed by 'CONFIDENCE: [high/medium/low]' and 'AGREEMENT: [N/M models agree]'" },
      { role: "user", content: `Question: ${prompt}\n\nResponses:\n${tally}` },
    ];
    const tallyResult = await this.ollama.chat(this.models[0], tallyMsgs);
    this.log("tally", tallyResult, "assistant", "TALLY");
    const tr: RoomResponse = { model: "tally", text: tallyResult, tag: "TALLY" };
    onResponse?.(tr);
    results.push(tr);

    return results;
  }

  // ── Persistence ────────────────────────────────────────

  toJSON(): object {
    return {
      name: this.name,
      models: this.models,
      mode: this.mode,
      history: this.history.slice(-50),
    };
  }

  save(filePath: string): void {
    try {
      mkdirSync(dirname(filePath), { recursive: true });
      writeFileSync(filePath, JSON.stringify(this.toJSON(), null, 2), "utf-8");
    } catch { /* silent */ }
  }

  static fromJSON(data: { name: string; models: string[]; mode: string; history: RoomEntry[] }, config?: Partial<RoomConfig>, nucleusFn?: () => Promise<string>): Room {
    const room = new Room(data.name, config, nucleusFn);
    room.models = data.models ?? [];
    room.mode = (ROOM_MODES.includes(data.mode as RoomMode) ? data.mode : "parallel") as RoomMode;
    room.history = data.history ?? [];
    return room;
  }

  static load(filePath: string, config?: Partial<RoomConfig>, nucleusFn?: () => Promise<string>): Room | null {
    try {
      const raw = readFileSync(filePath, "utf-8");
      const data = JSON.parse(raw);
      return Room.fromJSON(data, config, nucleusFn);
    } catch {
      return null;
    }
  }
}
