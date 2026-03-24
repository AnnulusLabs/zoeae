# Changelog

All notable changes to Zoeae are documented here.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) conventions.

---

## [0.6.0] — 2026-03-23

### Added
- Rust runtime: 225KB binary, 14 organs, zero runtime dependencies (`rust/`)
- Three-runtime canonical layout: `rust/`, `ts/`, `python/`
- PolicyEngine (`ts/src/policy.ts`) — enforces safety.yaml in-process
- UMPH verification gate (`UMPH.md`) — 4-line atomic prompt, 8 reasoning flaws
- K1C Moonraker bridge (`ts/src/k1c-bridge.ts`) — Creality K1C 3D printer integration
- Ecosystem tools (`ts/src/ecosystem-tools.ts`) — 7 maker organs as OpenClaw skills (1,592 lines)
- AgentPool (`ts/src/agent-pool.ts`) — persistent multi-agent coordination
- DreamEngine (`ts/src/dream-engine.ts`) — creative recombination during idle cycles
- SAFETY_SPEC.md v1.1.0 — enforcement mapping table for all 17 tools
- Dashboard TUI (`ts/src/dashboard.ts`) — real-time status rendering
- LICENSE (MIT, AnnulusLabs LLC)

### Changed
- PolicyEngine now gates all 17 tools via `policy.checkTool()`
- Filesystem operations gated by `policy.checkPathRead()` / `checkPathWrite()`
- Hardcoded `COMMAND_DENYLIST` removed from daemon.ts — policy.yaml is the single source
- Python framework restored to full 36-organ, 8-feed layout under `python/`
- Hardcoded paths scrubbed from all Python feeds
- README rewritten — every claim verified against source

### Fixed
- Version alignment across package.json, pyproject.toml, Cargo.toml (all 0.6.0)
- node_modules removed from git tracking

---

## [0.5.0] — 2026-03-23

### Added
- Rename: Clawtonomy → Zoeae (package `@openclaw/zoeae`)
- SAFETY_SPEC.md v1.0 — initial safety policy specification
- safety.yaml — machine-readable policy for PolicyEngine
- Daemon phase 3 — self-healing task execution loop
- Dashboard TUI — real-time service and task status

---

## [0.4.0] — 2026-03-23

### Added
- DreamEngine — idle-time creative recombination from genome facts
- tsconfig.json — strict TypeScript compilation settings
- .gitignore — excludes node_modules, __pycache__, .kerf/, .env

---

## [0.3.0] — 2026-03-16

### Added
- Cross-session continuity via ANNULUS_STATE.md genome injection
- Sovereign mail tool (`tools/mail.py`) — SMTP with port 587 fallback
- Device scanner — BLE, serial, LAN auto-discovery

---

## [0.2.0] — 2026-03-16

### Added
- Initial Clawtonomy v3 — sovereign cognitive agent for OpenClaw
- 21 tools registered via `api.registerTool()`
- Genome memory (triple-helix, because-chains)
- Task queue with priority, dependencies, retry, status lifecycle
- Multi-model room engine (KERF Room — adversarial debate, sparse-graph, Free-MAD)
- Planner — goal decomposition with breadth/depth model delegation
- Ollama integration — local model inference
- AUTONOMY v3.0 client — StressCompiler, metabolic awareness

---

*AnnulusLabs LLC — Taos, NM*
