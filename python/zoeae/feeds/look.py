"""Zoeae SensorNet auto-discovery.

Scans BLE, serial ports, and LAN to find what's available,
then attaches matching feeds to the ecosystem automatically.

Usage:
    eco = Ecosystem("taos")
    feeds = await look(eco)
    print(f"Found {len(feeds)} feeds")
"""
import asyncio
import json
import socket
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

from ..ecosystem import Ecosystem, SensorNet


@dataclass
class Device:
    name: str
    kind: str  # ble, serial, lan
    address: str
    feed: Optional[str] = None  # feed module name if recognized
    details: dict = field(default_factory=dict)


# ── Known device signatures ──────────────────────────────────────────────────

BLE_SIGNATURES = {
    0xB5B5: "ecoflow",
    0xC5C5: "ecoflow",
}

BLE_NAME_PATTERNS = {
    "R33": "ecoflow",
    "R35": "ecoflow",
    "BYD": "byd",
}

SERIAL_VID_PID = {
    "0483:5740": "nanovna",      # STM32 CDC — NanoVNA F V2
    "1A86:7523": "ch340",        # CH340 — Arduino/ESP/generic
}

MOONRAKER_MODELS = {
    "K1": "klipper",
    "K1C": "klipper",
    "Ender": "klipper",
}


# ── Scanners ──────────────────────────────────────────────────────────────────

async def scan_ble(timeout: float = 10.0) -> list[Device]:
    """Scan BLE advertisements."""
    devices = []
    try:
        from bleak import BleakScanner
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        for addr, (dev, adv) in found.items():
            name = dev.name or adv.local_name or ""
            mfr = adv.manufacturer_data or {}
            rssi = adv.rssi or 0

            feed = None
            for mfr_id, feed_name in BLE_SIGNATURES.items():
                if mfr_id in mfr:
                    feed = feed_name
                    break
            if not feed:
                for prefix, feed_name in BLE_NAME_PATTERNS.items():
                    if name.startswith(prefix):
                        feed = feed_name
                        break

            details = {"rssi": rssi, "name": name}
            if mfr:
                details["mfr"] = {f"0x{k:04x}": v.hex()[:40] for k, v in mfr.items()}
            if adv.service_uuids:
                details["services"] = [str(s) for s in adv.service_uuids]

            devices.append(Device(
                name=name or addr,
                kind="ble",
                address=addr,
                feed=feed,
                details=details,
            ))
    except ImportError:
        pass
    except Exception:
        pass
    return devices


def scan_serial() -> list[Device]:
    """Find serial ports and identify known devices."""
    devices = []
    try:
        import serial.tools.list_ports
        for port in serial.tools.list_ports.comports():
            vid_pid = f"{port.vid:04X}:{port.pid:04X}" if port.vid and port.pid else ""
            feed = SERIAL_VID_PID.get(vid_pid)

            devices.append(Device(
                name=port.description or port.device,
                kind="serial",
                address=port.device,
                feed=feed,
                details={
                    "vid_pid": vid_pid,
                    "manufacturer": port.manufacturer or "",
                    "serial_number": port.serial_number or "",
                    "hwid": port.hwid or "",
                },
            ))
    except ImportError:
        pass
    return devices


def scan_lan(subnet: str = "192.168.1", timeout: float = 0.5) -> list[Device]:
    """Scan LAN for known services."""
    devices = []

    def check_host(ip: str) -> Optional[Device]:
        services = {}
        checks = {
            80: "http", 443: "https", 22: "ssh",
            7125: "moonraker", 8080: "http_alt",
            1883: "mqtt", 8883: "mqtt_tls",
            9999: "creality",
        }
        for port, svc in checks.items():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                if s.connect_ex((ip, port)) == 0:
                    services[svc] = port
            except Exception:
                pass
            finally:
                s.close()

        if not services:
            return None

        # Identify device
        feed = None
        name = ip
        details = {"services": services}

        if "moonraker" in services:
            feed = "klipper"
            try:
                url = f"http://{ip}:7125/printer/info"
                with urllib.request.urlopen(url, timeout=3) as resp:
                    data = json.loads(resp.read())
                    hostname = data.get("result", {}).get("hostname", "")
                    name = hostname or f"klipper@{ip}"
                    details["hostname"] = hostname
            except Exception:
                name = f"moonraker@{ip}"

        elif services.keys() == {"http", "ssh"} or services.keys() == {"http"}:
            # Could be a router
            if ip.endswith(".1"):
                feed = "router"
                name = f"router@{ip}"

        return Device(name=name, kind="lan", address=ip,
                      feed=feed, details=details)

    # Get own IP to skip
    own_ip = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        own_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    ips = [f"{subnet}.{i}" for i in range(1, 255) if f"{subnet}.{i}" != own_ip]

    with ThreadPoolExecutor(max_workers=50) as ex:
        results = list(ex.map(check_host, ips))

    devices = [d for d in results if d is not None]
    return devices


# ── Main discovery ────────────────────────────────────────────────────────────

async def look(eco: Optional[Ecosystem] = None,
               ble: bool = True, serial: bool = True, lan: bool = True,
               attach: bool = True, quiet: bool = False) -> list[Device]:
    """Discover all available sensors and optionally attach to ecosystem.

    Returns list of discovered Device objects.
    """
    all_devices: list[Device] = []

    if not quiet:
        print("looking...")

    # BLE
    if ble:
        if not quiet:
            print("  ble...", end=" ", flush=True)
        ble_devices = await scan_ble()
        all_devices.extend(ble_devices)
        if not quiet:
            print(f"{len(ble_devices)} found")

    # Serial
    if serial:
        if not quiet:
            print("  serial...", end=" ", flush=True)
        serial_devices = scan_serial()
        all_devices.extend(serial_devices)
        if not quiet:
            print(f"{len(serial_devices)} found")

    # LAN
    if lan:
        if not quiet:
            print("  lan...", end=" ", flush=True)
        lan_devices = scan_lan()
        all_devices.extend(lan_devices)
        if not quiet:
            print(f"{len(lan_devices)} found")

    # Print summary
    if not quiet:
        print()
        for d in all_devices:
            tag = f" -> {d.feed}" if d.feed else ""
            print(f"  [{d.kind:6s}] {d.address:22s} {d.name:30s}{tag}")
        print(f"\n  {len(all_devices)} devices, "
              f"{sum(1 for d in all_devices if d.feed)} recognized")

    # Auto-attach recognized feeds
    if attach and eco:
        attached = _attach_feeds(eco, all_devices, quiet)
        if not quiet:
            print(f"  {attached} feeds attached to ecosystem")

    return all_devices


def _attach_feeds(eco: Ecosystem, devices: list[Device],
                  quiet: bool = False) -> int:
    """Attach recognized device feeds to ecosystem."""
    attached = 0

    for d in devices:
        if not d.feed:
            continue

        try:
            if d.feed == "ecoflow":
                from .ecoflow import EcoFlowFeed
                feed = EcoFlowFeed(mac=d.address)
                feed.attach(eco.sensor_net)
                attached += 1

            elif d.feed == "klipper":
                from .klipper import KlipperFeed
                host = d.address
                port = d.details.get("services", {}).get("moonraker", 7125)
                feed = KlipperFeed(host=host, port=port)
                feed.attach(eco.sensor_net)
                attached += 1

            elif d.feed == "nanovna":
                from .nanovna import NanoVNAFeed
                feed = NanoVNAFeed(port=d.address)
                feed.attach(eco.sensor_net)
                attached += 1

            elif d.feed == "router":
                from .router import RouterFeed
                feed = RouterFeed(host=d.address)
                feed.attach(eco.sensor_net)
                attached += 1

            elif d.feed == "ch340":
                # Could be Arduino or Geiger — try Geiger first (57600 baud)
                try:
                    import serial as ser_mod
                    s = ser_mod.Serial(d.address, 57600, timeout=2)
                    time.sleep(0.5)
                    s.write(b"<GETVER>>")
                    time.sleep(0.3)
                    resp = s.read(14)
                    s.close()
                    if b"GMC" in resp:
                        from .geiger import GeigerFeed
                        feed = GeigerFeed(port=d.address)
                        feed.attach(eco.sensor_net)
                        attached += 1
                        if not quiet:
                            print(f"    {d.address}: identified as GMC Geiger counter")
                        continue
                except Exception:
                    pass

                # Fall back to Arduino env
                from .arduino import ArduinoEnvFeed
                feed = ArduinoEnvFeed(port=d.address)
                feed.attach(eco.sensor_net)
                attached += 1

        except Exception as e:
            if not quiet:
                print(f"    {d.feed}@{d.address}: attach failed — {e}")

    # Always attach solar (no hardware needed)
    from .solar import SolarFeed
    SolarFeed().attach(eco.sensor_net)
    attached += 1

    return attached


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(look())
