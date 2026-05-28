"""Cliente Open-Meteo (https://open-meteo.com) — grátis, sem API key.

Configure via variáveis de ambiente (opcional, default = João Pessoa/PB):
    WEATHER_LAT       — latitude  (ex: "-7.1195")
    WEATHER_LON       — longitude (ex: "-34.8450")
    WEATHER_TIMEZONE  — timezone (ex: "America/Fortaleza")

A leitura roda em thread separada pra não travar o frame.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

UPDATE_INTERVAL_S = 10 * 60  # 10 min
DEFAULT_LAT = "-7.1195"
DEFAULT_LON = "-34.8450"
DEFAULT_TZ = "America/Fortaleza"

# WMO weather codes -> descrição curta em pt_BR (ASCII, pra fonte pixel renderizar).
# tabela oficial: https://open-meteo.com/en/docs (seção "Weather Code")
WMO_DESC = {
    0: "limpo",
    1: "quase limpo",
    2: "parc nublado",
    3: "nublado",
    45: "nevoa",
    48: "nevoa gelo",
    51: "garoa fraca",
    53: "garoa",
    55: "garoa forte",
    56: "garoa gelo",
    57: "garoa gelo+",
    61: "chuva fraca",
    63: "chuva",
    65: "chuva forte",
    66: "chuva gelada",
    67: "chuva gelo+",
    71: "neve fraca",
    73: "neve",
    75: "neve forte",
    77: "granizo",
    80: "pancadas",
    81: "pancadas+",
    82: "tempestade",
    85: "neve fraca",
    86: "neve forte",
    95: "trovoada",
    96: "trovoada+",
    99: "trovoada++",
}


@dataclass
class WeatherSnapshot:
    temp_c: float | None = None
    humidity: int | None = None
    description: str = ""
    fetched_at: float = 0.0
    ok: bool = False


class WeatherService:
    def __init__(self) -> None:
        self.lat = os.environ.get("WEATHER_LAT", DEFAULT_LAT).strip()
        self.lon = os.environ.get("WEATHER_LON", DEFAULT_LON).strip()
        self.tz = os.environ.get("WEATHER_TIMEZONE", DEFAULT_TZ).strip()
        self.snapshot = WeatherSnapshot()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            self._fetch()
            time.sleep(UPDATE_INTERVAL_S)

    def _fetch(self) -> None:
        params = urllib.parse.urlencode({
            "latitude": self.lat,
            "longitude": self.lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code",
            "timezone": self.tz,
        })
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.load(resp)
            cur = data["current"]
            code = int(cur.get("weather_code", -1))
            snap = WeatherSnapshot(
                temp_c=float(cur["temperature_2m"]),
                humidity=int(cur["relative_humidity_2m"]),
                description=WMO_DESC.get(code, "sem dados"),
                fetched_at=time.time(),
                ok=True,
            )
        except Exception:
            snap = WeatherSnapshot(fetched_at=time.time(), ok=False)
        with self._lock:
            self.snapshot = snap

    def get(self) -> WeatherSnapshot:
        with self._lock:
            return self.snapshot
