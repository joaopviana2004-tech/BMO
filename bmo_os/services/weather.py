"""Cliente OpenWeather com cache local e fallback.

Configure via variáveis de ambiente:
    OPENWEATHER_API_KEY  — chave da API (https://openweathermap.org/api)
    OPENWEATHER_CITY     — nome da cidade (ex: "Sao Paulo,BR")

Se não tiver chave, retorna valores placeholder e não tenta rede.
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


@dataclass
class WeatherSnapshot:
    temp_c: float | None = None
    humidity: int | None = None
    description: str = ""
    fetched_at: float = 0.0
    ok: bool = False


class WeatherService:
    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENWEATHER_API_KEY", "").strip()
        self.city = os.environ.get("OPENWEATHER_CITY", "Sao Paulo,BR").strip()
        self.snapshot = WeatherSnapshot()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        if self.api_key:
            self._kick_off()

    def _kick_off(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            self._fetch()
            time.sleep(UPDATE_INTERVAL_S)

    def _fetch(self) -> None:
        params = urllib.parse.urlencode({
            "q": self.city,
            "appid": self.api_key,
            "units": "metric",
            "lang": "pt_br",
        })
        url = f"https://api.openweathermap.org/data/2.5/weather?{params}"
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.load(resp)
            snap = WeatherSnapshot(
                temp_c=float(data["main"]["temp"]),
                humidity=int(data["main"]["humidity"]),
                description=str(data["weather"][0]["description"]),
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
