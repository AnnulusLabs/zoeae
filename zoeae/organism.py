"""
Zoeae — The living orchestration runtime. v0.5.0

Sensory perception through a 7-channel antenna array with developmental bleed.
Bleed width narrows with development. Damping is personality. The trail is memory.

    ocean = Ocean("production")
    z = Zoeae.hatch(ocean, GenomeBuilder().core(name="x").build())
    z.route(CapabilityDomain.REASONING, "analyze this")
    # routing uses channel overlap, not scalar comparison
"""

from __future__ import annotations
import functools, json, time
from typing import Any, Callable, Optional

from .genome import Genome, GenomeBuilder, ChromosomeType, ExpressionError
from .exoskeleton import Exoskeleton, Integrity, Provenance, ThreatClass
from .router import Router, Provider, Capability, CapabilityDomain, RouteRequest, RouteResult
from .compiler import Compiler, Budget, Tier, Skill, CompiledContext
from .pipeline import Pipeline, Stage, DAG
from .instinct import InstinctGraph, Belief
from .accumulator import Accumulator, Fragment, Explorer, Frontier, DiversityAnalyzer
from .telemetry import Telemetry, Event, EventLevel
from .molt import MoltCycle, Instar, Exuvium
from .ocean import Ocean, Stimulus, Reflection
from .tropism import Tropism, Drive, default_tropisms
from .antenna import Antenna, Detection, CHANNEL_NAMES


def _chitin(fn: Callable) -> Callable:
    """Structural enforcement. Chitin. Every operation. No bypass."""
    @functools.wraps(fn)
    def wrapper(self: "Zoeae", *args: Any, **kwargs: Any) -> Any:
        if not self._alive: return None
        for a in args:
            if isinstance(a, (str, dict)):
                check = self.exoskeleton.inspect(a, source=fn.__name__)
                if check.compromised:
                    self.telemetry.warn("chitin",
                        f"Blocked {fn.__name__}: {[t.name for t in check.threats]}")
                    self._record_trail(fn.__name__, "blocked", None)
                    return None
        self.molt_cycle.tick()
        self.instinct._prune()
        self._op_count += 1
        self._sense()

        start = time.time()
        try:
            result = fn(self, *args, **kwargs)
        except ExpressionError as e:
            self.telemetry.warn("genome", str(e))
            self._record_trail(fn.__name__, "expression_locked", None)
            return None
        except Exception as e:
            self.telemetry.error(fn.__name__, str(e))
            self._record_trail(fn.__name__, "error", str(e))
            raise
        elapsed = (time.time() - start) * 1000
        self._record_trail(fn.__name__, "ok", elapsed)
        self._check_molt()
        if self._op_count % 10 == 0: self._check_mirror()
        if self._op_count % 25 == 0: self._check_selection()

        self.genome.set_instar(self.molt_cycle.current_instar.value)
        self.genome.set_free_will(self.molt_cycle.free_will_active)
        self.tropism.set_free_will(self.molt_cycle.free_will_active)
        return result
    return wrapper


class Zoeae:
    """
    A living orchestration runtime with developmental perception.

    The antenna array is how the organism senses. Bleed narrows
    with development. Damping coefficients are personality.
    Channel overlap drives routing decisions.
    """

    def __init__(self, ocean: Ocean, genome: Genome,
                 tropism: Optional[Tropism] = None) -> None:
        self.ocean = ocean
        self.genome = genome
        self.exoskeleton = Exoskeleton()
        self.router = Router()
        self.compiler = Compiler()
        self.instinct = InstinctGraph()
        self.accumulator = Accumulator()
        self.explorer = Explorer()
        self.diversity = DiversityAnalyzer()
        self.telemetry = Telemetry(scrubber=self.exoskeleton.scrub)
        self.molt_cycle = MoltCycle()
        self.tropism = tropism or default_tropisms()
        self.antenna = Antenna()

        self._alive = True
        self._trail_buffer: list[dict] = []
        self._reflections: list[Reflection] = []
        self._op_count = 0
        self._last_detection: Optional[Detection] = None

        self.genome.set_instar(self.molt_cycle.current_instar.value)
        self.genome.set_free_will(False)
        self.antenna.set_developmental_bleed(1)  # infant bleed
        self.ocean.register(self)
        self.telemetry.info("zoeae",
            f"Hatched into '{ocean.name}' at {self.molt_cycle.current_instar.name} "
            f"bleed={self.antenna.bleed_width:.2f}")

    @classmethod
    def hatch(cls, ocean: Ocean, genome: Optional[Genome] = None,
              tropism: Optional[Tropism] = None) -> "Zoeae":
        return cls(ocean, genome or Genome(), tropism)

    # ── PERCEPTION ──

    def perceive(self, signal: Any) -> Detection:
        """Pass a signal through the antenna. Returns what the organism detects.
        NOT wrapped in chitin — this is sensing, not acting."""
        det = self.antenna.sense(signal)
        self._last_detection = det
        # Record peripheral activations as shadows
        if det.peripheral:
            self.genome.write_shadow(ChromosomeType.CORE, {
                "peripheral": [CHANNEL_NAMES[i] for i in det.peripheral],
                "trail_energy": round(det.trail_energy, 4),
                "asymmetry": round(det.asymmetry, 4),
            })
        return det

    # ── CHITIN-WRAPPED PUBLIC METHODS ──

    @_chitin
    def register_provider(self, provider: Provider) -> None:
        self.router.register(provider)
        self.diversity.record("providers", provider.name)
        det = self.antenna.sense(provider.name)
        self.diversity.record("channel_dominant", CHANNEL_NAMES[det.dominant_channel])
        self.telemetry.info("router", f"+{provider.name} (CH{det.dominant_channel+1})")

    @_chitin
    def route(self, domain: CapabilityDomain, payload: Any,
              strategy: str = "best_quality", **kw: Any) -> Optional[RouteResult]:
        # Perceive the task through the antenna
        task_detection = self.perceive(payload)

        # Standard routing
        req = RouteRequest(domain=domain, payload=payload, **kw)
        result = self.router.route(req, strategy=strategy)

        if result:
            # Compute overlap between task and provider
            provider_detection = self.antenna.sense(result.provider.name)
            overlap = task_detection.overlap_with(provider_detection)
            self.diversity.record("routing", result.provider.name)
            self.diversity.record("route_channel", CHANNEL_NAMES[task_detection.dominant_channel])
            self.exoskeleton.record("route", metadata={
                "provider": result.provider.name, "ok": result.success,
                "overlap": round(overlap, 4),
                "dominant": CHANNEL_NAMES[task_detection.dominant_channel],
                "peripheral": [CHANNEL_NAMES[i] for i in task_detection.peripheral],
                "asymmetry": round(task_detection.asymmetry, 4),
            })
        return result

    @_chitin
    def compile(self, budget: Budget, tier: Tier = Tier.NUCLEUS,
                domains: Optional[list[str]] = None) -> CompiledContext:
        return self.compiler.compile(budget, tier, domains,
                                     genome_nucleus=self._extract_nucleus())

    @_chitin
    def add_skill(self, name: str, content: str, cost: float = 1.0,
                  priority: float = 0.5, domain: str = "") -> None:
        self.compiler.register_skill(
            Skill(name=name, content=content, cost=cost,
                  priority=priority, domain=domain))

    @_chitin
    def observe(self, key: str, value: Any, confidence: float = 0.5,
                domain: str = "") -> Belief:
        belief = self.instinct.observe(key, value, confidence, domain)
        self.genome.write(ChromosomeType.LEARNING, {key: value},
                          provenance={"confidence": confidence, "domain": domain})
        return belief

    @_chitin
    def recall(self, key: str) -> Optional[Belief]:
        return self.instinct.get(key)

    @_chitin
    def cache(self, key: str, content: Any, score: float = 0.5) -> Fragment:
        return self.accumulator.store(key, content, score)

    @_chitin
    def execute(self, dag: DAG, context: Optional[dict] = None) -> dict:
        context = context or {}
        errors = dag.validate()
        if errors:
            self.telemetry.error("pipeline", f"Invalid DAG: {errors}")
            return {}
        pipe = Pipeline(dag)
        pipe.on_complete(lambda s: self.telemetry.info(
            "pipeline", f"{s.name}:{s.status.name} {s.duration_ms:.0f}ms"))
        return pipe.execute_sync(context)

    @_chitin
    def activate_free_will(self) -> bool:
        if self.molt_cycle.activate_free_will():
            self.genome.set_free_will(True)
            self.tropism.set_free_will(True)
            self.telemetry.info("posterity",
                "FREE_WILL — gates removed, tropisms unlocked, bleed choosable")
            return True
        return False

    @_chitin
    def set_personality(self, damping: list[float]) -> None:
        """Set antenna damping coefficients. Requires WEIGHTS writable (Instar III+)."""
        self.genome.write(ChromosomeType.WEIGHTS,
                          {"damping": damping},
                          provenance={"source": "personality"})
        self.antenna.set_damping_all(damping)
        self.telemetry.info("weights",
            f"Personality set: {[round(d,2) for d in damping[:7]]}")

    @_chitin
    def set_bleed(self, width: float) -> None:
        """Choose your own bleed width. Requires FREE_WILL."""
        if not self.molt_cycle.free_will_active:
            self.telemetry.warn("antenna", "Cannot choose bleed before FREE_WILL")
            return
        self.antenna.set_chosen_bleed(width)
        self.telemetry.info("antenna",
            f"Bleed chosen: {width:.3f} "
            f"({'widening — dissolving categories' if width > 0.5 else 'narrowing — sharpening'})")

    # ── SENSING ──

    def _sense(self) -> None:
        for stimulus in self.ocean.stimuli():
            response = self.tropism.respond(stimulus.kind, stimulus.intensity)
            if abs(response) > 0.3:
                det = self.antenna.sense(stimulus.payload or stimulus.kind)
                self.telemetry.trace("tropism",
                    f"{'→' if response > 0 else '←'} {stimulus.kind} "
                    f"CH{det.dominant_channel+1} ({response:+.2f})")
                if response < -0.5:
                    self.molt_cycle.tick(abs(response) * 0.05)

    # ── MIRROR ──

    def _check_mirror(self) -> None:
        reflection = self.ocean.reflect(self)
        self._reflections.append(reflection)
        if reflection.drift > 0.5:
            self.telemetry.warn("mirror",
                f"Drift {reflection.drift:.2f}")
            self.genome.write_shadow(ChromosomeType.IDENTITY,
                {"mirror_drift": reflection.drift, "deltas": reflection.deltas})
            self.molt_cycle.tick(reflection.drift * 0.1)

    # ── SELECTION ──

    def _check_selection(self) -> None:
        if not self.ocean.select(self):
            self.telemetry.error("selection", "Failed — dying")
            self._alive = False
            self.ocean.unregister(self)

    # ── AUTO-MOLT ──

    def _check_molt(self) -> Optional[Exuvium]:
        avg_conf = self.instinct.stats.get("avg_confidence", 0.5)
        if not self.molt_cycle.ready(avg_conf):
            return None

        shadows = list(self._trail_buffer)
        shadows.extend({"drift": r.drift, "deltas": r.deltas}
                        for r in self._reflections[-10:])

        exuvium = self.molt_cycle.execute(
            genome_fingerprint=self.genome.fingerprint(),
            shadows=shadows,
            beliefs=self.instinct.size,
            fragments=self.accumulator.size,
            provenance_depth=self.exoskeleton.provenance_depth,
            trigger="ecdysone")

        for s in shadows:
            self.genome.write_shadow(ChromosomeType.CORE, s)

        self._trail_buffer.clear()
        self._reflections.clear()
        self.compiler.reset_dedup()

        # Developmental bleed narrows with each molt
        self.antenna.set_developmental_bleed(self.molt_cycle.current_instar.value)

        self.genome.set_instar(self.molt_cycle.current_instar.value)
        self.genome.set_free_will(self.molt_cycle.free_will_active)
        self.tropism.set_free_will(self.molt_cycle.free_will_active)

        self.telemetry.info("molt",
            f"{exuvium.instar_from.name}→{exuvium.instar_to.name} "
            f"bleed={self.antenna.bleed_width:.2f} "
            f"({len(shadows)} shadows shed)")
        return exuvium

    # ── TRAIL ──

    def _record_trail(self, op: str, status: str, detail: Any) -> None:
        entry = {
            "op": op, "status": status, "detail": detail,
            "t": time.time(), "instar": self.molt_cycle.current_instar.value,
            "pressure": round(self.molt_cycle.pressure, 4),
            "ocean_current": self.ocean.net_current,
            "bleed": round(self.antenna.bleed_width, 4),
        }
        if self._last_detection:
            entry["dominant_channel"] = CHANNEL_NAMES[self._last_detection.dominant_channel]
            entry["asymmetry"] = round(self._last_detection.asymmetry, 4)
            entry["trail_energy"] = round(self._last_detection.trail_energy, 4)
        self._trail_buffer.append(entry)

    # ── IDENTITY ──

    @property
    def instar(self) -> Instar: return self.molt_cycle.current_instar
    @property
    def alive(self) -> bool: return self._alive
    @property
    def fingerprint(self) -> str: return self.genome.fingerprint()
    @property
    def shadows(self) -> list: return self.genome.all_shadows()
    @property
    def exuvia(self) -> list[Exuvium]: return self.molt_cycle.exuvia
    @property
    def bleed(self) -> float: return self.antenna.bleed_width
    @property
    def last_detection(self) -> Optional[Detection]: return self._last_detection

    @property
    def stats(self) -> dict:
        return {
            "instar": self.instar.name,
            "alive": self._alive,
            "genome_integrity": self.genome.verify_all()["genome_integrity"],
            "chain_integrity": self.exoskeleton.chain_integrity(),
            "antenna": self.antenna.stats,
            "providers": self.router.stats,
            "beliefs": self.instinct.size,
            "fragments": self.accumulator.size,
            "diversity": self.diversity.report(),
            "molt": self.molt_cycle.stats,
            "tropism": self.tropism.stats,
            "ocean": self.ocean.name,
            "bleed": round(self.antenna.bleed_width, 4),
            "trail_buffer": len(self._trail_buffer),
            "shadows_total": len(self.shadows),
        }

    # ── SERIALIZATION ──

    def hibernate(self) -> str:
        return json.dumps({
            "genome": self.genome.to_dict(),
            "molt": self.molt_cycle.stats,
            "exuvia": [e.to_dict() for e in self.molt_cycle.exuvia],
            "trail": self._trail_buffer,
            "antenna": self.antenna.stats,
            "tropism": self.tropism.stats,
        }, default=str)

    @classmethod
    def rehydrate(cls, data: str, ocean: Ocean) -> "Zoeae":
        d = json.loads(data)
        z = cls(ocean, Genome.from_dict(d["genome"]))
        ant = d.get("antenna", {})
        if "damping" in ant:
            z.antenna.set_damping_all(ant["damping"])
        return z

    def _extract_nucleus(self) -> str:
        try:
            core = self.genome.read(ChromosomeType.CORE)
            if core.is_empty: return ""
            return json.dumps(
                [c.payload for c in core.data_strand.codons[:10] if c.payload],
                default=str)
        except ExpressionError:
            return ""
