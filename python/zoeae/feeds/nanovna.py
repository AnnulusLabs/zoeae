"""NanoVNA F V2 sensor feed for Zoeae SensorNet.

The rfcanary pattern — ambient RF environment monitoring.
Sweeps a frequency range and reports signal characteristics.

Registers:
  - rf:sweep     (list of [freq_hz, s11_db] points)
  - rf:swr_min   (float, minimum SWR in sweep range)
  - rf:state     (full dict)

Usage:
    eco = Ecosystem("taos")
    vna = NanoVNAFeed(port="COM3")
    vna.attach(eco.sensor_net)
    vna.poll()
    print(eco.sensor_net.read("rf:swr_min"))
"""
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from ..ecosystem import SensorFeed, SensorNet


@dataclass
class RFState:
    sweep: list = field(default_factory=list)  # [[freq_hz, s11_db], ...]
    swr_min: float = 999.0
    swr_min_freq: float = 0.0
    start_hz: float = 0.0
    stop_hz: float = 0.0
    points: int = 0
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "swr_min": self.swr_min,
            "swr_min_freq_mhz": self.swr_min_freq / 1e6,
            "start_mhz": self.start_hz / 1e6,
            "stop_mhz": self.stop_hz / 1e6,
            "points": self.points,
            "timestamp": self.timestamp,
        }


def _s11_to_swr(s11_db: float) -> float:
    """Convert S11 in dB to SWR."""
    if s11_db >= 0:
        return 999.0
    gamma = 10 ** (s11_db / 20.0)
    if gamma >= 1.0:
        return 999.0
    return (1 + gamma) / (1 - gamma)


class NanoVNAFeed:
    """NanoVNA F V2 as an ambient RF sensor feed.

    Default sweep: 1 MHz to 30 MHz (HF band) with 101 points.
    Change start/stop for your antenna or band of interest.
    """

    def __init__(self, port: str = "COM3", baud: int = 115200,
                 start_hz: float = 1e6, stop_hz: float = 30e6,
                 points: int = 101, interval_s: float = 300.0):
        self.port = port
        self.baud = baud
        self.start_hz = start_hz
        self.stop_hz = stop_hz
        self.points = points
        self.interval_s = interval_s
        self._net: Optional[SensorNet] = None
        self._state = RFState()

    def attach(self, net: SensorNet) -> None:
        self._net = net
        for feed_id, kind in [
            ("rf:sweep", "rf_ambient"),
            ("rf:swr_min", "rf_ambient"),
            ("rf:state", "rf_ambient"),
        ]:
            net.register(SensorFeed(
                id=feed_id, kind=kind,
                endpoint=f"serial://{self.port}",
                interval_s=self.interval_s,
            ))

    def _send_cmd(self, ser, cmd: str, timeout: float = 3.0) -> list[str]:
        """Send command, collect response lines until prompt."""
        ser.write(f"{cmd}\r\n".encode())
        lines = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if line == "ch>" or line == "":
                if lines:
                    break
                continue
            if line == cmd:
                continue  # echo
            lines.append(line)
        return lines

    def poll(self) -> RFState:
        """Run a sweep and parse S11 data."""
        try:
            import serial
        except ImportError:
            return self._state

        try:
            ser = serial.Serial(self.port, self.baud, timeout=2)
            time.sleep(0.3)
            # Flush
            ser.read(ser.in_waiting or 256)

            # Set sweep range
            self._send_cmd(ser,
                f"sweep {int(self.start_hz)} {int(self.stop_hz)} {self.points}")

            # Wait for sweep to complete
            time.sleep(2)

            # Read S11 data (array 0 = S11)
            lines = self._send_cmd(ser, "data 0", timeout=5)

            # Parse: each line is "real imag" (linear, not dB)
            sweep = []
            freq_step = (self.stop_hz - self.start_hz) / max(self.points - 1, 1)
            swr_min = 999.0
            swr_min_freq = 0.0

            for i, line in enumerate(lines):
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    real = float(parts[0])
                    imag = float(parts[1])
                except ValueError:
                    continue

                freq = self.start_hz + i * freq_step
                gamma = math.sqrt(real * real + imag * imag)
                s11_db = 20 * math.log10(gamma) if gamma > 0 else -60.0
                swr = _s11_to_swr(s11_db)

                sweep.append([freq, round(s11_db, 2)])
                if swr < swr_min:
                    swr_min = swr
                    swr_min_freq = freq

            ser.close()

            self._state = RFState(
                sweep=sweep,
                swr_min=round(swr_min, 2),
                swr_min_freq=swr_min_freq,
                start_hz=self.start_hz,
                stop_hz=self.stop_hz,
                points=len(sweep),
                timestamp=time.time(),
            )

        except Exception:
            pass

        # Inject into SensorNet
        if self._net and self._state.points > 0:
            self._net.inject("rf:sweep", self._state.sweep)
            self._net.inject("rf:swr_min", self._state.swr_min)
            self._net.inject("rf:state", self._state.to_dict())

        return self._state

    @property
    def state(self) -> RFState:
        return self._state
