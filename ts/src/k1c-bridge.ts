/**
 * K1C Moonraker Bridge — 3D printer control via Moonraker API
 *
 * Enables the organism to manufacture on command. The K1C at
 * 192.168.1.82:7125 is accessible via Moonraker JSON-RPC.
 *
 * Commands: status, upload, print, cancel, pause, resume, home,
 * heat, cool, files, gcode
 *
 * AnnulusLabs LLC — Taos, NM
 * "The organism builds its own body"
 */

import { ActivityLog } from "./activity-log.js";

export type K1CConfig = {
  host: string;
  port: number;
  timeout: number;
};

const DEFAULTS: K1CConfig = {
  host: process.env.K1C_HOST ?? "192.168.1.82",
  port: Number(process.env.K1C_PORT ?? 7125),
  timeout: 10_000,
};

export type PrinterStatus = {
  state: string;
  filename: string;
  progress: number;
  extruder_temp: number;
  extruder_target: number;
  bed_temp: number;
  bed_target: number;
  print_duration: number;
  filament_used: number;
};

export class K1CBridge {
  private cfg: K1CConfig;
  private log: ActivityLog;
  private baseUrl: string;

  constructor(log: ActivityLog, config?: Partial<K1CConfig>) {
    this.cfg = { ...DEFAULTS, ...config };
    this.log = log;
    this.baseUrl = `http://${this.cfg.host}:${this.cfg.port}`;
  }

  /** Health check */
  async ping(): Promise<boolean> {
    try {
      const r = await fetch(`${this.baseUrl}/printer/info`, {
        signal: AbortSignal.timeout(this.cfg.timeout),
      });
      return r.ok;
    } catch {
      return false;
    }
  }

  /** Full printer status */
  async status(): Promise<PrinterStatus> {
    const r = await this._get(
      "/printer/objects/query?extruder&heater_bed&print_stats&display_status"
    );
    const s = r.result.status;
    const ps = s.print_stats ?? {};
    const ext = s.extruder ?? {};
    const bed = s.heater_bed ?? {};
    const ds = s.display_status ?? {};
    return {
      state: ps.state ?? "unknown",
      filename: ps.filename ?? "",
      progress: (ds.progress ?? 0) * 100,
      extruder_temp: ext.temperature ?? 0,
      extruder_target: ext.target ?? 0,
      bed_temp: bed.temperature ?? 0,
      bed_target: bed.target ?? 0,
      print_duration: ps.print_duration ?? 0,
      filament_used: ps.filament_used ?? 0,
    };
  }

  /** List gcode files on printer */
  async listFiles(): Promise<Array<{ path: string; size: number }>> {
    const r = await this._get("/server/files/list?root=gcodes");
    return (r.result ?? []).map((f: any) => ({
      path: f.path,
      size: f.size ?? 0,
    }));
  }

  /** Upload gcode file to printer */
  async upload(filePath: string): Promise<string> {
    const { readFileSync } = await import("node:fs");
    const { basename } = await import("node:path");
    const name = basename(filePath);
    const data = readFileSync(filePath);

    const form = new FormData();
    form.append("file", new Blob([data]), name);
    form.append("root", "gcodes");

    const r = await fetch(`${this.baseUrl}/server/files/upload`, {
      method: "POST",
      body: form,
      signal: AbortSignal.timeout(60_000),
    });

    if (!r.ok) throw new Error(`Upload failed: ${r.status}`);
    const json = await r.json() as any;
    this.log.emit("info", `[K1C] Uploaded ${name} (${(data.length / 1e6).toFixed(1)}MB)`);
    return json.result?.item?.path ?? name;
  }

  /** Start printing a file */
  async print(filename: string): Promise<boolean> {
    const r = await this._post("/printer/print/start", { filename });
    this.log.emit("info", `[K1C] Print started: ${filename}`);
    return r.result === "ok";
  }

  /** Cancel current print */
  async cancel(): Promise<boolean> {
    const r = await this._post("/printer/print/cancel");
    this.log.emit("info", "[K1C] Print cancelled");
    return r.result === "ok";
  }

  /** Pause current print */
  async pause(): Promise<boolean> {
    const r = await this._post("/printer/print/pause");
    this.log.emit("info", "[K1C] Print paused");
    return r.result === "ok";
  }

  /** Resume paused print */
  async resume(): Promise<boolean> {
    const r = await this._post("/printer/print/resume");
    this.log.emit("info", "[K1C] Print resumed");
    return r.result === "ok";
  }

  /** Home all axes */
  async home(): Promise<boolean> {
    return this._gcode("G28");
  }

  /** Set extruder temperature */
  async heatExtruder(temp: number): Promise<boolean> {
    return this._gcode(`M104 S${Math.min(temp, 300)}`);
  }

  /** Set bed temperature */
  async heatBed(temp: number): Promise<boolean> {
    return this._gcode(`M140 S${Math.min(temp, 120)}`);
  }

  /** Cool down everything */
  async coolDown(): Promise<boolean> {
    await this._gcode("M104 S0");
    await this._gcode("M140 S0");
    this.log.emit("info", "[K1C] Cooling down");
    return true;
  }

  /** Send raw gcode command */
  async gcode(cmd: string): Promise<boolean> {
    // Safety: block dangerous gcodes
    const dangerous = ["M112", "M502", "M500"];
    if (dangerous.some((d) => cmd.toUpperCase().startsWith(d))) {
      this.log.emit("error", `[K1C] BLOCKED dangerous gcode: ${cmd}`);
      return false;
    }
    return this._gcode(cmd);
  }

  /** Reset print state (clear stuck prints) */
  async resetPrintState(): Promise<boolean> {
    return this._gcode("SDCARD_RESET_FILE");
  }

  // ── Internal ────────────────────────────────────────────

  private async _get(path: string): Promise<any> {
    const r = await fetch(`${this.baseUrl}${path}`, {
      signal: AbortSignal.timeout(this.cfg.timeout),
    });
    if (!r.ok) throw new Error(`K1C GET ${path}: ${r.status}`);
    return r.json();
  }

  private async _post(path: string, body?: object): Promise<any> {
    const r = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(this.cfg.timeout),
    });
    if (!r.ok) throw new Error(`K1C POST ${path}: ${r.status}`);
    return r.json();
  }

  private async _gcode(script: string): Promise<boolean> {
    try {
      await this._post("/printer/gcode/script", { script });
      return true;
    } catch {
      return false;
    }
  }
}

/** Build MCP-style tool definitions for OpenClaw registration */
export function buildK1CTools(bridge: K1CBridge) {
  return [
    {
      name: "k1c",
      description:
        "Control the Creality K1C 3D printer via Moonraker API. " +
        "Actions: status, files, print <filename>, upload <path>, " +
        "cancel, pause, resume, home, heat <extruder_temp> [bed_temp], " +
        "cool, gcode <command>, reset.",
      parameters: {
        type: "object" as const,
        properties: {
          action: {
            type: "string",
            description:
              "status|files|print|upload|cancel|pause|resume|home|heat|cool|gcode|reset",
          },
          filename: { type: "string", description: "Gcode filename or upload path" },
          temp: { type: "number", description: "Extruder temperature" },
          bed_temp: { type: "number", description: "Bed temperature" },
          command: { type: "string", description: "Raw gcode command" },
        },
        required: ["action"],
      },
      async execute(args: {
        action: string;
        filename?: string;
        temp?: number;
        bed_temp?: number;
        command?: string;
      }) {
        switch (args.action) {
          case "status": {
            const s = await bridge.status();
            return {
              content: [
                `State: ${s.state}`,
                s.filename ? `File: ${s.filename}` : null,
                s.progress > 0 ? `Progress: ${s.progress.toFixed(1)}%` : null,
                `Extruder: ${s.extruder_temp.toFixed(0)}C / ${s.extruder_target.toFixed(0)}C`,
                `Bed: ${s.bed_temp.toFixed(0)}C / ${s.bed_target.toFixed(0)}C`,
                s.print_duration > 0
                  ? `Duration: ${Math.floor(s.print_duration / 60)}min`
                  : null,
              ]
                .filter(Boolean)
                .join("\n"),
            };
          }
          case "files": {
            const files = await bridge.listFiles();
            return {
              content:
                files.length === 0
                  ? "No gcode files on printer."
                  : files
                      .map(
                        (f) =>
                          `${f.path.padEnd(45)} ${(f.size / 1e6).toFixed(1)}MB`
                      )
                      .join("\n"),
            };
          }
          case "print": {
            if (!args.filename)
              return { content: "Specify filename to print." };
            await bridge.print(args.filename);
            return { content: `Print started: ${args.filename}` };
          }
          case "upload": {
            if (!args.filename) return { content: "Specify file path to upload." };
            const uploaded = await bridge.upload(args.filename);
            return { content: `Uploaded: ${uploaded}` };
          }
          case "cancel":
            await bridge.cancel();
            return { content: "Print cancelled." };
          case "pause":
            await bridge.pause();
            return { content: "Print paused." };
          case "resume":
            await bridge.resume();
            return { content: "Print resumed." };
          case "home":
            await bridge.home();
            return { content: "Homing all axes." };
          case "heat": {
            if (args.temp) await bridge.heatExtruder(args.temp);
            if (args.bed_temp) await bridge.heatBed(args.bed_temp);
            return {
              content: `Heating: extruder=${args.temp ?? "unchanged"}C bed=${args.bed_temp ?? "unchanged"}C`,
            };
          }
          case "cool":
            await bridge.coolDown();
            return { content: "Cooling down." };
          case "gcode": {
            if (!args.command) return { content: "Specify gcode command." };
            const ok = await bridge.gcode(args.command);
            return { content: ok ? `Sent: ${args.command}` : `BLOCKED: ${args.command}` };
          }
          case "reset":
            await bridge.resetPrintState();
            return { content: "Print state reset." };
          default:
            return {
              content: `Unknown action: ${args.action}. Use: status, files, print, upload, cancel, pause, resume, home, heat, cool, gcode, reset`,
            };
        }
      },
    },
  ];
}
