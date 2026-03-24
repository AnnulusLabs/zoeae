"""
Pipeline — Typed async stages and DAG execution.

Every complex system is a DAG. Manufacturing. Logistics. Drug discovery.
The executor doesn't know or care what the nodes do. It knows dependencies,
parallelism, and failure modes.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Awaitable, Callable, Optional


class StageStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass
class Stage:
    """A single execution stage in a pipeline."""
    name: str
    handler: Optional[Callable[..., Any]] = None
    async_handler: Optional[Callable[..., Awaitable[Any]]] = None
    depends_on: list[str] = field(default_factory=list)
    timeout_s: float = 300.0
    retries: int = 0
    status: StageStatus = StageStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    metadata: dict = field(default_factory=dict)

    def reset(self) -> None:
        self.status = StageStatus.PENDING
        self.result = None
        self.error = None
        self.duration_ms = 0.0


@dataclass
class DAG:
    """Directed acyclic graph of stages."""
    name: str = "pipeline"
    stages: dict[str, Stage] = field(default_factory=dict)

    def add(self, stage: Stage) -> "DAG":
        self.stages[stage.name] = stage
        return self

    def remove(self, name: str) -> None:
        self.stages.pop(name, None)
        for s in self.stages.values():
            s.depends_on = [d for d in s.depends_on if d != name]

    def roots(self) -> list[Stage]:
        """Stages with no dependencies."""
        return [s for s in self.stages.values() if not s.depends_on]

    def leaves(self) -> list[Stage]:
        """Stages nothing depends on."""
        depended_on = set()
        for s in self.stages.values():
            depended_on.update(s.depends_on)
        return [s for s in self.stages.values() if s.name not in depended_on]

    def ready(self) -> list[Stage]:
        """Stages whose dependencies are all completed."""
        return [
            s for s in self.stages.values()
            if s.status == StageStatus.PENDING
            and all(
                self.stages[dep].status == StageStatus.COMPLETED
                for dep in s.depends_on
                if dep in self.stages
            )
        ]

    def is_complete(self) -> bool:
        return all(
            s.status in (StageStatus.COMPLETED, StageStatus.SKIPPED, StageStatus.FAILED)
            for s in self.stages.values()
        )

    def validate(self) -> list[str]:
        """Check for cycles and missing dependencies."""
        errors = []
        for s in self.stages.values():
            for dep in s.depends_on:
                if dep not in self.stages:
                    errors.append(f"{s.name} depends on missing stage '{dep}'")
        # Cycle detection via topological sort
        visited: set[str] = set()
        path: set[str] = set()

        def visit(name: str) -> bool:
            if name in path:
                return True  # cycle
            if name in visited:
                return False
            path.add(name)
            stage = self.stages.get(name)
            if stage:
                for dep in stage.depends_on:
                    if visit(dep):
                        errors.append(f"Cycle detected involving '{name}'")
                        return True
            path.discard(name)
            visited.add(name)
            return False

        for name in self.stages:
            visit(name)
        return errors

    def reset(self) -> None:
        for s in self.stages.values():
            s.reset()

    @property
    def stats(self) -> dict:
        statuses = {}
        for s in self.stages.values():
            key = s.status.name
            statuses[key] = statuses.get(key, 0) + 1
        return {
            "total": len(self.stages),
            "statuses": statuses,
            "complete": self.is_complete(),
            "total_duration_ms": sum(s.duration_ms for s in self.stages.values()),
        }


class Pipeline:
    """
    Executes a DAG of stages with dependency resolution.

    Supports both sync and async execution, retries, timeouts,
    and result propagation between stages.
    """

    def __init__(self, dag: DAG) -> None:
        self.dag = dag
        self._results: dict[str, Any] = {}
        self._on_stage_complete: Optional[Callable[[Stage], None]] = None

    def on_complete(self, callback: Callable[[Stage], None]) -> None:
        self._on_stage_complete = callback

    def execute_sync(self, context: Optional[dict] = None) -> dict[str, Any]:
        """Execute DAG synchronously (stages run sequentially by dependency order)."""
        errors = self.dag.validate()
        if errors:
            raise ValueError(f"DAG validation failed: {errors}")

        ctx = context or {}
        while not self.dag.is_complete():
            ready = self.dag.ready()
            if not ready:
                # Deadlock — mark remaining as failed
                for s in self.dag.stages.values():
                    if s.status == StageStatus.PENDING:
                        s.status = StageStatus.FAILED
                        s.error = "Deadlocked — dependencies never completed"
                break

            for stage in ready:
                self._execute_stage(stage, ctx)

        return self._results

    def _execute_stage(self, stage: Stage, ctx: dict) -> None:
        stage.status = StageStatus.RUNNING
        attempts = 0
        while attempts <= stage.retries:
            start = time.time()
            try:
                if stage.handler:
                    stage.result = stage.handler(ctx, self._results)
                else:
                    stage.result = None
                stage.status = StageStatus.COMPLETED
                stage.duration_ms = (time.time() - start) * 1000
                self._results[stage.name] = stage.result
                if self._on_stage_complete:
                    self._on_stage_complete(stage)
                return
            except Exception as e:
                attempts += 1
                stage.error = str(e)
                stage.duration_ms = (time.time() - start) * 1000

        stage.status = StageStatus.FAILED

    async def execute_async(self, context: Optional[dict] = None) -> dict[str, Any]:
        """Execute DAG asynchronously (parallel where dependencies allow)."""
        errors = self.dag.validate()
        if errors:
            raise ValueError(f"DAG validation failed: {errors}")

        ctx = context or {}
        while not self.dag.is_complete():
            ready = self.dag.ready()
            if not ready:
                for s in self.dag.stages.values():
                    if s.status == StageStatus.PENDING:
                        s.status = StageStatus.FAILED
                        s.error = "Deadlocked"
                break

            tasks = [self._execute_stage_async(s, ctx) for s in ready]
            await asyncio.gather(*tasks)

        return self._results

    async def _execute_stage_async(self, stage: Stage, ctx: dict) -> None:
        stage.status = StageStatus.RUNNING
        start = time.time()
        try:
            if stage.async_handler:
                stage.result = await asyncio.wait_for(
                    stage.async_handler(ctx, self._results),
                    timeout=stage.timeout_s,
                )
            elif stage.handler:
                stage.result = stage.handler(ctx, self._results)
            else:
                stage.result = None
            stage.status = StageStatus.COMPLETED
            stage.duration_ms = (time.time() - start) * 1000
            self._results[stage.name] = stage.result
            if self._on_stage_complete:
                self._on_stage_complete(stage)
        except Exception as e:
            stage.status = StageStatus.FAILED
            stage.error = str(e)
            stage.duration_ms = (time.time() - start) * 1000

    @property
    def results(self) -> dict[str, Any]:
        return dict(self._results)
