"""GQ GMC-300E Geiger counter sensor feed for Zoeae SensorNet.

Reads CPM (counts per minute) over USB serial using GQ-RFC1201 protocol.
No dependencies beyond pyserial.

Registers:
  - rad:cpm       (int, counts per minute)
  - rad:usv_h     (float, microsieverts/hour estimate)
  - rad:state     (full dict)

Usage:
    eco = Ecosystem("taos")
    geiger = GeigerFeed(port="COM16")
    geiger.attach(eco.sensor_net)
    geiger.poll()
    print(eco.sensor_net.read("rad:cpm"))
"""
import time
from dataclasses import dataclass
from typing import Optional

from ..ecosystem import SensorFeed, SensorNet

# GMC-300E conversion factor (CPM to uSv/h)
# Varies by tube — SBM-20 is ~0.0057, LND-7317 is ~0.0083
# GMC-300E uses M4011 tube, factor ~0.0065
CPM_TO_USV = 0.0065


@dataclass
class GeigerState:
    cpm: int = 0
    usv_h: float = 0.0
    model: str = ""
    serial: str = ""
    timestamp: float = 0.0

    @property
    def level(self) -> str:
        if self.usv_h > 1.0:
            return "danger"
        if self.usv_h > 0.5:
            return "elevated"
        if self.usv_h > 0.2:
            return "above_normal"
        return "normal"  # background in Taos ~0.08-0.15 uSv/h

    def to_dict(self) -> dict:
        return {
            "cpm": self.cpm,
            "usv_h": self.usv_h,
            "level": self.level,
            "model": self.model,
            "serial": self.serial,
            "timestamp": self.timestamp,
        }


class GeigerFeed:
    """GQ GMC-300E Geiger counter feed using GQ-RFC1201 protocol."""

    def __init__(self, port: str = "COM16", baud: int = 57600,
                 interval_s: float = 60.0):
        self.port = port
        self.baud = baud
        self.interval_s = interval_s
        self._net: Optional[SensorNet] = None
        self._state = GeigerState()

    def attach(self, net: SensorNet) -> None:
        self._net = net
        for feed_id, kind in [
            ("rad:cpm", "radiation"),
            ("rad:usv_h", "radiation"),
            ("rad:state", "radiation"),
        ]:
            net.register(SensorFeed(
                id=feed_id, kind=kind,
                endpoint=f"serial://{self.port}",
                interval_s=self.interval_s,
            ))

    def _cmd(self, ser, cmd: str, response_len: int = 0) -> bytes:
        """Send GQ-RFC1201 command and read response."""
        ser.write(f"<{cmd}>>".encode("ascii"))
        time.sleep(0.2)
        if response_len > 0:
            return ser.read(response_len)
        return b""

    def poll(self) -> GeigerState:
        try:
            import serial
        except ImportError:
            return self._state

        try:
            ser = serial.Serial(self.port, self.baud, timeout=3)
            time.sleep(0.5)
            ser.read(ser.in_waiting or 256)  # flush

            # Get version/model (14 bytes)
            model_raw = self._cmd(ser, "GETVER", 14)
            model = model_raw.decode("ascii", errors="replace").strip()

            # Get serial (7 bytes)
            sn_raw = self._cmd(ser, "GETSERIAL", 7)
            sn = sn_raw.hex()

            # Get CPM (2 bytes, big-endian uint16)
            cpm_raw = self._cmd(ser, "GETCPM", 2)
            cpm = 0
            if len(cpm_raw) == 2:
                cpm = (cpm_raw[0] << 8) | cpm_raw[1]
                # GMC protocol: if bit 15 is set, value is in CPS mode
                if cpm & 0x8000:
                    cpm = (cpm & 0x3FFF) * 60  # convert CPS to CPM

            ser.close()

            self._state = GeigerState(
                cpm=cpm,
                usv_h=round(cpm * CPM_TO_USV, 4),
                model=model,
                serial=sn,
                timestamp=time.time(),
            )

        except Exception:
            pass

        if self._net:
            self._net.inject("rad:cpm", self._state.cpm)
            self._net.inject("rad:usv_h", self._state.usv_h)
            self._net.inject("rad:state", self._state.to_dict())

        return self._state

    @property
    def state(self) -> GeigerState:
        return self._state
