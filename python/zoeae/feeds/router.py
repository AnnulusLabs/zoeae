"""ASUS router sensor feed for Zoeae SensorNet.

Reads network stats from the ASUS router admin API.
Falls back to simple reachability + client count if auth isn't configured.

Registers:
  - net:wan_up       (bool)
  - net:clients      (int, connected device count)
  - net:state        (full dict)
"""
import json
import time
import urllib.request
import subprocess
from dataclasses import dataclass
from typing import Optional

from ..ecosystem import SensorFeed, SensorNet


@dataclass
class RouterState:
    reachable: bool = False
    wan_up: bool = False
    clients: int = 0
    latency_ms: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "reachable": self.reachable,
            "wan_up": self.wan_up,
            "clients": self.clients,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
        }


class RouterFeed:
    """ASUS router network health feed."""

    def __init__(self, host: str = "192.168.1.1", interval_s: float = 60.0):
        self.host = host
        self.interval_s = interval_s
        self._net: Optional[SensorNet] = None
        self._state = RouterState()

    def attach(self, net: SensorNet) -> None:
        self._net = net
        for feed_id, kind in [
            ("net:wan_up", "network"),
            ("net:clients", "network"),
            ("net:state", "network"),
        ]:
            net.register(SensorFeed(
                id=feed_id, kind=kind,
                endpoint=f"http://{self.host}",
                interval_s=self.interval_s,
            ))

    def poll(self) -> RouterState:
        reachable = False
        latency = 0.0

        # Ping check
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "2000", self.host],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                reachable = True
                # Parse latency from ping output
                for line in result.stdout.splitlines():
                    if "time=" in line.lower() or "time<" in line.lower():
                        import re
                        m = re.search(r'time[<=](\d+)', line, re.IGNORECASE)
                        if m:
                            latency = float(m.group(1))
        except Exception:
            pass

        # WAN check — can we reach the internet?
        wan_up = False
        try:
            urllib.request.urlopen("http://1.1.1.1", timeout=3)
            wan_up = True
        except Exception:
            pass

        # Client count from ARP table (passive, no auth needed)
        clients = 0
        try:
            result = subprocess.run(
                ["arp", "-a"], capture_output=True, text=True, timeout=3,
            )
            for line in result.stdout.splitlines():
                if "dynamic" in line.lower() and "192.168.1." in line:
                    clients += 1
        except Exception:
            pass

        self._state = RouterState(
            reachable=reachable,
            wan_up=wan_up,
            clients=clients,
            latency_ms=latency,
            timestamp=time.time(),
        )

        if self._net:
            self._net.inject("net:wan_up", self._state.wan_up)
            self._net.inject("net:clients", self._state.clients)
            self._net.inject("net:state", self._state.to_dict())

        return self._state

    @property
    def state(self) -> RouterState:
        return self._state
