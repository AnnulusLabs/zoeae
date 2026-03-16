/**
 * AUTONOMY v3.0 HTTP Client
 * Typed fetch wrapper for the genome + vision + research API
 * AnnulusLabs LLC
 */

export type AutonomyConfig = {
  baseUrl: string;
  timeoutMs: number;
};

export type GenomeStats = {
  total_nodes: number;
  active: number;
  stale: number;
  load_bearing: number;
  edges: number;
  edges_with_because: number;
  because_coverage: string;
  domains: number;
  bridges: number;
  domain_list: string[];
};

export type BootResult = { nucleus: string; tier: number };
export type RecordResult = { recorded: boolean };
export type WriteFactResult = { written: boolean; node_id?: string };
export type SearchResult = { results: Array<{ content: string; domain?: string; score?: number; tier?: string }> };
export type CcmResult = { ccm?: number; success: boolean; error?: string };
export type SyncExportResult = { state: string; nodes: number; edges: number; exportedAt: string };
export type SyncImportResult = { merged: boolean; nodesAdded: number; conflicts: number };
export type SyncStatusResult = { lastSync?: string; localNodes: number; pendingExports: number };

const DEFAULTS: AutonomyConfig = {
  baseUrl: "http://127.0.0.1:8766",
  timeoutMs: 30_000,
};

export class AutonomyClient {
  private cfg: AutonomyConfig;

  constructor(config?: Partial<AutonomyConfig>) {
    this.cfg = { ...DEFAULTS, ...config };
  }

  private async get<T>(path: string): Promise<T> {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), this.cfg.timeoutMs);
    try {
      const r = await fetch(`${this.cfg.baseUrl}${path}`, { signal: ac.signal });
      if (!r.ok) throw new Error(`AUTONOMY ${r.status}: ${await r.text().catch(() => "")}`);
      return (await r.json()) as T;
    } finally {
      clearTimeout(t);
    }
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), this.cfg.timeoutMs);
    try {
      const r = await fetch(`${this.cfg.baseUrl}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: ac.signal,
      });
      if (!r.ok) throw new Error(`AUTONOMY ${r.status}: ${await r.text().catch(() => "")}`);
      return (await r.json()) as T;
    } finally {
      clearTimeout(t);
    }
  }

  async ping(): Promise<boolean> {
    try { await this.get("/status"); return true; } catch { return false; }
  }

  async status() { return this.get<Record<string, unknown>>("/status"); }
  async boot(tier = 0, maxTokens = 0) { return this.get<BootResult>(`/genome/boot?tier=${tier}&tokens=${maxTokens}`); }
  async stats() { return this.get<GenomeStats>("/genome/stats"); }
  async compile(tier = 0) { return this.get<{ compiled: string }>(`/genome/compile?tier=${tier}`); }
  async record(role: string, content: string) { return this.post<RecordResult>("/genome/record", { role, content }); }
  async consolidate(auto = true) { return this.post<GenomeStats>("/genome/consolidate", { auto }); }
  async sync(state: unknown) { return this.post<{ synced: boolean }>("/genome/sync", state); }
  async daemonStart() { return this.get<{ started: boolean }>("/daemon/start"); }
  async daemonStop() { return this.get<{ stopped: boolean }>("/daemon/stop"); }
  async computeCcm(pdbId: string) { return this.get<CcmResult>(`/research/ccm?id=${encodeURIComponent(pdbId)}`); }
  async batchCcm(ids: string[]) { return this.get<Record<string, CcmResult>>(`/research/batch_ccm?ids=${ids.join(",")}`); }

  // ── Upgrade #2: Structured fact writing (bypasses turn recording) ──
  async writeFact(content: string, domain?: string, because?: string, confidence?: number) {
    return this.post<WriteFactResult>("/memory/write", {
      content,
      domain: domain ?? "general",
      because: because ?? "",
      confidence: confidence ?? 0.8,
    });
  }

  // ── Upgrade #3: Proactive context search ──
  async searchFacts(query: string, limit = 10) {
    return this.get<SearchResult>(`/memory/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }

  // ── Upgrade #4: Sleep-time deep consolidation ──
  async consolidateDeep(topics?: string[]) {
    return this.post<GenomeStats>("/genome/consolidate", {
      auto: true,
      deep: true,
      topics: topics ?? [],
    });
  }

  // ── Upgrade #7: Cross-device sync ──
  async syncExport() { return this.get<SyncExportResult>("/genome/sync/export"); }
  async syncImport(state: string) { return this.post<SyncImportResult>("/genome/sync/import", { state }); }
  async syncStatus() { return this.get<SyncStatusResult>("/genome/sync/status"); }
}
