"""
Muscle — Raw computation power. Abdominal flexor muscles.

When the organism needs to do heavy work — parallel processing,
batch operations, map-reduce over large datasets — it flexes.
The tail-flip escape response uses the same muscles: fast, powerful,
exhausting.

Uses ThreadPoolExecutor internally. The muscle knows the machine's
actual compute capacity (CPU cores, available memory). It tracks
strain (current load) and fatigue (overloaded state).

    from zoeae.muscle import Muscle

    muscle = Muscle()
    results = muscle.flex([task1, task2, task3])   # parallel execution
    print(muscle.strain())                         # 0.0 - 1.0
    print(muscle.fatigued)                         # True if overloaded

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ── CAPACITY DETECTION ──

def _detect_cpu_cores() -> int:
    """Detect available CPU cores."""
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def _detect_memory_bytes() -> int:
    """Best-effort memory detection. Returns 0 if unknown."""
    # Try psutil-free approaches
    try:
        # Linux
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    return int(parts[1]) * 1024  # kB -> bytes
    except (FileNotFoundError, OSError):
        pass

    try:
        # Windows via ctypes
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
        return mem.ullTotalPhys
    except Exception:
        pass

    return 0


# ── TASK RESULT ──

@dataclass
class FlexResult:
    """The outcome of a muscle flex (parallel task execution)."""
    results: list[Any] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)
    total_tasks: int = 0
    completed: int = 0
    failed: int = 0
    duration_s: float = 0.0

    @property
    def success(self) -> bool:
        return self.failed == 0

    @property
    def success_rate(self) -> float:
        return self.completed / max(self.total_tasks, 1)


# ── MUSCLE ──

class Muscle:
    """The abdominal flexor muscles. Raw parallel computation.

    Manages a thread pool scaled to the machine's CPU cores.
    Tracks strain (current utilization) and fatigue (whether
    the organism is overloaded). Thread-safe.
    """

    def __init__(self, max_workers: Optional[int] = None,
                 fatigue_threshold: float = 0.85) -> None:
        self._cpu_cores = _detect_cpu_cores()
        self._memory_bytes = _detect_memory_bytes()
        self._max_workers = max_workers or min(32, (self._cpu_cores + 4))
        self._fatigue_threshold = fatigue_threshold

        self._pool = ThreadPoolExecutor(max_workers=self._max_workers)
        self._lock = threading.Lock()
        self._active_tasks: int = 0
        self._total_flexed: int = 0
        self._total_completed: int = 0
        self._total_failed: int = 0
        self._total_flex_calls: int = 0
        self._t0 = time.time()

    # ── PRIMARY INTERFACE ──

    def flex(self, tasks: list[Callable], timeout: Optional[float] = None) -> FlexResult:
        """Execute tasks in parallel. Returns when all complete.

        Each task is a callable (no arguments). If a task raises,
        its error is captured in FlexResult.errors but other tasks
        continue.

        Thread pool size is bounded by the machine's CPU cores.
        """
        t0 = time.time()
        self._total_flex_calls += 1

        results: list[Any] = [None] * len(tasks)
        errors: list[tuple[int, str]] = []
        futures: list[tuple[int, Future]] = []

        with self._lock:
            self._active_tasks += len(tasks)
            self._total_flexed += len(tasks)

        try:
            for i, task in enumerate(tasks):
                future = self._pool.submit(task)
                futures.append((i, future))

            # Collect results
            completed = 0
            failed = 0
            for i, future in futures:
                try:
                    result = future.result(timeout=timeout)
                    results[i] = result
                    completed += 1
                except Exception as e:
                    errors.append((i, f"{type(e).__name__}: {e}"))
                    failed += 1

        finally:
            with self._lock:
                self._active_tasks -= len(tasks)
                self._total_completed += completed
                self._total_failed += failed

        return FlexResult(
            results=results,
            errors=errors,
            total_tasks=len(tasks),
            completed=completed,
            failed=failed,
            duration_s=time.time() - t0,
        )

    def flex_map(self, fn: Callable, items: list[Any],
                 timeout: Optional[float] = None) -> FlexResult:
        """Map a function over items in parallel. Convenience wrapper.

            results = muscle.flex_map(process, data_chunks)
        """
        tasks = [lambda item=item: fn(item) for item in items]
        return self.flex(tasks, timeout=timeout)

    def submit(self, task: Callable) -> Future:
        """Submit a single task to the pool. Returns a Future.

        For fine-grained control when you don't want to wait
        for all tasks to complete.
        """
        with self._lock:
            self._active_tasks += 1
            self._total_flexed += 1

        future = self._pool.submit(task)

        def _on_done(f: Future) -> None:
            with self._lock:
                self._active_tasks -= 1
                if f.exception() is not None:
                    self._total_failed += 1
                else:
                    self._total_completed += 1

        future.add_done_callback(_on_done)
        return future

    # ── STRAIN / FATIGUE ──

    def strain(self) -> float:
        """Current load as a fraction of capacity. 0.0 = idle, 1.0 = maxed."""
        with self._lock:
            active = self._active_tasks
        return min(1.0, active / max(self._max_workers, 1))

    @property
    def fatigued(self) -> bool:
        """True if the muscle is overloaded (strain exceeds threshold)."""
        return self.strain() >= self._fatigue_threshold

    # ── CAPACITY INFO ──

    @property
    def capacity(self) -> dict:
        """The machine's compute capacity as the muscle sees it."""
        mem_gb = self._memory_bytes / (1024 ** 3) if self._memory_bytes else 0.0
        return {
            "cpu_cores": self._cpu_cores,
            "memory_bytes": self._memory_bytes,
            "memory_gb": round(mem_gb, 2),
            "max_workers": self._max_workers,
        }

    # ── LIFECYCLE ──

    def rest(self) -> None:
        """Shut down the thread pool gracefully. No more tasks after this.

        A new pool can be created by calling recover().
        """
        self._pool.shutdown(wait=True)

    def recover(self) -> None:
        """Create a fresh thread pool after rest(). The muscle regenerates."""
        self._pool = ThreadPoolExecutor(max_workers=self._max_workers)

    # ── STATS ──

    @property
    def stats(self) -> dict:
        return {
            "cpu_cores": self._cpu_cores,
            "max_workers": self._max_workers,
            "active_tasks": self._active_tasks,
            "strain": round(self.strain(), 3),
            "fatigued": self.fatigued,
            "total_flex_calls": self._total_flex_calls,
            "total_tasks_submitted": self._total_flexed,
            "total_completed": self._total_completed,
            "total_failed": self._total_failed,
            "success_rate": round(
                self._total_completed / max(self._total_flexed, 1), 3
            ),
            "uptime_s": round(time.time() - self._t0, 1),
        }
