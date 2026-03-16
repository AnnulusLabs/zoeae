/**
 * Ollama HTTP Client — stdlib fetch, no dependencies
 * Direct port from KERF nerve/gtui.py ollama_chat/ollama_models
 * AnnulusLabs LLC
 */

export type OllamaChatMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type OllamaModel = {
  name: string;
  size: number;
  parameter_size?: string;
};

export class OllamaClient {
  private baseUrl: string;
  private timeoutMs: number;

  constructor(baseUrl = "http://127.0.0.1:11434", timeoutMs = 120_000) {
    this.baseUrl = baseUrl;
    this.timeoutMs = timeoutMs;
  }

  async chat(model: string, messages: OllamaChatMessage[]): Promise<string> {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), this.timeoutMs);
    try {
      const r = await fetch(`${this.baseUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model, messages, stream: false }),
        signal: ac.signal,
      });
      if (!r.ok) throw new Error(`Ollama ${r.status}: ${await r.text().catch(() => "")}`);
      const data = (await r.json()) as { message?: { content?: string } };
      return data.message?.content?.trim() ?? "";
    } catch (err) {
      return `[ERROR] ${err}`;
    } finally {
      clearTimeout(t);
    }
  }

  async listModels(): Promise<OllamaModel[]> {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), 5_000);
    try {
      const r = await fetch(`${this.baseUrl}/api/tags`, { signal: ac.signal });
      if (!r.ok) return [];
      const data = (await r.json()) as { models?: OllamaModel[] };
      return data.models ?? [];
    } catch {
      return [];
    } finally {
      clearTimeout(t);
    }
  }

  async ping(): Promise<boolean> {
    try {
      const models = await this.listModels();
      return models.length > 0;
    } catch {
      return false;
    }
  }
}
