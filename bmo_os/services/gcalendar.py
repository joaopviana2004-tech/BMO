"""Leitor de Google Calendar (read-only, multi-conta). Duas fontes:

1) iCal (sem login) — env GCAL_ICS_URLS, separadas por vírgula, rótulo
   opcional `Rotulo=...`. Cada fonte pode ser:
     - URL .ics completa: secreta ("Endereço secreto no formato iCal") OU
       pública (calendário tornado público);
     - só o ID/e-mail de um calendário PÚBLICO — a URL pública é montada.

2) OAuth (login com a conta) — pra calendário PRIVADO, inclusive Google
   Workspace onde o admin bloqueia compartilhamento/endereço secreto. Lê a
   API do Calendar com um refresh token salvo em `gcal_tokens.json` (gerado
   pelo `scripts/gcal_auth.py`). Precisa de GCAL_CLIENT_ID/GCAL_CLIENT_SECRET
   no .env. A API já expande recorrência (singleEvents), então a fonte OAuth
   funciona mesmo SEM a lib icalendar. Implementação em urllib puro.

As duas fontes podem coexistir; cada conta ganha uma cor na tela AGENDA.
Roda em thread (igual weather/todoist) e mantém o último snapshot bom.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import urllib.error
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


# ---------- OAuth (calendário privado / Workspace) ----------

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
CAL_API = "https://www.googleapis.com/calendar/v3/calendars"
TOKENS_PATH = config.REPO_ROOT / "gcal_tokens.json"


def _oauth_creds() -> tuple[str, str]:
    cid = os.environ.get("GCAL_CLIENT_ID", "").strip()
    csec = os.environ.get("GCAL_CLIENT_SECRET", "").strip()
    return cid, csec


def _resolve_oauth_accounts() -> list[dict]:
    """Contas OAuth salvas em gcal_tokens.json. Cada conta pode trazer seu próprio
    client_id/client_secret (multi-cliente: pessoal e empresa têm clientes
    diferentes); cai pro GCAL_CLIENT_ID global do .env se a conta não tiver."""
    if not TOKENS_PATH.exists():
        return []
    try:
        data = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    return [a for a in accounts
            if a.get("refresh_token") and (a.get("client_id") or _oauth_creds()[0])]


def _parse_api_dt(node: dict):
    """Converte o {start|end} da API v3 em datetime/date pra cair no _to_local.

    dateTime: RFC3339 (com offset, às vezes 'Z'); date: all-day.
    """
    if not node:
        return None, False
    if "dateTime" in node:
        raw = node["dateTime"].replace("Z", "+00:00")
        return dt.datetime.fromisoformat(raw), False
    if "date" in node:
        return dt.date.fromisoformat(node["date"]), True
    return None, False


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
        # cache de access_token por refresh_token: refresh -> (token, expira_em)
        self._token_cache: dict[str, tuple[str, float]] = {}

        ical_sources = _resolve_sources()
        oauth_accounts = _resolve_oauth_accounts()

        if not ical_sources and not oauth_accounts:
            self.snapshot = CalendarSnapshot(ok=False, error="sem URLs")
            return
        # só tem iCal e falta a lib -> não dá pra parsear nada
        if ical_sources and not oauth_accounts and not HAS_ICAL:
            self.snapshot = CalendarSnapshot(ok=False, error="sem libs")
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
        # fontes unificadas: ("ical", label, url) e ("oauth", label, conta)
        sources: list[tuple[str, str, object]] = []
        for label, url in _resolve_sources():
            sources.append(("ical", label, url))
        for acc in _resolve_oauth_accounts():
            sources.append(("oauth", acc.get("label", "conta"), acc))

        if not sources:
            self._set(CalendarSnapshot(ok=False, error="sem URLs"))
            return

        now = dt.datetime.now(_local_tz())
        day = now.date()
        start = dt.datetime.combine(day, dt.time.min, tzinfo=_local_tz())
        end = dt.datetime.combine(day, dt.time.max, tzinfo=_local_tz())

        events: list[CalEvent] = []
        errors: list[str] = []
        for idx, (kind, label, payload) in enumerate(sources):
            color = ACCOUNT_COLORS[idx % len(ACCOUNT_COLORS)]
            try:
                if kind == "oauth":
                    events += self._fetch_oauth(payload, label, color, start, end)
                elif not HAS_ICAL:
                    errors.append("falta icalendar")
                else:
                    events += self._fetch_one(payload, label, color, start, end)
            except Exception as e:  # uma conta falhando não derruba as outras
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

    # ---------- OAuth ----------

    def _access_token(self, account: dict) -> str:
        """Troca o refresh token por um access token (cacheado até expirar).
        Usa o client_id/secret DA CONTA (cada conta pode ter o seu); cai pro
        global do .env se a conta não trouxer."""
        refresh_token = account["refresh_token"]
        now = time.time()
        cached = self._token_cache.get(refresh_token)
        if cached and cached[1] - 60 > now:
            return cached[0]
        cid = account.get("client_id") or _oauth_creds()[0]
        csec = account.get("client_secret") or _oauth_creds()[1]
        body = urllib.parse.urlencode({
            "client_id": cid,
            "client_secret": csec,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).encode("utf-8")
        req = urllib.request.Request(OAUTH_TOKEN_URL, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            tok = json.load(resp)
        access = tok["access_token"]
        expires = now + int(tok.get("expires_in", 3600))
        self._token_cache[refresh_token] = (access, expires)
        return access

    def _fetch_oauth(self, account: dict, label: str, color, start, end) -> list[CalEvent]:
        token = self._access_token(account)
        cal_id = account.get("calendar_id") or "primary"
        params = urllib.parse.urlencode({
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",     # expande recorrência no servidor
            "orderBy": "startTime",
            "maxResults": "50",
        })
        url = f"{CAL_API}/{urllib.parse.quote(cal_id, safe='')}/events?{params}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.load(resp)

        out: list[CalEvent] = []
        for item in data.get("items", []):
            if item.get("status") == "cancelled":
                continue
            s_val, all_day = _parse_api_dt(item.get("start", {}))
            if s_val is None:
                continue
            e_val, _ = _parse_api_dt(item.get("end", {}))
            ev_start, _ = _to_local(s_val)
            ev_end, _ = _to_local(e_val) if e_val is not None else (ev_start, all_day)
            title = (item.get("summary") or "(sem titulo)").strip() or "(sem titulo)"
            out.append(CalEvent(
                title=title,
                start=ev_start,
                end=ev_end,
                all_day=all_day,
                cal_label=label,
                color=color,
            ))
        return out

    # ---------- escrita (criar evento) ----------

    def _writable_account(self) -> dict | None:
        """Primeira conta OAuth autorizada com escopo de ESCRITA (gcal_auth
        --write marca "write": true). None se nenhuma pode escrever."""
        for a in _resolve_oauth_accounts():
            if a.get("write"):
                return a
        return None

    def can_write(self) -> bool:
        return self._writable_account() is not None

    def create_event(self, title: str, date: str, time: str = "",
                     duration_min: int = 60) -> dict:
        """Cria um evento na conta com permissão de escrita (a pessoal).
        date = "YYYY-MM-DD"; time = "HH:MM" ("" = dia todo). Retorna
        {ok, error?, title, date, time}. Dispara refresh do snapshot."""
        acc = self._writable_account()
        if acc is None:
            return {"ok": False, "error": "nenhuma conta com permissao de escrita "
                    "(rode: python scripts/gcal_auth.py --write)"}
        title = (title or "").strip() or "(sem titulo)"
        try:
            d = dt.date.fromisoformat((date or "").strip()[:10])
        except Exception:
            return {"ok": False, "error": "data invalida (use YYYY-MM-DD)"}
        body: dict = {"summary": title}
        time = (time or "").strip()
        if time:
            try:
                hh, mm = (int(x) for x in time.split(":")[:2])
            except Exception:
                hh, mm = 9, 0
            start_dt = dt.datetime.combine(d, dt.time(hh, mm), tzinfo=_local_tz())
            end_dt = start_dt + dt.timedelta(minutes=max(5, int(duration_min or 60)))
            body["start"] = {"dateTime": start_dt.isoformat()}
            body["end"] = {"dateTime": end_dt.isoformat()}
        else:
            body["start"] = {"date": d.isoformat()}
            body["end"] = {"date": (d + dt.timedelta(days=1)).isoformat()}
        try:
            token = self._access_token(acc)
        except Exception as e:
            return {"ok": False, "error": "auth: " + str(e)[:70]}
        cal_id = acc.get("calendar_id") or "primary"
        url = f"{CAL_API}/{urllib.parse.quote(cal_id, safe='')}/events"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                created = json.load(resp)
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": f"HTTP {e.code} ao criar evento"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:80]}
        self.trigger_refresh()
        return {"ok": True, "id": created.get("id", ""), "title": title,
                "date": d.isoformat(), "time": time}

    def _set(self, snap: CalendarSnapshot) -> None:
        with self._lock:
            self.snapshot = snap

    # ---------- snapshot ----------

    def get(self) -> CalendarSnapshot:
        with self._lock:
            return self.snapshot
