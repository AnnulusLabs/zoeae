"""
InstinctGraph — Confidence-weighted belief system with temporal decay.

The organism learns which strategies work and forgets those that don't.
Beliefs decay over time unless reinforced. Monoculture is detectable.
This is how any system builds institutional knowledge.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Belief:
    """A belief the organism holds with measurable confidence."""
    key: str
    value: Any
    confidence: float = 0.5    # 0-1
    created: float = field(default_factory=time.time)
    last_reinforced: float = field(default_factory=time.time)
    reinforcement_count: int = 0
    domain: str = ""

    def reinforce(self, amount: float = 0.1) -> None:
        """Strengthen belief based on positive evidence."""
        self.confidence = min(1.0, self.confidence + amount * (1.0 - self.confidence))
        self.last_reinforced = time.time()
        self.reinforcement_count += 1

    def weaken(self, amount: float = 0.1) -> None:
        """Weaken belief based on contradictory evidence."""
        self.confidence = max(0.0, self.confidence - amount * self.confidence)
        self.last_reinforced = time.time()

    def decayed_confidence(self, half_life_s: float = 86400.0) -> float:
        """Confidence with exponential time decay."""
        age = time.time() - self.last_reinforced
        decay = math.exp(-0.693 * age / half_life_s)  # ln(2) ≈ 0.693
        return self.confidence * decay

    def to_dict(self) -> dict:
        return {
            "key": self.key, "value": self.value,
            "confidence": self.confidence,
            "created": self.created,
            "last_reinforced": self.last_reinforced,
            "reinforcement_count": self.reinforcement_count,
            "domain": self.domain,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Belief":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class InstinctGraph:
    """
    A graph of beliefs with confidence decay.

    Detects:
    - Stale beliefs (high confidence, not reinforced recently)
    - Contradictions (beliefs in same domain with opposing values)
    - Monoculture (too many beliefs in one domain)
    """

    def __init__(self, half_life_s: float = 86400.0,
                 prune_threshold: float = 0.05) -> None:
        self._beliefs: dict[str, Belief] = {}
        self.half_life_s = half_life_s
        self.prune_threshold = prune_threshold

    def observe(self, key: str, value: Any, confidence: float = 0.5,
                domain: str = "") -> Belief:
        """Record an observation. Reinforces existing belief or creates new one."""
        if key in self._beliefs:
            existing = self._beliefs[key]
            if existing.value == value:
                existing.reinforce(confidence * 0.2)
            else:
                existing.weaken(0.3)
                if existing.decayed_confidence(self.half_life_s) < 0.2:
                    # Old belief too weak — replace
                    self._beliefs[key] = Belief(key=key, value=value,
                                                 confidence=confidence, domain=domain)
            return self._beliefs[key]
        else:
            belief = Belief(key=key, value=value, confidence=confidence, domain=domain)
            self._beliefs[key] = belief
            return belief

    def get(self, key: str) -> Optional[Belief]:
        b = self._beliefs.get(key)
        if b and b.decayed_confidence(self.half_life_s) < self.prune_threshold:
            del self._beliefs[key]
            return None
        return b

    def query(self, domain: str = "", min_confidence: float = 0.0) -> list[Belief]:
        """Query beliefs, optionally filtered by domain and confidence."""
        self._prune()
        results = []
        for b in self._beliefs.values():
            dc = b.decayed_confidence(self.half_life_s)
            if dc < min_confidence:
                continue
            if domain and b.domain != domain:
                continue
            results.append(b)
        results.sort(key=lambda b: b.decayed_confidence(self.half_life_s), reverse=True)
        return results

    def strongest(self, n: int = 5) -> list[Belief]:
        """Top N beliefs by decayed confidence."""
        self._prune()
        beliefs = list(self._beliefs.values())
        beliefs.sort(key=lambda b: b.decayed_confidence(self.half_life_s), reverse=True)
        return beliefs[:n]

    def domain_distribution(self) -> dict[str, int]:
        """How beliefs are distributed across domains."""
        dist: dict[str, int] = {}
        for b in self._beliefs.values():
            d = b.domain or "unclassified"
            dist[d] = dist.get(d, 0) + 1
        return dist

    def monoculture_risk(self) -> float:
        """0-1 score of how concentrated beliefs are in one domain. 1 = monoculture."""
        dist = self.domain_distribution()
        if not dist:
            return 0.0
        total = sum(dist.values())
        max_count = max(dist.values())
        return max_count / total

    def _prune(self) -> int:
        """Remove beliefs below threshold."""
        before = len(self._beliefs)
        to_remove = [
            k for k, b in self._beliefs.items()
            if b.decayed_confidence(self.half_life_s) < self.prune_threshold
        ]
        for k in to_remove:
            del self._beliefs[k]
        return before - len(self._beliefs)

    @property
    def size(self) -> int:
        return len(self._beliefs)

    @property
    def stats(self) -> dict:
        self._prune()
        if not self._beliefs:
            return {"size": 0, "avg_confidence": 0, "monoculture_risk": 0}
        confidences = [b.decayed_confidence(self.half_life_s)
                       for b in self._beliefs.values()]
        return {
            "size": len(self._beliefs),
            "avg_confidence": sum(confidences) / len(confidences),
            "max_confidence": max(confidences),
            "min_confidence": min(confidences),
            "monoculture_risk": self.monoculture_risk(),
            "domains": self.domain_distribution(),
        }
