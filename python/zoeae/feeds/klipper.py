"""Creality K1C (Klipper/Moonraker) sensor feed for Zoeae SensorNet.

Reads printer telemetry over HTTP from the Moonraker API.

Registers:
  - fab:bed_temp     (float, Celsius)
  - fab:hotend_temp  (float, Celsius)
  - fab:print_state  (str: standby/printing/complete/error)
  - fab:state        (full dict)

Usage:
    eco = Ecosystem("taos")
    k1c = KlipperFeed(host="192.168.1.82")
    k1c.attach(eco.sensor_net)
    k1c.poll()
"""
import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

from ..ecosystem import SensorFeed, SensorNet


@dataclass
class PrinterState:
    bed_temp: float = 0.0
    bed_target: float = 0.0
    hotend_temp: float = 0.0
    hotend_target: float = 0.0
    print_state: str = "unknown"
    filename: str = ""
    progress_pct: float = 0.0
    filament_used_mm: float = 0.0
    print_duration_s: float = 0.0
    timestamp: float = 0.0

    @property
    def is_printing(self) -> bool:
        return self.print_state == "printing"

    def to_dict(self) -> dict:
        return {
            "bed_temp": self.bed_temp,
            "bed_target": self.bed_target,
            "hotend_temp": self.hotend_temp,
            "hotend_target": self.hotend_target,
            "print_state": self.print_state,
            "filename": self.filename,
            "progress_pct": self.progress_pct,
            "filament_used_mm": self.filament_used_mm,
            "print_duration_s": self.print_duration_s,
            "timestamp": self.timestamp,
        }


class KlipperFeed:
    """Moonraker API feed from Creality K1C."""

    def __init__(self, host: str = "192.168.1.82", port: int = 7125,
                 interval_s: float = 30.0):
        self.base_url = f"http://{host}:{port}"
        self.interval_s = interval_s
        self._net: Optional[SensorNet] = None
        self._state = PrinterState()

    def attach(self, net: SensorNet) -> None:
        self._net = net
        for feed_id, kind in [
            ("fab:bed_temp", "climate"),
            ("fab:hotend_temp", "climate"),
            ("fab:print_state", "fabrication"),
            ("fab:state", "fabrication"),
        ]:
            net.register(SensorFeed(
                id=feed_id, kind=kind,
                endpoint=self.base_url,
                interval_s=self.interval_s,
            ))

    def poll(self) -> PrinterState:
        try:
            url = (f"{self.base_url}/printer/objects/query"
                   f"?heater_bed&extruder&print_stats&display_status")
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

            status = data.get("result", {}).get("status", {})
            bed = status.get("heater_bed", {})
            ext = status.get("extruder", {})
            ps = status.get("print_stats", {})
            ds = status.get("display_status", {})

            self._state = PrinterState(
                bed_temp=bed.get("temperature", 0.0),
                bed_target=bed.get("target", 0.0),
                hotend_temp=ext.get("temperature", 0.0),
                hotend_target=ext.get("target", 0.0),
                print_state=ps.get("state", "unknown"),
                filename=ps.get("filename", ""),
                progress_pct=ds.get("progress", 0.0) * 100,
                filament_used_mm=ps.get("filament_used", 0.0),
                print_duration_s=ps.get("print_duration", 0.0),
                timestamp=time.time(),
            )
        except Exception:
            pass

        if self._net:
            self._net.inject("fab:bed_temp", self._state.bed_temp)
            self._net.inject("fab:hotend_temp", self._state.hotend_temp)
            self._net.inject("fab:print_state", self._state.print_state)
            self._net.inject("fab:state", self._state.to_dict())

        return self._state

    @property
    def state(self) -> PrinterState:
        return self._state
