"""
Router — Capability-based routing to any provider.

Routes tasks to providers based on capability matching, not identity.
Providers can be anything: models, services, sensors, humans, other Zoeae.
The router doesn't care what's on the other end. It cares about capability fit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Awaitable, Callable, Optional


class CapabilityDomain(Enum):
    """What kind of capability a provider offers."""
    REASONING = auto()
    GENERATION = auto()
    ANALYSIS = auto()
    SENSING = auto()
    ACTUATION = auto()
    STORAGE = auto()
    COMMUNICATION = auto()
    COMPUTATION = auto()
    CUSTOM = auto()


@dataclass
class Capability:
    """A specific capability with quality and cost characteristics."""
    domain: CapabilityDomain
    name: str
    quality: float = 0.5       # 0-1, how good at this
    cost_per_unit: float = 0.0 # resource cost per invocation
    latency_ms: float = 100.0  # expected latency
    metadata: dict = field(default_factory=dict)


@dataclass
class Provider:
    """Something that can fulfill tasks. Model-agnostic."""
    name: str
    capabilities: list[Capability] = field(default_factory=list)
    handler: Optional[Callable[..., Any]] = None
    async_handler: Optional[Callable[..., Awaitable[Any]]] = None
    healthy: bool = True
    last_used: float = 0.0
    success_rate: float = 1.0
    _total_calls: int = 0
    _total_failures: int = 0

    def record_success(self) -> None:
        self._total_calls += 1
        self.success_rate = 1.0 - (self._total_failures / max(self._total_calls, 1))
        self.last_used = time.time()

    def record_failure(self) -> None:
        self._total_calls += 1
        self._total_failures += 1
        self.success_rate = 1.0 - (self._total_failures / max(self._total_calls, 1))
        self.last_used = time.time()

    def supports(self, domain: CapabilityDomain, min_quality: float = 0.0) -> bool:
        return any(
            c.domain == domain and c.quality >= min_quality
            for c in self.capabilities
        )

    def best_capability(self, domain: CapabilityDomain) -> Optional[Capability]:
        matches = [c for c in self.capabilities if c.domain == domain]
        return max(matches, key=lambda c: c.quality) if matches else None


@dataclass
class RouteRequest:
    """A request to be routed to the best provider."""
    domain: CapabilityDomain
    payload: Any
    min_quality: float = 0.0
    max_cost: float = float("inf")
    max_latency_ms: float = float("inf")
    preferred_provider: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class RouteResult:
    """The result of routing a request."""
    provider: Provider
    capability: Capability
    response: Any = None
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None


class Router:
    """
    Routes tasks to providers based on capability, quality, cost, and health.

    Strategies:
    - best_quality: highest quality provider that meets constraints
    - lowest_cost: cheapest provider that meets quality threshold
    - fastest: lowest latency provider
    - round_robin: distribute load across eligible providers
    """

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}
        self._fallback_chain: list[str] = []
        self._route_count: int = 0

    def register(self, provider: Provider) -> None:
        """Register a provider."""
        self._providers[provider.name] = provider

    def unregister(self, name: str) -> None:
        self._providers.pop(name, None)

    def route(self, request: RouteRequest,
              strategy: str = "best_quality") -> Optional[RouteResult]:
        """Route a request to the best provider."""
        candidates = self._filter_candidates(request)
        if not candidates:
            # Try fallback chain
            for fb_name in self._fallback_chain:
                fb = self._providers.get(fb_name)
                if fb and fb.healthy and fb.supports(request.domain):
                    candidates = [(fb, fb.best_capability(request.domain))]
                    break

        if not candidates:
            return None

        # Apply strategy
        if strategy == "lowest_cost":
            candidates.sort(key=lambda x: x[1].cost_per_unit)
        elif strategy == "fastest":
            candidates.sort(key=lambda x: x[1].latency_ms)
        elif strategy == "round_robin":
            candidates.sort(key=lambda x: x[0].last_used)
        else:  # best_quality
            candidates.sort(key=lambda x: x[1].quality, reverse=True)

        provider, capability = candidates[0]

        # Execute
        start = time.time()
        try:
            response = None
            if provider.handler:
                response = provider.handler(request.payload)
            provider.record_success()
            latency = (time.time() - start) * 1000
            self._route_count += 1
            return RouteResult(
                provider=provider,
                capability=capability,
                response=response,
                latency_ms=latency,
            )
        except Exception as e:
            provider.record_failure()
            return RouteResult(
                provider=provider,
                capability=capability,
                success=False,
                error=str(e),
            )

    def _filter_candidates(
        self, request: RouteRequest
    ) -> list[tuple[Provider, Capability]]:
        """Filter providers by request constraints."""
        results = []
        for p in self._providers.values():
            if not p.healthy:
                continue
            if request.preferred_provider and p.name != request.preferred_provider:
                continue
            cap = p.best_capability(request.domain)
            if cap is None:
                continue
            if cap.quality < request.min_quality:
                continue
            if cap.cost_per_unit > request.max_cost:
                continue
            if cap.latency_ms > request.max_latency_ms:
                continue
            results.append((p, cap))
        return results

    def set_fallback_chain(self, names: list[str]) -> None:
        self._fallback_chain = names

    @property
    def providers(self) -> list[Provider]:
        return list(self._providers.values())

    @property
    def healthy_count(self) -> int:
        return sum(1 for p in self._providers.values() if p.healthy)

    @property
    def stats(self) -> dict:
        return {
            "total_providers": len(self._providers),
            "healthy": self.healthy_count,
            "total_routes": self._route_count,
        }
