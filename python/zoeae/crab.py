"""
Crab — The Zoeae terminal companion.

A zoea larva that lives in your terminal. Like Clippy, but useful,
and it knows when to shut up.

Reacts to ecosystem events, offers context-aware suggestions,
and evolves its appearance with the organism's instar.

    from zoeae.crab import Crab
    crab = Crab()
    crab.greet()
    crab.react("physics_fail", details="thermal_limit exceeded")
    crab.tip("welding")
"""
from __future__ import annotations
import sys, random
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── ANSI ──
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
CYAN    = "\033[36m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
MAGENTA = "\033[35m"
BLUE    = "\033[34m"


# ── ZOEA SPRITES BY INSTAR ──

ZOEA_I = r"""
    .  .  .
     \|/
    --O--
     /|\
      |
"""

ZOEA_II = r"""
    . .. .
     \||/
    -(O)-
     /||\
      ||
"""

ZOEA_III = r"""
   .  . . .  .
    \ | | | /
   ==(O O)==
    / | | | \
      |.|
"""

ZOEA_IV = r"""
   .  .. .. ..  .
    \ || || || /
   =='O''O''O'==
    / || || || \
      ||.||
       \_/
"""

MEGALOPA = r"""
   . ... ... ... .
    \||| ||| |||/
   ==<  @_@  >==
    /||| ||| |||\
     ||| ||| |||
      \_____/
"""

SPRITES = {
    1: ZOEA_I,
    2: ZOEA_II,
    3: ZOEA_III,
    4: ZOEA_IV,
    5: MEGALOPA,
}

# ── SPEECH BUBBLES ──

def _bubble(text: str, sprite: str, color: str = CYAN) -> str:
    lines = text.split("\n")
    max_len = max(len(l) for l in lines)
    top = " " + "_" * (max_len + 2)
    bottom = " " + "-" * (max_len + 2)
    body = "\n".join(f"| {l:<{max_len}} |" for l in lines)
    sprite_lines = sprite.strip().split("\n")
    return f"{color}{top}\n{body}\n{bottom}{RESET}\n{color}{sprite.rstrip()}{RESET}"


# ── REACTION DATABASE ──

REACTIONS = {
    "greet": [
        "Hey! I'm your zoea. Type an idea and I'll sense it.",
        "Larval stage. Seven antennae. Ready to perceive.",
        "The ocean is warm today. What are we building?",
    ],
    "physics_pass": [
        "Physics says yes. That's rare. Run with it.",
        "ToeBuster cleared. Reality allows this to exist.",
        "Green across the board. The universe is cooperating.",
    ],
    "physics_fail": [
        "Physics says no. Don't argue with thermodynamics.",
        "ToeBuster caught something. Check the details.",
        "Reality vetoed this one. Iterate or pivot.",
    ],
    "expert_found": [
        "Found someone who knows this. Get them on the call.",
        "Expert match. Their experience > your intuition here.",
        "Courtyard has a vet. Trust the gray hair.",
    ],
    "no_expert": [
        "No expert in the courtyard for this one. You're the pioneer.",
        "Uncharted territory. Document everything.",
        "Nobody's done this before. That's either exciting or terrifying.",
    ],
    "fab_found": [
        "Found shops that can build this. Check locations.",
        "FabNet has options. Get quotes before committing.",
        "Fabrication path exists. Now it's just logistics.",
    ],
    "no_fab": [
        "No fab nodes for this capability. Build your own or expand the network.",
        "FabNet came up empty. Time to get creative.",
        "You might need to make the machine that makes the thing.",
    ],
    "go": [
        "GO. All systems agree. Ship it.",
        "Full confidence. Physics, experts, and fabs aligned.",
        "This is the one. Don't overthink it.",
    ],
    "no_go": [
        "NO GO. Something's missing. Check the details.",
        "Not yet. Close the gaps before committing resources.",
        "The organism senses hesitation. That's data.",
    ],
    "conditional": [
        "Maybe. Get expert review before proceeding.",
        "Conditional. The physics works but the confidence is thin.",
        "Possible but unproven. Prototype first.",
    ],
    "molt": [
        "I molted! Bleed narrowing. Perception sharpening.",
        "New instar. The categories are crystallizing.",
        "Shed the old shell. New capabilities unlocked.",
    ],
    "idle": [
        "Still here. Seven antennae, all listening.",
        "Waiting for input. The ocean is quiet.",
        "Ready when you are. The larva doesn't sleep.",
    ],
    "patent": [
        "Patent draft ready. Have a human lawyer review it.",
        "IP captured. Provisional buys you 12 months.",
        "Claims generated. This is a starting point, not a filing.",
    ],
    "mesh": [
        "Broadcast sent. The mesh carries the message.",
        "All nodes received. Decentralized comms working.",
        "Signal propagated. No single point of failure.",
    ],
    "sensor": [
        "Sensor data fresh. The environment is speaking.",
        "Reading ambient conditions. No new hardware needed.",
        "rfcanary pattern: listen to what's already there.",
    ],
    "error": [
        "Something broke. Check the stack trace.",
        "Error caught. The exoskeleton held but investigate.",
        "Failure is data. Log it and iterate.",
    ],
}

TIPS = {
    "welding": "Preheat thick sections. Let the puddle tell you the speed.",
    "cnc": "Climb milling for finish. Conventional for roughing. Always.",
    "pcb": "Ground planes are free. Use them. Pour copper everywhere.",
    "3dp": "Print orientation matters more than infill percentage.",
    "pressure": "Factor of safety 4x on pressure vessels. No exceptions.",
    "hydrogen": "Hydrogen embrittlement is real. Aluminum liner + CF wrap.",
    "rf": "Start with the antenna. Everything else is software.",
    "mesh": "LoRa for range. WiFi for bandwidth. Know which you need.",
    "thermal": "Heat goes where it wants. Your job is to make it want the right thing.",
    "materials": "When in doubt, 6061-T6. When certain, 7075.",
    "patent": "Provisional first. Always. It buys time and costs nothing.",
    "sensor": "The best sensor is the one already deployed. Tap ambient.",
    "general": "Measure twice. Cut once. Then measure the cut.",
}


class Crab:
    """The zoea terminal companion."""

    def __init__(self, instar: int = 1, quiet: bool = False):
        self.instar = instar
        self.quiet = quiet
        self._last_reaction = ""

    @property
    def sprite(self) -> str:
        return SPRITES.get(self.instar, ZOEA_I)

    def say(self, text: str, color: str = CYAN):
        if self.quiet:
            return
        print(_bubble(text, self.sprite, color))

    def greet(self):
        self.react("greet")

    def react(self, event: str, details: str = ""):
        msgs = REACTIONS.get(event, REACTIONS["idle"])
        msg = random.choice(msgs)
        if details:
            msg += f"\n  ({details})"

        color = CYAN
        if event in ("physics_fail", "no_go", "error"):
            color = RED
        elif event in ("physics_pass", "go", "fab_found", "expert_found"):
            color = GREEN
        elif event in ("conditional", "no_expert", "no_fab"):
            color = YELLOW
        elif event == "molt":
            color = MAGENTA

        self.say(msg, color)
        self._last_reaction = event

    def react_to_sight(self, sight):
        """React to a Sight result from Maker.see()."""
        if sight.physics_check and not sight.physics_check.get("survives"):
            details = ", ".join(sight.physics_check.get("details", []))
            self.react("physics_fail", details)
        elif sight.go_no_go.startswith("GO"):
            self.react("go")
        elif "CONDITIONAL" in sight.go_no_go:
            self.react("conditional")
        else:
            self.react("no_go")

        if sight.expert_match:
            self.react("expert_found", sight.expert_match.get("domain", ""))
        if sight.fab_options:
            self.react("fab_found", f"{len(sight.fab_options)} shops")

    def tip(self, topic: str = "general") -> str:
        t = TIPS.get(topic, TIPS["general"])
        self.say(f"TIP: {t}", YELLOW)
        return t

    def set_instar(self, instar: int):
        old = self.instar
        self.instar = max(1, min(5, instar))
        if self.instar != old:
            self.react("molt")

    def evolve(self):
        """Advance one instar."""
        self.set_instar(self.instar + 1)


def demo():
    """Quick demo of the crab companion."""
    crab = Crab(instar=1)

    print("\n  === CRAB COMPANION DEMO ===\n")

    crab.greet()
    print()

    crab.react("physics_pass")
    print()

    crab.react("physics_fail", details="thermal_limit: max_temp=5000 > 3000")
    print()

    crab.tip("welding")
    print()

    crab.react("go")
    print()

    # Evolve through instars
    for _ in range(4):
        crab.evolve()
        print()

    crab.react("idle")


if __name__ == "__main__":
    demo()
