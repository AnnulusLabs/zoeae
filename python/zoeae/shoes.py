"""
Shoes — Device mobility for Zoeae organisms.

Serialize the full organism state (genome, antenna, brain config,
ecosystem, sensors, instincts, trail) into a portable capsule.
Move between devices. Resume exactly where you left off.

    capsule = shoes.pack(maker)
    shoes.save(capsule, "maker.zoeae")
    # ... move file to another device ...
    maker2 = shoes.unpack("maker.zoeae", Ecosystem("new-location"))

The capsule is a JSON file. No binary blobs, no pickles, no
platform-specific state. Just data.

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import json
import gzip
import hashlib
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from .organism import Zoeae
from .ocean import Ocean
from .ecosystem import (
    Ecosystem, Maker, Expert, PhysicsTest, FabNode,
    SensorFeed, MeshNode, Courtyard, ToeBuster, FabNet,
    SensorNet,
)
from .genome import Genome, GenomeBuilder
from .antenna import Antenna
from .brain import Brain, OllamaBackend, AnthropicBackend, HTTPBackend, ReasoningMode
from .molt import Instar


# ── CAPSULE ──

def pack(maker: Maker, include_brain: bool = True,
         include_ecosystem: bool = True) -> dict:
    """Pack a Maker's full state into a portable dict.

    This is the organism's travel form — everything needed to
    resume on another device.
    """
    capsule = {
        "_zoeae_version": "0.5.0",
        "_packed_at": time.time(),
        "_packed_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    # Organism core
    capsule["genome"] = maker.genome.to_dict()
    capsule["instar"] = maker.instar.value if hasattr(maker.instar, "value") else 1
    capsule["alive"] = maker.alive

    # Antenna state
    capsule["antenna"] = {
        "bleed_width": maker.antenna.bleed_width,
        "developmental_bleed": maker.antenna._bleed,
        "chosen_bleed": maker.antenna._override_bleed,
        "damping": maker.antenna.damping,
        "trail_position": maker.antenna.trail_position,
    }

    # Molt history
    capsule["molt"] = {
        "current_instar": maker.molt_cycle.current_instar.value if hasattr(maker.molt_cycle.current_instar, "value") else 1,
        "stats": maker.molt_cycle.stats,
        "exuvia": [e.to_dict() for e in maker.molt_cycle.exuvia],
    }

    # Tropism
    capsule["tropism"] = maker.tropism.stats

    # Trail buffer (perception history)
    capsule["trail"] = maker._trail_buffer[-200:]  # last 200 events

    # Instinct graph
    if hasattr(maker, "_instinct_graph"):
        ig = maker._instinct_graph
        capsule["instincts"] = {
            k: {"confidence": b.confidence, "observations": b.observations}
            for k, b in ig._beliefs.items()
        } if hasattr(ig, "_beliefs") else {}

    # Brain config (not the model weights — just which backend to use)
    if include_brain and hasattr(maker, "brain") and maker.brain:
        brain = maker.brain
        brain_cfg = {
            "backend_name": brain.backend.name if brain.backend else "none",
            "thought_count": brain.thought_count,
        }
        if isinstance(brain.backend, OllamaBackend):
            brain_cfg["backend_type"] = "ollama"
            brain_cfg["model"] = brain.backend.model
            brain_cfg["url"] = brain.backend.url
        elif isinstance(brain.backend, AnthropicBackend):
            brain_cfg["backend_type"] = "anthropic"
            brain_cfg["model"] = brain.backend.model
            # Don't pack API keys
        elif isinstance(brain.backend, HTTPBackend):
            brain_cfg["backend_type"] = "http"
            brain_cfg["model"] = brain.backend.model
            brain_cfg["url"] = brain.backend.url
        capsule["brain"] = brain_cfg

    # Ecosystem config
    if include_ecosystem and hasattr(maker, "eco") and maker.eco:
        eco = maker.eco
        eco_cfg = {"name": eco.name}

        # Experts
        eco_cfg["experts"] = [
            {"id": e.id, "domain": e.domain,
             "experience_years": e.experience_years,
             "rate_per_hour": e.rate_per_hour}
            for e in eco.courtyard._experts.values()
        ]

        # Fab nodes
        eco_cfg["fab_nodes"] = [
            {"id": n.id, "name": n.name, "location": n.location,
             "capabilities": n.capabilities, "lat": n.lat, "lon": n.lon,
             "discrete": n.discrete}
            for n in eco.fab_net._nodes.values()
        ]

        # Sensor feeds (config only, not current values)
        eco_cfg["sensors"] = [
            {"id": f.id, "kind": f.kind, "endpoint": f.endpoint,
             "interval_s": f.interval_s}
            for f in eco.sensor_net._feeds.values()
        ]

        # Mesh nodes
        eco_cfg["mesh_nodes"] = [
            {"id": n.id, "transport": n.transport}
            for n in eco.mesh_nodes.values()
        ]

        # Physics tests are functions — can't serialize them,
        # but we store the names/domains for documentation
        eco_cfg["physics_tests"] = [
            {"name": t.name, "domain": t.domain}
            for t in eco.toebuster._tests
        ]

        capsule["ecosystem"] = eco_cfg

    # Integrity hash
    content = json.dumps(capsule, sort_keys=True, default=str)
    capsule["_hash"] = hashlib.sha256(content.encode()).hexdigest()[:16]

    return capsule


def unpack(capsule: dict, eco: Optional[Ecosystem] = None) -> Maker:
    """Unpack a capsule into a live Maker on the given ecosystem.

    If no ecosystem is provided, one is reconstructed from the capsule.
    Physics tests cannot be restored (they're functions) — you'll need
    to re-register them.
    """
    # Rebuild ecosystem if needed
    if eco is None:
        eco_cfg = capsule.get("ecosystem", {})
        eco = Ecosystem(eco_cfg.get("name", "restored"))

        for e in eco_cfg.get("experts", []):
            eco.courtyard.register_expert(Expert(**e))

        for n in eco_cfg.get("fab_nodes", []):
            eco.fab_net.register(FabNode(**n))

        for s in eco_cfg.get("sensors", []):
            eco.sensor_net.register(SensorFeed(**s))

        for m in eco_cfg.get("mesh_nodes", []):
            eco.add_mesh_node(MeshNode(node_id=m["id"], transport=m.get("transport", "lora")))

    # Rebuild genome
    genome = Genome.from_dict(capsule["genome"])

    # Hatch maker
    maker = Maker(eco, genome)

    # Restore antenna state
    ant = capsule.get("antenna", {})
    if "damping" in ant:
        maker.antenna.set_damping_all(ant["damping"])
    if "developmental_bleed" in ant:
        maker.antenna._bleed = ant["developmental_bleed"]
    if ant.get("chosen_bleed") is not None:
        maker.antenna.set_chosen_bleed(ant["chosen_bleed"])
    if "trail_position" in ant:
        maker.antenna.set_trail_position(ant["trail_position"])

    # Restore molt state
    molt = capsule.get("molt", {})
    instar_val = molt.get("current_instar", capsule.get("instar", 1))
    if instar_val > 1:
        maker.molt_cycle.current_instar = Instar(instar_val)
        maker.genome.set_instar(instar_val)
        maker.antenna.set_developmental_bleed(instar_val)

    # Restore trail
    maker._trail_buffer = capsule.get("trail", [])

    # Restore brain config
    brain_cfg = capsule.get("brain", {})
    if brain_cfg:
        backend = None
        bt = brain_cfg.get("backend_type", "")
        if bt == "ollama":
            backend = OllamaBackend(
                model=brain_cfg.get("model", "hermes3:8b"),
                url=brain_cfg.get("url", "http://127.0.0.1:11434"),
            )
        elif bt == "anthropic":
            backend = AnthropicBackend(
                model=brain_cfg.get("model", "claude-sonnet-4-6"),
            )
        elif bt == "http":
            backend = HTTPBackend(
                url=brain_cfg.get("url", ""),
                model=brain_cfg.get("model", "default"),
            )
        if backend:
            maker.brain = Brain(backend=backend)

    return maker


# ── FILE I/O ──

def save(capsule: dict, path: str, compress: bool = True) -> Path:
    """Save capsule to a .zoeae file (gzipped JSON)."""
    p = Path(path)
    if not p.suffix:
        p = p.with_suffix(".zoeae")

    content = json.dumps(capsule, indent=2, default=str).encode("utf-8")

    if compress:
        content = gzip.compress(content)
        if not p.suffix.endswith(".gz"):
            p = Path(str(p) + ".gz")

    p.write_bytes(content)
    return p


def load(path: str) -> dict:
    """Load capsule from a .zoeae file."""
    p = Path(path)
    raw = p.read_bytes()

    # Try gzip first, fall back to plain JSON
    try:
        raw = gzip.decompress(raw)
    except gzip.BadGzipFile:
        pass

    return json.loads(raw)


# ── CONVENIENCE ──

def migrate(maker: Maker, path: str) -> Path:
    """One-liner: pack + save."""
    capsule = pack(maker)
    return save(capsule, path)


def arrive(path: str, eco: Optional[Ecosystem] = None) -> Maker:
    """One-liner: load + unpack."""
    capsule = load(path)
    return unpack(capsule, eco)


def shoe_size(capsule: dict) -> dict:
    """Report what's in a capsule without unpacking it."""
    content = json.dumps(capsule, default=str)
    return {
        "version": capsule.get("_zoeae_version", "?"),
        "packed_at": capsule.get("_packed_iso", "?"),
        "hash": capsule.get("_hash", "?"),
        "size_bytes": len(content),
        "instar": capsule.get("instar", "?"),
        "alive": capsule.get("alive", "?"),
        "has_brain": "brain" in capsule,
        "has_ecosystem": "ecosystem" in capsule,
        "experts": len(capsule.get("ecosystem", {}).get("experts", [])),
        "fab_nodes": len(capsule.get("ecosystem", {}).get("fab_nodes", [])),
        "sensors": len(capsule.get("ecosystem", {}).get("sensors", [])),
        "trail_events": len(capsule.get("trail", [])),
        "antenna_bleed": capsule.get("antenna", {}).get("bleed_width", "?"),
    }
