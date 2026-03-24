"""
Heart — Heartbeat/scheduler organ.

The pump. Keeps the organism alive between interactions. Schedules
recurring tasks ("beats") and one-shot delayed callbacks. Runs in
a background daemon thread with clean shutdown semantics.

Built-in beats: sensor polling, ocean sensing, telemetry flush.
Thread-safe. The heart does not die before the organism.

    heart = Heart()
    heart.beat(lambda: print("alive"), interval_s=5.0)
    heart.once(lambda: print("startup done"), delay_s=1.0)
    heart.start()
    # ... later ...
    vitals = heart.pulse()
    heart.stop()

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional


# ── HEALTH STATUS ──

class HealthStatus(Enum):
    DORMANT  = auto()  # not started
    BEATING  = auto()  # running normally
    STRESSED = auto()  # missed beats or high error rate
    STOPPED  = auto()  # clean shutdown
    FAILED   = auto()  # unrecoverable error


# ── HEARTBEAT EVENT ──

@dataclass
class HeartbeatEvent:
    """A scheduled callback — recurring or one-shot."""
    name: str
    callback: Callable
    interval_s: float            # 0 = one-shot
    delay_s: float = 0.0         # initial delay before first fire
    recurring: bool = True
    last_fired: float = 0.0
    fire_count: int = 0
    errors: int = 0
    next_fire: float = field(default=0.0, init=False)
    _active: bool = field(default=True, init=False, repr=False)

    def __post_init__(self) -> None:
        self.next_fire = time.time() + self.delay_s

    @property
    def active(self) -> bool:
        return self._active

    def cancel(self) -> None:
        self._active = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "interval_s": self.interval_s,
            "recurring": self.recurring,
            "fire_count": self.fire_count,
            "errors": self.errors,
            "active": self._active,
        }


# ── HEART ──

class Heart:
    """The heartbeat organ. Background scheduler for the organism.

    Runs a single daemon thread that ticks at a configurable resolution.
    Registered beats fire at their specified intervals. One-shot events
    fire once after their delay and are removed.

    Thread-safe: all mutations go through a lock.
    Daemon thread: the heart dies with the organism, never outlives it.
    """

    def __init__(self, tick_resolution_s: float = 0.25) -> None:
        self._tick = tick_resolution_s
        self._events: list[HeartbeatEvent] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._status = HealthStatus.DORMANT
        self._beat_count = 0
        self._start_time: float = 0.0
        self._last_beat: float = 0.0
        self._error_log: list[dict] = []

    # ── LIFECYCLE ──

    def start(self) -> None:
        """Start the heartbeat thread."""
        if self._running:
            return
        self._running = True
        self._status = HealthStatus.BEATING
        self._start_time = time.time()
        self._thread = threading.Thread(
            target=self._loop,
            name="zoeae-heart",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        """Stop the heartbeat cleanly."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout_s)
        self._status = HealthStatus.STOPPED
        self._thread = None

    @property
    def alive(self) -> bool:
        return self._running and self._status == HealthStatus.BEATING

    # ── REGISTERING BEATS ──

    def beat(self, callback: Callable, interval_s: float,
             name: str = "", delay_s: float = 0.0) -> HeartbeatEvent:
        """Register a recurring task. Returns the event for later cancellation."""
        event_name = name or f"beat_{len(self._events)}"
        event = HeartbeatEvent(
            name=event_name,
            callback=callback,
            interval_s=interval_s,
            delay_s=delay_s,
            recurring=True,
        )
        with self._lock:
            self._events.append(event)
        return event

    def once(self, callback: Callable, delay_s: float,
             name: str = "") -> HeartbeatEvent:
        """Register a one-shot delayed callback."""
        event_name = name or f"once_{len(self._events)}"
        event = HeartbeatEvent(
            name=event_name,
            callback=callback,
            interval_s=0.0,
            delay_s=delay_s,
            recurring=False,
        )
        with self._lock:
            self._events.append(event)
        return event

    def cancel(self, name: str) -> bool:
        """Cancel a registered event by name."""
        with self._lock:
            for event in self._events:
                if event.name == name and event.active:
                    event.cancel()
                    return True
        return False

    # ── VITALS ──

    def pulse(self) -> dict:
        """Current vitals snapshot. Thread-safe read."""
        with self._lock:
            active_events = [e for e in self._events if e.active]
            total_fires = sum(e.fire_count for e in self._events)
            total_errors = sum(e.errors for e in self._events)

        uptime = time.time() - self._start_time if self._start_time else 0.0

        return {
            "status": self._status.name,
            "uptime_s": round(uptime, 1),
            "beat_count": self._beat_count,
            "last_beat": self._last_beat,
            "registered_tasks": len(active_events),
            "total_fires": total_fires,
            "total_errors": total_errors,
            "health": self._assess_health(),
            "tasks": [e.to_dict() for e in active_events],
        }

    def _assess_health(self) -> str:
        """Assess overall health from error rates and timing."""
        if self._status in (HealthStatus.DORMANT, HealthStatus.STOPPED):
            return self._status.name.lower()

        with self._lock:
            total_fires = sum(e.fire_count for e in self._events)
            total_errors = sum(e.errors for e in self._events)

        if total_fires == 0:
            return "idle"

        error_rate = total_errors / max(total_fires, 1)
        if error_rate > 0.5:
            self._status = HealthStatus.STRESSED
            return "critical"
        elif error_rate > 0.1:
            self._status = HealthStatus.STRESSED
            return "stressed"
        else:
            if self._status == HealthStatus.STRESSED:
                self._status = HealthStatus.BEATING
            return "healthy"

    # ── BUILT-IN BEATS ──

    def add_sensor_poll(self, sensor_read_fn: Callable,
                        interval_s: float = 60.0) -> HeartbeatEvent:
        """Register a sensor polling beat."""
        return self.beat(sensor_read_fn, interval_s, name="sensor_poll")

    def add_ocean_sense(self, ocean_sense_fn: Callable,
                        interval_s: float = 30.0) -> HeartbeatEvent:
        """Register an ocean sensing beat."""
        return self.beat(ocean_sense_fn, interval_s, name="ocean_sense")

    def add_telemetry_flush(self, flush_fn: Callable,
                            interval_s: float = 120.0) -> HeartbeatEvent:
        """Register a telemetry flush beat."""
        return self.beat(flush_fn, interval_s, name="telemetry_flush")

    # ── THE LOOP ──

    def _loop(self) -> None:
        """Main heartbeat loop. Runs in daemon thread."""
        while self._running:
            now = time.time()
            self._beat_count += 1
            self._last_beat = now

            # Snapshot events under lock
            with self._lock:
                snapshot = [e for e in self._events if e.active]

            # Fire events that are due
            fired_any = False
            for event in snapshot:
                if not event.active:
                    continue
                if now >= event.next_fire:
                    fired_any = True
                    try:
                        event.callback()
                        event.fire_count += 1
                        event.last_fired = now
                    except Exception as exc:
                        event.errors += 1
                        self._error_log.append({
                            "event": event.name,
                            "error": str(exc),
                            "time": now,
                        })
                        # Keep the error log bounded
                        if len(self._error_log) > 100:
                            self._error_log = self._error_log[-50:]

                    if event.recurring:
                        event.next_fire = now + event.interval_s
                    else:
                        event.cancel()

            # Prune cancelled events periodically
            if self._beat_count % 100 == 0:
                with self._lock:
                    self._events = [e for e in self._events if e.active]

            # Sleep for one tick
            elapsed = time.time() - now
            sleep_time = max(0.01, self._tick - elapsed)
            time.sleep(sleep_time)

    # ── STATS ──

    @property
    def stats(self) -> dict:
        return self.pulse()

    @property
    def error_log(self) -> list[dict]:
        return list(self._error_log)
