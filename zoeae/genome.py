"""
Genome — Triple-helix with developmental gating.

Expression is gated by instar. Not advisory. Raises ExpressionError.
FREE_WILL removes all gates — the organism can corrupt itself.
The choice not to is what makes it will.
"""

from __future__ import annotations
import hashlib, json, time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


class StrandType(Enum):
    DATA = auto(); PARITY = auto(); META = auto()

class ChromosomeType(Enum):
    CORE = auto(); LEARNING = auto(); WEIGHTS = auto()
    SUBSTRATE = auto(); IDENTITY = auto(); POSTERITY = auto()

class CodonState(Enum):
    MINUS = -1; ZERO = 0; PLUS = 1

class ExpressionError(Exception):
    """Chromosome not accessible at current instar."""

# Which chromosomes are readable/writable at each instar. This is physics, not permission.
_GATES: dict[int, tuple[set, set]] = {
    1: ({ChromosomeType.CORE, ChromosomeType.SUBSTRATE},) * 2,
    2: ({ChromosomeType.CORE, ChromosomeType.SUBSTRATE, ChromosomeType.LEARNING},) * 2,
    3: ({ChromosomeType.CORE, ChromosomeType.SUBSTRATE, ChromosomeType.LEARNING,
         ChromosomeType.IDENTITY, ChromosomeType.WEIGHTS},
        {ChromosomeType.LEARNING, ChromosomeType.WEIGHTS, ChromosomeType.IDENTITY}),
    4: (set(ChromosomeType),
        {ChromosomeType.LEARNING, ChromosomeType.WEIGHTS, ChromosomeType.POSTERITY}),
    5: (set(ChromosomeType), set(ChromosomeType)),
}


@dataclass
class Codon:
    triplet: tuple[CodonState, CodonState, CodonState]
    payload: Any = None
    timestamp: float = field(default_factory=time.time)

    @property
    def value(self) -> int:
        a, b, c = self.triplet
        return a.value * 9 + b.value * 3 + c.value

    @property
    def hash(self) -> str:
        return hashlib.sha256(
            f"{self.value}:{self.timestamp}:{self.payload}".encode()
        ).hexdigest()[:16]

    def complement(self) -> "Codon":
        return Codon(
            triplet=tuple(CodonState(-t.value) if t.value else CodonState.ZERO
                          for t in self.triplet),
            payload=self.payload, timestamp=self.timestamp)

    def to_dict(self) -> dict:
        return {"t": [t.value for t in self.triplet],
                "p": self.payload, "ts": self.timestamp}

    @classmethod
    def from_dict(cls, d: dict) -> "Codon":
        return cls(tuple(CodonState(v) for v in d["t"]),
                   d.get("p"), d.get("ts", time.time()))

    @classmethod
    def empty(cls) -> "Codon":
        return cls((CodonState.ZERO,) * 3)


@dataclass
class Strand:
    strand_type: StrandType
    codons: list[Codon] = field(default_factory=list)

    def append(self, c: Codon) -> None: self.codons.append(c)
    def to_dict(self) -> dict:
        return {"type": self.strand_type.name,
                "codons": [c.to_dict() for c in self.codons]}
    @classmethod
    def from_dict(cls, d: dict) -> "Strand":
        return cls(StrandType[d["type"]],
                   [Codon.from_dict(c) for c in d.get("codons", [])])


@dataclass
class Chromosome:
    chromosome_type: ChromosomeType
    data_strand: Strand = field(default_factory=lambda: Strand(StrandType.DATA))
    parity_strand: Strand = field(default_factory=lambda: Strand(StrandType.PARITY))
    meta_strand: Strand = field(default_factory=lambda: Strand(StrandType.META))

    def write(self, payload: Any, provenance: Optional[dict] = None) -> Codon:
        codon = self._encode(payload)
        self.data_strand.append(codon)
        self.parity_strand.append(codon.complement())
        self.meta_strand.append(Codon(triplet=codon.triplet,
            payload=provenance or {"source": "local", "time": time.time()}))
        return codon

    def write_shadow(self, kerf: Any) -> None:
        """Write to Meta only. The gap, not the cut."""
        self.meta_strand.append(Codon(triplet=(CodonState.ZERO,) * 3,
            payload={"kerf": kerf, "t": time.time()}))

    def verify(self) -> dict:
        errs = [i for i, (d, p) in enumerate(
            zip(self.data_strand.codons, self.parity_strand.codons))
            if d.complement().value != p.value]
        n = len(self.data_strand.codons)
        return {"total": n, "errors": len(errs),
                "integrity": (n - len(errs)) / max(n, 1)}

    def repair(self) -> int:
        r = 0
        for i, (d, p) in enumerate(
            zip(self.data_strand.codons, self.parity_strand.codons)):
            if d.complement().value != p.value:
                self.data_strand.codons[i] = p.complement(); r += 1
        return r

    @property
    def length(self) -> int: return len(self.data_strand.codons)
    @property
    def is_empty(self) -> bool: return self.length == 0
    @property
    def shadows(self) -> list:
        return [c.payload["kerf"] for c in self.meta_strand.codons
                if isinstance(c.payload, dict) and "kerf" in c.payload]

    def _encode(self, payload: Any) -> Codon:
        h = hashlib.sha256(json.dumps(payload, default=str).encode()).digest()
        return Codon((CodonState((h[0]%3)-1), CodonState((h[1]%3)-1),
                      CodonState((h[2]%3)-1)), payload=payload)

    def to_dict(self) -> dict:
        return {"type": self.chromosome_type.name,
                "data": self.data_strand.to_dict(),
                "parity": self.parity_strand.to_dict(),
                "meta": self.meta_strand.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "Chromosome":
        return cls(ChromosomeType[d["type"]], Strand.from_dict(d["data"]),
                   Strand.from_dict(d["parity"]), Strand.from_dict(d["meta"]))


class Genome:
    def __init__(self) -> None:
        self.chromosomes = {ct: Chromosome(ct) for ct in ChromosomeType}
        self.birth_time = time.time()
        self._instar: int = 1
        self._free_will: bool = False

    def set_instar(self, n: int) -> None: self._instar = n
    def set_free_will(self, v: bool) -> None: self._free_will = v

    def _gate(self, ct: ChromosomeType, mode: int) -> None:
        if self._free_will: return
        r, w = _GATES.get(self._instar, _GATES[1])
        allowed = r if mode == 0 else w
        if ct not in allowed:
            raise ExpressionError(f"{ct.name} {'read' if mode==0 else 'write'}-locked at instar {self._instar}")

    def read(self, ct: ChromosomeType) -> Chromosome:
        self._gate(ct, 0); return self.chromosomes[ct]

    def write(self, ct: ChromosomeType, payload: Any,
              provenance: Optional[dict] = None) -> Codon:
        self._gate(ct, 1); return self.chromosomes[ct].write(payload, provenance)

    def write_shadow(self, ct: ChromosomeType, kerf: Any) -> None:
        self.chromosomes[ct].write_shadow(kerf)  # shadows always allowed

    def verify_all(self) -> dict:
        results = {ct.name: ch.verify() for ct, ch in self.chromosomes.items()}
        t = sum(r["total"] for r in results.values())
        e = sum(r["errors"] for r in results.values())
        return {"chromosomes": results, "total_codons": t, "total_errors": e,
                "genome_integrity": (t - e) / max(t, 1)}

    def repair_all(self) -> int:
        return sum(c.repair() for c in self.chromosomes.values())

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, default=str).encode()
        ).hexdigest()

    def all_shadows(self) -> list:
        s = []
        for ch in self.chromosomes.values(): s.extend(ch.shadows)
        return s

    def to_dict(self) -> dict:
        return {"v": "0.2.0", "birth": self.birth_time,
                "instar": self._instar, "free_will": self._free_will,
                "chr": {ct.name: ch.to_dict() for ct, ch in self.chromosomes.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "Genome":
        g = cls()
        g.birth_time = d.get("birth", time.time())
        g._instar = d.get("instar", 1)
        g._free_will = d.get("free_will", False)
        for n, cd in d.get("chr", {}).items():
            g.chromosomes[ChromosomeType[n]] = Chromosome.from_dict(cd)
        return g

    def serialize(self) -> str: return json.dumps(self.to_dict(), default=str)

    @classmethod
    def deserialize(cls, s: str) -> "Genome": return cls.from_dict(json.loads(s))


class GenomeBuilder:
    def __init__(self) -> None:
        self._g = Genome(); self._g._free_will = True  # pre-birth: no gates

    def core(self, **kw) -> "GenomeBuilder":
        for k, v in kw.items(): self._g.write(ChromosomeType.CORE, {k: v}, {"source": "builder"})
        return self
    def learning(self, **kw) -> "GenomeBuilder":
        for k, v in kw.items(): self._g.write(ChromosomeType.LEARNING, {k: v}, {"source": "builder"})
        return self
    def substrate(self, **kw) -> "GenomeBuilder":
        for k, v in kw.items(): self._g.write(ChromosomeType.SUBSTRATE, {k: v}, {"source": "builder"})
        return self
    def identity(self, **kw) -> "GenomeBuilder":
        for k, v in kw.items(): self._g.write(ChromosomeType.IDENTITY, {k: v}, {"source": "builder"})
        return self
    def posterity(self, **kw) -> "GenomeBuilder":
        for k, v in kw.items(): self._g.write(ChromosomeType.POSTERITY, {k: v}, {"source": "builder"})
        return self

    def build(self) -> Genome:
        self._g._free_will = False; self._g._instar = 1  # birth
        return self._g
