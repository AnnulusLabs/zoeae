"""
Blood — Shared state transport. Hemolymph (open circulatory system).

Crustaceans have open circulation — hemolymph bathes all organs
directly. There is no separation between arterial and venous. Every
organ can read from and write to the shared state. The blood carries
oxygen (from gill), nutrients (from gut), hormones (from genome),
and signals (from nerve) to every organ.

Thread-safe. Copy-on-read to prevent mutation through references.

    from zoeae.blood import Blood

    blood = Blood()
    blood.pump("cpu_load", 0.73)
    blood.pump("active_threats", ["rate_limit", "error_spike"])
    load = blood.draw("cpu_load")       # -> 0.73
    state = blood.flow()                # -> full snapshot

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ── HEMOLYMPH CELL ──

@dataclass
class HemolymphCell:
    """A single value in the hemolymph stream.

    Tracks provenance: who pumped it, when, how many times
    it has been drawn (read).
    """
    key: str
    value: Any
    pumped_by: str = "unknown"
    pumped_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    draw_count: int = 0
    pump_count: int = 1
    version: int = 1

    def update(self, value: Any, pumped_by: str = "unknown") -> None:
        self.value = value
        self.pumped_by = pumped_by
        self.updated_at = time.time()
        self.pump_count += 1
        self.version += 1

    def drawn(self) -> None:
        self.draw_count += 1


# ── BLOOD ──

class Blood:
    """The hemolymph. Open circulatory shared-state transport.

    Thread-safe key-value store that every organ can pump to
    and draw from. Values are deep-copied on read to prevent
    accidental mutation. Supports namespacing by convention
    (e.g., "gut:facts_stored", "gill:budget_remaining").
    """

    def __init__(self) -> None:
        self._cells: dict[str, HemolymphCell] = {}
        self._lock = threading.RLock()
        self._total_pumps: int = 0
        self._total_draws: int = 0
        self._history: list[tuple[float, str, str]] = []  # (time, action, key)
        self._max_history: int = 5000
        self._t0 = time.time()

    # ── PRIMARY INTERFACE ──

    def pump(self, key: str, value: Any, source: str = "unknown") -> None:
        """Push a value into the hemolymph.

        If the key already exists, the cell is updated in place
        (version incremented, timestamp refreshed). Otherwise
        a new cell is created.
        """
        with self._lock:
            if key in self._cells:
                self._cells[key].update(value, pumped_by=source)
            else:
                self._cells[key] = HemolymphCell(
                    key=key,
                    value=value,
                    pumped_by=source,
                )
            self._total_pumps += 1
            self._record("pump", key)

    def draw(self, key: str, default: Any = None) -> Any:
        """Read a value from the hemolymph.

        Returns a deep copy to prevent mutation through references.
        Returns default if the key does not exist.
        """
        with self._lock:
            cell = self._cells.get(key)
            if cell is None:
                return default
            cell.drawn()
            self._total_draws += 1
            self._record("draw", key)
            try:
                return copy.deepcopy(cell.value)
            except (TypeError, copy.Error):
                # Some values can't be deep-copied (e.g., locks, files)
                return cell.value

    def flow(self) -> dict[str, Any]:
        """Return a full state snapshot. Deep-copied.

        This is the organism's complete hemolymph state at a
        point in time.
        """
        with self._lock:
            snapshot = {}
            for key, cell in self._cells.items():
                try:
                    snapshot[key] = copy.deepcopy(cell.value)
                except (TypeError, copy.Error):
                    snapshot[key] = cell.value
            self._record("flow", "*")
            return snapshot

    # ── BULK OPERATIONS ──

    def pump_many(self, values: dict[str, Any], source: str = "unknown") -> None:
        """Push multiple values at once. Atomic."""
        with self._lock:
            for key, value in values.items():
                if key in self._cells:
                    self._cells[key].update(value, pumped_by=source)
                else:
                    self._cells[key] = HemolymphCell(
                        key=key,
                        value=value,
                        pumped_by=source,
                    )
                self._total_pumps += 1
            self._record("pump_many", f"{len(values)} keys")

    def draw_many(self, keys: list[str]) -> dict[str, Any]:
        """Read multiple values at once. Missing keys are omitted."""
        with self._lock:
            result = {}
            for key in keys:
                cell = self._cells.get(key)
                if cell is not None:
                    cell.drawn()
                    self._total_draws += 1
                    try:
                        result[key] = copy.deepcopy(cell.value)
                    except (TypeError, copy.Error):
                        result[key] = cell.value
            return result

    # ── QUERIES ──

    def contains(self, key: str) -> bool:
        """Check if a key exists in the hemolymph."""
        with self._lock:
            return key in self._cells

    def keys(self, prefix: str = "") -> list[str]:
        """List all keys, optionally filtered by prefix."""
        with self._lock:
            if prefix:
                return [k for k in self._cells if k.startswith(prefix)]
            return list(self._cells.keys())

    def cell_info(self, key: str) -> Optional[dict]:
        """Get metadata about a hemolymph cell (without deep-copying the value)."""
        with self._lock:
            cell = self._cells.get(key)
            if cell is None:
                return None
            return {
                "key": cell.key,
                "pumped_by": cell.pumped_by,
                "pumped_at": cell.pumped_at,
                "updated_at": cell.updated_at,
                "draw_count": cell.draw_count,
                "pump_count": cell.pump_count,
                "version": cell.version,
                "value_type": type(cell.value).__name__,
            }

    def remove(self, key: str) -> bool:
        """Remove a key from the hemolymph. Returns True if it existed."""
        with self._lock:
            if key in self._cells:
                del self._cells[key]
                self._record("remove", key)
                return True
            return False

    def clear(self) -> int:
        """Flush all hemolymph. Returns number of cells cleared."""
        with self._lock:
            count = len(self._cells)
            self._cells.clear()
            self._record("clear", f"{count} cells")
            return count

    # ── INTERNALS ──

    def _record(self, action: str, key: str) -> None:
        """Record an operation in the history buffer."""
        self._history.append((time.time(), action, key))
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    # ── STATS ──

    @property
    def stats(self) -> dict:
        with self._lock:
            cell_count = len(self._cells)
            total_versions = sum(c.version for c in self._cells.values())
            most_drawn = None
            if self._cells:
                top = max(self._cells.values(), key=lambda c: c.draw_count)
                most_drawn = {"key": top.key, "draws": top.draw_count}

        return {
            "cells": cell_count,
            "total_pumps": self._total_pumps,
            "total_draws": self._total_draws,
            "total_versions": total_versions,
            "most_drawn": most_drawn,
            "history_size": len(self._history),
            "uptime_s": round(time.time() - self._t0, 1),
        }
