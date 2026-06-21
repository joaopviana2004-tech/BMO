"""Serviço de alarme — thread que checa hora atual vs config.

Quando o relógio bate em (alarm_hour:alarm_minute) e alarm_enabled é True,
dispara o callback `on_ring` UMA vez por minuto-do-dia (não re-toca se
ainda for o mesmo minuto).

A UI (AlarmSetScreen) edita os valores no `bmo_config.json`. Este serviço
só lê config a cada 5 segundos.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Callable

from ..core import config


CHECK_INTERVAL_S = 5.0


class AlarmService:
    def __init__(self, on_ring: Callable[[], None]) -> None:
        self.on_ring = on_ring
        # marca último (date, hour, minute) que disparou pra não re-fire
        self._last_fire_key: tuple | None = None
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop:
            try:
                self._check()
            except Exception:
                pass
            time.sleep(CHECK_INTERVAL_S)

    def _check(self) -> None:
        if not config.get("alarm_enabled"):
            return
        try:
            h = int(config.get("alarm_hour") or 0)
            m = int(config.get("alarm_minute") or 0)
        except Exception:
            return
        now = dt.datetime.now()
        if now.hour != h or now.minute != m:
            return
        key = (now.date(), h, m)
        if self._last_fire_key == key:
            return
        self._last_fire_key = key
        self.on_ring()

    def stop(self) -> None:
        self._stop = True
