"""
Eye — Pattern recognition and threat detection organ. Compound eye (stalked).

The zoea's compound eyes sit on stalks, scanning 360 degrees. Each
facet sees a different angle — together they build a panoramic view.
The eye adapts to light level (bleed): high bleed = wide field, dim
vision (many patterns, low confidence). Low bleed = narrow field,
sharp vision (fewer patterns, high confidence).

Threats and opportunities are classified through the exoskeleton's
integrity system. The eye watches; it does not act.

    from zoeae import Exoskeleton
    from zoeae.eye import Eye

    eye = Eye(exo=Exoskeleton(), bleed=0.5)
    scan_result = eye.scan({"requests": [...], "errors": [...], "load": 0.7})
    detail = eye.focus("error_spike")
    eye.track("error_spike")

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .exoskeleton import Exoskeleton


# ── VISION STRUCTURES ──

@dataclass
class Threat:
    """Something the eye identifies as dangerous."""
    threat_id: str
    description: str
    severity: float = 0.5       # 0.0 = negligible, 1.0 = critical
    pattern: str = ""           # the pattern that triggered detection
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    sightings: int = 1

    def reinforce(self) -> None:
        self.sightings += 1
        self.last_seen = time.time()
        # Severity creeps up with repeated sightings
        self.severity = min(1.0, self.severity + 0.05)


@dataclass
class Opportunity:
    """Something the eye identifies as potentially beneficial."""
    opportunity_id: str
    description: str
    value: float = 0.5          # 0.0 = low value, 1.0 = high value
    pattern: str = ""
    first_seen: float = field(default_factory=time.time)
    expires: float = 0.0        # 0 = no expiry

    @property
    def expired(self) -> bool:
        return self.expires > 0 and time.time() > self.expires


@dataclass
class ScanResult:
    """The output of a full environmental scan."""
    threats: list[Threat] = field(default_factory=list)
    opportunities: list[Opportunity] = field(default_factory=list)
    facets_active: int = 0
    confidence: float = 0.5
    timestamp: float = field(default_factory=time.time)

    @property
    def threat_level(self) -> float:
        if not self.threats:
            return 0.0
        return max(t.severity for t in self.threats)


@dataclass
class DetailedView:
    """High-resolution view of a single target."""
    target_id: str
    observations: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)


# ── FACET PATTERNS ──

# Built-in threat patterns (each facet sees a different angle)
_THREAT_FACETS: list[tuple[str, str, float]] = [
    ("error_spike", r"(?i)\b(error|exception|fail|crash|panic)\b", 0.6),
    ("resource_exhaustion", r"(?i)\b(oom|out.of.memory|disk.full|no.space)\b", 0.8),
    ("security_breach", r"(?i)\b(unauthorized|forbidden|denied|breach|intrusion)\b", 0.9),
    ("rate_limit", r"(?i)\b(rate.limit|throttl|too.many.requests|429)\b", 0.5),
    ("timeout", r"(?i)\b(timeout|timed?.out|deadline.exceeded)\b", 0.5),
    ("data_corruption", r"(?i)\b(corrupt|invalid|malformed|checksum.fail)\b", 0.7),
    ("dependency_down", r"(?i)\b(connection.refused|unreachable|dns.fail|502|503)\b", 0.6),
]

_OPPORTUNITY_FACETS: list[tuple[str, str, float]] = [
    ("optimization", r"(?i)\b(optimiz|improv|faster|efficient|cache.hit)\b", 0.5),
    ("new_data", r"(?i)\b(new.data|update|fresh|incoming|available)\b", 0.4),
    ("idle_capacity", r"(?i)\b(idle|unused|available|free.capacity)\b", 0.3),
    ("pattern_match", r"(?i)\b(match|found|detected|correlat)\b", 0.4),
]


# ── EYE ──

class Eye:
    """The compound eye. Pattern recognition and environmental scanning.

    Facet count scales with bleed: high bleed activates all facets
    (wide field, lower confidence per detection). Low bleed activates
    fewer facets (narrow field, higher confidence per detection).

    Integrates with the exoskeleton for threat classification.
    """

    def __init__(self, exo: Optional[Exoskeleton] = None,
                 bleed: float = 0.5) -> None:
        self.exo = exo or Exoskeleton()
        self._bleed = bleed
        self._tracked: dict[str, list[dict]] = {}
        self._scan_count: int = 0
        self._threats_seen: int = 0
        self._opportunities_seen: int = 0
        self._known_threats: dict[str, Threat] = {}
        self._t0 = time.time()

    @property
    def bleed(self) -> float:
        return self._bleed

    @bleed.setter
    def bleed(self, value: float) -> None:
        self._bleed = max(0.0, min(1.0, value))

    @property
    def facet_count(self) -> int:
        """Number of active facets based on bleed level."""
        total = len(_THREAT_FACETS) + len(_OPPORTUNITY_FACETS)
        if self._bleed > 0.7:
            return total                    # all facets, wide field
        elif self._bleed > 0.4:
            return int(total * 0.7)         # most facets
        elif self._bleed > 0.15:
            return int(total * 0.4)         # selective
        else:
            return max(2, int(total * 0.2)) # laser focus

    @property
    def confidence_modifier(self) -> float:
        """Confidence scales inversely with bleed. Low bleed = sharp vision."""
        return 1.0 - (self._bleed * 0.5)

    # ── PRIMARY INTERFACE ──

    def scan(self, environment: dict[str, Any]) -> ScanResult:
        """Scan an environment dict for threats and opportunities.

        The environment is a dict of observable signals — log lines,
        metrics, request data, error counts, etc. Each value is
        stringified and matched against active facets.
        """
        self._scan_count += 1

        # Flatten environment to searchable text
        text_parts = []
        for key, value in environment.items():
            if isinstance(value, (list, tuple)):
                for item in value:
                    text_parts.append(f"{key}: {item}")
            else:
                text_parts.append(f"{key}: {value}")
        full_text = "\n".join(text_parts)

        # Determine active facets based on bleed
        active_threats = _THREAT_FACETS[:self.facet_count]
        active_opps = _OPPORTUNITY_FACETS[:max(0, self.facet_count - len(_THREAT_FACETS))]

        threats: list[Threat] = []
        opportunities: list[Opportunity] = []

        # Scan for threats
        for facet_id, pattern, base_severity in active_threats:
            matches = re.findall(pattern, full_text)
            if matches:
                severity = min(1.0, base_severity * self.confidence_modifier)
                tid = f"eye:{facet_id}:{hashlib.sha256(str(matches).encode()).hexdigest()[:6]}"

                if facet_id in self._known_threats:
                    self._known_threats[facet_id].reinforce()
                    threats.append(self._known_threats[facet_id])
                else:
                    threat = Threat(
                        threat_id=tid,
                        description=f"{facet_id}: {len(matches)} occurrence(s)",
                        severity=severity,
                        pattern=facet_id,
                    )
                    self._known_threats[facet_id] = threat
                    threats.append(threat)

                # Also run through exoskeleton inspection
                for match_text in matches[:5]:
                    self.exo.inspect(str(match_text), source="eye")

        # Scan for opportunities
        for facet_id, pattern, base_value in active_opps:
            matches = re.findall(pattern, full_text)
            if matches:
                value = min(1.0, base_value * self.confidence_modifier)
                oid = f"eye:{facet_id}:{hashlib.sha256(str(matches).encode()).hexdigest()[:6]}"
                opportunities.append(Opportunity(
                    opportunity_id=oid,
                    description=f"{facet_id}: {len(matches)} signal(s)",
                    value=value,
                    pattern=facet_id,
                ))

        self._threats_seen += len(threats)
        self._opportunities_seen += len(opportunities)

        # Check metrics-based threats from numeric values
        for key, value in environment.items():
            if isinstance(value, (int, float)):
                if key in ("load", "cpu", "cpu_percent") and value > 0.9:
                    threats.append(Threat(
                        threat_id=f"eye:overload:{key}",
                        description=f"{key} at {value:.1%}",
                        severity=0.7,
                        pattern="metric_threshold",
                    ))
                elif key in ("error_rate", "failure_rate") and value > 0.1:
                    threats.append(Threat(
                        threat_id=f"eye:error_rate:{key}",
                        description=f"{key} at {value:.1%}",
                        severity=min(1.0, value * 2),
                        pattern="metric_threshold",
                    ))

        return ScanResult(
            threats=threats,
            opportunities=opportunities,
            facets_active=self.facet_count,
            confidence=self.confidence_modifier,
        )

    def focus(self, target_id: str) -> DetailedView:
        """Focus on a specific target for high-resolution observation.

        If the target is a known threat, returns accumulated detail.
        If tracked, returns the tracking history as observations.
        """
        observations: list[str] = []
        metrics: dict[str, float] = {}

        # Check known threats
        for facet_id, threat in self._known_threats.items():
            if target_id in (threat.threat_id, facet_id, threat.pattern):
                observations.append(
                    f"Threat: {threat.description} "
                    f"(severity={threat.severity:.2f}, seen={threat.sightings}x)"
                )
                metrics["severity"] = threat.severity
                metrics["sightings"] = float(threat.sightings)
                metrics["age_s"] = time.time() - threat.first_seen

        # Check tracking history
        if target_id in self._tracked:
            history = self._tracked[target_id]
            for entry in history[-10:]:  # last 10 observations
                observations.append(
                    f"[{entry.get('t', 0):.0f}] {entry.get('note', 'observed')}"
                )
            metrics["tracking_entries"] = float(len(history))

        confidence = self.confidence_modifier if observations else 0.0

        return DetailedView(
            target_id=target_id,
            observations=observations,
            metrics=metrics,
            confidence=confidence,
        )

    def track(self, target_id: str, note: str = "tracking") -> None:
        """Begin or continue tracking a target.

        Each call appends a timestamped observation. Use focus()
        to review the accumulated tracking data.
        """
        if target_id not in self._tracked:
            self._tracked[target_id] = []

        self._tracked[target_id].append({
            "t": time.time(),
            "note": note,
        })

    def untrack(self, target_id: str) -> bool:
        """Stop tracking a target. Returns True if it was being tracked."""
        return self._tracked.pop(target_id, None) is not None

    # ── QUERIES ──

    @property
    def tracked_targets(self) -> list[str]:
        return list(self._tracked.keys())

    @property
    def known_threat_ids(self) -> list[str]:
        return [t.threat_id for t in self._known_threats.values()]

    # ── STATS ──

    @property
    def stats(self) -> dict:
        return {
            "scans": self._scan_count,
            "threats_seen": self._threats_seen,
            "opportunities_seen": self._opportunities_seen,
            "known_threats": len(self._known_threats),
            "tracked_targets": len(self._tracked),
            "facets_active": self.facet_count,
            "bleed": self._bleed,
            "confidence": round(self.confidence_modifier, 3),
            "uptime_s": round(time.time() - self._t0, 1),
        }
