"""
Accumulator — Self-optimizing fragment cache.
Explorer — Pareto frontier search.
DiversityAnalyzer — Brittleness detection via Shannon entropy.
"""

from __future__ import annotations
import hashlib, json, math, time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Fragment:
    key: str; content: Any; score: float = 0.0; uses: int = 0
    created: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    def use(self, delta: float = 0.1) -> None:
        self.uses += 1; self.score += delta * (1.0 - self.score)
        self.last_used = time.time()


class Accumulator:
    def __init__(self, cap: int = 1000, floor: float = 0.1) -> None:
        self._f: dict[str, Fragment] = {}; self.cap = cap; self.floor = floor

    def store(self, key: str, content: Any, score: float = 0.5) -> Fragment:
        if key in self._f: self._f[key].use(score * 0.2); return self._f[key]
        f = Fragment(key=key, content=content, score=score)
        self._f[key] = f; self._evict(); return f

    def retrieve(self, key: str) -> Optional[Fragment]:
        f = self._f.get(key)
        if f: f.use(0.05)
        return f

    def search(self, prefix: str = "", min_score: float = 0.0) -> list[Fragment]:
        return sorted([f for f in self._f.values()
                       if f.key.startswith(prefix) and f.score >= min_score],
                      key=lambda f: f.score, reverse=True)

    def prune(self) -> int:
        before = len(self._f)
        self._f = {k: f for k, f in self._f.items() if f.score >= self.floor}
        return before - len(self._f)

    def _evict(self) -> None:
        while len(self._f) > self.cap:
            worst = min(self._f.values(), key=lambda f: f.score)
            del self._f[worst.key]

    @property
    def size(self) -> int: return len(self._f)
    @property
    def stats(self) -> dict:
        if not self._f: return {"size": 0}
        scores = [f.score for f in self._f.values()]
        return {"size": len(self._f), "avg": sum(scores)/len(scores),
                "uses": sum(f.uses for f in self._f.values())}


@dataclass
class Frontier:
    config: dict; score: float = 0.0; evaluated: bool = False
    @property
    def hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.config, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]


class Explorer:
    def __init__(self, objectives: Optional[list[str]] = None) -> None:
        self.objectives = objectives or ["quality", "cost"]
        self._frontier: list[Frontier] = []; self._seen: set[str] = set()
        self._eval: Optional[Callable] = None

    def set_evaluator(self, fn: Callable) -> None: self._eval = fn

    def seed(self, configs: list[dict]) -> None:
        for c in configs:
            f = Frontier(config=c)
            if f.hash not in self._seen:
                self._frontier.append(f); self._seen.add(f.hash)

    def evaluate(self, f: Frontier) -> dict[str, float]:
        if not self._eval: return {o: 0.0 for o in self.objectives}
        scores = self._eval(f.config)
        f.score = sum(scores.values()) / max(len(scores), 1)
        f.evaluated = True; return scores

    def evaluate_all(self) -> list[Frontier]:
        todo = [f for f in self._frontier if not f.evaluated]
        for f in todo: self.evaluate(f)
        return todo

    def pareto_front(self) -> list[Frontier]:
        ev = sorted([f for f in self._frontier if f.evaluated],
                    key=lambda f: f.score, reverse=True)
        return ev[:max(1, len(ev)//5)] if ev else []

    def suggest(self, n: int = 5) -> list[dict]:
        out = []
        for f in self.pareto_front()[:n]:
            cfg = {k: v * (1.1 if len(out) % 2 == 0 else 0.9)
                   if isinstance(v, (int, float)) else v
                   for k, v in f.config.items()}
            h = hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]
            if h not in self._seen: out.append(cfg); self._seen.add(h)
        return out

    @property
    def explored_count(self) -> int: return len(self._seen)


class DiversityAnalyzer:
    def __init__(self) -> None: self._pop: dict[str, dict[str, int]] = {}

    def record(self, dim: str, val: str, n: int = 1) -> None:
        self._pop.setdefault(dim, {}); self._pop[dim][val] = self._pop[dim].get(val, 0) + n

    def entropy(self, dim: str) -> float:
        p = self._pop.get(dim, {}); t = sum(p.values())
        if not t: return 0.0
        return -sum((c/t) * math.log2(c/t) for c in p.values() if c > 0)

    def evenness(self, dim: str) -> float:
        h = self.entropy(dim)
        mx = math.log2(len(self._pop.get(dim, {}))) if len(self._pop.get(dim, {})) > 1 else 0
        return h / mx if mx else 0.0

    def brittleness(self, dim: str) -> float: return 1.0 - self.evenness(dim)

    def dominant(self, dim: str) -> Optional[tuple[str, float]]:
        p = self._pop.get(dim, {})
        if not p: return None
        t = sum(p.values()); top = max(p.items(), key=lambda x: x[1])
        return (top[0], top[1]/t)

    def report(self) -> dict:
        return {d: {"entropy": round(self.entropy(d), 4),
                     "evenness": round(self.evenness(d), 4),
                     "brittleness": round(self.brittleness(d), 4),
                     "dominant": self.dominant(d)}
                for d in self._pop}
