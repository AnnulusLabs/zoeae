# Zoeae — Persistent Cognitive Genome for OpenClaw

Bridges AUTONOMY v3.0 into OpenClaw as a stock extension.

## What It Does

- **Cross-session memory**: Knowledge persists via triple-helix genome with because-chain reasoning
- **NUCLEUS injection**: Each session boots with minimum viable stress context (StressCompiler Tier 0)
- **Auto recording**: User/assistant turns recorded to genome conversation buffer
- **Auto consolidation**: On `/new` or `/reset`, conversation extracted into knowledge nodes/edges
- **Autonomous daemon**: Background bridge discovery, entropy combat, genome compaction
- **Research tools**: PDB download and Avnir CCM computation

## Requirements

AUTONOMY v3.0 on `localhost:8766`:
```bash
python autonomy.py --serve --daemon
```

## CLI

```bash
openclaw genome stats
openclaw genome boot [-t 0-3]
openclaw genome consolidate
openclaw genome daemon start|stop
openclaw genome ccm 1MUC 3NJP 1YY9 4ZUL
```

## Tools

- `genome_search` — query genome by content
- `genome_stats` — show genome health
- `genome_ccm` — compute CCM on PDB structures

## Architecture

```
OpenClaw <-> Zoeae (TS) <-> AUTONOMY v3.0 (Python, :8766)
                                   ├─ Genome Engine (SQLite+CRDT)
                                   ├─ StressCompiler (4 tiers)
                                   ├─ Daemon (bridge/entropy/compact)
                                   ├─ Vision (X11/Wayland)
                                   └─ Research (PDB/CCM)
```

MIT — AnnulusLabs LLC
