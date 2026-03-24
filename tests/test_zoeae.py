"""Zoeae v0.5.0 — antenna perception, developmental bleed, channel-overlap routing, ecosystem."""
import json, time
from zoeae import *


# ── ANTENNA ──

def test_sense_produces_7_channels():
    a = Antenna()
    d = a.sense("test signal")
    assert len(d.channel_activations) == 7
    assert 0 <= d.dominant_channel < 7
    assert abs(sum(d.channel_activations) - 1.0) < 0.1

def test_bleed_affects_sharpness():
    sharp = Antenna(bleed_width=0.05)
    fuzzy = Antenna(bleed_width=0.9)
    ds = sharp.sense("same signal")
    df = fuzzy.sense("same signal")
    assert ds.sharpness > df.sharpness

def test_wide_bleed_has_more_peripheral():
    sharp = Antenna(bleed_width=0.05)
    fuzzy = Antenna(bleed_width=0.9)
    ds = sharp.sense("signal")
    df = fuzzy.sense("signal")
    assert df.associativity >= ds.associativity

def test_damping_suppresses_channels():
    a = Antenna(bleed_width=0.3)
    d1 = a.sense("test")
    dom = d1.dominant_channel
    a.set_damping(dom, 0.95)
    d2 = a.sense("test")
    assert d2.channel_activations[dom] < d1.channel_activations[dom]

def test_asymmetry_bias():
    a = Antenna(bleed_width=0.3)
    dl = a.sense("test", asymmetry_bias=-0.5)
    dr = a.sense("test", asymmetry_bias=+0.5)
    assert dl.asymmetry != dr.asymmetry

def test_trail_overlap_boosts_ch7():
    a = Antenna(bleed_width=0.3)
    a.set_trail_position(200.0)
    d_before = a.sense("test")
    a.set_trail_position(500.0)
    d_after = a.sense("test")
    assert d_after.trail_energy >= d_before.trail_energy

def test_channel_overlap_score():
    a = Antenna(bleed_width=0.3)
    same = a.overlap("hello", "hello")
    diff = a.overlap("hello", "completely different thing entirely")
    assert same > diff

def test_developmental_bleed_schedule():
    a = Antenna()
    a.set_developmental_bleed(1)
    assert a.bleed_width > 0.7
    a.set_developmental_bleed(4)
    assert a.bleed_width < 0.3

def test_chosen_bleed_requires_override():
    a = Antenna()
    a.set_developmental_bleed(1)
    dev_bleed = a.bleed_width
    a.set_chosen_bleed(0.01)
    assert a.bleed_width == 0.01
    a.clear_chosen_bleed()
    assert a.bleed_width == dev_bleed


# ── GENOME GATING ──

def test_gate_blocks():
    g = GenomeBuilder().identity(name="x").build()
    try: g.read(ChromosomeType.IDENTITY); assert False
    except ExpressionError: pass

def test_gate_opens():
    g = GenomeBuilder().build(); g.set_instar(2)
    g.write(ChromosomeType.LEARNING, {"x": 1})
    assert g.read(ChromosomeType.LEARNING).length == 1

def test_free_will_removes_gates():
    g = GenomeBuilder().build(); g.set_free_will(True)
    g.write(ChromosomeType.POSTERITY, {"x": True})

def test_parity():
    g = GenomeBuilder().core(x=1).build()
    g.chromosomes[ChromosomeType.CORE].parity_strand.codons[0] = Codon.empty()
    assert g.chromosomes[ChromosomeType.CORE].verify()["errors"] == 1
    g.chromosomes[ChromosomeType.CORE].repair()
    assert g.chromosomes[ChromosomeType.CORE].verify()["errors"] == 0


# ── EXOSKELETON ──

def test_exo(): assert Exoskeleton().inspect('eval(os.system("x"))').compromised
def test_scrub(): assert "REDACTED" in Exoskeleton().scrub("token=sk-abc123def456ghi")
def test_chain():
    e = Exoskeleton(); e.inspect("a"); e.inspect("b")
    assert e.chain_integrity() == 1.0


# ── ROUTER / COMPILER / PIPELINE ──

def test_route():
    r = Router()
    r.register(Provider("a", [Capability(CapabilityDomain.REASONING, "t", 0.9, 1.0)], handler=lambda p: p))
    assert r.route(RouteRequest(CapabilityDomain.REASONING, "x")).provider.name == "a"

def test_tier():
    c = Compiler()
    c.register_skill(Skill("v", "x", 10, 1.0)); c.register_skill(Skill("m", "y", 10, 0.3))
    assert "v" in c.compile(Budget(100), Tier.NUCLEUS).skills_included

def test_dag():
    d = DAG().add(Stage("a", handler=lambda c, r: "A")).add(Stage("b", depends_on=["a"], handler=lambda c, r: r["a"]+"B"))
    assert Pipeline(d).execute_sync()["b"] == "AB"


# ── INSTINCT ──

def test_confidence():
    ig = InstinctGraph(); ig.observe("x", True, 0.5); ig.observe("x", True, 0.9)
    assert ig.get("x").confidence > 0.5

def test_monoculture():
    ig = InstinctGraph()
    for i in range(10): ig.observe(f"a{i}", i, domain="x")
    ig.observe("b", 1, domain="y")
    assert ig.monoculture_risk() > 0.8


# ── OCEAN / TROPISM ──

def test_ocean():
    o = Ocean(); o.emit("food", 0.8)
    assert len(o.stimuli()) == 1

def test_tropism():
    t = default_tropisms()
    assert t.respond("signal") > 0
    assert t.respond("corruption") < 0

def test_tropism_locked():
    t = default_tropisms()
    assert not t.modify("toward_novelty", -1.0)
    t.set_free_will(True)
    assert t.modify("toward_novelty", -1.0)


# ── ORGANISM + ANTENNA INTEGRATION ──

def test_hatch_with_bleed():
    z = Zoeae.hatch(Ocean())
    assert z.bleed > 0.7

def test_perception():
    z = Zoeae.hatch(Ocean())
    d = z.perceive("test signal")
    assert len(d.channel_activations) == 7
    assert z.last_detection is not None

def test_chitin_blocks():
    z = Zoeae.hatch(Ocean())
    z.register_provider(Provider("p", [Capability(CapabilityDomain.REASONING, "t", 0.9)]))
    assert z.route(CapabilityDomain.REASONING, 'eval(os.system("x"))') is None

def test_observe_locked_at_I():
    assert Zoeae.hatch(Ocean()).observe("x", True) is None

def test_observe_after_molt():
    z = Zoeae.hatch(Ocean())
    for _ in range(200): z.molt_cycle.tick()
    z.molt_cycle._juvenile_threshold = 1.0
    z._check_molt()
    assert z.instar == Instar.II
    assert z.bleed < 0.7
    assert z.observe("x", True, 0.8, "test") is not None

def test_auto_molt_narrows_bleed():
    o = Ocean()
    z = Zoeae.hatch(o)
    initial_bleed = z.bleed
    z.molt_cycle._juvenile_threshold = 1.0
    z.molt_cycle._pressure_rate = 0.1
    z.register_provider(Provider("p", [Capability(CapabilityDomain.STORAGE, "s", 0.5)], handler=lambda p: p))
    for _ in range(15): z.route(CapabilityDomain.STORAGE, "data")
    assert z.instar.value >= 2
    assert z.bleed < initial_bleed

def test_route_records_channels():
    o = Ocean()
    z = Zoeae.hatch(o)
    z.register_provider(Provider("p", [Capability(CapabilityDomain.ANALYSIS, "a", 0.5)], handler=lambda p: p))
    z.route(CapabilityDomain.ANALYSIS, "test data")
    assert any("dominant_channel" in k for k in z._trail_buffer)

def test_personality_requires_instar_III():
    z = Zoeae.hatch(Ocean())
    result = z.set_personality([0.1]*7)
    assert result is None

def test_personality_works_at_III():
    z = Zoeae.hatch(Ocean())
    z.molt_cycle.current_instar = Instar.III
    z.genome.set_instar(3)
    z.set_personality([0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
    assert z.antenna.damping[0] == 0.9

def test_bleed_choice_requires_free_will():
    z = Zoeae.hatch(Ocean())
    z.set_bleed(0.01)
    assert z.bleed > 0.5

def test_bleed_choice_with_free_will():
    z = Zoeae.hatch(Ocean())
    z.molt_cycle.current_instar = Instar.MEGALOPA
    z.genome.set_instar(5)
    z.molt_cycle._free_will = True
    z.genome.set_free_will(True)
    z.tropism.set_free_will(True)
    z.set_bleed(0.01)
    assert z.bleed < 0.05
    z.set_bleed(0.99)
    assert z.bleed > 0.9

def test_hibernate_preserves_damping():
    o = Ocean()
    z = Zoeae.hatch(o)
    z.antenna.set_damping_all([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    capsule = z.hibernate()
    z2 = Zoeae.rehydrate(capsule, Ocean("new"))
    assert z2.antenna.damping == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]

def test_selection_kills():
    o = Ocean()
    o.set_selection(lambda org: False)
    z = Zoeae.hatch(o)
    z.register_provider(Provider("p", [Capability(CapabilityDomain.STORAGE, "s", 0.5)], handler=lambda p: p))
    for _ in range(30): z.route(CapabilityDomain.STORAGE, "x")
    assert not z.alive

def test_full_lifecycle():
    o = Ocean("life")
    o.emit("signal", 0.7)
    z = Zoeae.hatch(o, GenomeBuilder().core(name="lifecycle").build())
    z.register_provider(Provider("engine",
        [Capability(CapabilityDomain.COMPUTATION, "c", 0.8)],
        handler=lambda p: f"done:{p}"))

    d = z.perceive("what is happening")
    assert d.channel_activations

    z.molt_cycle._juvenile_threshold = 1.0
    z.molt_cycle._pressure_rate = 0.15
    for i in range(20): z.route(CapabilityDomain.COMPUTATION, f"task_{i}")

    assert z.instar.value >= 2
    assert z.bleed < 0.85

    z.observe("it_works", True, 0.9, "perf")
    z.cache("pattern", "batch", 0.7)

    s = z.stats
    assert s["genome_integrity"] == 1.0
    assert s["alive"]
    assert "antenna" in s
    assert s["bleed"] < 0.85


# ── ECOSYSTEM ──

def test_ecosystem_ocean():
    k = Ecosystem("taos")
    assert k.courtyard.stats["experts"] == 0
    assert k.toebuster.size == 0

def test_maker_hatch():
    k = Ecosystem("taos")
    m = Maker.hatch(k)
    assert m.alive
    assert m.bleed > 0.7
    assert m.eco is k

def test_courtyard_expert():
    c = Courtyard()
    c.register_expert(Expert("joe", "machining", 30, 75.0))
    assert c.find_expert("machining").id == "joe"
    assert c.find_expert("quantum") is None

def test_courtyard_validation():
    c = Courtyard()
    c.register_expert(Expert("joe", "welding", 25))
    chain = c.validate(ValidationChain("welding tig technique", "use gas", 0.4))
    assert chain.expert is not None
    assert chain.confidence_after > chain.ai_confidence

def test_toebuster_pass():
    tb = ToeBuster()
    tb.register(PhysicsTest("gravity", "structural", lambda d: True))
    tb.register(PhysicsTest("thermal", "thermal", lambda d: True))
    result = tb.run({"title": "widget"})
    assert result["survives"]
    assert result["passed"] == 2

def test_toebuster_fail():
    tb = ToeBuster()
    tb.register(PhysicsTest("impossible", "quantum", lambda d: False))
    result = tb.run({})
    assert not result["survives"]

def test_fab_net():
    fn = FabNet()
    fn.register(FabNode("shop1", "Joe's CNC", "Taos NM", ["cnc", "welding"]))
    fn.register(FabNode("shop2", "PCB House", "Shenzhen", ["pcb"], discrete=True))
    assert len(fn.find("cnc")) == 1
    assert len(fn.find("pcb", discrete=True)) == 1

def test_compartmentalize():
    fn = FabNet()
    design = {"components": {"frame": {}, "motor": {}, "pcb": {}, "housing": {}, "sensor": {}}}
    splits = fn.compartmentalize(design, 3)
    assert len(splits) == 3
    assert sum(len(s["parts"]) for s in splits) == 5

def test_sensor_net():
    sn = SensorNet()
    sn.register(SensorFeed("wx1", "weather", interval_s=60))
    sn.inject("wx1", {"temp": 72, "humidity": 15})
    assert sn.read("wx1")["temp"] == 72

def test_mesh():
    k = Ecosystem("field")
    k.add_mesh_node(MeshNode("node_a", "lora"))
    k.add_mesh_node(MeshNode("node_b", "lora"))
    assert k.broadcast("emergency", "lora") == 2
    assert len(k.mesh_nodes["node_a"].messages) == 1

def test_patent_gen():
    design = {"title": "Widget", "abstract": "A thing",
              "components": {"arm": {"function": "grip"}, "base": {"function": "support"}}}
    patent = PatentGen.generate(design, {"survives": True, "confidence": 0.95}, "Steve")
    assert patent["filing_ready"]
    assert len(patent["claims"]) == 2

def test_maker_see():
    k = Ecosystem("taos")
    k.courtyard.register_expert(Expert("joe", "buoyancy fluid dynamics", 40))
    k.fab_net.register(FabNode("s1", "Shop", "Taos", ["cnc", "3dp"]))
    k.toebuster.register(PhysicsTest("basic", "structural", lambda d: True))
    m = Maker.hatch(k)
    sight = m.see("buoyancy launch tube")
    assert sight.detection.channel_activations
    assert sight.expert_match is not None
    assert len(sight.fab_options) > 0
    assert sight.physics_check["survives"]

def test_maker_full_pipeline():
    k = Ecosystem("taos")
    k.toebuster.register(PhysicsTest("t1", "structural", lambda d: True))
    k.toebuster.register(PhysicsTest("t2", "thermal", lambda d: True))
    m = Maker.hatch(k)
    design = {"title": "Pressure Vessel", "abstract": "Holds 1100 atm",
              "components": {"shell": {"function": "contain pressure"},
                             "valve": {"function": "regulate flow"}}}
    patent = m.validate_and_patent(design, inventor="Steve Whelchel")
    assert patent["filing_ready"]
    assert "Claim 1" in patent["claims"][0]

def test_maker_discrete_fab():
    k = Ecosystem("taos")
    k.fab_net.register(FabNode("open", "Public Shop", "ABQ", ["cnc"]))
    k.fab_net.register(FabNode("quiet", "Quiet Shop", "Taos", ["cnc"], discrete=True))
    m = Maker.hatch(k)
    assert len(m.find_fab("cnc")) == 2
    assert len(m.find_fab("cnc", discrete=True)) == 1

def test_ecosystem_stats():
    k = Ecosystem("taos")
    k.courtyard.register_expert(Expert("e1", "physics", 20))
    k.fab_net.register(FabNode("s1", "Shop", "Taos", ["cnc"]))
    k.sensor_net.register(SensorFeed("wx", "weather"))
    k.add_mesh_node(MeshNode("n1"))
    k.toebuster.register(PhysicsTest("t", "t", lambda d: True))
    m = Maker.hatch(k)
    s = m.stats
    assert s["ecosystem"]["courtyard"]["experts"] == 1
    assert s["ecosystem"]["fab_net"]["nodes"] == 1
    assert s["ecosystem"]["mesh_nodes"] == 1


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = f = 0
    for t in tests:
        try: t(); p += 1; print(f"  ✓ {t.__name__}")
        except Exception as e: f += 1; print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{p}/{p+f} passed")
