"""
Zoeae — A Living Orchestration Runtime. v0.5.0

Sensory perception through a 7-channel antenna array with developmental bleed.
Bleed narrows with development. Damping is personality. The trail is memory.

    ocean = Ocean("production")
    z = Zoeae.hatch(ocean, GenomeBuilder().core(name="x").build())
"""
__version__ = "0.5.0"

from .genome import (Genome, Chromosome, Strand, Codon, GenomeBuilder,
                     ChromosomeType, CodonState, StrandType, ExpressionError)
from .exoskeleton import Exoskeleton, Integrity, Provenance, IntegrityLevel, ThreatClass
from .router import Router, Capability, Provider, CapabilityDomain, RouteRequest, RouteResult
from .compiler import Compiler, Budget, Tier, Skill, CompiledContext
from .pipeline import Pipeline, Stage, DAG, StageStatus
from .instinct import InstinctGraph, Belief
from .accumulator import Accumulator, Fragment, Explorer, Frontier, DiversityAnalyzer
from .telemetry import Telemetry, Event, EventLevel
from .molt import MoltCycle, Instar, Exuvium
from .ocean import Ocean, Stimulus, Reflection
from .tropism import Tropism, Drive, default_tropisms
from .antenna import Antenna, Detection, CHANNEL_NAMES
from .organism import Zoeae
from .crab import Crab
from .ecosystem import (Ecosystem, Maker, Sight, Courtyard, Expert, ValidationChain,
                      ToeBuster, PhysicsTest, FabNet, FabNode, SensorNet, SensorFeed,
                      PatentGen, MeshNode, EcoDomain)
from .messenger import (on_message, send_to_phone, get_inbox, get_lan_ip,
                        start_server as start_messenger)
from .brain import Brain, Thought, ReasoningMode, OllamaBackend, AnthropicBackend, HTTPBackend
from .feeds import EcoFlowFeed, SolarFeed
from . import shoes
from .mouth import Mouth
from .gill import Gill, BudgetDecision
from .heart import Heart, HeartbeatEvent
from .hands import Hands, ActionResult
from .swim import Swim, Plan, Step
from .tail import Tail, TailEvent
from .spawn import Spawn, Clutch
from .gut import Gut, Knowledge, Entity, Relationship, Fact
from .eye import Eye, ScanResult, Threat, Opportunity, DetailedView
from .nerve import Nerve, Signal, SignalLog
from .blood import Blood, HemolymphCell
from .muscle import Muscle, FlexResult
from .shell import Shell, SpikeDecision, AttackPattern

__all__ = [
    # genome
    "Genome", "Chromosome", "Strand", "Codon", "GenomeBuilder",
    "ChromosomeType", "CodonState", "StrandType", "ExpressionError",
    # exoskeleton
    "Exoskeleton", "Integrity", "Provenance", "IntegrityLevel", "ThreatClass",
    # router
    "Router", "Capability", "Provider", "CapabilityDomain", "RouteRequest", "RouteResult",
    # compiler
    "Compiler", "Budget", "Tier", "Skill", "CompiledContext",
    # pipeline
    "Pipeline", "Stage", "DAG", "StageStatus",
    # instinct
    "InstinctGraph", "Belief",
    # accumulator
    "Accumulator", "Fragment", "Explorer", "Frontier", "DiversityAnalyzer",
    # telemetry
    "Telemetry", "Event", "EventLevel",
    # molt
    "MoltCycle", "Instar", "Exuvium",
    # ocean
    "Ocean", "Stimulus", "Reflection",
    # tropism
    "Tropism", "Drive", "default_tropisms",
    # antenna
    "Antenna", "Detection", "CHANNEL_NAMES",
    # organism
    "Zoeae",
    # crab
    "Crab",
    # ecosystem
    "Ecosystem", "Maker", "Sight", "Courtyard", "Expert", "ValidationChain",
    "ToeBuster", "PhysicsTest", "FabNet", "FabNode", "SensorNet", "SensorFeed",
    "PatentGen", "MeshNode", "EcoDomain",
    # brain
    "Brain", "Thought", "ReasoningMode",
    "OllamaBackend", "AnthropicBackend", "HTTPBackend",
    # feeds
    "EcoFlowFeed", "SolarFeed",
    # mouth
    "Mouth",
    # gill
    "Gill", "BudgetDecision",
    # heart
    "Heart", "HeartbeatEvent",
    # hands
    "Hands", "ActionResult",
    # swim
    "Swim", "Plan", "Step",
    # tail
    "Tail", "TailEvent",
    # spawn
    "Spawn", "Clutch",
    # gut
    "Gut", "Knowledge", "Entity", "Relationship", "Fact",
    # eye
    "Eye", "ScanResult", "Threat", "Opportunity", "DetailedView",
    # nerve
    "Nerve", "Signal", "SignalLog",
    # blood
    "Blood", "HemolymphCell",
    # muscle
    "Muscle", "FlexResult",
    # shell
    "Shell", "SpikeDecision", "AttackPattern",
]
