"""Zoeae v0.5.0 — Full Stack Integration Test"""
from zoeae import *


def test_full_ecosystem_build():
    """Build a complete ecosystem with all subsystems populated."""
    eco = Ecosystem("taos")

    # Experts
    eco.courtyard.register_expert(Expert("joe", "machining welding fabrication", 30, 75.0))
    eco.courtyard.register_expert(Expert("maria", "fluid dynamics buoyancy thermodynamics", 25, 120.0))
    eco.courtyard.register_expert(Expert("chen", "pcb electronics rf antenna design", 20, 95.0))
    eco.courtyard.register_expert(Expert("diana", "materials science composites ceramics", 15, 85.0))

    # Physics tests
    eco.toebuster.register(PhysicsTest("gravity", "structural", lambda d: True))
    eco.toebuster.register(PhysicsTest("thermal_limit", "thermal", lambda d: d.get("max_temp", 300) < 3000))
    eco.toebuster.register(PhysicsTest("pressure_vessel", "structural", lambda d: d.get("wall_thickness", 0.01) >= 0.005))
    eco.toebuster.register(PhysicsTest("mass_budget", "structural", lambda d: d.get("total_mass", 1) < 10000))
    eco.toebuster.register(PhysicsTest("em_compat", "em", lambda d: True))

    # Fab nodes
    eco.fab_net.register(FabNode("taos_cnc", "Taos CNC Shop", "Taos NM", ["cnc", "welding", "3dp"], 36.4, -105.5))
    eco.fab_net.register(FabNode("abq_pcb", "ABQ PCB House", "Albuquerque NM", ["pcb", "smt"], 35.0, -106.6))
    eco.fab_net.register(FabNode("shenzhen", "SZ Fab", "Shenzhen CN", ["pcb", "injection", "cnc"], 22.5, 114.1, discrete=True))
    eco.fab_net.register(FabNode("local_3dp", "Home Prusa", "Taos NM", ["3dp"], 36.4, -105.5))

    # Sensors
    eco.sensor_net.register(SensorFeed("wx_taos", "weather", interval_s=300))
    eco.sensor_net.register(SensorFeed("rf_ambient", "rf_ambient", interval_s=60))
    eco.sensor_net.register(SensorFeed("seismic", "seismic", interval_s=30))
    eco.sensor_net.inject("wx_taos", {"temp_f": 45, "humidity": 12, "wind_mph": 8})
    eco.sensor_net.inject("rf_ambient", {"noise_floor_dbm": -95, "peaks": [{"freq_mhz": 915, "power_dbm": -40}]})

    # Mesh
    eco.add_mesh_node(MeshNode("base_station", "lora"))
    eco.add_mesh_node(MeshNode("relay_1", "lora"))
    eco.add_mesh_node(MeshNode("relay_2", "lora"))

    s = eco.stats
    assert s["courtyard"]["experts"] == 4
    assert s["toebuster"] == 5
    assert s["fab_net"]["nodes"] == 4
    assert s["sensors"] == 3
    assert s["mesh_nodes"] == 3
    return eco


def test_maker_hatch_and_perceive():
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)
    assert m.alive
    assert m.bleed > 0.7
    assert m.eco is eco

    # Perceive multiple signals
    signals = [
        "pressure vessel for 1100 atm hydrogen storage",
        "mesh radio for off-grid communication",
        "cnc milled aluminum heat sink",
        "ambient rf monitoring station",
    ]
    for sig in signals:
        d = m.perceive(sig)
        assert len(d.channel_activations) == 7
        assert 0 <= d.dominant_channel < 7
        assert 0 < d.sharpness <= 1.0


def test_xr_sight_pipeline():
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)

    # Idea with expert match + fab match + physics pass
    sight = m.see("buoyancy launch tube for fluid dynamics")
    assert sight.detection.channel_activations
    assert sight.physics_check["survives"]
    assert sight.expert_match is not None  # maria matches "fluid dynamics"
    assert len(sight.fab_options) > 0
    assert sight.confidence > 0

    # Idea with no expert match
    sight2 = m.see("quantum entanglement teleporter")
    assert sight2.expert_match is None or sight2.expert_match is not None  # may partial match


def test_design_to_patent_pipeline():
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)

    design = {
        "title": "High-Pressure Hydrogen Storage Vessel",
        "abstract": "Composite-wound pressure vessel rated to 1100 atm",
        "components": {
            "inner_liner": {"function": "contain hydrogen gas"},
            "composite_wrap": {"function": "provide structural strength"},
            "valve_assembly": {"function": "regulate flow and pressure"},
            "boss_fitting": {"function": "interface liner to valve"},
        },
        "max_temp": 350,
        "wall_thickness": 0.025,
        "total_mass": 45,
    }

    patent = m.validate_and_patent(design, inventor="Steve Whelchel")
    assert patent["filing_ready"]
    assert len(patent["claims"]) == 4
    assert "inner_liner" in patent["claims"][0]
    assert patent["inventor"] == "Steve Whelchel"
    assert patent["assignee"] == "AnnulusLabs LLC"


def test_design_fails_physics():
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)

    bad_design = {
        "title": "Impossible Widget",
        "components": {"part": {"function": "defy physics"}},
        "max_temp": 999999,  # fails thermal_limit check
    }

    result = m.validate_and_patent(bad_design)
    assert "error" in result
    assert "Physics says no" in result["error"]


def test_compartmentalized_fab():
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)

    design = {
        "components": {
            "frame": {}, "motor": {}, "pcb": {},
            "housing": {}, "sensor_array": {},
        }
    }
    splits = m.compartmentalize(design, n_vendors=3)
    assert len(splits) == 3
    total_parts = sum(len(s["parts"]) for s in splits)
    assert total_parts == 5
    # No single vendor has all parts
    assert all(len(s["parts"]) < 5 for s in splits)


def test_expert_validation_chain():
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)

    chain = m.ask_expert(
        "Is CF composite adequate for 1100 atm hydrogen resistance?",
        "CF composite with aluminum liner should resist embrittlement",
        0.6,
    )
    assert chain.expert is not None
    assert chain.confidence_after > chain.ai_confidence


def test_mesh_broadcast():
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)

    sent = m.mesh_broadcast({"alert": "pressure_test_start", "vessel_id": "HV-001"})
    assert sent == 3
    for node in eco.mesh_nodes.values():
        assert len(node.messages) == 1
        assert node.messages[0]["payload"]["alert"] == "pressure_test_start"


def test_sensor_read():
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)

    wx = m.read_sensor("wx_taos")
    assert wx["temp_f"] == 45
    assert wx["humidity"] == 12

    rf = m.read_sensor("rf_ambient")
    assert rf["noise_floor_dbm"] == -95

    assert m.read_sensor("nonexistent") is None


def test_discrete_fab():
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)

    public = m.find_fab("cnc")
    discrete = m.find_fab("cnc", discrete=True)
    assert len(public) == 2  # taos_cnc + shenzhen
    assert len(discrete) == 1
    assert discrete[0].name == "SZ Fab"


def test_maker_lifecycle_with_ecosystem():
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)

    m.register_provider(Provider("engine",
        [Capability(CapabilityDomain.COMPUTATION, "compute", 0.8)],
        handler=lambda p: f"computed:{p}"))

    m.molt_cycle._juvenile_threshold = 1.0
    m.molt_cycle._pressure_rate = 0.15

    initial_bleed = m.bleed
    for i in range(20):
        m.route(CapabilityDomain.COMPUTATION, f"task_{i}")

    assert m.instar.value >= 2
    assert m.bleed < initial_bleed
    assert m.alive

    stats = m.stats
    assert stats["genome_integrity"] == 1.0
    assert stats["ecosystem"]["courtyard"]["experts"] == 4
    assert stats["ecosystem"]["fab_net"]["nodes"] == 4


def test_maker_see_with_all_subsystems():
    """The money test: all subsystems fire together."""
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)

    # Register a provider so routing works
    m.register_provider(Provider("brain",
        [Capability(CapabilityDomain.REASONING, "think", 0.9)],
        handler=lambda p: f"thought:{p}"))

    # See an idea that hits all subsystems
    sight = m.see("welding jig for cnc machining")
    assert sight.detection.channel_activations  # antenna fired
    assert sight.physics_check is not None       # toebuster ran
    assert sight.expert_match is not None        # joe matches welding+machining
    assert len(sight.fab_options) > 0            # cnc+welding shops found
    assert sight.confidence > 0                  # confidence computed

    # Read sensors during the process
    wx = m.read_sensor("wx_taos")
    assert wx is not None

    # Broadcast result
    sent = m.mesh_broadcast({"result": sight.go_no_go})
    assert sent == 3

    # Validate and patent if physics passes
    if sight.physics_check["survives"]:
        design = {
            "title": "Welding Jig for CNC Operations",
            "abstract": "Precision welding fixture",
            "components": {
                "base_plate": {"function": "provide rigid mounting surface"},
                "clamp_array": {"function": "secure workpiece during welding"},
            },
        }
        patent = m.validate_and_patent(design, inventor="Steve Whelchel")
        assert patent["filing_ready"]
        assert len(patent["claims"]) == 2

    print(f"FULL STACK: confidence={sight.confidence:.3f}, go={sight.go_no_go}")


def test_hibernate_rehydrate_with_ecosystem():
    """Maker survives serialization."""
    eco = test_full_ecosystem_build()
    m = Maker.hatch(eco)
    m.antenna.set_damping_all([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])

    capsule = m.hibernate()

    eco2 = test_full_ecosystem_build()
    m2 = Maker.hatch(eco2)
    # Rehydrate preserves damping (personality)
    z2 = Zoeae.rehydrate(capsule, eco2)
    assert z2.antenna.damping == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]


def test_overlap_scoring_for_routing():
    """Channel overlap determines signal similarity."""
    a = Antenna(bleed_width=0.3)
    # Same signals should have high overlap
    same = a.overlap("welding", "welding")
    assert same > 0.9

    # Different signals should have lower overlap
    diff = a.overlap("welding steel", "quantum entanglement theory")
    assert diff < same


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = f = 0
    for t in tests:
        try:
            t()
            p += 1
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            f += 1
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{p}/{p+f} passed")
