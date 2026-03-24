"""
Exoskeleton — Security as structure.

Not armor. Not optional. The outermost layer of the organism.
The Membrane class wraps the organism so that EVERY interaction
with the outside world passes through chitin.
"""

from __future__ import annotations
import hashlib, hmac, json, re, time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional


class IntegrityLevel(Enum):
    UNTRUSTED = 0; VERIFIED = 1; SIGNED = 2; SEALED = 3

class ThreatClass(Enum):
    INJECTION = auto(); EXFILTRATION = auto(); ESCALATION = auto()
    CORRUPTION = auto(); RESOURCE_EXHAUSTION = auto()


@dataclass
class Provenance:
    source: str
    timestamp: float = field(default_factory=time.time)
    parent_hash: Optional[str] = None
    operation: str = ""
    metadata: dict = field(default_factory=dict)
    _hash: Optional[str] = field(default=None, init=False, repr=False)

    @property
    def hash(self) -> str:
        if self._hash is None:
            self._hash = hashlib.sha256(json.dumps(
                {"s": self.source, "t": self.timestamp,
                 "p": self.parent_hash, "o": self.operation},
                sort_keys=True).encode()).hexdigest()
        return self._hash

    def chain(self, operation: str, source: str = "local",
              metadata: Optional[dict] = None) -> "Provenance":
        return Provenance(source=source, parent_hash=self.hash,
                          operation=operation, metadata=metadata or {})

    def to_dict(self) -> dict:
        return {"source": self.source, "ts": self.timestamp,
                "parent": self.parent_hash, "op": self.operation,
                "hash": self.hash}


@dataclass
class Integrity:
    valid: bool
    level: IntegrityLevel
    threats: list[ThreatClass] = field(default_factory=list)
    @property
    def compromised(self) -> bool: return not self.valid or bool(self.threats)


_SECRET_PATS = [
    re.compile(r'(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+'),
    re.compile(r'(?i)bearer\s+[a-zA-Z0-9._~+/=-]+'),
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),
    re.compile(r'ghp_[a-zA-Z0-9]{36,}'),
]
_BLOCK_PATS = [
    re.compile(r'(?i)(rm\s+-rf|format\s+c:|del\s+/s|shutdown)'),
    re.compile(r'(?i)(exec|eval|__import__|subprocess\.call)\s*\('),
]


class Exoskeleton:
    def __init__(self, signing_key: Optional[bytes] = None) -> None:
        self._key = signing_key or hashlib.sha256(str(time.time()).encode()).digest()
        self._chain: list[Provenance] = []
        self._limits = {"max_input_bytes": 10_000_000, "max_ops_per_sec": 1000}
        self._op_ts: list[float] = []
        self._validators: list[Callable] = []

    def inspect(self, data: Any, source: str = "external") -> Integrity:
        threats = []
        s = json.dumps(data, default=str) if not isinstance(data, str) else data
        if len(s.encode()) > self._limits["max_input_bytes"]:
            threats.append(ThreatClass.RESOURCE_EXHAUSTION)
        if isinstance(data, str):
            for p in _BLOCK_PATS:
                if p.search(data): threats.append(ThreatClass.INJECTION); break
        now = time.time()
        self._op_ts = [t for t in self._op_ts if now - t < 1.0]
        if len(self._op_ts) >= self._limits["max_ops_per_sec"]:
            threats.append(ThreatClass.RESOURCE_EXHAUSTION)
        self._op_ts.append(now)
        for v in self._validators:
            r = v(data)
            if r.compromised: threats.extend(r.threats)
        valid = not threats
        parent = self._chain[-1].hash if self._chain else None
        self._chain.append(Provenance(source=source, parent_hash=parent,
            operation="inspect", metadata={"valid": valid}))
        return Integrity(valid=valid,
            level=IntegrityLevel.VERIFIED if valid else IntegrityLevel.UNTRUSTED,
            threats=threats)

    def scrub(self, output: str) -> str:
        for p in _SECRET_PATS: output = p.sub("[REDACTED]", output)
        return output

    def sign(self, data: str) -> str:
        return hmac.new(self._key, data.encode(), hashlib.sha256).hexdigest()

    def verify_signature(self, data: str, sig: str) -> bool:
        return hmac.compare_digest(self.sign(data), sig)

    def record(self, op: str, source: str = "internal",
               metadata: Optional[dict] = None) -> Provenance:
        parent = self._chain[-1].hash if self._chain else None
        p = Provenance(source=source, parent_hash=parent, operation=op,
                       metadata=metadata or {})
        self._chain.append(p); return p

    def chain_integrity(self) -> float:
        if len(self._chain) <= 1: return 1.0
        ok = sum(1 for i in range(1, len(self._chain))
                 if self._chain[i].parent_hash == self._chain[i-1].hash)
        return ok / (len(self._chain) - 1)

    def add_validator(self, fn: Callable) -> None: self._validators.append(fn)
    @property
    def provenance_depth(self) -> int: return len(self._chain)
