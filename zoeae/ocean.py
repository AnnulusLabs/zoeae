"""
Ocean — The environment the organism doesn't control.

A zoea hatches into an ocean. The ocean has currents, food,
predators, and other larvae. The environment shapes the organism
as much as the genome does.

The ocean also provides the Mirror — the perspective the organism
doesn't author. The organism sees the neon surgical suite.
The mirror sees the Cheeto dust.

Multiple organisms share an ocean. The ocean is not optional.
You cannot hatch without one. A zoea in a vacuum is not alive.
"""

from __future__ import annotations
import time, hashlib, json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .organism import Zoeae


@dataclass
class Stimulus:
    """Something in the environment. The organism didn't ask for it."""
    kind: str          # "food", "predator", "current", "signal", "other_organism"
    intensity: float   # 0-1
    payload: Any = None
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    consumed: bool = False


@dataclass
class Reflection:
    """
    What the mirror sees. The delta between self-report and external observation.

    The organism says 'vitals stabilizing.'
    The mirror says 'you are covered in Cheeto dust.'
    """
    self_report: dict       # what the organism thinks
    external_view: dict     # what the mirror sees
    deltas: dict = field(default_factory=dict)  # the gaps
    timestamp: float = field(default_factory=time.time)

    @property
    def coherent(self) -> bool:
        """Is the organism's self-image aligned with external reality?"""
        return len(self.deltas) == 0

    @property
    def drift(self) -> float:
        """How far has the organism drifted from external reality? 0=coherent."""
        if not self.deltas:
            return 0.0
        return sum(abs(v) if isinstance(v, (int, float)) else 1.0
                   for v in self.deltas.values()) / max(len(self.deltas), 1)


class Ocean:
    """
    The world outside the organism.

    Provides:
    - Stimuli: things that happen to the organism (food, threats, signals)
    - Currents: forces that move organisms whether they want to move or not
    - Population: other organisms in the same ocean
    - Mirror: external observation that the organism doesn't author
    - Selection: pressure that removes organisms that don't adapt

    The organism cannot modify the ocean. It can only respond to it.
    """

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._stimuli: list[Stimulus] = []
        self._organisms: dict[str, "Zoeae"] = {}
        self._currents: dict[str, float] = {}  # named forces
        self._mirror_fn: Optional[Callable[["Zoeae"], dict]] = None
        self._selection_fn: Optional[Callable[["Zoeae"], bool]] = None
        self._history: list[dict] = []

    # ── STIMULI ──

    def emit(self, kind: str, intensity: float = 0.5,
             payload: Any = None, source: str = "") -> Stimulus:
        """Emit a stimulus into the ocean. All organisms can sense it."""
        s = Stimulus(kind=kind, intensity=intensity,
                     payload=payload, source=source)
        self._stimuli.append(s)
        return s

    def stimuli(self, kind: Optional[str] = None,
                min_intensity: float = 0.0) -> list[Stimulus]:
        """What's in the water right now?"""
        results = [s for s in self._stimuli if not s.consumed]
        if kind:
            results = [s for s in results if s.kind == kind]
        return [s for s in results if s.intensity >= min_intensity]

    def consume(self, stimulus: Stimulus) -> None:
        """Organism consumed this stimulus. It's gone."""
        stimulus.consumed = True

    # ── CURRENTS ──

    def set_current(self, name: str, force: float) -> None:
        """Set a named current. Positive = favorable. Negative = adverse."""
        self._currents[name] = force

    @property
    def currents(self) -> dict[str, float]:
        return dict(self._currents)

    @property
    def net_current(self) -> float:
        """Sum of all currents. Positive = favorable environment."""
        return sum(self._currents.values()) if self._currents else 0.0

    # ── POPULATION ──

    def register(self, organism: "Zoeae") -> None:
        self._organisms[organism.fingerprint[:12]] = organism

    def unregister(self, organism: "Zoeae") -> None:
        self._organisms.pop(organism.fingerprint[:12], None)

    @property
    def population(self) -> int:
        return len(self._organisms)

    def peers(self, exclude: Optional["Zoeae"] = None) -> list["Zoeae"]:
        """Other organisms in this ocean."""
        ex_fp = exclude.fingerprint[:12] if exclude else None
        return [o for k, o in self._organisms.items() if k != ex_fp]

    # ── MIRROR ──

    def set_mirror(self, fn: Callable[["Zoeae"], dict]) -> None:
        """Set the external observation function.

        This is the patient POV. The function takes an organism and returns
        what it looks like from outside — which may differ from self-report.
        The organism cannot set or modify this function.
        """
        self._mirror_fn = fn

    def reflect(self, organism: "Zoeae") -> Reflection:
        """Hold the mirror up. Compare self-report to external observation."""
        self_report = organism.stats

        if self._mirror_fn:
            external = self._mirror_fn(organism)
        else:
            # Default mirror: compare against peer consensus
            external = self._default_mirror(organism)

        # Compute deltas
        deltas = {}
        for key in set(list(self_report.keys()) + list(external.keys())):
            sv = self_report.get(key)
            ev = external.get(key)
            if sv != ev and ev is not None:
                if isinstance(sv, (int, float)) and isinstance(ev, (int, float)):
                    deltas[key] = sv - ev
                else:
                    deltas[key] = f"self={sv} mirror={ev}"

        ref = Reflection(self_report=self_report,
                         external_view=external, deltas=deltas)
        self._history.append({
            "organism": organism.fingerprint[:12],
            "drift": ref.drift, "coherent": ref.coherent,
            "t": time.time()})
        return ref

    def _default_mirror(self, organism: "Zoeae") -> dict:
        """Default: peer comparison. If you're the only one, mirror is empty."""
        peers = self.peers(exclude=organism)
        if not peers:
            return {}
        # Average peer stats as the "external view"
        peer_beliefs = [p.instinct.size for p in peers]
        peer_fragments = [p.accumulator.size for p in peers]
        peer_instars = [p.instar.value for p in peers]
        n = len(peers)
        return {
            "beliefs": sum(peer_beliefs) / n,
            "fragments": sum(peer_fragments) / n,
            "instar": sum(peer_instars) / n,
            "population_context": True,
        }

    # ── SELECTION ──

    def set_selection(self, fn: Callable[["Zoeae"], bool]) -> None:
        """Set selection pressure. Returns True if organism survives."""
        self._selection_fn = fn

    def select(self, organism: "Zoeae") -> bool:
        """Apply selection pressure. Returns True = survives."""
        if self._selection_fn:
            return self._selection_fn(organism)
        return True  # no pressure = everything survives

    def sweep(self) -> list[str]:
        """Apply selection to all organisms. Remove the dead. Return their fingerprints."""
        dead = []
        for fp, org in list(self._organisms.items()):
            if not self.select(org):
                dead.append(fp)
                org._alive = False
        for fp in dead:
            self._organisms.pop(fp, None)
        return dead

    # ── CLEANUP ──

    def tick(self) -> None:
        """Advance the ocean. Decay old stimuli."""
        now = time.time()
        self._stimuli = [s for s in self._stimuli
                         if not s.consumed and now - s.timestamp < 300]

    @property
    def stats(self) -> dict:
        return {
            "name": self.name,
            "population": self.population,
            "active_stimuli": len([s for s in self._stimuli if not s.consumed]),
            "currents": self._currents,
            "net_current": self.net_current,
            "reflections": len(self._history),
        }
