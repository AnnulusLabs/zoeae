"""
Nerve — Internal messaging bus. Ventral nerve cord.

Every organ talks through the nerve cord, not directly to each other.
This enforces modularity — organs are decoupled, the nerve cord is
the only inter-organ communication channel. Signals are logged for
diagnostics.

The ventral nerve cord runs the length of the organism. Ganglia
(message queues) sit at each organ. Signals propagate in order.
Broadcast hits all ganglia simultaneously.

    from zoeae.nerve import Nerve

    nerve = Nerve()
    nerve.signal("mouth", "gut", {"type": "fragment", "data": fragment})
    nerve.broadcast({"type": "molt_imminent", "instar": 3})
    messages = nerve.listen("gut")

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Optional


# ── SIGNAL ──

@dataclass
class Signal:
    """A message traveling through the nerve cord."""
    from_organ: str
    to_organ: str                # "*" for broadcast
    payload: Any = None
    signal_type: str = "data"    # data, event, command, query
    timestamp: float = field(default_factory=time.time)
    delivered: bool = False
    signal_id: str = ""

    def __post_init__(self) -> None:
        if not self.signal_id:
            self.signal_id = f"sig:{self.from_organ}>{self.to_organ}:{self.timestamp:.6f}"


@dataclass
class SignalLog:
    """Diagnostic log entry for a signal."""
    signal_id: str
    from_organ: str
    to_organ: str
    signal_type: str
    timestamp: float
    delivered: bool
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.signal_id,
            "from": self.from_organ,
            "to": self.to_organ,
            "type": self.signal_type,
            "t": self.timestamp,
            "delivered": self.delivered,
            "latency_ms": self.latency_ms,
        }


# ── NERVE ──

class Nerve:
    """The ventral nerve cord. Inter-organ messaging bus.

    Thread-safe. Each organ has a ganglion (message queue) identified
    by name. Signals are point-to-point or broadcast. All signals
    are logged for diagnostics.
    """

    def __init__(self, max_queue: int = 1000,
                 max_log: int = 10000) -> None:
        self._ganglia: dict[str, deque[Signal]] = defaultdict(
            lambda: deque(maxlen=max_queue)
        )
        self._max_queue = max_queue
        self._log: deque[SignalLog] = deque(maxlen=max_log)
        self._lock = threading.Lock()
        self._subscribers: dict[str, list] = defaultdict(list)
        self._total_sent: int = 0
        self._total_delivered: int = 0
        self._total_broadcast: int = 0
        self._t0 = time.time()

    # ── PRIMARY INTERFACE ──

    def signal(self, from_organ: str, to_organ: str,
               payload: Any = None, signal_type: str = "data") -> Signal:
        """Send a signal from one organ to another.

        The signal is placed in the recipient's ganglion (queue).
        Returns the Signal object for reference.
        """
        sig = Signal(
            from_organ=from_organ,
            to_organ=to_organ,
            payload=payload,
            signal_type=signal_type,
        )

        t0 = time.time()

        with self._lock:
            self._ganglia[to_organ].append(sig)
            sig.delivered = True
            self._total_sent += 1
            self._total_delivered += 1

        latency = (time.time() - t0) * 1000.0
        self._log_signal(sig, latency)

        # Notify subscribers
        self._notify(to_organ, sig)

        return sig

    def broadcast(self, payload: Any, from_organ: str = "system",
                  signal_type: str = "event") -> list[Signal]:
        """Send a signal to all known ganglia.

        Returns a list of all Signal objects created. Each organ
        gets its own copy of the signal.
        """
        signals: list[Signal] = []
        t0 = time.time()

        with self._lock:
            organ_names = list(self._ganglia.keys())

        for organ in organ_names:
            sig = Signal(
                from_organ=from_organ,
                to_organ=organ,
                payload=payload,
                signal_type=signal_type,
            )
            with self._lock:
                self._ganglia[organ].append(sig)
                sig.delivered = True
                self._total_sent += 1
                self._total_delivered += 1

            latency = (time.time() - t0) * 1000.0
            self._log_signal(sig, latency)
            self._notify(organ, sig)
            signals.append(sig)

        self._total_broadcast += 1
        return signals

    def listen(self, organ_id: str, limit: Optional[int] = None) -> list[Signal]:
        """Read and drain messages from an organ's ganglion.

        Returns all pending signals (up to limit). Messages are
        removed from the queue after reading — each signal is
        consumed exactly once.
        """
        with self._lock:
            q = self._ganglia[organ_id]
            if limit is None:
                messages = list(q)
                q.clear()
            else:
                messages = []
                for _ in range(min(limit, len(q))):
                    messages.append(q.popleft())

        return messages

    def peek(self, organ_id: str, limit: int = 5) -> list[Signal]:
        """Peek at messages without consuming them."""
        with self._lock:
            q = self._ganglia[organ_id]
            return list(q)[:limit]

    # ── SUBSCRIPTIONS (async-capable pattern) ──

    def subscribe(self, organ_id: str, callback: Any) -> None:
        """Register a callback for when signals arrive at an organ's ganglion.

        The callback receives the Signal object. This enables
        event-driven (async-capable) communication patterns.
        """
        with self._lock:
            self._subscribers[organ_id].append(callback)

    def unsubscribe(self, organ_id: str) -> None:
        """Remove all callbacks for an organ."""
        with self._lock:
            self._subscribers[organ_id] = []

    def _notify(self, organ_id: str, sig: Signal) -> None:
        """Fire callbacks for an organ's subscribers."""
        with self._lock:
            callbacks = list(self._subscribers.get(organ_id, []))
        for cb in callbacks:
            try:
                cb(sig)
            except Exception:
                pass  # Nerve cord does not propagate callback errors

    # ── MANAGEMENT ──

    def register(self, organ_id: str) -> None:
        """Explicitly register an organ's ganglion.

        Optional — ganglia are auto-created on first signal.
        Explicit registration ensures the organ appears in broadcasts
        even before it receives its first message.
        """
        with self._lock:
            if organ_id not in self._ganglia:
                self._ganglia[organ_id] = deque(maxlen=self._max_queue)

    def registered_organs(self) -> list[str]:
        """List all organs with ganglia."""
        with self._lock:
            return list(self._ganglia.keys())

    def pending_count(self, organ_id: str) -> int:
        """Number of unread signals in an organ's ganglion."""
        with self._lock:
            return len(self._ganglia.get(organ_id, []))

    def clear(self, organ_id: str) -> int:
        """Clear an organ's ganglion. Returns number of messages dropped."""
        with self._lock:
            q = self._ganglia.get(organ_id)
            if q is None:
                return 0
            count = len(q)
            q.clear()
            return count

    # ── DIAGNOSTICS ──

    def diagnostic_log(self, limit: int = 50) -> list[dict]:
        """Return recent signal log entries for debugging."""
        with self._lock:
            entries = list(self._log)
        return [e.to_dict() for e in entries[-limit:]]

    def _log_signal(self, sig: Signal, latency_ms: float) -> None:
        """Record a signal in the diagnostic log."""
        entry = SignalLog(
            signal_id=sig.signal_id,
            from_organ=sig.from_organ,
            to_organ=sig.to_organ,
            signal_type=sig.signal_type,
            timestamp=sig.timestamp,
            delivered=sig.delivered,
            latency_ms=round(latency_ms, 3),
        )
        with self._lock:
            self._log.append(entry)

    # ── STATS ──

    @property
    def stats(self) -> dict:
        with self._lock:
            organ_counts = {
                organ: len(q) for organ, q in self._ganglia.items()
            }
        return {
            "total_sent": self._total_sent,
            "total_delivered": self._total_delivered,
            "total_broadcasts": self._total_broadcast,
            "registered_organs": len(organ_counts),
            "pending_by_organ": organ_counts,
            "log_entries": len(self._log),
            "uptime_s": round(time.time() - self._t0, 1),
        }
