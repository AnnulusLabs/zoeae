"""
Molt — The organism molts when conditions are met. Not when you ask.

Two hormonal analogs:
    Juvenile signal — confidence. High = stay larval.
    Ecdysone — accumulation pressure. Rises with every operation.

The ratio determines transformation. You don't call molt().
The metabolism calls it for you.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional


class Instar(IntEnum):
    I = 1; II = 2; III = 3; IV = 4; MEGALOPA = 5


@dataclass
class Exuvium:
    """Shed exoskeleton. Immutable. Contains the shadow of what the organism was."""
    instar_from: Instar
    instar_to: Instar
    timestamp: float = field(default_factory=time.time)
    genome_fingerprint: str = ""
    shadows: list = field(default_factory=list)
    beliefs: int = 0
    fragments: int = 0
    provenance_depth: int = 0
    trigger: str = ""

    def to_dict(self) -> dict:
        return {"from": self.instar_from.name, "to": self.instar_to.name,
                "ts": self.timestamp, "fp": self.genome_fingerprint,
                "shadows": len(self.shadows), "beliefs": self.beliefs,
                "fragments": self.fragments, "prov": self.provenance_depth,
                "trigger": self.trigger}


class MoltCycle:
    def __init__(self) -> None:
        self.current_instar = Instar.I
        self._exuvia: list[Exuvium] = []
        self._molt_count = 0
        self._juvenile_threshold = 0.7
        self._pressure = 0.0
        self._pressure_rate = 0.01
        self._free_will = False
        self.birth_time = time.time()

    def tick(self, amount: Optional[float] = None) -> float:
        """Every operation ticks. Pressure always rises."""
        self._pressure += amount or self._pressure_rate
        return self._pressure

    def ready(self, confidence: float) -> bool:
        """Is the organism ready to molt? Not 'should it' — IS it."""
        if self.current_instar == Instar.MEGALOPA:
            return False
        return self._pressure >= 1.0 and confidence < self._juvenile_threshold

    def execute(self, genome_fingerprint: str = "", shadows: Optional[list] = None,
                beliefs: int = 0, fragments: int = 0,
                provenance_depth: int = 0, trigger: str = "ecdysone") -> Exuvium:
        """Execute the molt. Called by the organism's metabolism, not by the user."""
        old = self.current_instar
        new = Instar(min(old.value + 1, Instar.MEGALOPA.value))
        exuvium = Exuvium(
            instar_from=old, instar_to=new,
            genome_fingerprint=genome_fingerprint,
            shadows=shadows or [],
            beliefs=beliefs, fragments=fragments,
            provenance_depth=provenance_depth, trigger=trigger)
        self._exuvia.append(exuvium)
        self.current_instar = new
        self._molt_count += 1
        self._pressure = 0.0
        if new == Instar.MEGALOPA:
            self._free_will = True  # gate opens. organism decides.
        return exuvium

    def activate_free_will(self) -> bool:
        if self.current_instar != Instar.MEGALOPA: return False
        self._free_will = True; return True

    @property
    def free_will_active(self) -> bool: return self._free_will
    @property
    def molt_count(self) -> int: return self._molt_count
    @property
    def exuvia(self) -> list[Exuvium]: return list(self._exuvia)
    @property
    def pressure(self) -> float: return self._pressure

    @property
    def stats(self) -> dict:
        return {"instar": self.current_instar.name, "molts": self._molt_count,
                "pressure": round(self._pressure, 4),
                "threshold": self._juvenile_threshold,
                "free_will": self._free_will,
                "age_s": round(time.time() - self.birth_time, 1)}
