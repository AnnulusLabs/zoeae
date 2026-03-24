"""
Telemetry — Observability baked into the organism.

Every event is recorded. Secrets are scrubbed before emission.
The telemetry stream is the organism's nervous system —
it doesn't just report, it enables the organism to feel.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional


class EventLevel(Enum):
    TRACE = 0
    DEBUG = 1
    INFO = 2
    WARN = 3
    ERROR = 4
    FATAL = 5


@dataclass
class Event:
    """A single telemetry event."""
    level: EventLevel
    source: str
    message: str
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)
    duration_ms: Optional[float] = None
    parent_id: Optional[str] = None

    @property
    def id(self) -> str:
        import hashlib
        raw = f"{self.timestamp}:{self.source}:{self.message}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level.name,
            "source": self.source,
            "message": self.message,
            "timestamp": self.timestamp,
            "data": self.data,
            "duration_ms": self.duration_ms,
            "parent_id": self.parent_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class Telemetry:
    """
    Event stream with filtering, scrubbing, and subscriber notification.
    """

    def __init__(self, min_level: EventLevel = EventLevel.INFO,
                 scrubber: Optional[Callable[[str], str]] = None) -> None:
        self.min_level = min_level
        self._scrubber = scrubber
        self._events: list[Event] = []
        self._subscribers: list[Callable[[Event], None]] = []
        self._max_events: int = 10000

    def emit(self, level: EventLevel, source: str, message: str,
             data: Optional[dict] = None, duration_ms: Optional[float] = None,
             parent_id: Optional[str] = None) -> Optional[Event]:
        """Emit an event if it meets the minimum level."""
        if level.value < self.min_level.value:
            return None

        # Scrub message
        if self._scrubber:
            message = self._scrubber(message)

        event = Event(
            level=level, source=source, message=message,
            data=data or {}, duration_ms=duration_ms, parent_id=parent_id,
        )
        self._events.append(event)

        # Evict old events
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

        # Notify subscribers
        for sub in self._subscribers:
            try:
                sub(event)
            except Exception:
                pass

        return event

    def info(self, source: str, message: str, **kwargs: Any) -> Optional[Event]:
        return self.emit(EventLevel.INFO, source, message, **kwargs)

    def warn(self, source: str, message: str, **kwargs: Any) -> Optional[Event]:
        return self.emit(EventLevel.WARN, source, message, **kwargs)

    def error(self, source: str, message: str, **kwargs: Any) -> Optional[Event]:
        return self.emit(EventLevel.ERROR, source, message, **kwargs)

    def trace(self, source: str, message: str, **kwargs: Any) -> Optional[Event]:
        return self.emit(EventLevel.TRACE, source, message, **kwargs)

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        self._subscribers.append(callback)

    def query(self, source: Optional[str] = None,
              level: Optional[EventLevel] = None,
              since: Optional[float] = None,
              limit: int = 100) -> list[Event]:
        results = self._events
        if source:
            results = [e for e in results if e.source == source]
        if level:
            results = [e for e in results if e.level.value >= level.value]
        if since:
            results = [e for e in results if e.timestamp >= since]
        return results[-limit:]

    @property
    def stats(self) -> dict:
        if not self._events:
            return {"total": 0}
        by_level = {}
        for e in self._events:
            by_level[e.level.name] = by_level.get(e.level.name, 0) + 1
        return {
            "total": len(self._events),
            "by_level": by_level,
            "subscribers": len(self._subscribers),
        }
