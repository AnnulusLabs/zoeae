"""Solar position + resource sensor feed for Zoeae SensorNet.

Uses NOAA/Meeus algorithm for position (zero dependencies).
Pulls monthly averages from NREL Solar Resource API (free, DEMO_KEY).

Usage:
    eco = Ecosystem("taos")
    solar = SolarFeed(lat=36.4072, lon=-105.5734)
    solar.attach(eco.sensor_net)
    solar.update()
    print(eco.sensor_net.read("solar:irradiance"))
"""
import json
import math
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..ecosystem import SensorFeed, SensorNet

NREL_API_URL = "https://developer.nlr.gov/api/solar/solar_resource/v1.json"
NREL_API_KEY = "DEMO_KEY"

MONTH_KEYS = ["jan", "feb", "mar", "apr", "may", "jun",
              "jul", "aug", "sep", "oct", "nov", "dec"]


@dataclass
class SolarState:
    altitude_deg: float = 0.0
    azimuth_deg: float = 0.0
    is_daylight: bool = False
    irradiance_w_m2: float = 0.0
    ghi_kwh_m2_day: float = 0.0
    dni_kwh_m2_day: float = 0.0
    lat_tilt_kwh_m2_day: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "altitude_deg": self.altitude_deg,
            "azimuth_deg": self.azimuth_deg,
            "is_daylight": self.is_daylight,
            "irradiance_w_m2": self.irradiance_w_m2,
            "ghi_kwh_m2_day": self.ghi_kwh_m2_day,
            "dni_kwh_m2_day": self.dni_kwh_m2_day,
            "lat_tilt_kwh_m2_day": self.lat_tilt_kwh_m2_day,
            "timestamp": self.timestamp,
        }


def _rad(d): return d * math.pi / 180.0
def _deg(r): return r * 180.0 / math.pi


class SolarFeed:
    """Solar position + irradiance calculator as a SensorNet feed."""

    def __init__(self, lat: float = 36.4072, lon: float = -105.5734,
                 altitude_m: float = 2124.0, interval_s: float = 300.0):
        self.lat = lat
        self.lon = lon
        self.altitude_m = altitude_m
        self.interval_s = interval_s
        self._net: Optional[SensorNet] = None
        self._state = SolarState()

    def attach(self, net: SensorNet) -> None:
        self._net = net
        for feed_id in ["solar:position", "solar:irradiance",
                        "solar:ghi", "solar:dni", "solar:state"]:
            net.register(SensorFeed(
                id=feed_id, kind="weather",
                interval_s=self.interval_s,
            ))
        # Fetch NREL monthly averages once on attach
        self._fetch_nrel()

    def update(self, dt: Optional[datetime] = None) -> SolarState:
        if dt is None:
            dt = datetime.now(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        y, m = dt.year, dt.month
        d = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0
        if m <= 2:
            y -= 1
            m += 12
        A = int(y / 100)
        B = 2 - A + int(A / 4)
        jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5
        t = (jd - 2451545.0) / 36525.0

        L0 = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360.0
        M = (357.52911 + t * (35999.05029 - 0.0001537 * t)) % 360.0
        e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
        Mr = _rad(M)
        C = (math.sin(Mr) * (1.914602 - t * (0.004817 + 0.000014 * t)) +
             math.sin(2 * Mr) * (0.019993 - 0.000101 * t) +
             math.sin(3 * Mr) * 0.000289)
        sun_lon = L0 + C
        sun_anom = M + C

        omega = 125.04 - 1934.136 * t
        app_lon = sun_lon - 0.00569 - 0.00478 * math.sin(_rad(omega))
        obl = 23.439291 - t * (0.0130042 + t * (0.00000016 - 0.000000504 * t))
        obl_corr = obl + 0.00256 * math.cos(_rad(omega))

        decl = _deg(math.asin(math.sin(_rad(obl_corr)) * math.sin(_rad(app_lon))))

        y_var = math.tan(_rad(obl_corr / 2)) ** 2
        eot = 4 * _deg(
            y_var * math.sin(2 * _rad(L0)) -
            2 * e * math.sin(Mr) +
            4 * e * y_var * math.sin(Mr) * math.cos(2 * _rad(L0)) -
            0.5 * y_var * y_var * math.sin(4 * _rad(L0)) -
            1.25 * e * e * math.sin(2 * Mr)
        )

        utc_minutes = dt.hour * 60 + dt.minute + dt.second / 60.0
        ts = (utc_minutes + eot + 4 * self.lon) % 1440
        ha = ts / 4 - 180 if ts > 0 else ts / 4 + 180

        lat_r = _rad(self.lat)
        decl_r = _rad(decl)
        ha_r = _rad(ha)
        sin_alt = (math.sin(lat_r) * math.sin(decl_r) +
                   math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r))
        altitude = _deg(math.asin(max(-1, min(1, sin_alt))))

        cos_az = ((math.sin(decl_r) - math.sin(lat_r) * sin_alt) /
                  (math.cos(lat_r) * math.cos(math.asin(max(-1, min(1, sin_alt)))) + 1e-10))
        azimuth = _deg(math.acos(max(-1, min(1, cos_az))))
        if ha > 0:
            azimuth = 360 - azimuth

        irradiance = 0.0
        if altitude > 0:
            am = 1.0 / (math.sin(_rad(altitude)) + 0.50572 * (6.07995 + altitude) ** -1.6364)
            p_ratio = math.exp(-self.altitude_m / 8500)
            irradiance = 1361.0 * 0.7 ** ((am * p_ratio) ** 0.678)
            irradiance *= math.sin(_rad(altitude))

        self._state = SolarState(
            altitude_deg=round(altitude, 2),
            azimuth_deg=round(azimuth, 2),
            is_daylight=altitude > 0,
            irradiance_w_m2=round(irradiance, 1),
            timestamp=time.time(),
        )

        # Add NREL monthly data for current month
        month_idx = (dt.month - 1) % 12
        self._state.ghi_kwh_m2_day = self._nrel_ghi.get(month_idx, 0.0)
        self._state.dni_kwh_m2_day = self._nrel_dni.get(month_idx, 0.0)
        self._state.lat_tilt_kwh_m2_day = self._nrel_tilt.get(month_idx, 0.0)

        if self._net:
            self._net.inject("solar:position", {
                "altitude_deg": self._state.altitude_deg,
                "azimuth_deg": self._state.azimuth_deg,
            })
            self._net.inject("solar:irradiance", self._state.irradiance_w_m2)
            self._net.inject("solar:ghi", self._state.ghi_kwh_m2_day)
            self._net.inject("solar:dni", self._state.dni_kwh_m2_day)
            self._net.inject("solar:state", self._state.to_dict())

        return self._state

    def _fetch_nrel(self) -> None:
        """Pull monthly GHI/DNI/tilt averages from NREL. Cached per instance."""
        self._nrel_ghi: dict[int, float] = {}
        self._nrel_dni: dict[int, float] = {}
        self._nrel_tilt: dict[int, float] = {}
        try:
            url = (f"{NREL_API_URL}?api_key={NREL_API_KEY}"
                   f"&lat={self.lat}&lon={self.lon}")
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            outputs = data.get("outputs", {})
            for i, key in enumerate(MONTH_KEYS):
                self._nrel_ghi[i] = outputs.get("avg_ghi", {}).get("monthly", {}).get(key, 0.0)
                self._nrel_dni[i] = outputs.get("avg_dni", {}).get("monthly", {}).get(key, 0.0)
                self._nrel_tilt[i] = outputs.get("avg_lat_tilt", {}).get("monthly", {}).get(key, 0.0)
        except Exception:
            pass

    @property
    def state(self) -> SolarState:
        return self._state
