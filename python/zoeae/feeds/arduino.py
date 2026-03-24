"""Arduino environmental sensor feed for Zoeae SensorNet.

Reads JSON from a Lonely Binary TinkerBlock Uno over serial.
Expects the arduino_env.ino sketch running on the Uno.

Registers:
  - env:temperature  (float, Celsius)
  - env:light        (float, 0-100%)
  - env:proximity    (int, 0 or 1)
  - env:state        (full dict)

Usage:
    eco = Ecosystem("taos")
    env = ArduinoEnvFeed(port="COM15")
    env.attach(eco.sensor_net)
    env.poll()
    print(eco.sensor_net.read("env:temperature"))
"""
import json
import time
from dataclasses import dataclass
from typing import Any, Optional

from ..ecosystem import SensorFeed, SensorNet


@dataclass
class EnvState:
    temperature_c: float = 0.0
    temperature_f: float = 0.0
    light_pct: float = 0.0
    proximity: int = 0
    timestamp: float = 0.0

    @property
    def is_valid(self) -> bool:
        return -40 <= self.temperature_c <= 80

    def to_dict(self) -> dict:
        return {
            "temperature_c": self.temperature_c,
            "temperature_f": self.temperature_f,
            "light_pct": self.light_pct,
            "proximity": self.proximity,
            "timestamp": self.timestamp,
        }


class ArduinoEnvFeed:
    """Serial sensor feed from TinkerBlock Uno with TK12/TK20/TK57."""

    def __init__(self, port: str = "COM15", baud: int = 9600,
                 interval_s: float = 10.0):
        self.port = port
        self.baud = baud
        self.interval_s = interval_s
        self._net: Optional[SensorNet] = None
        self._state = EnvState()

    def attach(self, net: SensorNet) -> None:
        self._net = net
        for feed_id, kind in [
            ("env:temperature", "climate"),
            ("env:light", "climate"),
            ("env:proximity", "motion"),
            ("env:state", "climate"),
        ]:
            net.register(SensorFeed(
                id=feed_id, kind=kind,
                endpoint=f"serial://{self.port}",
                interval_s=self.interval_s,
            ))

    def poll(self) -> EnvState:
        """Read one JSON line from serial."""
        try:
            import serial
        except ImportError:
            return self._state

        try:
            ser = serial.Serial(self.port, self.baud, timeout=8)
            # Arduino resets on connect — wait for boot
            time.sleep(2.5)

            # Read lines until we get a valid sensor reading
            deadline = time.time() + 10
            while time.time() < deadline:
                line = ser.readline().decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Skip boot message
                if "event" in data:
                    continue

                if "t_c" in data:
                    self._state = EnvState(
                        temperature_c=data.get("t_c", 0.0),
                        temperature_f=data.get("t_f", 0.0),
                        light_pct=data.get("light", 0.0),
                        proximity=data.get("prox", 0),
                        timestamp=time.time(),
                    )
                    break

            ser.close()
        except Exception:
            pass

        # Inject into SensorNet
        if self._net and self._state.is_valid:
            self._net.inject("env:temperature", self._state.temperature_c)
            self._net.inject("env:light", self._state.light_pct)
            self._net.inject("env:proximity", self._state.proximity)
            self._net.inject("env:state", self._state.to_dict())

        return self._state

    @property
    def state(self) -> EnvState:
        return self._state
