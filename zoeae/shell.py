"""
Shell — Defensive projections. Rostral and dorsal spines.

Not the exoskeleton (which wraps all I/O) but the spines — active
deterrents. Rate limiting, request throttling, abuse detection,
IP blocking. The spines make the organism costly to attack.

In real zoea larvae, the rostral spine (forward) and dorsal spine
(upward) increase the effective body size, making the larva harder
for predators to swallow. These spines are shed and regrown at
each molt.

    from zoeae.shell import Shell

    shell = Shell(rate_limit=100)   # 100 requests per window
    decision = shell.spike(request)
    if decision.allowed:
        process(request)
    else:
        reject(request, decision.reason)

    shell.sharpen(threat_data)       # update rules from eye/exo data
    shell.shed()                     # reset on molt

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional


# ── SPIKE DECISION ──

@dataclass
class SpikeDecision:
    """The result of a spine evaluation on a request."""
    allowed: bool
    reason: str = ""
    source: str = ""
    spike_type: str = ""    # rate_limit, blocked, throttled, abuse
    timestamp: float = field(default_factory=time.time)

    @property
    def denied(self) -> bool:
        return not self.allowed


# ── ATTACK PATTERN ──

@dataclass
class AttackPattern:
    """A detected pattern of abuse."""
    pattern_id: str
    source: str              # IP, user, agent, etc.
    pattern_type: str        # brute_force, flood, scan, etc.
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    count: int = 1
    blocked: bool = False

    def reinforce(self) -> None:
        self.count += 1
        self.last_seen = time.time()

    @property
    def age_s(self) -> float:
        return time.time() - self.first_seen


# ── SHELL ──

class Shell:
    """Rostral and dorsal spines. Active defensive projections.

    Rate limiting per source, IP/source blocking, request throttling,
    and abuse detection. Thread-safe. Rules are shed (reset) on molt
    and sharpened with new threat data.
    """

    def __init__(self, rate_limit: int = 100,
                 window_s: float = 60.0,
                 burst_limit: int = 20,
                 burst_window_s: float = 1.0,
                 block_after: int = 5) -> None:
        # Rate limiting
        self._rate_limit = rate_limit             # max requests per window
        self._window_s = window_s                 # window duration in seconds
        self._burst_limit = burst_limit           # max requests per burst window
        self._burst_window_s = burst_window_s     # burst window duration

        # Auto-block threshold: block source after N denials in a window
        self._block_after = block_after

        # State
        self._lock = threading.Lock()
        self._request_log: dict[str, list[float]] = defaultdict(list)
        self._blocked: dict[str, float] = {}      # source -> blocked_until timestamp
        self._denial_counts: dict[str, int] = defaultdict(int)
        self._patterns: dict[str, AttackPattern] = {}
        self._custom_rules: list[dict[str, Any]] = []

        # Counters
        self._total_requests: int = 0
        self._total_allowed: int = 0
        self._total_denied: int = 0
        self._total_blocks: int = 0
        self._t0 = time.time()

    # ── PRIMARY INTERFACE ──

    def spike(self, request: dict[str, Any]) -> SpikeDecision:
        """Evaluate a request against the spines.

        The request dict should contain at least a 'source' key
        (IP address, user ID, etc.). Additional keys like 'path',
        'method', 'payload' enable richer abuse detection.

        Returns a SpikeDecision: allowed=True if the request passes,
        allowed=False with a reason if it's blocked.
        """
        source = str(request.get("source", request.get("ip", "unknown")))
        now = time.time()
        self._total_requests += 1

        with self._lock:
            # Check block list first
            if source in self._blocked:
                if now < self._blocked[source]:
                    self._total_denied += 1
                    self._record_pattern(source, "blocked_request")
                    return SpikeDecision(
                        allowed=False,
                        reason=f"Source {source} is blocked until "
                               f"{self._blocked[source] - now:.0f}s from now",
                        source=source,
                        spike_type="blocked",
                    )
                else:
                    # Block expired
                    del self._blocked[source]

            # Check custom rules
            for rule in self._custom_rules:
                if self._match_rule(request, rule):
                    self._total_denied += 1
                    return SpikeDecision(
                        allowed=False,
                        reason=f"Matched rule: {rule.get('name', 'custom')}",
                        source=source,
                        spike_type="rule",
                    )

            # Clean old entries from request log
            window_start = now - self._window_s
            burst_start = now - self._burst_window_s
            log = self._request_log[source]
            self._request_log[source] = [t for t in log if t > window_start]
            log = self._request_log[source]

            # Check burst limit
            recent = sum(1 for t in log if t > burst_start)
            if recent >= self._burst_limit:
                self._total_denied += 1
                self._denial_counts[source] += 1
                self._record_pattern(source, "burst")
                self._maybe_auto_block(source, now)
                return SpikeDecision(
                    allowed=False,
                    reason=f"Burst limit exceeded: {recent}/{self._burst_limit} "
                           f"in {self._burst_window_s}s",
                    source=source,
                    spike_type="throttled",
                )

            # Check rate limit
            if len(log) >= self._rate_limit:
                self._total_denied += 1
                self._denial_counts[source] += 1
                self._record_pattern(source, "rate_limit")
                self._maybe_auto_block(source, now)
                return SpikeDecision(
                    allowed=False,
                    reason=f"Rate limit exceeded: {len(log)}/{self._rate_limit} "
                           f"in {self._window_s}s",
                    source=source,
                    spike_type="rate_limit",
                )

            # Request allowed — record timestamp
            self._request_log[source].append(now)
            self._total_allowed += 1

        return SpikeDecision(
            allowed=True,
            source=source,
        )

    def sharpen(self, threat_data: dict[str, Any]) -> int:
        """Update defensive rules from threat intelligence.

        Accepts threat data from the eye or exoskeleton.
        Keys:
          - 'block': list of sources to block immediately
          - 'block_duration': seconds to block (default 3600)
          - 'rules': list of custom rule dicts
          - 'patterns': list of attack pattern dicts to merge

        Returns number of rules/blocks added.
        """
        added = 0
        now = time.time()
        duration = threat_data.get("block_duration", 3600)

        with self._lock:
            # Block specific sources
            for source in threat_data.get("block", []):
                self._blocked[source] = now + duration
                self._total_blocks += 1
                added += 1

            # Add custom rules
            for rule in threat_data.get("rules", []):
                self._custom_rules.append(rule)
                added += 1

            # Merge attack patterns
            for pat_data in threat_data.get("patterns", []):
                source = pat_data.get("source", "unknown")
                ptype = pat_data.get("type", "unknown")
                pid = f"{source}:{ptype}"
                if pid in self._patterns:
                    self._patterns[pid].reinforce()
                else:
                    self._patterns[pid] = AttackPattern(
                        pattern_id=pid,
                        source=source,
                        pattern_type=ptype,
                    )
                added += 1

        return added

    def shed(self) -> dict:
        """Reset all rules on molt. The spines are regrown fresh.

        Returns a summary of what was shed. Rate limit settings
        are preserved — only dynamic state is cleared.
        """
        with self._lock:
            summary = {
                "blocked_cleared": len(self._blocked),
                "patterns_cleared": len(self._patterns),
                "rules_cleared": len(self._custom_rules),
                "request_logs_cleared": len(self._request_log),
            }
            self._blocked.clear()
            self._patterns.clear()
            self._custom_rules.clear()
            self._request_log.clear()
            self._denial_counts.clear()

        return summary

    # ── MANAGEMENT ──

    def block(self, source: str, duration_s: float = 3600.0) -> None:
        """Manually block a source."""
        with self._lock:
            self._blocked[source] = time.time() + duration_s
            self._total_blocks += 1

    def unblock(self, source: str) -> bool:
        """Remove a source from the block list. Returns True if it was blocked."""
        with self._lock:
            return self._blocked.pop(source, None) is not None

    def blocked_sources(self) -> list[str]:
        """List currently blocked sources."""
        now = time.time()
        with self._lock:
            return [s for s, until in self._blocked.items() if until > now]

    def attack_patterns(self) -> list[AttackPattern]:
        """List detected attack patterns, sorted by count."""
        with self._lock:
            patterns = list(self._patterns.values())
        return sorted(patterns, key=lambda p: p.count, reverse=True)

    # ── INTERNALS ──

    def _match_rule(self, request: dict[str, Any], rule: dict[str, Any]) -> bool:
        """Check if a request matches a custom rule."""
        for key, value in rule.items():
            if key == "name":
                continue
            req_value = request.get(key)
            if req_value is None:
                continue
            if isinstance(value, str) and value in str(req_value):
                return True
            elif req_value == value:
                return True
        return False

    def _record_pattern(self, source: str, pattern_type: str) -> None:
        """Record an abuse pattern detection."""
        pid = f"{source}:{pattern_type}"
        if pid in self._patterns:
            self._patterns[pid].reinforce()
        else:
            self._patterns[pid] = AttackPattern(
                pattern_id=pid,
                source=source,
                pattern_type=pattern_type,
            )

    def _maybe_auto_block(self, source: str, now: float) -> None:
        """Auto-block a source if it has exceeded the denial threshold."""
        if self._denial_counts.get(source, 0) >= self._block_after:
            block_duration = self._window_s * 2  # block for 2x the window
            self._blocked[source] = now + block_duration
            self._total_blocks += 1
            self._denial_counts[source] = 0  # reset counter
            self._record_pattern(source, "auto_blocked")

    # ── STATS ──

    @property
    def stats(self) -> dict:
        with self._lock:
            active_blocks = sum(
                1 for until in self._blocked.values() if until > time.time()
            )
        return {
            "total_requests": self._total_requests,
            "total_allowed": self._total_allowed,
            "total_denied": self._total_denied,
            "denial_rate": round(
                self._total_denied / max(self._total_requests, 1), 4
            ),
            "active_blocks": active_blocks,
            "total_blocks": self._total_blocks,
            "attack_patterns": len(self._patterns),
            "custom_rules": len(self._custom_rules),
            "rate_limit": self._rate_limit,
            "burst_limit": self._burst_limit,
            "uptime_s": round(time.time() - self._t0, 1),
        }
