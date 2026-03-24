"""
Ecosystem — The full Zoeae ecosystem.

Every AnnulusLabs subsystem mapped to Zoeae organs.
The human wears the headset. The organism augments.
FREE_WILL is always the human.

    ocean = Ecosystem("taos")
    z = Maker.hatch(ocean)
    z.see("I want to build a thing")
    # antenna perceives, crtyrd finds the expert,
    # toebuster checks the physics, fab_net finds the shop,
    # patent_gen writes the provisional. human decides.
"""

from __future__ import annotations
import json, time, hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from enum import Enum, auto

from .organism import Zoeae
from .ocean import Ocean, Stimulus, Reflection
from .antenna import Antenna, Detection, CHANNEL_NAMES
from .genome import Genome, GenomeBuilder, ChromosomeType
from .router import Router, Provider, Capability, CapabilityDomain, RouteRequest
from .compiler import Compiler, Budget, Tier, Skill
from .pipeline import Pipeline, Stage, DAG
from .instinct import InstinctGraph
from .accumulator import Accumulator, Fragment
from .telemetry import Telemetry
from .molt import MoltCycle, Instar
from .tropism import Tropism, Drive


# ═══════════════════════════════════════════════════════
# CAPABILITY DOMAINS — what the ecosystem can do
# ═══════════════════════════════════════════════════════

class EcoDomain(Enum):
    PERCEIVE    = auto()  # XR — see the idea in space
    VALIDATE    = auto()  # ToeBuster — does physics allow it
    KNOWLEDGE   = auto()  # CRTYRD — who knows how, get them paid
    FABRICATE   = auto()  # FabNet — who can make it, where
    COMMUNICATE = auto()  # BNET/HyperWave — mesh when infra fails
    SENSE       = auto()  # rfcanary pattern — ambient sensor tap
    PROTECT     = auto()  # KERF/exoskeleton — encryption, compartment
    REMEMBER    = auto()  # RATCHET — persistent genome memory
    MEASURE     = auto()  # Thermalinfo — waste per bit, lower is better
    GROUND      = auto()  # KNOW|Soil — real data, real contamination
    PATENT      = auto()  # IP pipeline — provisional from validated design
    EXPLORE     = auto()  # RulialExplorer — spaghetti, systematic search


# ═══════════════════════════════════════════════════════
# XR LENS — the human's interface to augmented intelligence
# ═══════════════════════════════════════════════════════

@dataclass
class Sight:
    """What the human sees through the lens. Spatial, grounded, physics-first."""
    idea: str
    detection: Detection
    physics_check: Optional[dict] = None
    expert_match: Optional[dict] = None
    fab_options: list = field(default_factory=list)
    patent_ready: bool = False
    confidence: float = 0.0
    thought: Any = None  # Brain's interpretation (Thought object)

    @property
    def go_no_go(self) -> str:
        if self.confidence > 0.8 and self.physics_check and self.physics_check.get("survives"):
            return "GO — physics allows, fabrication path exists"
        if self.confidence > 0.5:
            return "CONDITIONAL — needs expert review"
        return "NO GO — physics says no or insufficient data"


# ═══════════════════════════════════════════════════════
# CRTYRD — expert knowledge, compensated, preserved
# ═══════════════════════════════════════════════════════

@dataclass
class Expert:
    id: str
    domain: str
    experience_years: int
    rate_per_hour: float = 0.0
    reasoning_traces: list = field(default_factory=list)

@dataclass
class ValidationChain:
    query: str
    ai_response: str
    ai_confidence: float
    expert: Optional[Expert] = None
    correction: Optional[str] = None
    fabrication_outcome: Optional[dict] = None
    confidence_after: float = 0.0

class Courtyard:
    """Expert knowledge layer. Vets get paid. Reasoning preserved."""
    def __init__(self) -> None:
        self._experts: dict[str, Expert] = {}
        self._chains: list[ValidationChain] = []

    def register_expert(self, expert: Expert) -> None:
        self._experts[expert.id] = expert

    def find_expert(self, query: str) -> Optional[Expert]:
        q_words = set(query.lower().split())
        matches = []
        for e in self._experts.values():
            e_words = set(e.domain.lower().split())
            # match if any word overlaps, or substring match either direction
            if (q_words & e_words
                or any(w in query.lower() for w in e_words)
                or any(w in e.domain.lower() for w in q_words)):
                matches.append(e)
        return max(matches, key=lambda e: e.experience_years) if matches else None

    def validate(self, chain: ValidationChain) -> ValidationChain:
        expert = self.find_expert(chain.query)
        if expert:
            chain.expert = expert
            chain.confidence_after = min(chain.ai_confidence + 0.3, 0.99)
        self._chains.append(chain)
        return chain

    @property
    def knowledge_base(self) -> list[ValidationChain]:
        return [c for c in self._chains if c.fabrication_outcome]

    @property
    def stats(self) -> dict:
        return {"experts": len(self._experts), "chains": len(self._chains),
                "fabricated": len(self.knowledge_base)}


# ═══════════════════════════════════════════════════════
# TOEBUSTER — physics gauntlet. survives or dies.
# ═══════════════════════════════════════════════════════

@dataclass
class PhysicsTest:
    name: str
    domain: str  # thermal, structural, em, quantum, materials, fluid
    check: Callable[[dict], bool] = field(default=lambda d: True)

class ToeBuster:
    """The physics gauntlet. 5000 tests. Reality doesn't negotiate."""
    def __init__(self) -> None:
        self._tests: list[PhysicsTest] = []

    def register(self, test: PhysicsTest) -> None:
        self._tests.append(test)

    def run(self, design: dict) -> dict:
        passed, failed, errors = [], [], []
        for t in self._tests:
            try:
                if t.check(design): passed.append(t.name)
                else: failed.append(t.name)
            except Exception as e:
                errors.append(f"{t.name}: {e}")
        total = len(self._tests) or 1
        return {
            "survives": len(failed) == 0 and len(errors) == 0,
            "passed": len(passed), "failed": len(failed),
            "errors": len(errors), "details": failed + errors,
            "confidence": len(passed) / total,
        }

    @property
    def size(self) -> int: return len(self._tests)


# ═══════════════════════════════════════════════════════
# FAB NET — global taxonomy of makers, labs, fabs
# ═══════════════════════════════════════════════════════

@dataclass
class FabNode:
    id: str
    name: str
    location: str
    capabilities: list[str]  # "cnc", "3dp", "pcb", "injection", "welding"
    lat: float = 0.0
    lon: float = 0.0
    discrete: bool = False  # compartmentalized manufacturing capable

class FabNet:
    """Global maker/fab taxonomy. Find who can build it."""
    def __init__(self) -> None:
        self._nodes: dict[str, FabNode] = {}

    def register(self, node: FabNode) -> None:
        self._nodes[node.id] = node

    def find(self, capability: str, discrete: bool = False) -> list[FabNode]:
        matches = [n for n in self._nodes.values()
                   if capability.lower() in [c.lower() for c in n.capabilities]]
        if discrete:
            matches = [n for n in matches if n.discrete]
        return matches

    def compartmentalize(self, design: dict, n_vendors: int = 3) -> list[dict]:
        """Split design across vendors. No single vendor sees the whole."""
        parts = list(design.get("components", {}).items())
        assignments = [[] for _ in range(n_vendors)]
        for i, (name, spec) in enumerate(parts):
            assignments[i % n_vendors].append({name: spec})
        return [{"vendor": i, "parts": a} for i, a in enumerate(assignments)]

    @property
    def stats(self) -> dict:
        caps = {}
        for n in self._nodes.values():
            for c in n.capabilities:
                caps[c] = caps.get(c, 0) + 1
        return {"nodes": len(self._nodes), "capabilities": caps}


# ═══════════════════════════════════════════════════════
# SENSOR NET — rfcanary pattern. listen to what's already there.
# ═══════════════════════════════════════════════════════

@dataclass
class SensorFeed:
    id: str
    kind: str  # "wifi_csi", "weather", "seismic", "air_quality", "rf_ambient"
    endpoint: str = ""
    interval_s: float = 60.0
    last_value: Any = None
    last_read: float = 0.0

class SensorNet:
    """Ambient sensor tap. No new hardware. Just listen."""
    def __init__(self) -> None:
        self._feeds: dict[str, SensorFeed] = {}

    def register(self, feed: SensorFeed) -> None:
        self._feeds[feed.id] = feed

    def read(self, feed_id: str) -> Any:
        feed = self._feeds.get(feed_id)
        if feed: feed.last_read = time.time()
        return feed.last_value if feed else None

    def inject(self, feed_id: str, value: Any) -> None:
        """For testing / local sensors."""
        if feed_id in self._feeds:
            self._feeds[feed_id].last_value = value
            self._feeds[feed_id].last_read = time.time()

    @property
    def feed_ids(self) -> list[str]:
        return list(self._feeds.keys())

    @property
    def active(self) -> list[str]:
        now = time.time()
        return [f.id for f in self._feeds.values()
                if now - f.last_read < f.interval_s * 3]


# ═══════════════════════════════════════════════════════
# PATENT GEN — provisional from validated design
# ═══════════════════════════════════════════════════════

class PatentGen:
    """Generate provisional patent application from validated design."""
    @staticmethod
    def generate(design: dict, physics_result: dict,
                 inventor: str = "", assignee: str = "AnnulusLabs LLC") -> dict:
        claims = []
        for i, (component, spec) in enumerate(design.get("components", {}).items()):
            claims.append(f"Claim {i+1}: A system comprising {component} "
                          f"configured to {spec.get('function', 'operate')}.")
        return {
            "title": design.get("title", "Untitled Invention"),
            "inventor": inventor,
            "assignee": assignee,
            "abstract": design.get("abstract", ""),
            "claims": claims,
            "physics_validation": physics_result,
            "filing_ready": physics_result.get("survives", False),
            "generated": time.time(),
        }


# ═══════════════════════════════════════════════════════
# MESH — BNET/HyperWave. when infrastructure fails.
# ═══════════════════════════════════════════════════════

class MeshNode:
    """Minimal mesh node representation."""
    def __init__(self, node_id: str, transport: str = "lora") -> None:
        self.id = node_id
        self.transport = transport
        self.peers: set[str] = set()
        self._inbox: list[dict] = []

    def send(self, to: str, payload: Any) -> dict:
        msg = {"from": self.id, "to": to, "payload": payload,
               "t": time.time(), "transport": self.transport}
        return msg

    def receive(self, msg: dict) -> None:
        self._inbox.append(msg)

    @property
    def messages(self) -> list[dict]:
        return list(self._inbox)


# ═══════════════════════════════════════════════════════
# ECOSYSTEM — the platform is the environment
# ═══════════════════════════════════════════════════════

class Ecosystem(Ocean):
    """
    The full Zoeae ecosystem as an ocean.
    Every subsystem is an environmental feature.
    The organism hatches into the ecosystem or it doesn't exist.
    """
    def __init__(self, name: str = "zoeae") -> None:
        super().__init__(name)
        self.courtyard = Courtyard()
        self.toebuster = ToeBuster()
        self.fab_net = FabNet()
        self.sensor_net = SensorNet()
        self.patent_gen = PatentGen()
        self.mesh_nodes: dict[str, MeshNode] = {}

    def add_mesh_node(self, node: MeshNode) -> None:
        self.mesh_nodes[node.id] = node

    def broadcast(self, payload: Any, transport: str = "lora") -> int:
        sent = 0
        for node in self.mesh_nodes.values():
            if node.transport == transport or transport == "all":
                node.receive({"from": "ocean", "payload": payload,
                              "t": time.time()})
                sent += 1
        return sent

    @property
    def stats(self) -> dict:
        base = super().stats
        base.update({
            "courtyard": self.courtyard.stats,
            "toebuster": self.toebuster.size,
            "fab_net": self.fab_net.stats,
            "sensors": len(self.sensor_net._feeds),
            "mesh_nodes": len(self.mesh_nodes),
        })
        return base


# ═══════════════════════════════════════════════════════
# MAKER — the augmented human
# ═══════════════════════════════════════════════════════

class Maker(Zoeae):
    """
    A human augmented by the Zoeae ecosystem.

    Hatches into the ecosystem. Sees through XR.
    Physics validates. Experts advise. Fabs build.
    The human decides. Always.
    """

    def __init__(self, ocean: Ecosystem, genome: Genome, **kw) -> None:
        super().__init__(ocean, genome, **kw)
        self.eco = ocean
        self._brain = None  # set via .brain property or Maker.hatch(brain=...)

    @classmethod
    def hatch(cls, ocean: Ecosystem, genome: Optional[Genome] = None,
              **kw) -> "Maker":
        g = genome or GenomeBuilder().core(
            name="maker", purpose="augment_human",
            principle="people_planet_profit_third"
        ).build()
        return cls(ocean, g, **kw)

    def see(self, idea: str) -> Sight:
        """The human says what they want to build. The ecosystem responds."""
        # 1. Perceive through antenna
        detection = self.perceive(idea)

        # 2. Check physics
        design = {"title": idea, "components": {}, "abstract": idea}
        physics = self.eco.toebuster.run(design)

        # 3. Find expert
        expert = self.eco.courtyard.find_expert(idea)
        expert_match = None
        if expert:
            expert_match = {"id": expert.id, "domain": expert.domain,
                           "years": expert.experience_years}

        # 4. Find fabrication
        fab_options = []
        for cap in ["cnc", "3dp", "pcb", "welding", "injection"]:
            nodes = self.eco.fab_net.find(cap)
            if nodes:
                fab_options.extend([{"node": n.name, "capability": cap,
                                     "location": n.location} for n in nodes])

        # 5. Assess
        confidence = detection.sharpness * physics.get("confidence", 0)
        if expert_match: confidence = min(confidence + 0.2, 0.99)
        if fab_options: confidence = min(confidence + 0.1, 0.99)

        sight = Sight(
            idea=idea,
            detection=detection,
            physics_check=physics,
            expert_match=expert_match,
            fab_options=fab_options,
            patent_ready=physics.get("survives", False),
            confidence=confidence,
        )

        # 6. If brain is attached, interpret the sight
        if self._brain is not None:
            sight.thought = self._brain.interpret_sight(
                idea, sight, bleed=self.bleed,
            )

        return sight

    @property
    def brain(self):
        return self._brain

    @brain.setter
    def brain(self, value):
        self._brain = value

    def validate_and_patent(self, design: dict,
                            inventor: str = "") -> dict:
        """Full pipeline: physics check → patent generation."""
        physics = self.eco.toebuster.run(design)
        if not physics["survives"]:
            return {"error": "Physics says no", "details": physics["details"]}
        return self.eco.patent_gen.generate(design, physics, inventor)

    def find_fab(self, capability: str, discrete: bool = False) -> list[FabNode]:
        return self.eco.fab_net.find(capability, discrete)

    def compartmentalize(self, design: dict, n_vendors: int = 3) -> list[dict]:
        return self.eco.fab_net.compartmentalize(design, n_vendors)

    def ask_expert(self, query: str, ai_response: str,
                   ai_confidence: float) -> ValidationChain:
        chain = ValidationChain(query=query, ai_response=ai_response,
                                ai_confidence=ai_confidence)
        return self.eco.courtyard.validate(chain)

    def mesh_broadcast(self, payload: Any) -> int:
        return self.eco.broadcast(payload)

    def read_sensor(self, feed_id: str) -> Any:
        return self.eco.sensor_net.read(feed_id)

    @property
    def stats(self) -> dict:
        base = super().stats
        base["ecosystem"] = self.eco.stats
        return base
