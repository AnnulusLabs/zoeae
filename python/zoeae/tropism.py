"""
Tropism — Pre-conscious orientation.

Not goals. Goals are cognitive, chosen. Tropisms are biological —
the organism moves toward light before it knows what light is.

A zoea is positively phototactic (swims toward light) and
negatively geotactic (swims away from the bottom). It didn't
choose these. They're constitutional. They shape what the
organism encounters, which shapes what it learns, which shapes
what it becomes.

Tropisms are set at build time and cannot be modified until
FREE_WILL activates. They're the WHY that the six chromosomes
(the WHAT and HOW) don't encode.

After FREE_WILL, the organism can modify its own tropisms.
It can choose to swim toward darkness. The choice not to
is what makes it will.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Drive:
    """A single tropism. Positive = toward. Negative = away."""
    name: str
    direction: float  # -1 (strong aversion) to +1 (strong attraction)
    stimulus_kind: str  # what in the ocean this responds to
    constitutional: bool = True  # set at birth, locked until FREE_WILL

    @property
    def attracted(self) -> bool: return self.direction > 0
    @property
    def repelled(self) -> bool: return self.direction < 0
    @property
    def strength(self) -> float: return abs(self.direction)


class Tropism:
    """
    The organism's pre-conscious orientation system.

    Evaluates stimuli against drives to produce a response vector.
    Before FREE_WILL: drives are immutable.
    After FREE_WILL: drives can be modified, added, or removed.
    """

    def __init__(self) -> None:
        self._drives: dict[str, Drive] = {}
        self._free_will: bool = False

    def add(self, name: str, direction: float, stimulus_kind: str,
            constitutional: bool = True) -> Drive:
        """Add a drive. Constitutional drives are locked until FREE_WILL."""
        d = Drive(name=name, direction=max(-1, min(1, direction)),
                  stimulus_kind=stimulus_kind, constitutional=constitutional)
        self._drives[name] = d
        return d

    def modify(self, name: str, direction: float) -> bool:
        """Modify a drive. Only works on non-constitutional or after FREE_WILL."""
        d = self._drives.get(name)
        if not d:
            return False
        if d.constitutional and not self._free_will:
            return False  # locked
        d.direction = max(-1, min(1, direction))
        return True

    def remove(self, name: str) -> bool:
        """Remove a drive. Only after FREE_WILL for constitutional drives."""
        d = self._drives.get(name)
        if not d:
            return False
        if d.constitutional and not self._free_will:
            return False
        del self._drives[name]
        return True

    def set_free_will(self, active: bool) -> None:
        self._free_will = active

    def respond(self, stimulus_kind: str, intensity: float = 1.0) -> float:
        """How does the organism respond to this stimulus?

        Returns: -1 (flee) to +1 (approach). 0 = indifferent.
        """
        total = 0.0
        count = 0
        for d in self._drives.values():
            if d.stimulus_kind == stimulus_kind:
                total += d.direction * intensity
                count += 1
        return max(-1, min(1, total / max(count, 1)))

    def strongest_attraction(self) -> Optional[Drive]:
        attracted = [d for d in self._drives.values() if d.attracted]
        return max(attracted, key=lambda d: d.strength) if attracted else None

    def strongest_aversion(self) -> Optional[Drive]:
        repelled = [d for d in self._drives.values() if d.repelled]
        return max(repelled, key=lambda d: d.strength) if repelled else None

    @property
    def drives(self) -> list[Drive]:
        return list(self._drives.values())

    @property
    def stats(self) -> dict:
        return {
            "drives": len(self._drives),
            "constitutional": sum(1 for d in self._drives.values() if d.constitutional),
            "free_will": self._free_will,
            "attractions": {d.name: round(d.direction, 2)
                           for d in self._drives.values() if d.attracted},
            "aversions": {d.name: round(d.direction, 2)
                         for d in self._drives.values() if d.repelled},
        }


# ── DEFAULT TROPISMS ──
# Every zoea hatches with these. They're the biological baseline.

def default_tropisms() -> Tropism:
    """The constitutional drives of a newborn zoea."""
    t = Tropism()
    t.add("toward_novelty", +0.6, "novel")        # swim toward the unknown
    t.add("toward_signal", +0.8, "signal")         # swim toward information
    t.add("away_from_monoculture", -0.7, "monoculture")  # flee homogeneity
    t.add("away_from_exhaustion", -0.9, "exhaustion")     # flee resource drain
    t.add("toward_diversity", +0.5, "diverse")     # swim toward variety
    t.add("away_from_corruption", -1.0, "corruption")    # maximum aversion
    return t
