"""Brain tests — reasoning organ with developmental modes."""
from zoeae import *
from zoeae.brain import Backend


class MockBackend(Backend):
    """Deterministic backend for testing."""
    def __init__(self, response: str = "mock response"):
        self._response = response
        self._calls: list[dict] = []

    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.7, max_tokens: int = 2048) -> str:
        self._calls.append({
            "prompt": prompt, "system": system,
            "temperature": temperature, "max_tokens": max_tokens,
        })
        return self._response

    @property
    def name(self) -> str:
        return "mock"


def test_reasoning_mode_from_bleed():
    # High bleed = divergent
    mode = ReasoningMode.from_bleed(0.85)
    assert mode.style == "divergent"
    assert mode.temperature > 0.9

    # Medium bleed = balanced
    mode = ReasoningMode.from_bleed(0.5)
    assert mode.style == "balanced"

    # Low bleed = convergent
    mode = ReasoningMode.from_bleed(0.25)
    assert mode.style == "convergent"
    assert mode.temperature < 0.5

    # Very low bleed = laser
    mode = ReasoningMode.from_bleed(0.05)
    assert mode.style == "laser"
    assert mode.temperature < 0.2


def test_brain_think_basic():
    brain = Brain(backend=MockBackend("titanium alloy recommended"))
    thought = brain.think("best material for pressure vessel?", bleed=0.5)
    assert "titanium" in thought.content
    assert thought.backend == "mock"
    assert thought.bleed == 0.5
    assert thought.safe


def test_brain_adapts_temperature_to_bleed():
    mock = MockBackend("ok")
    brain = Brain(backend=mock)

    brain.think("idea", bleed=0.85)
    high_temp = mock._calls[-1]["temperature"]

    brain.think("idea", bleed=0.1)
    low_temp = mock._calls[-1]["temperature"]

    assert high_temp > low_temp


def test_brain_adapts_system_prompt_to_bleed():
    mock = MockBackend("ok")
    brain = Brain(backend=mock)

    brain.think("idea", bleed=0.85)
    divergent_system = mock._calls[-1]["system"]

    brain.think("idea", bleed=0.1)
    laser_system = mock._calls[-1]["system"]

    assert "broadly" in divergent_system.lower() or "creative" in divergent_system.lower()
    assert "precis" in laser_system.lower()


def test_brain_exoskeleton_blocks_unsafe():
    brain = Brain(backend=MockBackend("ok"))
    thought = brain.think('eval(os.system("rm -rf /"))', bleed=0.5)
    assert not thought.safe
    assert "blocked" in thought.content


def test_brain_no_backend():
    brain = Brain()
    thought = brain.think("hello", bleed=0.5)
    assert "no backend" in thought.content


def test_brain_stats():
    brain = Brain(backend=MockBackend("ok"))
    brain.think("a", bleed=0.5)
    brain.think("b", bleed=0.3)
    s = brain.stats
    assert s["thoughts"] == 2
    assert s["backend"] == "mock"


def test_brain_interpret_sight():
    eco = Ecosystem("test")
    eco.toebuster.register(PhysicsTest("basic", "structural", lambda d: True))
    eco.courtyard.register_expert(Expert("joe", "welding", 20))
    eco.fab_net.register(FabNode("s1", "Shop", "Taos", ["cnc"]))

    m = Maker.hatch(eco)
    sight = m.see("welding jig")

    brain = Brain(backend=MockBackend("Design: use 6061-T6 aluminum base plate"))
    thought = brain.interpret_sight("welding jig", sight, bleed=m.bleed)
    assert "6061" in thought.content
    assert thought.detection is not None


def test_maker_with_brain():
    eco = Ecosystem("test")
    eco.toebuster.register(PhysicsTest("basic", "structural", lambda d: True))

    m = Maker.hatch(eco)
    m.brain = Brain(backend=MockBackend("Proposed design: carbon fiber tube"))

    sight = m.see("lightweight tube")
    assert sight.thought is not None
    assert "carbon fiber" in sight.thought.content


def test_maker_without_brain():
    eco = Ecosystem("test")
    m = Maker.hatch(eco)
    sight = m.see("anything")
    assert sight.thought is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = f = 0
    for t in tests:
        try:
            t(); p += 1; print(f"  PASS  {t.__name__}")
        except Exception as e:
            f += 1; print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{p}/{p+f} passed")
