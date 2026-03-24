"""
Gut — Memory consolidation and knowledge extraction organ. Hepatopancreas.

The digestive gland. Takes raw Fragments from the mouth and extracts
structured knowledge — entities, relationships, facts, patterns.
The gut digests what the mouth chews. High-value information is absorbed
into long-term storage; stale or low-value knowledge is excreted.

Each fragment is scored for nutritional_value (information density).
Dense fragments yield more Knowledge; thin ones pass through quickly.

    from zoeae import Mouth, Exoskeleton
    from zoeae.gut import Gut

    mouth = Mouth(exo=Exoskeleton())
    gut = Gut()

    fragments = mouth.eat("research_paper.pdf")
    knowledge = gut.digest(fragments)
    gut.absorb(knowledge)
    purged = gut.excrete()  # drop stale facts

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ── KNOWLEDGE STRUCTURES ──

@dataclass
class Entity:
    """A named thing extracted from text."""
    name: str
    entity_type: str = "unknown"   # person, place, concept, metric, etc.
    mentions: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def reinforce(self) -> None:
        self.mentions += 1
        self.last_seen = time.time()


@dataclass
class Relationship:
    """A connection between two entities."""
    subject: str
    predicate: str
    obj: str
    confidence: float = 0.5
    source_key: str = ""

    @property
    def triple(self) -> tuple[str, str, str]:
        return (self.subject, self.predicate, self.obj)


@dataclass
class Fact:
    """An atomic piece of extracted knowledge."""
    key: str
    content: str
    confidence: float = 0.5
    nutritional_value: float = 0.0
    created: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0

    def access(self) -> None:
        self.access_count += 1
        self.last_accessed = time.time()

    @property
    def staleness(self) -> float:
        """How stale this fact is. 0.0 = fresh, approaches 1.0 over hours."""
        age = time.time() - self.last_accessed
        # Half-life of ~1 hour
        return 1.0 - (0.5 ** (age / 3600.0))


@dataclass
class Knowledge:
    """The structured output of digestion."""
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    source_keys: list[str] = field(default_factory=list)
    nutritional_value: float = 0.0

    @property
    def empty(self) -> bool:
        return not self.entities and not self.relationships and not self.facts


# ── NUTRITIONAL ANALYSIS ──

def _information_density(text: str) -> float:
    """Estimate information density of text. 0.0 = empty, 1.0 = maximally dense.

    Heuristic: unique-word ratio, presence of numbers/technical terms,
    sentence complexity. No NLP dependencies.
    """
    if not text or not text.strip():
        return 0.0

    words = text.split()
    if not words:
        return 0.0

    # Unique word ratio (type-token ratio)
    unique = len(set(w.lower() for w in words))
    ttr = unique / len(words) if words else 0.0

    # Numeric content (data-rich text has numbers)
    numeric = sum(1 for w in words if any(c.isdigit() for c in w))
    numeric_ratio = numeric / len(words)

    # Long words tend to be technical/specific
    long_words = sum(1 for w in words if len(w) > 8)
    long_ratio = long_words / len(words)

    # Combine signals
    density = (ttr * 0.4) + (numeric_ratio * 0.3) + (long_ratio * 0.3)
    return min(1.0, max(0.0, density))


def _extract_entities_simple(text: str) -> list[Entity]:
    """Extract likely entity names from text using capitalization heuristics."""
    entities: dict[str, Entity] = {}

    # Capitalized multi-word sequences (likely proper nouns)
    for match in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', text):
        name = match.group(1)
        if len(name) > 2 and name not in ("The", "This", "That", "And", "But"):
            if name in entities:
                entities[name].reinforce()
            else:
                entities[name] = Entity(name=name, entity_type="named")

    # ALL-CAPS acronyms (3+ letters)
    for match in re.finditer(r'\b([A-Z]{3,})\b', text):
        name = match.group(1)
        if name in entities:
            entities[name].reinforce()
        else:
            entities[name] = Entity(name=name, entity_type="acronym")

    # Numbers with units (metrics)
    for match in re.finditer(r'(\d+\.?\d*\s*(?:kg|mb|gb|tb|ms|us|ns|hz|mhz|ghz|'
                             r'mm|cm|km|°[cf]|psi|bar|watts?|amps?|volts?|ohms?))',
                             text, re.IGNORECASE):
        name = match.group(1).strip()
        if name not in entities:
            entities[name] = Entity(name=name, entity_type="metric")

    return list(entities.values())


def _extract_relationships_simple(text: str, entities: list[Entity]) -> list[Relationship]:
    """Extract simple subject-predicate-object triples from text."""
    relationships: list[Relationship] = []
    entity_names = {e.name.lower() for e in entities}

    # Look for "X is/are Y" patterns
    for match in re.finditer(r'(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+'
                             r'(?:is|are|was|were|has|have|uses?|produces?|contains?)\s+'
                             r'(.+?)(?:\.|,|;|$)', text):
        subj = match.group(1).strip()
        verb_and_obj = match.group(0).strip().rstrip(".,;")
        # Extract the verb
        verb_match = re.search(r'\b(is|are|was|were|has|have|uses?|produces?|contains?)\b',
                               verb_and_obj, re.IGNORECASE)
        if verb_match:
            pred = verb_match.group(1)
            obj_text = verb_and_obj[verb_match.end():].strip()
            if obj_text and len(obj_text) < 100:
                relationships.append(Relationship(
                    subject=subj,
                    predicate=pred,
                    obj=obj_text,
                    confidence=0.4,
                ))

    return relationships[:50]  # Cap to prevent explosion


# ── GUT ──

class Gut:
    """The digestive gland. Hepatopancreas.

    Extracts structured knowledge from raw Fragments. Tracks
    nutritional value per fragment and manages long-term fact storage.
    Stale knowledge is excreted on demand.
    """

    def __init__(self, staleness_threshold: float = 0.9,
                 max_facts: int = 5000) -> None:
        self._staleness_threshold = staleness_threshold
        self._max_facts = max_facts
        self._facts: dict[str, Fact] = {}
        self._entities: dict[str, Entity] = {}
        self._relationships: list[Relationship] = []
        self._digested: int = 0
        self._absorbed: int = 0
        self._excreted: int = 0
        self._t0 = time.time()

    # ── PRIMARY INTERFACE ──

    def digest(self, fragments: list) -> Knowledge:
        """Break down raw fragments into structured Knowledge.

        Each fragment is analyzed for information density (nutritional
        value). Entities, relationships, and atomic facts are extracted.
        This does NOT store anything — call absorb() to commit.
        """
        all_entities: list[Entity] = []
        all_relationships: list[Relationship] = []
        all_facts: list[Fact] = []
        source_keys: list[str] = []
        total_nutrition = 0.0

        for frag in fragments:
            content = frag.content if hasattr(frag, 'content') else str(frag)
            key = frag.key if hasattr(frag, 'key') else hashlib.sha256(
                str(frag).encode()).hexdigest()[:12]

            nutrition = _information_density(content)
            total_nutrition += nutrition

            # Extract entities
            entities = _extract_entities_simple(content)
            all_entities.extend(entities)

            # Extract relationships
            rels = _extract_relationships_simple(content, entities)
            for r in rels:
                r.source_key = key
            all_relationships.extend(rels)

            # Create atomic facts from sentences with high info density
            sentences = re.split(r'(?<=[.!?])\s+', content)
            for sent in sentences:
                sent = sent.strip()
                if len(sent) < 10:
                    continue
                sent_density = _information_density(sent)
                if sent_density > 0.15:
                    fact_key = f"gut:{hashlib.sha256(sent.encode()).hexdigest()[:10]}"
                    all_facts.append(Fact(
                        key=fact_key,
                        content=sent,
                        confidence=min(0.9, sent_density + 0.2),
                        nutritional_value=sent_density,
                    ))

            source_keys.append(key)

        avg_nutrition = total_nutrition / max(len(fragments), 1)
        self._digested += len(fragments)

        return Knowledge(
            entities=all_entities,
            relationships=all_relationships,
            facts=all_facts,
            source_keys=source_keys,
            nutritional_value=avg_nutrition,
        )

    def absorb(self, knowledge: Knowledge) -> int:
        """Commit digested knowledge to long-term storage.

        Merges entities (reinforcing duplicates), appends relationships,
        and stores facts. Returns the number of new facts absorbed.
        """
        new_count = 0

        # Merge entities
        for entity in knowledge.entities:
            if entity.name in self._entities:
                self._entities[entity.name].reinforce()
            else:
                self._entities[entity.name] = entity

        # Append relationships (dedup by triple)
        existing_triples = {r.triple for r in self._relationships}
        for rel in knowledge.relationships:
            if rel.triple not in existing_triples:
                self._relationships.append(rel)
                existing_triples.add(rel.triple)

        # Store facts
        for fact in knowledge.facts:
            if fact.key not in self._facts:
                self._facts[fact.key] = fact
                new_count += 1
            else:
                self._facts[fact.key].access()

        # Evict if over capacity
        self._evict()
        self._absorbed += new_count
        return new_count

    def excrete(self, threshold: Optional[float] = None) -> int:
        """Purge stale and low-value knowledge.

        Removes facts whose staleness exceeds the threshold.
        Returns the number of facts excreted.
        """
        cutoff = threshold if threshold is not None else self._staleness_threshold
        before = len(self._facts)

        to_remove = [
            key for key, fact in self._facts.items()
            if fact.staleness > cutoff and fact.nutritional_value < 0.5
        ]
        for key in to_remove:
            del self._facts[key]

        purged = before - len(self._facts)
        self._excreted += purged
        return purged

    # ── QUERIES ──

    def recall(self, query: str, limit: int = 10) -> list[Fact]:
        """Search stored facts by substring match. Returns best matches."""
        query_lower = query.lower()
        matches = [
            f for f in self._facts.values()
            if query_lower in f.content.lower()
        ]
        # Sort by nutritional value * confidence, descending
        matches.sort(key=lambda f: f.nutritional_value * f.confidence, reverse=True)
        for f in matches[:limit]:
            f.access()
        return matches[:limit]

    def get_entities(self, entity_type: Optional[str] = None) -> list[Entity]:
        """List known entities, optionally filtered by type."""
        entities = list(self._entities.values())
        if entity_type:
            entities = [e for e in entities if e.entity_type == entity_type]
        return sorted(entities, key=lambda e: e.mentions, reverse=True)

    def get_relationships(self, subject: Optional[str] = None) -> list[Relationship]:
        """List known relationships, optionally filtered by subject."""
        if subject:
            return [r for r in self._relationships if r.subject == subject]
        return list(self._relationships)

    # ── INTERNALS ──

    def _evict(self) -> None:
        """Evict lowest-value facts if over capacity."""
        while len(self._facts) > self._max_facts:
            worst_key = min(
                self._facts,
                key=lambda k: self._facts[k].nutritional_value * (1.0 - self._facts[k].staleness),
            )
            del self._facts[worst_key]
            self._excreted += 1

    # ── STATS ──

    @property
    def stats(self) -> dict:
        avg_nutrition = 0.0
        if self._facts:
            avg_nutrition = sum(f.nutritional_value for f in self._facts.values()) / len(self._facts)
        return {
            "facts_stored": len(self._facts),
            "entities_known": len(self._entities),
            "relationships": len(self._relationships),
            "digested_fragments": self._digested,
            "absorbed_facts": self._absorbed,
            "excreted_facts": self._excreted,
            "avg_nutritional_value": round(avg_nutrition, 4),
            "uptime_s": round(time.time() - self._t0, 1),
        }
