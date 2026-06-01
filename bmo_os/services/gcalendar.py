"""Leitor de Google Calendar via iCal (read-only, multi-conta).

Baixa .ics, expande eventos recorrentes e devolve só os eventos de HOJE.

Cada fonte (separadas por vírgula, rótulo opcional `Rotulo=...`) pode ser:
  - uma URL .ics completa: secreta (Configurações -> "Endereço secreto no
    formato iCal") OU pública (calendário tornado público);
  - só o ID/e-mail de um calendário PÚBLICO (ex: seu@gmail.com ou
    `xxx@group.calendar.google.com`) — a gente monta a URL pública sozinho.

Cada conta ganha uma cor pra diferenciar na tela AGENDA.

Config:
    env GCAL_ICS_URLS  (ganha de config['gcal_ics_urls'])
    formato: "Pessoal=https://...,Feriados=br#holiday@group.v.calendar.google.com"

Roda em thread (igual weather/todoist) e mantém o último snapshot bom.
Sem as libs `icalendar`/`recurring_ical_events` -> snapshot.ok=False com
mensagem amigável (degrada igual a câmera no Windows).
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from ..core import config
from ..core.theme import Colors

# libs opcionais — sem elas o serviço degrada com mensagem amigável
try:
    from icalendar import Calendar
    HAS_ICAL = True
except Exception:  # pragma: no cover - depende do ambiente
    Calendar = None  # type: ignore[assignment]
    HAS_ICAL = False

try:
    import recurring_ical_events
    HAS_RECUR = True
except Exception:  # pragma: no cover
    recurring_ical_events = None  # type: ignore[assignment]
    HAS_RECUR = False

UPDATE_INTERVAL_S = 5 * 60   # ICS é cacheável; 5 min está de bom tamanho
HTTP_TIMEOUT = 12

# Cores por conta (único respingo de cor da tela; texto continua P&B).
ACCOUNT_COLORS = [
    Colors.CYAN,
    Colors.YELLOW,
    Colors.GREEN_BTN,
    Colors.RED,
    Colors.BMO_BLUE,
]


@dataclass
class CalEvent:
    title: str
    start: dt.datetime          # sempre aware (tz local) — exceto all_day (date 00:00)
    end: dt.datetime
    all_day: bool
    cal_label: str
    color: tuple

    def key(self) -> str:
        """Identidade estável pro sistema de alertas (não refazer aviso)."""
        return f"{self.cal_label}|{self.title}|{self.start.isoformat()}"


@dataclass
class CalendarSnapshot:
    ok: bool = False
    error: str = ""              # "" | "sem URLs" | "sem libs" | "<msg rede>"
    events: list[CalEvent] = field(default_factory=list)   # de HOJE, ordenados
    fetched_at: float = 0.0


# URL pública iCal de um calendário (montada a partir do ID/e-mail).
PUBLIC_ICS = "https://calendar.google.com/calendar/ical/{}/public/basic.ics"


def _to_ics_url(value: str) -> str:
    """Resolve a fonte numa URL .ics.

    - http(s):// ou webcal:// -> usa como está (URL secreta ou pública pronta);
    - qualquer outra coisa -> trata como ID de calendário público e monta a URL.
    """
    value = value.strip()
    if value.startswith("webcal://"):
        return "https://" + value[len("webcal://"):]
    if value.startswith(("http://", "https://")):
        return value
    # ID/e-mail de calendário público (precisa estar "público" no Google)
    return PUBLIC_ICS.format(urllib.parse.quote(value, safe=""))


def _parse_sources(raw: str) -> list[tuple[str, str]]:
    """Quebra "Rotulo=fonte,fonte2" em [(rotulo, url_ics), ...].

    'fonte' pode ser URL completa ou ID de calendário público. URL secreta e
    IDs do Google não têm ',' e o ID não tem '=', então os splits são seguros.
    """
    out: list[tuple[str, str]] = []
    for i, chunk in enumerate(raw.split(",")):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk and not chunk.startswith(("http://", "https://", "webcal://")):
            label, _, src = chunk.partition("=")
            label, src = label.strip(), src.strip()
        else:
            label, src = f"Conta {i + 1}", chunk
        url = _to_ics_url(src)
        if url:
            out.append((label, url))
    return out


def _resolve_sources() -> list[tuple[str, str]]:
    raw = os.environ.get("GCAL_ICS_URLS", "").strip()
    if not raw:
        raw = (config.get("gcal_ics_urls") or "").strip()
    return _parse_sources(raw)


def _to_local(value) -> tuple[dt.datetime, bool]:
    """Normaliza DTSTART/DTEND do ics pra datetime aware local.

    Retorna (datetime_local, all_day). All-day vem como `date` (sem hora).
    """
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_local_tz())
        return value.astimezone(_local_tz()), False
    if isinstance(value, dt.date):
        # all-day: ancora em 00:00 local
        d = dt.datetime.combine(value, dt.time.min, tzinfo=_local_tz())
        return d, True
    # fallback improvável
    return dt.datetime.now(_local_tz()), False


def _local_tz() -> dt.tzinfo:
    # tz local do sistema (o Pi roda no fuso configurado)
    return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


class CalendarService:
    def __init__(self) -> None:
        self.snapshot = CalendarSnapshot()
        self._lock = threading.Lock()
        self._wake = threading.Event()

        if not HAS_ICAL:
            self.snapshot = CalendarSnapshot(ok=False, error="sem libs")
            return
        if not _resolve_sources():
            self.snapshot = CalendarSnapshot(ok=False, error="sem URLs")
            return

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ---------- loop ----------

    def _loop(self) -> None:
        while True:
            self._fetch()
            self._wake.wait(UPDATE_INTERVAL_S)
            self._wake.clear()

    def trigger_refresh(self) -> None:
        """Acorda o loop pra refazer fetch agora (botão SYNC)."""
        self._wake.set()

    # ---------- fetch ----------

    def _fetch(self) -> None:
        sources = _resolve_sources()
        if not sources:
            self._set(CalendarSnapshot(ok=False, error="sem URLs"))
            return

        now = dt.datetime.now(_local_tz())
        day = now.date()
        start = dt.datetime.combine(day, dt.time.min, tzinfo=_local_tz())
        end = dt.datetime.combine(day, dt.time.max, tzinfo=_local_tz())

        events: list[CalEvent] = []
        errors: list[str] = []
        for idx, (label, url) in enumerate(sources):
            color = ACCOUNT_COLORS[idx % len(ACCOUNT_COLORS)]
            try:
                events += self._fetch_one(url, label, color, start, end)
            except Exception as e:  # rede / parse de uma conta não derruba as outras
                errors.append(str(e)[:40])

        if not events and errors:
            # nenhuma conta respondeu — mantém último snapshot bom se existir
            with self._lock:
                if self.snapshot.ok and self.snapshot.events:
                    self.snapshot.fetched_at = time.time()
                    return
            self._set(CalendarSnapshot(ok=False, error=errors[0], fetched_at=time.time()))
            return

        events.sort(key=lambda e: (not e.all_day, e.start))
        self._set(CalendarSnapshot(ok=True, events=events, fetched_at=time.time()))

    def _fetch_one(self, url: str, label: str, color, start, end) -> list[CalEvent]:
        req = urllib.request.Request(url, headers={"User-Agent": "BMO-OS/1.0"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
        cal = Calendar.from_ical(raw)

        if HAS_RECUR:
            comps = recurring_ical_events.of(cal).between(start, end)
        else:
            # fallback sem expansão de recorrência: só pega VEVENTs simples
            comps = [c for c in cal.walk("VEVENT")]

        out: list[CalEvent] = []
        for comp in comps:
            dtstart_field = comp.get("DTSTART")
            if dtstart_field is None:
                continue
            ev_start, all_day = _to_local(dtstart_field.dt)

            dtend_field = comp.get("DTEND")
            if dtend_field is not None:
                ev_end, _ = _to_local(dtend_field.dt)
            elif all_day:
                ev_end = ev_start + dt.timedelta(days=1)
            else:
                ev_end = ev_start + dt.timedelta(hours=1)

            # sem expansão: filtra manualmente quem cai hoje
            if not HAS_RECUR:
                if all_day:
                    if ev_start.date() != start.date():
                        continue
                elif not (ev_start <= end and ev_end >= start):
                    continue

            title = str(comp.get("SUMMARY", "(sem titulo)")).strip() or "(sem titulo)"
            out.append(CalEvent(
                title=title,
                start=ev_start,
                end=ev_end,
                all_day=all_day,
                cal_label=label,
                color=color,
            ))
        return out

    def _set(self, snap: CalendarSnapshot) -> None:
        with self._lock:
            self.snapshot = snap

    # ---------- snapshot ----------

    def get(self) -> CalendarSnapshot:
        with self._lock:
            return self.snapshot
