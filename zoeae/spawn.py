"""
Spawn — Reproduction organ (gonads).

Create child organisms with inherited genome + mutations.
Children hatch at Instar I with their parent's personality (damping)
but fresh developmental bleed — infant perception, adult instincts.

    eco = Ecosystem("taos")
    parent = Maker.hatch(eco)
    spawn = Spawn()

    # simple reproduction
    child = spawn.reproduce(parent, eco)

    # reproduction with mutations
    child = spawn.reproduce(parent, eco, mutations={
        "CORE": {"purpose": "explore_mars"},
        "SUBSTRATE": {"environment": "vacuum"},
    })

    # batch reproduction
    clutch = spawn.batch(parent, eco, n=5, mutations={
        "CORE": {"purpose": "variant"},
    })
    print(spawn.diversity(clutch))  # 0.0 = clones, 1.0 = all unique

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .genome import Genome, GenomeBuilder, ChromosomeType
from .ecosystem import Ecosystem, Maker


# ── CLUTCH ──

@dataclass
class Clutch:
    """A batch of offspring from a single reproductive event."""
    parent_fingerprint: str
    children: list[Maker] = field(default_factory=list)
    generation: int = 1
    timestamp: float = field(default_factory=time.time)

    @property
    def size(self) -> int:
        return len(self.children)

    def to_dict(self) -> dict:
        return {
            "parent": self.parent_fingerprint,
            "children": [c.fingerprint for c in self.children],
            "generation": self.generation,
            "size": self.size,
            "t": self.timestamp,
        }


# ── SPAWN ──

class Spawn:
    """The reproduction organ. Creates children from parents.

    Children inherit the parent's genome with optional mutations.
    They always start at Instar I — fresh developmental stage,
    fresh bleed — but carry the parent's damping (personality).
    Lineage is tracked: every child's genome stores its parent's
    fingerprint in the POSTERITY chromosome.
    """

    def __init__(self) -> None:
        self._clutches: list[Clutch] = []
        self._total_offspring: int = 0

    # ── REPRODUCE ──

    def reproduce(self, parent: Maker, eco: Ecosystem,
                  mutations: Optional[dict] = None) -> Maker:
        """Create a single child organism from a parent.

        The child gets:
          - Parent's genome (deep-copied) with mutations applied
          - Parent's antenna damping (personality inheritance)
          - Fresh Instar I developmental stage
          - Fresh bleed width (infant perception)
          - Parent fingerprint recorded in POSTERITY chromosome

        Mutations target chromosomes by name:
            {"CORE": {"new_key": "new_value"},
             "LEARNING": {"skill": "welding"}}
        """
        mutations = mutations or {}

        # Deep-copy the parent genome as a dict, mutate, rebuild
        parent_genome_dict = parent.genome.to_dict()
        parent_fp = parent.genome.fingerprint()

        child_genome_dict = self.mutate(parent_genome_dict, mutations)

        # Force child to Instar I regardless of parent stage
        child_genome_dict["instar"] = 1
        child_genome_dict["free_will"] = False

        # Rebuild genome from the mutated dict
        child_genome = Genome.from_dict(child_genome_dict)

        # Record lineage in POSTERITY (use free_will temporarily to bypass gates)
        child_genome.set_free_will(True)
        child_genome.write(
            ChromosomeType.POSTERITY,
            {"parent_fingerprint": parent_fp, "born": time.time()},
            provenance={"source": "spawn", "parent": parent_fp},
        )
        child_genome.set_free_will(False)
        child_genome.set_instar(1)

        # Hatch child into the ecosystem
        child = Maker(eco, child_genome)

        # Inherit parent's antenna damping (personality)
        parent_damping = parent.antenna.damping
        if parent_damping:
            child.antenna.set_damping_all(parent_damping)

        # Child gets fresh developmental bleed (Instar I)
        child.antenna.set_developmental_bleed(1)

        self._total_offspring += 1
        return child

    # ── BATCH ──

    def batch(self, parent: Maker, eco: Ecosystem,
              n: int = 3, mutations: Optional[dict] = None,
              generation: int = 1) -> Clutch:
        """Produce a clutch of n children from a single parent.

        All children get the same mutations (if any). For varied
        mutations per child, call reproduce() individually.
        """
        parent_fp = parent.genome.fingerprint()
        children = [
            self.reproduce(parent, eco, mutations)
            for _ in range(n)
        ]
        clutch = Clutch(
            parent_fingerprint=parent_fp,
            children=children,
            generation=generation,
        )
        self._clutches.append(clutch)
        return clutch

    # ── MUTATE ──

    @staticmethod
    def mutate(genome_dict: dict, mutations: dict) -> dict:
        """Apply mutations to a genome dict (deep copy, non-destructive).

        Mutations are keyed by chromosome name:
            {"CORE": {"new_key": "new_value"},
             "WEIGHTS": [0.1, 0.2, 0.3, ...]}

        For dict-valued mutations, new codons are appended to the
        chromosome's data strand. For list-valued mutations (e.g.
        WEIGHTS), the entire payload is written as a single codon.

        Returns a new genome dict — the original is not modified.
        """
        result = copy.deepcopy(genome_dict)
        chromosomes = result.get("chr", {})

        for chrom_name, payload in mutations.items():
            chrom_name = chrom_name.upper()
            if chrom_name not in chromosomes:
                continue

            chrom = chromosomes[chrom_name]
            data_strand = chrom.get("data", {})
            parity_strand = chrom.get("parity", {})
            meta_strand = chrom.get("meta", {})
            data_codons = data_strand.get("codons", [])
            parity_codons = parity_strand.get("codons", [])
            meta_codons = meta_strand.get("codons", [])

            # Build codon entries for the mutation
            if isinstance(payload, dict):
                entries = [{k: v} for k, v in payload.items()]
            else:
                entries = [payload]

            now = time.time()
            for entry in entries:
                # Hash-based triplet (matches Chromosome._encode pattern)
                h = hashlib.sha256(
                    json.dumps(entry, default=str).encode()
                ).digest()
                triplet = [(h[0] % 3) - 1, (h[1] % 3) - 1, (h[2] % 3) - 1]
                complement = [(-v if v != 0 else 0) for v in triplet]

                data_codons.append({"t": triplet, "p": entry, "ts": now})
                parity_codons.append({"t": complement, "p": entry, "ts": now})
                meta_codons.append({
                    "t": triplet,
                    "p": {"source": "mutation", "time": now},
                    "ts": now,
                })

            data_strand["codons"] = data_codons
            parity_strand["codons"] = parity_codons
            meta_strand["codons"] = meta_codons

        return result

    # ── DIVERSITY ──

    @staticmethod
    def diversity(clutch: Clutch) -> float:
        """Measure genetic diversity in a clutch.

        Returns 0.0 for clones (all identical fingerprints),
        1.0 when every child has a unique fingerprint.
        Works on any clutch size >= 1.
        """
        if clutch.size <= 1:
            return 0.0

        fingerprints = [c.fingerprint for c in clutch.children]
        unique = len(set(fingerprints))

        # diversity = (unique - 1) / (total - 1)
        # 1 unique out of N => 0.0 (all clones)
        # N unique out of N => 1.0 (all different)
        return (unique - 1) / (clutch.size - 1)

    # ── QUERIES ──

    @property
    def clutches(self) -> list[Clutch]:
        return list(self._clutches)

    @property
    def total_offspring(self) -> int:
        return self._total_offspring

    @property
    def stats(self) -> dict:
        return {
            "total_offspring": self._total_offspring,
            "clutches": len(self._clutches),
            "avg_clutch_size": (
                sum(c.size for c in self._clutches) / len(self._clutches)
                if self._clutches else 0
            ),
        }
