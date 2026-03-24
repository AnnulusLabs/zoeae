"""
XR — Interactive startup configurator for Zoeae Ecosystem + Maker.

TUI that lets the user tune ecosystem parameters via prompts,
then drops into a live sight loop.

    python -m zoeae.xr

No webapp. TUI only. ANSI color-coded.
"""
from __future__ import annotations
import sys, os, json, time
from typing import Optional

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

from .ecosystem import (
    Ecosystem, Maker, Expert, PhysicsTest, FabNode,
    SensorFeed, MeshNode, Sight,
)
from .antenna import Antenna, CHANNEL_NAMES
from .genome import GenomeBuilder
from .crab import Crab


# ── ANSI COLORS ──

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
MAGENTA = "\033[35m"
WHITE  = "\033[37m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"


def _banner():
    print(_c(CYAN, r"""
     /|\ /|\ /|\ /|\ /|\ /|\ /|\
      1   2   3   4   5   6   7
     ─────────────────────────────
              z o e a e
      a living orchestration runtime
    """))
    print(_c(DIM, "    v0.5.0 — AnnulusLabs LLC\n"))


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {_c(YELLOW, label)}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return val if val else default


def _prompt_int(label: str, default: int) -> int:
    val = _prompt(label, str(default))
    try:
        return int(val)
    except ValueError:
        return default


def _prompt_float(label: str, default: float) -> float:
    val = _prompt(label, str(default))
    try:
        return float(val)
    except ValueError:
        return default


def _prompt_yn(label: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    val = _prompt(label, d).lower()
    if val in ("y", "yes"):
        return True
    if val in ("n", "no"):
        return False
    return default


def _section(title: str):
    print(f"\n  {_c(BOLD + CYAN, '── ' + title + ' ──')}")


# ── ECOSYSTEM BUILDER ──

def build_ecosystem_interactive() -> Ecosystem:
    """Walk the user through ecosystem configuration."""

    _section("ECOSYSTEM")
    name = _prompt("Ecosystem name", "taos")
    eco = Ecosystem(name)

    # ── Experts ──
    _section("COURTYARD (Expert Knowledge)")
    if _prompt_yn("Add experts?"):
        print(_c(DIM, "    Enter experts (blank name to stop)"))
        while True:
            eid = _prompt("  Expert name", "")
            if not eid:
                break
            domain = _prompt("  Domain", "general")
            years = _prompt_int("  Years experience", 10)
            rate = _prompt_float("  Rate $/hr", 50.0)
            eco.courtyard.register_expert(Expert(eid, domain, years, rate))
            print(_c(GREEN, f"    + {eid} ({domain}, {years}yr)"))

    # ── Physics tests ──
    _section("TOEBUSTER (Physics Gauntlet)")
    if _prompt_yn("Load default physics tests?"):
        defaults = [
            PhysicsTest("gravity", "structural", lambda d: True),
            PhysicsTest("thermal_limit", "thermal", lambda d: d.get("max_temp", 300) < 3000),
            PhysicsTest("pressure_integrity", "structural", lambda d: d.get("wall_thickness", 0.01) >= 0.005),
            PhysicsTest("mass_budget", "structural", lambda d: d.get("total_mass", 1) < 10000),
            PhysicsTest("em_compatibility", "em", lambda d: True),
        ]
        for t in defaults:
            eco.toebuster.register(t)
        print(_c(GREEN, f"    + {len(defaults)} default physics tests loaded"))

    # ── Fab nodes ──
    _section("FAB NET (Fabrication Network)")
    if _prompt_yn("Add fab nodes?"):
        print(_c(DIM, "    Enter fab shops (blank name to stop)"))
        while True:
            fname = _prompt("  Shop name", "")
            if not fname:
                break
            loc = _prompt("  Location", "unknown")
            caps_str = _prompt("  Capabilities (comma-sep)", "cnc,3dp")
            caps = [c.strip() for c in caps_str.split(",")]
            discrete = _prompt_yn("  Discrete (compartmentalized)?", False)
            fid = fname.lower().replace(" ", "_")
            eco.fab_net.register(FabNode(fid, fname, loc, caps, discrete=discrete))
            print(_c(GREEN, f"    + {fname} ({loc}) [{', '.join(caps)}]"))

    # ── Sensors ──
    _section("SENSOR NET (rfcanary)")
    if _prompt_yn("Add sensor feeds?"):
        print(_c(DIM, "    Enter sensors (blank id to stop)"))
        while True:
            sid = _prompt("  Sensor ID", "")
            if not sid:
                break
            kind = _prompt("  Kind", "weather")
            interval = _prompt_float("  Interval (seconds)", 60.0)
            eco.sensor_net.register(SensorFeed(sid, kind, interval_s=interval))
            print(_c(GREEN, f"    + {sid} ({kind}, every {interval}s)"))

    # ── Mesh ──
    _section("MESH NET (BNET/HyperWave)")
    n_mesh = _prompt_int("Number of mesh nodes", 0)
    for i in range(n_mesh):
        nid = _prompt(f"  Node {i+1} ID", f"node_{i+1}")
        transport = _prompt(f"  Transport", "lora")
        eco.add_mesh_node(MeshNode(nid, transport))
        print(_c(GREEN, f"    + {nid} ({transport})"))

    return eco


def configure_maker(eco: Ecosystem) -> Maker:
    """Configure and hatch a Maker."""
    _section("MAKER (Augmented Human)")
    purpose = _prompt("Purpose", "augment_human")
    principle = _prompt("Guiding principle", "people_planet_profit_third")

    genome = GenomeBuilder().core(
        name="maker",
        purpose=purpose,
        principle=principle,
    ).build()

    m = Maker(eco, genome)
    print(_c(GREEN, f"  Maker hatched: bleed={m.bleed:.2f}, instar={m.instar}"))
    return m


# ── SIGHT LOOP ──

def _print_sight(sight: Sight):
    """Pretty-print a Sight result."""
    # Detection
    d = sight.detection
    print(f"\n  {_c(BOLD, 'ANTENNA')}")
    for i, v in enumerate(d.channel_activations):
        bar = "█" * int(v * 40)
        marker = " ◄" if i == d.dominant_channel else ""
        ch_name = CHANNEL_NAMES[i] if i < len(CHANNEL_NAMES) else f"CH{i+1}"
        print(f"    {_c(CYAN, ch_name):>30s}  {_c(GREEN, bar)}{marker}  {v:.3f}")
    print(f"    {'Sharpness':>22s}: {d.sharpness:.3f}")
    print(f"    {'Asymmetry':>22s}: {d.asymmetry:.3f}")
    print(f"    {'Trail energy':>22s}: {d.trail_energy:.3f}")
    print(f"    {'Bleed width':>22s}: {d.bleed_width:.2f}")

    # Physics
    pc = sight.physics_check
    if pc:
        status = _c(GREEN, "PASS") if pc["survives"] else _c(RED, "FAIL")
        print(f"\n  {_c(BOLD, 'TOEBUSTER')}: {status}")
        print(f"    Passed: {pc['passed']}, Failed: {pc['failed']}, Errors: {pc['errors']}")
        if pc["details"]:
            for detail in pc["details"]:
                print(f"    {_c(RED, '  x ' + detail)}")

    # Expert
    if sight.expert_match:
        e = sight.expert_match
        print(f"\n  {_c(BOLD, 'COURTYARD')}: {_c(GREEN, e['id'])} — {e['domain']} ({e['years']}yr)")
    else:
        print(f"\n  {_c(BOLD, 'COURTYARD')}: {_c(DIM, 'no expert match')}")

    # Fabrication
    if sight.fab_options:
        print(f"\n  {_c(BOLD, 'FAB NET')}: {len(sight.fab_options)} options")
        for fo in sight.fab_options[:5]:
            print(f"    {fo['node']} — {fo['capability']} ({fo['location']})")
    else:
        print(f"\n  {_c(BOLD, 'FAB NET')}: {_c(DIM, 'no fab options')}")

    # Verdict
    go = sight.go_no_go
    if "GO" == go[:2]:
        color = GREEN
    elif "CONDITIONAL" in go:
        color = YELLOW
    else:
        color = RED

    print(f"\n  {_c(BOLD, 'VERDICT')}: {_c(color, go)}")
    print(f"  {_c(BOLD, 'Confidence')}: {sight.confidence:.3f}")
    print(f"  {_c(BOLD, 'Patent ready')}: {sight.patent_ready}")


def sight_loop(maker: Maker, crab: Optional[Crab] = None):
    """Interactive sight loop — the human says what they want to build."""
    if crab is None:
        crab = Crab(instar=maker.instar.value if hasattr(maker.instar, 'value') else 1)

    _section("XR SIGHT LOOP")
    crab.greet()
    print(_c(DIM, "  Type an idea to see through the lens. 'quit' to exit.\n"))

    while True:
        try:
            idea = input(f"  {_c(MAGENTA, 'see')} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not idea or idea.lower() in ("quit", "exit", "q"):
            break

        if idea.startswith("/"):
            _handle_command(maker, idea, crab)
            continue

        sight = maker.see(idea)
        _print_sight(sight)
        crab.react_to_sight(sight)
        # Sync crab instar with maker
        new_instar = maker.instar.value if hasattr(maker.instar, 'value') else 1
        if new_instar != crab.instar:
            crab.set_instar(new_instar)
        print()


def _handle_command(maker: Maker, cmd: str, crab: Optional[Crab] = None):
    """Handle slash commands in the sight loop."""
    parts = cmd.strip().split(None, 1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/stats":
        s = maker.stats
        print(f"\n  {_c(BOLD, 'MAKER STATS')}")
        print(f"    Alive: {s['alive']}")
        print(f"    Instar: {s['instar']}")
        print(f"    Bleed: {s['bleed']:.2f}")
        print(f"    Providers: {s.get('providers', 0)}")
        print(f"    Genome integrity: {s.get('genome_integrity', 'n/a')}")
        eco = s.get("ecosystem", {})
        print(f"    Experts: {eco.get('courtyard', {}).get('experts', 0)}")
        print(f"    Physics tests: {eco.get('toebuster', 0)}")
        print(f"    Fab nodes: {eco.get('fab_net', {}).get('nodes', 0)}")
        print(f"    Sensors: {eco.get('sensors', 0)}")
        print(f"    Mesh nodes: {eco.get('mesh_nodes', 0)}")

    elif command == "/sensor":
        if arg:
            val = maker.read_sensor(arg)
            print(f"  {arg}: {val}")
        else:
            feeds = maker.eco.sensor_net.feed_ids
            print(f"  Sensors: {feeds}")

    elif command == "/broadcast":
        if arg:
            sent = maker.mesh_broadcast({"message": arg})
            print(f"  Broadcast to {sent} nodes")
        else:
            print("  Usage: /broadcast <message>")

    elif command == "/bleed":
        if arg:
            try:
                maker.set_bleed(float(arg))
                print(f"  Bleed set to {maker.bleed:.2f}")
            except Exception as e:
                print(f"  {_c(RED, str(e))}")
        else:
            print(f"  Current bleed: {maker.bleed:.2f}")

    elif command == "/damping":
        print(f"  Damping: {maker.antenna.damping}")
        for i, name in enumerate(CHANNEL_NAMES):
            print(f"    {name}: {maker.antenna.damping[i]:.3f}")

    elif command == "/expert":
        if arg:
            e = maker.eco.courtyard.find_expert(arg)
            if e:
                print(f"  {e.id}: {e.domain} ({e.experience_years}yr, ${e.rate_per_hour}/hr)")
            else:
                print(f"  No expert found for: {arg}")
        else:
            for eid, e in maker.eco.courtyard._experts.items():
                print(f"  {eid}: {e.domain} ({e.experience_years}yr)")

    elif command == "/fab":
        cap = arg or "cnc"
        nodes = maker.find_fab(cap)
        if nodes:
            for n in nodes:
                d = " [DISCRETE]" if n.discrete else ""
                print(f"  {n.name} — {n.location} [{', '.join(n.capabilities)}]{d}")
        else:
            print(f"  No fab nodes for: {cap}")

    elif command == "/patent":
        if not arg:
            print("  Usage: /patent <title>")
            return
        design = {"title": arg, "abstract": arg, "components": {"part": {"function": "operate"}}}
        result = maker.validate_and_patent(design)
        if "error" in result:
            print(f"  {_c(RED, result['error'])}")
        else:
            print(f"  Filing ready: {result['filing_ready']}")
            for c in result["claims"]:
                print(f"    {c}")

    elif command == "/crab":
        if crab:
            if arg == "off":
                crab.quiet = True
                print("  Crab silenced.")
            elif arg == "on":
                crab.quiet = False
                print("  Crab is back.")
            elif arg == "tip":
                crab.tip("general")
            elif arg:
                crab.tip(arg)
            else:
                crab.say(f"Instar {crab.instar} | {'quiet' if crab.quiet else 'chatty'}")

    elif command in ("/help", "/?"):
        print(f"""
  {_c(BOLD, 'Commands')}:
    /stats        — Maker & ecosystem stats
    /sensor [id]  — Read sensor (or list all)
    /broadcast    — Send to mesh network
    /bleed [val]  — Get/set antenna bleed width
    /damping      — Show channel damping (personality)
    /expert [q]   — Find expert (or list all)
    /fab [cap]    — Search fab network
    /patent <t>   — Quick patent from title
    /crab [topic] — Crab companion (off/on/tip/topic)
    /help         — This message
    quit          — Exit
""")
    else:
        print(f"  Unknown command: {command}. Try /help")


# ── MAIN ──

def main():
    _banner()

    # Quick start or interactive?
    mode = _prompt("Mode (quick/full)", "quick")

    if mode == "full":
        eco = build_ecosystem_interactive()
        maker = configure_maker(eco)
    else:
        # Quick start with sensible defaults
        eco = Ecosystem("taos")
        eco.courtyard.register_expert(Expert("default", "general engineering", 10))
        eco.toebuster.register(PhysicsTest("basic", "structural", lambda d: True))
        eco.fab_net.register(FabNode("local", "Local Shop", "local", ["cnc", "3dp", "welding"]))
        eco.sensor_net.register(SensorFeed("ambient", "weather", interval_s=300))
        eco.add_mesh_node(MeshNode("base", "lora"))
        maker = Maker.hatch(eco)
        print(_c(GREEN, "\n  Quick start: ecosystem loaded with defaults"))
        print(f"  {_c(DIM, 'Use /help for commands, or just type an idea')}\n")

    sight_loop(maker)
    print(_c(DIM, "\n  Session ended. The organism rests.\n"))


if __name__ == "__main__":
    main()
