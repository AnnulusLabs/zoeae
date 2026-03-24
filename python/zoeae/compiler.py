"""
Compiler — Resource-budget-aware assembly.

The compiler doesn't compile code. It compiles context: selecting, deduplicating,
and compacting relevant information within a resource budget. The budget can be
tokens, energy, time, money, bandwidth — any finite resource.

Tiers control compression level:
    NUCLEUS   — minimal stress, maximum compression, core identity only
    CELL      — domain-specific nodes added
    ORGANISM  — full operational context
    ECOSYSTEM — everything, no compression
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional


class Tier(IntEnum):
    NUCLEUS = 0
    CELL = 1
    ORGANISM = 2
    ECOSYSTEM = 3


@dataclass
class Budget:
    """Resource budget for compilation."""
    total: float
    used: float = 0.0
    unit: str = "units"

    @property
    def remaining(self) -> float:
        return max(0.0, self.total - self.used)

    @property
    def utilization(self) -> float:
        return self.used / max(self.total, 1e-9)

    def consume(self, amount: float) -> bool:
        """Consume budget. Returns False if insufficient."""
        if amount > self.remaining:
            return False
        self.used += amount
        return True

    def reset(self) -> None:
        self.used = 0.0


@dataclass
class Skill:
    """A unit of knowledge the compiler can inject into context."""
    name: str
    content: str
    cost: float          # resource cost to include
    priority: float      # 0-1, how important
    domain: str = ""
    hash: str = ""

    def __post_init__(self):
        if not self.hash:
            self.hash = hashlib.sha256(self.content.encode()).hexdigest()[:12]


@dataclass
class CompiledContext:
    """The result of compilation."""
    tier: Tier
    segments: list[str]
    skills_included: list[str]
    skills_excluded: list[str]
    budget_used: float
    budget_total: float
    dedup_savings: float = 0.0

    @property
    def text(self) -> str:
        return "\n\n".join(self.segments)


class Compiler:
    """
    Assembles context from genome, skills, and history within a budget.

    The key insight from ETH Zurich arxiv:2602.11988v1: verbatim skill injection
    decreases performance 3% and increases cost 20%. The compiler selects,
    deduplicates, and compacts — it never dumps everything.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._history: list[str] = []
        self._dedup_hashes: set[str] = set()

    def register_skill(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def register_skills(self, skills: list[Skill]) -> None:
        for s in skills:
            self.register_skill(s)

    def add_history(self, entry: str) -> None:
        self._history.append(entry)

    def compile(self, budget: Budget, tier: Tier = Tier.NUCLEUS,
                required_domains: Optional[list[str]] = None,
                genome_nucleus: Optional[str] = None) -> CompiledContext:
        """Compile context within budget at the given tier."""
        segments: list[str] = []
        included: list[str] = []
        excluded: list[str] = []
        dedup_saved: float = 0.0

        # Always include nucleus identity if available
        if genome_nucleus:
            cost = len(genome_nucleus) * 0.001  # approximate
            if budget.consume(cost):
                segments.append(genome_nucleus)

        # Select skills by tier
        candidates = self._rank_skills(tier, required_domains)

        for skill in candidates:
            # Dedup check
            if skill.hash in self._dedup_hashes:
                dedup_saved += skill.cost
                excluded.append(f"{skill.name} (dedup)")
                continue

            if budget.consume(skill.cost):
                segments.append(f"[{skill.name}]\n{skill.content}")
                included.append(skill.name)
                self._dedup_hashes.add(skill.hash)
            else:
                excluded.append(f"{skill.name} (budget)")

        # History — most recent first, within remaining budget
        if tier >= Tier.ORGANISM:
            for entry in reversed(self._history[-100:]):
                cost = len(entry) * 0.001
                if budget.consume(cost):
                    segments.append(entry)
                else:
                    break

        return CompiledContext(
            tier=tier,
            segments=segments,
            skills_included=included,
            skills_excluded=excluded,
            budget_used=budget.used,
            budget_total=budget.total,
            dedup_savings=dedup_saved,
        )

    def _rank_skills(self, tier: Tier,
                     required_domains: Optional[list[str]]) -> list[Skill]:
        """Rank skills by priority, filtered by tier."""
        candidates = list(self._skills.values())

        if tier == Tier.NUCLEUS:
            candidates = [s for s in candidates if s.priority >= 0.9]
        elif tier == Tier.CELL:
            candidates = [s for s in candidates if s.priority >= 0.5]
            if required_domains:
                domain_skills = [s for s in candidates if s.domain in required_domains]
                other_skills = [s for s in candidates if s.domain not in required_domains]
                candidates = domain_skills + other_skills
        elif tier == Tier.ORGANISM:
            candidates = [s for s in candidates if s.priority >= 0.1]

        candidates.sort(key=lambda s: s.priority, reverse=True)
        return candidates

    def compact(self, text: str, target_ratio: float = 0.5) -> str:
        """Compact text to target ratio. Preserves structure, removes redundancy."""
        lines = text.split("\n")
        if len(lines) <= 3:
            return text
        target_lines = max(3, int(len(lines) * target_ratio))
        # Keep first line, last line, and evenly spaced middle lines
        if target_lines >= len(lines):
            return text
        indices = {0, len(lines) - 1}
        step = len(lines) / target_lines
        for i in range(target_lines):
            indices.add(int(i * step))
        selected = [lines[i] for i in sorted(indices) if i < len(lines)]
        return "\n".join(selected)

    def reset_dedup(self) -> None:
        self._dedup_hashes.clear()

    @property
    def skill_count(self) -> int:
        return len(self._skills)

    @property
    def history_depth(self) -> int:
        return len(self._history)
