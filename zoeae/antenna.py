"""
Antenna — 7-channel sensory array with gaussian bleed and asymmetric coupling.

The organism's perception layer. Signals enter and activate across
coupled channels with configurable boundary bleed. What the organism
perceives is determined by the coupling matrix and bleed width.

Bleed width is developmental:
    Instar I  — maximum bleed, undifferentiated perception
    Instar II — narrowing, categories forming
    III       — differentiated, identity crystallizing
    IV        — mature, precise but still permeable
    Megalopa  — chosen. Can widen to infant. Can narrow to laser.

Trail overlap (past 360° on the spiral) means the organism's past
configurations interfere with current ones. Temporal memory in geometry.
"""

from __future__ import annotations
import math, hashlib
from dataclasses import dataclass, field
from typing import Any, Optional


# The 7 sensory channels
CHANNEL_NAMES = [
    "CH1_PRIMARY",       # main signal body
    "CH2_HARMONIC",      # secondary harmonics
    "CH3_INPUT",         # fuel/input interface
    "CH4_OUTPUT",        # output/dissipation
    "CH5_DIAGNOSTIC",    # self-observation
    "CH6_EXTRACTION",    # energy/value capture
    "CH7_TRAIL",         # overlap, memory, remainder
]

# Channel coupling matrix — who influences whom. Not symmetric.
# Row influences column. Values 0-1.
_COUPLING = [
    #  CH1   CH2   CH3   CH4   CH5   CH6   CH7
    [0.00, 0.70, 0.30, 0.20, 0.10, 0.15, 0.50],  # CH1 primary
    [0.60, 0.00, 0.10, 0.30, 0.05, 0.20, 0.40],  # CH2 harmonic
    [0.40, 0.15, 0.00, 0.05, 0.10, 0.05, 0.20],  # CH3 input
    [0.10, 0.20, 0.05, 0.00, 0.30, 0.60, 0.35],  # CH4 output
    [0.25, 0.10, 0.15, 0.20, 0.00, 0.10, 0.30],  # CH5 diagnostic
    [0.15, 0.25, 0.05, 0.40, 0.20, 0.00, 0.25],  # CH6 extraction
    [0.50, 0.35, 0.25, 0.30, 0.30, 0.20, 0.00],  # CH7 trail (couples to everything)
]

# Developmental bleed schedule. Maps instar -> base bleed width (0-1).
# 1.0 = fully blurred (infant). 0.05 = nearly sharp (mature).
_BLEED_BY_INSTAR = {1: 0.85, 2: 0.60, 3: 0.35, 4: 0.15, 5: 0.10}

# Three zones: which channels belong to which processing zone
_ZONES = {
    "activation": [2],       # CH3 — raw activation, creative
    "sustain":    [0, 1],    # CH1, CH2 — sustained signal, analytical
    "decay":      [3],       # CH4 — controlled decay, precision
    # CH5, CH6, CH7 span all zones
}


@dataclass
class Detection:
    """Result of passing a signal through the antenna array."""
    channel_activations: list[float]   # 7 values, how much each channel responded
    dominant_channel: int              # strongest activation
    peripheral: list[int]              # channels that activated weakly
    asymmetry: float                   # -1 to +1 asymmetry between even/odd channels
    trail_energy: float                # energy in the overlap/memory channel (CH7)
    bleed_width: float                 # developmental bleed at time of detection
    zone_residence: dict[str, float]   # time in each processing zone

    @property
    def sharpness(self) -> float:
        """How concentrated is the activation? 1=all one channel, 0=uniform."""
        if not self.channel_activations:
            return 0.0
        mx = max(self.channel_activations)
        total = sum(self.channel_activations)
        return mx / total if total > 0 else 0.0

    @property
    def associativity(self) -> float:
        """How much cross-channel bleed? Inverse of sharpness."""
        return 1.0 - self.sharpness

    def overlap_with(self, other: "Detection") -> float:
        """Bhattacharyya coefficient between two detection patterns.
        High overlap = signals activate similar channels."""
        if len(self.channel_activations) != len(other.channel_activations):
            return 0.0
        a = self.channel_activations
        b = other.channel_activations
        sa = sum(a) or 1.0
        sb = sum(b) or 1.0
        return sum(math.sqrt((ai/sa) * (bi/sb)) for ai, bi in zip(a, b))


class Antenna:
    """
    7-channel sensory array with gaussian bleed and asymmetric coupling.

    The organism's perception layer. Signals enter and activate across
    coupled channels with configurable boundary bleed.
    """

    def __init__(self, bleed_width: Optional[float] = None) -> None:
        self._bleed = bleed_width or _BLEED_BY_INSTAR[1]
        self._coupling = [row[:] for row in _COUPLING]
        self._damping = [0.5] * 7  # per-channel suppression weights
        self._trail_position = 0.0  # position on spiral (0-693°)
        self._override_bleed: Optional[float] = None  # FREE_WILL override

    # ── SENSING ──

    def sense(self, signal: Any, asymmetry_bias: float = 0.0) -> Detection:
        """Pass a signal through the antenna. Returns full detection pattern."""
        h = hashlib.sha256(str(signal).encode()).digest()

        # Initial activation: 7 channels from hash bytes
        raw = [(h[i] / 255.0) for i in range(7)]

        # Apply damping (suppression weights)
        damped = [r * (1.0 - self._damping[i]) for i, r in enumerate(raw)]

        # Apply coupling — each channel influences its neighbors
        coupled = [0.0] * 7
        for i in range(7):
            coupled[i] = damped[i]
            for j in range(7):
                coupled[i] += damped[j] * self._coupling[j][i] * self._bleed_factor

        # Normalize
        total = sum(coupled) or 1.0
        activated = [max(0.0, c / total) for c in coupled]

        # Apply asymmetry — left/right weighting
        if asymmetry_bias != 0.0:
            for i in range(7):
                sign = 1.0 if i % 2 == 0 else -1.0
                activated[i] *= (1.0 + sign * asymmetry_bias * 0.2)
            total = sum(activated) or 1.0
            activated = [a / total for a in activated]

        # Trail overlap: CH7 gets extra energy from spiral self-interference
        if self._trail_position > 360.0:
            overlap_factor = (self._trail_position - 360.0) / 333.0
            activated[6] += overlap_factor * 0.1
            total = sum(activated) or 1.0
            activated = [a / total for a in activated]

        # Determine dominant and peripheral
        dominant = max(range(7), key=lambda i: activated[i])
        threshold = max(activated) * 0.2
        peripheral = [i for i in range(7)
                      if i != dominant and activated[i] > threshold]

        # Asymmetry measurement: difference between even/odd channels
        even = sum(activated[i] for i in range(0, 7, 2))
        odd = sum(activated[i] for i in range(1, 7, 2))
        asymmetry = (even - odd) / (even + odd) if (even + odd) > 0 else 0.0

        # Zone residence
        zone_res = {}
        for zone, channels in _ZONES.items():
            zone_res[zone] = sum(activated[f] for f in channels)

        return Detection(
            channel_activations=activated,
            dominant_channel=dominant,
            peripheral=peripheral,
            asymmetry=asymmetry,
            trail_energy=activated[6],
            bleed_width=self.bleed_width,
            zone_residence=zone_res,
        )

    # ── BLEED CONTROL ──

    @property
    def bleed_width(self) -> float:
        return self._override_bleed if self._override_bleed is not None else self._bleed

    @property
    def _bleed_factor(self) -> float:
        """How much coupling bleeds between channels. Derived from bleed width."""
        return self.bleed_width

    def set_developmental_bleed(self, instar: int) -> None:
        """Set bleed from developmental schedule. Not a choice."""
        self._bleed = _BLEED_BY_INSTAR.get(instar, 0.1)

    def set_chosen_bleed(self, width: float) -> None:
        """Override bleed. Only valid after FREE_WILL. Caller must enforce."""
        self._override_bleed = max(0.0, min(1.0, width))

    def clear_chosen_bleed(self) -> None:
        """Return to developmental bleed."""
        self._override_bleed = None

    # ── WEIGHTS (damping coefficients) ──

    def set_damping(self, channel: int, value: float) -> None:
        """Set damping for a channel. 0=full signal, 1=full suppression."""
        if 0 <= channel < 7:
            self._damping[channel] = max(0.0, min(1.0, value))

    def set_damping_all(self, values: list[float]) -> None:
        for i, v in enumerate(values[:7]):
            self._damping[i] = max(0.0, min(1.0, v))

    @property
    def damping(self) -> list[float]:
        return list(self._damping)

    # ── TRAIL POSITION ──

    def set_trail_position(self, degrees: float) -> None:
        """Position on the spiral. 0-693°. Past 360° = trail overlap."""
        self._trail_position = max(0.0, min(693.0, degrees))

    @property
    def trail_position(self) -> float:
        return self._trail_position

    @property
    def in_trail_overlap(self) -> bool:
        return self._trail_position > 360.0

    # ── OVERLAP SCORING ──

    def overlap(self, signal_a: Any, signal_b: Any) -> float:
        """Bhattacharyya coefficient between two signals' detection patterns.
        High overlap = signals activate similar channels.
        Low overlap = complementary detection."""
        ra = self.sense(signal_a)
        rb = self.sense(signal_b)
        return ra.overlap_with(rb)

    # ── INTROSPECTION ──

    @property
    def stats(self) -> dict:
        return {
            "bleed_width": round(self.bleed_width, 4),
            "developmental_bleed": round(self._bleed, 4),
            "chosen_bleed": self._override_bleed,
            "damping": [round(d, 3) for d in self._damping],
            "trail_position": round(self._trail_position, 1),
            "in_trail_overlap": self.in_trail_overlap,
        }
