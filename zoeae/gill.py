"""
Gill — Resource management organ.

Respiratory system. Manages token/compute budgets. Knows when to
breathe deep (expensive model) vs shallow (cheap model). Tracks
cumulative usage, warns when budget is low, and suggests model
downgrades to conserve resources.

Budget levels mirror the compiler tiers:
    NUCLEUS   — minimal, conserve everything
    CELL      — moderate, balanced usage
    ORGANISM  — full operational budget
    ECOSYSTEM — unlimited, spend freely

    gill = Gill(budget_tokens=100_000)
    decision = gill.breathe("summarize these notes", estimated_tokens=500)
    if decision.approved:
        # use decision.model_tier to pick backend
        result = brain.think(prompt, ...)
        gill.exhale(actual_tokens)

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from .compiler import Tier


# ── BUDGET LEVELS ──

class BudgetLevel(IntEnum):
    """Maps to compiler tiers. Controls spending behavior."""
    NUCLEUS   = 0  # minimal — only critical tasks approved
    CELL      = 1  # moderate — balanced model selection
    ORGANISM  = 2  # full — most tasks approved at best tier
    ECOSYSTEM = 3  # unlimited — no restrictions


# ── MODEL TIERS ──

MODEL_TIERS = {
    "cheap":     {"examples": ["hermes3:8b", "qwen2.5:7b", "phi3:3.8b"],
                  "cost_weight": 0.1},
    "balanced":  {"examples": ["mistral:7b", "deepseek-r1:14b", "qwen2.5:32b"],
                  "cost_weight": 0.5},
    "expensive": {"examples": ["deepseek-r1:32b", "deepseek-r1:70b",
                                "claude-sonnet-4-6"],
                  "cost_weight": 1.0},
}


# ── BUDGET DECISION ──

@dataclass
class BudgetDecision:
    """The gill's recommendation for a task."""
    model_tier: str          # "cheap", "balanced", "expensive"
    max_tokens: int          # recommended max output tokens
    approved: bool           # whether the task fits within budget
    reason: str = ""         # human-readable explanation
    suggestion: str = ""     # model suggestion, e.g. "use hermes3:8b for this"
    budget_remaining: float = 0.0
    budget_utilization: float = 0.0


# ── USAGE RECORD ──

@dataclass
class BreathRecord:
    """One breathing cycle: a task that consumed tokens."""
    task: str
    estimated: int
    actual: int = 0
    tier: str = "balanced"
    timestamp: float = field(default_factory=time.time)
    duration_s: float = 0.0


# ── GILL ──

class Gill:
    """Resource management organ. Tracks token budgets and recommends
    model tiers based on remaining resources and task complexity.

    Breathing metaphor:
        breathe() = inhale, assess the task, decide how much to spend
        exhale()  = record what was actually consumed
    """

    def __init__(self, budget_tokens: int = 100_000,
                 level: BudgetLevel = BudgetLevel.ORGANISM) -> None:
        self._budget_total = budget_tokens
        self._budget_used = 0
        self._level = level
        self._history: list[BreathRecord] = []
        self._warnings: list[str] = []
        self._t0 = time.time()

    @property
    def level(self) -> BudgetLevel:
        return self._level

    @level.setter
    def level(self, value: BudgetLevel) -> None:
        self._level = value

    # ── PRIMARY INTERFACE ──

    def breathe(self, task_description: str,
                estimated_tokens: int) -> BudgetDecision:
        """Assess a task and decide: which model tier, how many tokens,
        and whether to approve it at all."""
        remaining = self._budget_total - self._budget_used
        utilization = self._budget_used / max(self._budget_total, 1)

        # Ecosystem level = unlimited, always approve at best tier
        if self._level == BudgetLevel.ECOSYSTEM:
            return BudgetDecision(
                model_tier="expensive",
                max_tokens=estimated_tokens,
                approved=True,
                reason="Ecosystem budget — no limits",
                budget_remaining=float(remaining),
                budget_utilization=utilization,
            )

        # Check if we can afford it at all
        if estimated_tokens > remaining and self._level != BudgetLevel.ECOSYSTEM:
            # Still approve at cheap tier if we have *some* budget
            if remaining > 0:
                tier = "cheap"
                capped = min(estimated_tokens, int(remaining * 0.8))
                return BudgetDecision(
                    model_tier=tier,
                    max_tokens=max(capped, 64),
                    approved=True,
                    reason="Budget low — downgrading to cheap tier",
                    suggestion=self._suggest_model(tier),
                    budget_remaining=float(remaining),
                    budget_utilization=utilization,
                )
            else:
                return BudgetDecision(
                    model_tier="cheap",
                    max_tokens=0,
                    approved=False,
                    reason="Budget exhausted",
                    budget_remaining=0.0,
                    budget_utilization=utilization,
                )

        # Select tier based on budget level and utilization
        tier = self._select_tier(estimated_tokens, remaining, utilization)

        # Generate warning if budget is getting low
        if utilization > 0.8:
            warn = (f"Budget {utilization:.0%} used — "
                    f"{remaining:,} tokens remaining")
            self._warnings.append(warn)
        elif utilization > 0.6 and self._level <= BudgetLevel.CELL:
            warn = f"Moderate usage at {self._level.name} level — conserving"
            self._warnings.append(warn)

        return BudgetDecision(
            model_tier=tier,
            max_tokens=self._cap_tokens(estimated_tokens, tier),
            approved=True,
            reason=f"{self._level.name} budget, {utilization:.0%} used",
            suggestion=self._suggest_model(tier),
            budget_remaining=float(remaining),
            budget_utilization=utilization,
        )

    def exhale(self, actual_tokens_used: int,
               task: str = "", duration_s: float = 0.0) -> None:
        """Record actual token usage after a task completes."""
        self._budget_used += actual_tokens_used

        # Find the last breathe record and update it, or create new
        record = BreathRecord(
            task=task or f"task_{len(self._history)}",
            estimated=actual_tokens_used,
            actual=actual_tokens_used,
            duration_s=duration_s,
        )
        self._history.append(record)

    def remaining(self) -> dict:
        """Current budget status."""
        total = self._budget_total
        used = self._budget_used
        rem = max(0, total - used)
        return {
            "total": total,
            "used": used,
            "remaining": rem,
            "utilization": used / max(total, 1),
            "level": self._level.name,
            "warnings": list(self._warnings[-5:]),
            "tasks_completed": len(self._history),
        }

    # ── TIER SELECTION ──

    def _select_tier(self, estimated: int, remaining: int,
                     utilization: float) -> str:
        """Pick model tier based on budget state."""
        if self._level == BudgetLevel.NUCLEUS:
            # Always cheap unless task is tiny
            if estimated < 100:
                return "balanced"
            return "cheap"

        elif self._level == BudgetLevel.CELL:
            if utilization > 0.7:
                return "cheap"
            elif utilization > 0.4:
                return "balanced"
            else:
                return "balanced"

        elif self._level == BudgetLevel.ORGANISM:
            if utilization > 0.85:
                return "cheap"
            elif utilization > 0.6:
                return "balanced"
            else:
                return "expensive"

        # ECOSYSTEM handled above, but safety fallback
        return "expensive"

    def _cap_tokens(self, requested: int, tier: str) -> int:
        """Cap max tokens based on tier."""
        caps = {
            "cheap": min(requested, 1024),
            "balanced": min(requested, 4096),
            "expensive": min(requested, 16384),
        }
        return caps.get(tier, requested)

    @staticmethod
    def _suggest_model(tier: str) -> str:
        """Suggest a specific model for the tier."""
        info = MODEL_TIERS.get(tier, {})
        examples = info.get("examples", [])
        if not examples:
            return ""
        # Suggest first (cheapest/most common) model in the tier
        model = examples[0]
        if tier == "cheap":
            return f"use {model} for this, save deepseek-r1 for the hard stuff"
        elif tier == "balanced":
            return f"use {model} — good balance of quality and cost"
        else:
            return f"use {model} — full power for this task"

    # ── BUDGET MANAGEMENT ──

    def refill(self, tokens: int) -> None:
        """Add tokens to the budget."""
        self._budget_total += tokens
        self._warnings.clear()

    def reset(self) -> None:
        """Reset budget to full. History preserved."""
        self._budget_used = 0
        self._warnings.clear()

    def set_budget(self, total: int) -> None:
        """Set a new total budget."""
        self._budget_total = total
        self._warnings.clear()

    # ── ANALYTICS ──

    def avg_tokens_per_task(self) -> float:
        """Average actual tokens per completed task."""
        if not self._history:
            return 0.0
        return sum(r.actual for r in self._history) / len(self._history)

    def burn_rate(self) -> float:
        """Tokens consumed per second of uptime."""
        elapsed = time.time() - self._t0
        if elapsed <= 0:
            return 0.0
        return self._budget_used / elapsed

    def estimated_remaining_tasks(self) -> int:
        """Estimate how many more tasks we can afford."""
        avg = self.avg_tokens_per_task()
        if avg <= 0:
            return -1  # unknown
        remaining = max(0, self._budget_total - self._budget_used)
        return int(remaining / avg)

    @property
    def stats(self) -> dict:
        return {
            "budget": self.remaining(),
            "avg_tokens_per_task": round(self.avg_tokens_per_task(), 1),
            "burn_rate": round(self.burn_rate(), 2),
            "est_remaining_tasks": self.estimated_remaining_tasks(),
            "uptime_s": round(time.time() - self._t0, 1),
            "total_tasks": len(self._history),
        }
