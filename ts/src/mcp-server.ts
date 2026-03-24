/**
 * MCP Server — Model Context Protocol interface for Zoeae
 *
 * Exposes all tools + resources via MCP so ANY client can use them:
 * Claude Code, Cursor, Windsurf, custom agents, anything that speaks MCP.
 *
 * Competitive with MemOS's cloud plugin. But sovereign — runs locally.
 *
 * Upgrade #5 from 10x spec (arxiv:2505.22101 / arxiv:2507.03724)
 *
 * AnnulusLabs LLC
 */

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

export type McpToolDef = {
  name: string;
  description: string;
  inputSchema: {
    type: "object";
    properties: Record<string, unknown>;
    required?: string[];
  };
};

export type McpResource = {
  uri: string;
  name: string;
  description: string;
  mimeType: string;
};

export type McpServerConfig = {
  port: number;
  host: string;
};

const DEFAULTS: McpServerConfig = {
  port: 8768,
  host: "127.0.0.1",
};

/**
 * Lightweight MCP-compatible JSON-RPC server.
 * Implements: tools/list, tools/call, resources/list, resources/read
 * Transport: HTTP + SSE for activity streaming
 */
export class McpServer {
  private cfg: McpServerConfig;
  private server: ReturnType<typeof createServer> | null = null;
  private tools: Map<string, { def: McpToolDef; handler: (args: Record<string, unknown>) => Promise<string> }> = new Map();
  private resources: Map<string, { def: McpResource; reader: () => Promise<string> }> = new Map();
  private sseClients: Set<ServerResponse> = new Set();
  private running = false;

  constructor(config?: Partial<McpServerConfig>) {
    this.cfg = { ...DEFAULTS, ...config };
  }

  registerTool(def: McpToolDef, handler: (args: Record<string, unknown>) => Promise<string>): void {
    this.tools.set(def.name, { def, handler });
  }

  registerResource(def: McpResource, reader: () => Promise<string>): void {
    this.resources.set(def.uri, { def, reader });
  }

  /** Push an event to all SSE clients (for activity streaming) */
  pushEvent(event: string, data: string): void {
    for (const res of this.sseClients) {
      try { res.write(`event: ${event}\ndata: ${data}\n\n`); } catch { this.sseClients.delete(res); }
    }
  }

  start(): boolean {
    if (this.running) return false;

    this.server = createServer(async (req, res) => {
      // CORS
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
      res.setHeader("Access-Control-Allow-Headers", "Content-Type");
      if (req.method === "OPTIONS") { res.writeHead(204); res.end(); return; }

      const url = new URL(req.url ?? "/", `http://${req.headers.host}`);

      // SSE endpoint for activity streaming
      if (url.pathname === "/sse" && req.method === "GET") {
        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
        });
        this.sseClients.add(res);
        req.on("close", () => this.sseClients.delete(res));
        return;
      }

      // JSON-RPC endpoint
      if (req.method === "POST") {
        const body = await readBody(req);
        try {
          const rpc = JSON.parse(body);
          const result = await this.handleRpc(rpc);
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ jsonrpc: "2.0", id: rpc.id, result }));
        } catch (err) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ jsonrpc: "2.0", id: null, error: { code: -32600, message: String(err) } }));
        }
        return;
      }

      // Health check
      if (url.pathname === "/health") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ status: "ok", tools: this.tools.size, resources: this.resources.size }));
        return;
      }

      res.writeHead(404);
      res.end("Not found");
    });

    this.server.listen(this.cfg.port, this.cfg.host, () => {
      this.running = true;
    });
    return true;
  }

  stop(): boolean {
    if (!this.running || !this.server) return false;
    for (const c of this.sseClients) { try { c.end(); } catch { /* */ } }
    this.sseClients.clear();
    this.server.close();
    this.server = null;
    this.running = false;
    return true;
  }

  isRunning(): boolean { return this.running; }

  private async handleRpc(rpc: { method: string; params?: Record<string, unknown> }): Promise<unknown> {
    switch (rpc.method) {
      case "initialize":
        return {
          protocolVersion: "2024-11-05",
          capabilities: { tools: {}, resources: {} },
          serverInfo: { name: "zoeae", version: "2026.3.16" },
        };

      case "tools/list":
        return { tools: Array.from(this.tools.values()).map((t) => t.def) };

      case "tools/call": {
        const name = rpc.params?.name as string;
        const args = (rpc.params?.arguments ?? {}) as Record<string, unknown>;
        const tool = this.tools.get(name);
        if (!tool) throw new Error(`Unknown tool: ${name}`);
        const content = await tool.handler(args);
        return { content: [{ type: "text", text: content }] };
      }

      case "resources/list":
        return { resources: Array.from(this.resources.values()).map((r) => r.def) };

      case "resources/read": {
        const uri = rpc.params?.uri as string;
        const resource = this.resources.get(uri);
        if (!resource) throw new Error(`Unknown resource: ${uri}`);
        const content = await resource.reader();
        return { contents: [{ uri, mimeType: resource.def.mimeType, text: content }] };
      }

      case "ping":
        return {};

      default:
        throw new Error(`Unknown method: ${rpc.method}`);
    }
  }
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString()));
    req.on("error", reject);
  });
}
