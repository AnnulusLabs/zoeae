"""EcoFlow Delta 2 sensor feed for Zoeae SensorNet.

Registers as a SensorFeed, polls BLE advertisements for battery state.
The ecosystem reads it like any other ambient sensor — no special wiring.

Usage:
    eco = Ecosystem("taos")
    ecoflow = EcoFlowFeed()
    ecoflow.attach(eco.sensor_net)
    await ecoflow.poll()
    print(eco.sensor_net.read("ecoflow:battery"))
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..ecosystem import SensorFeed, SensorNet

ECOFLOW_MFR_ID = 46517  # 0xB5B5

# Default Delta 2 — override with your MAC
DEFAULT_MAC = "A0:85:E3:67:88:99"


@dataclass
class EcoFlowState:
    battery_pct: int = -1
    rssi: int = 0
    serial: str = ""
    mac: str = ""
    input_w: Optional[int] = None
    output_w: Optional[int] = None
    timestamp: float = 0.0

    @property
    def is_valid(self) -> bool:
        return 0 <= self.battery_pct <= 100

    @property
    def status(self) -> str:
        if self.battery_pct <= 10:
            return "critical"
        if self.battery_pct <= 15:
            return "warn"
        return "ok"

    def to_dict(self) -> dict:
        return {
            "battery_pct": self.battery_pct,
            "rssi": self.rssi,
            "serial": self.serial,
            "mac": self.mac,
            "input_w": self.input_w,
            "output_w": self.output_w,
            "status": self.status,
            "timestamp": self.timestamp,
        }


class EcoFlowFeed:
    """BLE sensor feed for EcoFlow Delta 2.

    Attaches to a SensorNet and registers three feeds:
      - ecoflow:battery  (int, 0-100)
      - ecoflow:power    (dict with input_w, output_w)
      - ecoflow:state    (full EcoFlowState dict)
    """

    def __init__(self, mac: str = DEFAULT_MAC, interval_s: float = 300.0):
        self.mac = mac.upper()
        self.interval_s = interval_s
        self._net: Optional[SensorNet] = None
        self._state = EcoFlowState()

    def attach(self, net: SensorNet) -> None:
        """Register feeds with a SensorNet."""
        self._net = net
        net.register(SensorFeed(
            id="ecoflow:battery", kind="power",
            endpoint=f"ble://{self.mac}", interval_s=self.interval_s,
        ))
        net.register(SensorFeed(
            id="ecoflow:power", kind="power",
            endpoint=f"ble://{self.mac}", interval_s=self.interval_s,
        ))
        net.register(SensorFeed(
            id="ecoflow:state", kind="power",
            endpoint=f"ble://{self.mac}", interval_s=self.interval_s,
        ))

    async def poll(self) -> EcoFlowState:
        """Scan BLE, update state, inject into SensorNet."""
        try:
            from bleak import BleakScanner
        except ImportError:
            return self._state

        devices = await BleakScanner.discover(timeout=8, return_adv=True)
        for addr, (dev, adv) in devices.items():
            mfr = adv.manufacturer_data or {}
            if ECOFLOW_MFR_ID in mfr:
                raw = mfr[ECOFLOW_MFR_ID]
                self._state = EcoFlowState(
                    battery_pct=raw[17] if len(raw) > 17 else -1,
                    rssi=adv.rssi,
                    serial=raw[1:17].decode("ascii", errors="replace") if len(raw) > 17 else "?",
                    mac=addr,
                    timestamp=time.time(),
                )
                break

        # Inject into SensorNet
        if self._net and self._state.is_valid:
            self._net.inject("ecoflow:battery", self._state.battery_pct)
            self._net.inject("ecoflow:power", {
                "input_w": self._state.input_w,
                "output_w": self._state.output_w,
            })
            self._net.inject("ecoflow:state", self._state.to_dict())

        return self._state

    async def poll_loop(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """Continuous polling loop."""
        while True:
            await self.poll()
            if stop_event and stop_event.is_set():
                break
            await asyncio.sleep(self.interval_s)

    @property
    def state(self) -> EcoFlowState:
        return self._state
