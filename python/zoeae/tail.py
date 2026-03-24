"""
Tail — Emergency response organ (telson fan).

Escape response — the organism can snap backward to safety.
Checkpoint state, rollback on failure, emergency shutdown.
The crustacean tail-flip: fastest escape in the ocean.

    eco = Ecosystem("taos")
    m = Maker.hatch(eco)
    tail = Tail()

    # safe experimentation
    result = tail.flick(m, lambda: m.see("dangerous experiment"))

    # manual checkpoint/rollback
    cp_id = tail.checkpoint(m)
    # ... risky operations ...
    m = tail.rollback(cp_id, eco)

    # emergency shutdown
    tail.snap("reactor pressure exceeded limit")

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import shoes
from .ecosystem import Ecosystem, Maker


# ── EVENTS ──

@dataclass
class TailEvent:
    """Audit trail entry for tail operations."""
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""       # checkpoint | rollback | snap | flick
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "t": self.timestamp,
            "type": self.event_type,
            "details": self.details,
        }


# ── TAIL ──

class Tail:
    """The emergency response organ. Checkpoints, rollbacks, escape.

    Keeps a ring buffer of recent state snapshots (from shoes.pack)
    in memory for fast rollback. No disk IO on the hot path.
    """

    def __init__(self, max_checkpoints: int = 5) -> None:
        self._ring: deque[tuple[str, dict]] = deque(maxlen=max_checkpoints)
        self._events: list[TailEvent] = []
        self._snap_count: int = 0

    # ── CHECKPOINT ──

    def checkpoint(self, maker: Maker) -> str:
        """Save the organism's current state. Returns a checkpoint ID.

        Uses shoes.pack internally — the capsule is a dict in memory.
        Fast. No disk writes.
        """
        capsule = shoes.pack(maker)
        cp_id = self._make_id(capsule)
        self._ring.append((cp_id, capsule))
        self._record("checkpoint", {
            "id": cp_id,
            "instar": capsule.get("instar", "?"),
            "hash": capsule.get("_hash", "?"),
        })
        return cp_id

    # ── ROLLBACK ──

    def rollback(self, checkpoint_id: str, eco: Ecosystem) -> Maker:
        """Restore the organism from a checkpoint.

        Uses shoes.unpack to rebuild a live Maker from the stored capsule.
        The checkpoint remains in the ring buffer (can be reused).
        """
        capsule = self._find(checkpoint_id)
        if capsule is None:
            raise KeyError(
                f"Checkpoint {checkpoint_id!r} not found. "
                f"Available: {[cid for cid, _ in self._ring]}"
            )
        maker = shoes.unpack(capsule, eco)
        self._record("rollback", {
            "id": checkpoint_id,
            "instar": capsule.get("instar", "?"),
        })
        return maker

    # ── SNAP (emergency shutdown) ──

    def snap(self, reason: str) -> None:
        """Emergency tail-flip. Log the reason, record the event, exit.

        This is the organism's last resort. The tail snaps backward
        and the process terminates. The audit trail survives in the
        event log (caller should persist it before this point if needed).
        """
        self._snap_count += 1
        self._record("snap", {
            "reason": reason,
            "snap_number": self._snap_count,
        })
        raise SystemExit(f"SNAP: {reason}")

    # ── FLICK (try with auto-rollback) ──

    def flick(self, maker: Maker, action: Callable) -> Any:
        """Try an action with automatic rollback on failure.

        1. Checkpoint the current state
        2. Run the action
        3. On success: return the result, keep the checkpoint
        4. On failure: rollback, re-raise the exception

        The maker passed in is used for the checkpoint. On failure,
        the rollback produces a fresh Maker from the stored capsule,
        but the caller must capture the returned value on success
        (the maker reference itself is not modified in-place by rollback).
        """
        cp_id = self.checkpoint(maker)
        eco = maker.eco

        try:
            result = action()
        except SystemExit:
            # Don't catch snap() — let it propagate
            raise
        except Exception as exc:
            # Rollback and record failure
            self._record("flick", {
                "id": cp_id,
                "outcome": "rollback",
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            # Restore from checkpoint (the returned Maker is the rollback)
            restored = self.rollback(cp_id, eco)
            # Re-raise so the caller knows it failed
            raise
        else:
            self._record("flick", {
                "id": cp_id,
                "outcome": "success",
            })
            return result

    # ── QUERIES ──

    @property
    def checkpoint_ids(self) -> list[str]:
        """List checkpoint IDs currently in the ring buffer (oldest first)."""
        return [cid for cid, _ in self._ring]

    @property
    def checkpoint_count(self) -> int:
        return len(self._ring)

    @property
    def events(self) -> list[TailEvent]:
        return list(self._events)

    @property
    def stats(self) -> dict:
        type_counts: dict[str, int] = {}
        for e in self._events:
            type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1
        return {
            "checkpoints_stored": len(self._ring),
            "max_checkpoints": self._ring.maxlen,
            "total_events": len(self._events),
            "snaps": self._snap_count,
            "events_by_type": type_counts,
        }

    # ── INTERNALS ──

    def _find(self, checkpoint_id: str) -> Optional[dict]:
        """Find a capsule by checkpoint ID."""
        for cid, capsule in self._ring:
            if cid == checkpoint_id:
                return capsule
        return None

    def _make_id(self, capsule: dict) -> str:
        """Deterministic ID from capsule content + timestamp."""
        raw = json.dumps(capsule, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _record(self, event_type: str, details: dict) -> None:
        """Append to the audit trail."""
        self._events.append(TailEvent(
            timestamp=time.time(),
            event_type=event_type,
            details=details,
        ))
