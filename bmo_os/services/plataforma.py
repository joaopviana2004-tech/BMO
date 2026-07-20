"""Cliente da Plataforma Central (a "Secretaria Pessoal") pro BMO OS.

A Plataforma roda no PC (TanStack Start, porta 8080) e expõe uma API REST
autenticada por Bearer token. Este serviço lê tarefas + compromissos + assuntos
de lá e escreve de volta (concluir/criar tarefa, criar evento), degradando
sozinho quando o PC está desligado — igual weather/todoist/gcalendar.

Ele NÃO é consumido direto pelas telas: expõe dois adaptadores *drop-in*, com
exatamente a mesma interface dos serviços que substituem, pra a UI não mudar:

  - `PlataformaBoard`  ↔ TodoistService  (tela TAREFAS, pomodoro, brain, painel,
    IA). Board GLOBAL (todos os assuntos juntos) em 3 colunas — REVISÃO dobra em
    CONCLUÍDO (decisão do dono).
  - `PlataformaCalendar` ↔ CalendarService (tela AGENDA, alerter, brain, painel).
    Compromissos de HOJE. `MergedCalendar` junta com o Google (se configurado),
    sem duplicar os eventos que a própria Plataforma já espelha no Google.

E `PlataformaNotify` assina o tópico ntfy da Plataforma pra receber, em tempo
real, os MESMOS avisos que vão pro celular (o frame_hook do main vira isso em
AlertScreen + voz).

Config (env ganha do bmo_config.json):
    PLATAFORMA_URL         ex "http://192.168.0.10:8080"  (default localhost:8080)
    PLATAFORMA_TOKEN       Bearer da Plataforma (workspace-data/.store/mcp-config.json)
    PLATAFORMA_ASSUNTO     assunto default ao criar tarefa/evento (default "pessoal")
    PLATAFORMA_NTFY_TOPIC  tópico ntfy (workspace-data/.store/notify.json)
    PLATAFORMA_NTFY_SERVER servidor ntfy (default https://ntfy.sh)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..core import config
from .gcalendar import ACCOUNT_COLORS, CalEvent

UPDATE_INTERVAL_S = 60
HTTP_TIMEOUT = 10

# 4 colunas da Plataforma -> 3 do board do BMO. "review" dobra em "done".
SECTION_NAMES = ["to-do", "doing", "done"]
SECTION_LABELS = {"to-do": "TO-DO", "doing": "DOING", "done": "DONE"}
STATUS_TO_SECTION = {"todo": "to-do", "doing": "doing", "review": "done", "done": "done"}
SECTION_TO_STATUS = {"to-do": "todo", "doing": "doing", "done": "done"}


# --------------------------------------------------------------------------- #
#  Config helpers                                                             #
# --------------------------------------------------------------------------- #

def _cfg(env_key: str, cfg_key: str, default: str = "") -> str:
    val = os.environ.get(env_key, "").strip()
    if val:
        return val
    return (config.get(cfg_key) or "").strip() or default


def _base_url() -> str:
    return _cfg("PLATAFORMA_URL", "plataforma_url", "http://localhost:8080").rstrip("/")


def _token() -> str:
    return _cfg("PLATAFORMA_TOKEN", "plataforma_token")


def _default_assunto() -> str:
    return _cfg("PLATAFORMA_ASSUNTO", "plataforma_assunto", "pessoal")


def _local_tz() -> dt.tzinfo:
    return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


def _today_iso() -> str:
    return dt.date.today().isoformat()


def _request(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8")
        except Exception:
            return e.code, ""


# --------------------------------------------------------------------------- #
#  Board (tarefas) — formato compatível com todoist.Task / TodoistSnapshot    #
# --------------------------------------------------------------------------- #

@dataclass
class BoardTask:
    id: str
    content: str          # = titulo
    section_key: str      # "to-do" | "doing" | "done"
    due: str = ""         # prazo "YYYY-MM-DD" ("" = sem prazo)
    assunto: str = ""


@dataclass
class BoardSnapshot:
    ok: bool = False
    error: str = ""
    tasks: list[BoardTask] = field(default_factory=list)
    fetched_at: float = 0.0
    # presentes só por compatibilidade com quem lia o snapshot do Todoist
    project_id: str = ""
    sections: dict[str, str] = field(default_factory=dict)


@dataclass
class EventsSnapshot:
    ok: bool = False
    error: str = ""
    events: list[CalEvent] = field(default_factory=list)   # de HOJE, ordenados
    fetched_at: float = 0.0


# --------------------------------------------------------------------------- #
#  Serviço base — um poller, dois snapshots (board + eventos de hoje)         #
# --------------------------------------------------------------------------- #

class PlataformaService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._board = BoardSnapshot()
        self._events = EventsSnapshot()
        self._assunto_color: dict[str, tuple] = {}
        self._assunto_nome: dict[str, str] = {}
        if not _token():
            self._board = BoardSnapshot(ok=False, error="sem PLATAFORMA_TOKEN")
            self._events = EventsSnapshot(ok=False, error="sem PLATAFORMA_TOKEN")
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
        self._wake.set()

    # ---------- fetch ----------

    def _fetch(self) -> None:
        base, token = _base_url(), _token()
        if not token:
            with self._lock:
                self._board = BoardSnapshot(ok=False, error="sem PLATAFORMA_TOKEN")
                self._events = EventsSnapshot(ok=False, error="sem PLATAFORMA_TOKEN")
            return

        # assuntos (nomes + cores) — best-effort, não derruba o resto se falhar
        try:
            status, body = _request("GET", f"{base}/api/assuntos", token)
            if status == 200:
                self._ingest_assuntos(json.loads(body))
        except Exception:
            pass

        board_ok = self._fetch_board(base, token)
        self._fetch_events(base, token, board_ok)

    def _ingest_assuntos(self, assuntos: list) -> None:
        nome: dict[str, str] = {}
        color: dict[str, tuple] = {}
        for i, a in enumerate(assuntos if isinstance(assuntos, list) else []):
            aid = str(a.get("id") or "")
            if not aid:
                continue
            nome[aid] = str(a.get("nome") or aid)
            color[aid] = ACCOUNT_COLORS[i % len(ACCOUNT_COLORS)]
        with self._lock:
            self._assunto_nome = nome
            self._assunto_color = color

    def _fetch_board(self, base: str, token: str) -> bool:
        try:
            status, body = _request("GET", f"{base}/api/tasks", token)
        except Exception as e:
            self._set_board_error(_neterr(e))
            return False
        if status == 401:
            self._set_board_error("token invalido (401)")
            return False
        if status != 200:
            self._set_board_error(f"HTTP {status}")
            return False
        try:
            raw = json.loads(body)
        except Exception:
            self._set_board_error("resposta invalida")
            return False

        tasks: list[BoardTask] = []
        for t in raw if isinstance(raw, list) else []:
            st = str(t.get("status") or "todo")
            section = STATUS_TO_SECTION.get(st, "to-do")
            tasks.append(BoardTask(
                id=str(t.get("id") or ""),
                content=(t.get("titulo") or "").strip(),
                section_key=section,
                due=(t.get("prazo") or "")[:10],
                assunto=str(t.get("assunto") or ""),
            ))
        with self._lock:
            self._board = BoardSnapshot(ok=True, error="", tasks=tasks, fetched_at=time.time())
        return True

    def _fetch_events(self, base: str, token: str, board_ok: bool) -> None:
        today = _today_iso()
        try:
            status, body = _request(
                "GET", f"{base}/api/events?de={today}&ate={today}", token)
        except Exception as e:
            self._set_events_error(_neterr(e))
            return
        if status != 200:
            self._set_events_error(f"HTTP {status}")
            return
        try:
            raw = json.loads(body)
        except Exception:
            self._set_events_error("resposta invalida")
            return

        events: list[CalEvent] = []
        for e in raw if isinstance(raw, list) else []:
            ev = self._to_calevent(e)
            if ev is not None:
                events.append(ev)
        events.sort(key=lambda ev: (ev.all_day, ev.start))
        with self._lock:
            self._events = EventsSnapshot(ok=True, error="", events=events, fetched_at=time.time())

    def _to_calevent(self, e: dict) -> CalEvent | None:
        data = str(e.get("data") or "")
        hora = str(e.get("hora") or "")
        if not data:
            return None
        try:
            y, mo, d = (int(x) for x in data.split("-")[:3])
            if hora:
                hh, mm = (int(x) for x in hora.split(":")[:2])
            else:
                hh, mm = 9, 0
            start = dt.datetime(y, mo, d, hh, mm, tzinfo=_local_tz())
        except Exception:
            return None
        dur = e.get("duracaoMin")
        dur = int(dur) if isinstance(dur, (int, float)) and dur else 60
        end = start + dt.timedelta(minutes=max(5, dur))
        assunto = str(e.get("assunto") or "")
        with self._lock:
            label = self._assunto_nome.get(assunto, assunto or "Plataforma")
            color = self._assunto_color.get(assunto, ACCOUNT_COLORS[0])
        return CalEvent(
            title=(e.get("titulo") or "(sem titulo)").strip() or "(sem titulo)",
            start=start, end=end, all_day=False, cal_label=label, color=color,
        )

    def _set_board_error(self, msg: str) -> None:
        with self._lock:
            self._board = BoardSnapshot(
                ok=False, error=msg, tasks=self._board.tasks, fetched_at=time.time())

    def _set_events_error(self, msg: str) -> None:
        with self._lock:
            self._events = EventsSnapshot(
                ok=False, error=msg, events=self._events.events, fetched_at=time.time())

    # ---------- leitura ----------

    def board_snapshot(self) -> BoardSnapshot:
        with self._lock:
            return self._board

    def events_snapshot(self) -> EventsSnapshot:
        with self._lock:
            return self._events

    # ---------- escrita ----------

    def patch_status(self, task_id: str, status: str) -> bool:
        base, token = _base_url(), _token()
        if not token or not task_id:
            return False

        def work():
            _request("PATCH", f"{base}/api/tasks/{task_id}", token, body={"status": status})
            time.sleep(1)
            self.trigger_refresh()

        threading.Thread(target=work, daemon=True).start()
        return True

    def create_task(self, titulo: str, status: str = "todo", assunto: str = "") -> bool:
        titulo = (titulo or "").strip()
        base, token = _base_url(), _token()
        if not titulo or not token:
            return False
        body = {"titulo": titulo, "assunto": assunto or _default_assunto(), "status": status}

        def work():
            _request("POST", f"{base}/api/tasks", token, body=body)
            time.sleep(1)
            self.trigger_refresh()

        threading.Thread(target=work, daemon=True).start()
        return True

    def create_event(self, titulo: str, data: str, hora: str = "",
                     duracao_min: int = 60, assunto: str = "") -> dict:
        base, token = _base_url(), _token()
        if not token:
            return {"ok": False, "error": "sem PLATAFORMA_TOKEN"}
        titulo = (titulo or "").strip() or "(sem titulo)"
        try:
            d = dt.date.fromisoformat((data or "").strip()[:10])
        except Exception:
            return {"ok": False, "error": "data invalida (use YYYY-MM-DD)"}
        hora = (hora or "").strip() or "09:00"
        body = {
            "titulo": titulo, "assunto": assunto or _default_assunto(),
            "data": d.isoformat(), "hora": hora,
            "duracaoMin": max(5, int(duracao_min or 60)),
        }
        status, resp = _request("POST", f"{base}/api/events", token, body=body)
        if status not in (200, 201):
            return {"ok": False, "error": f"HTTP {status}"}
        self.trigger_refresh()
        return {"ok": True, "title": titulo, "date": d.isoformat(), "time": hora}


def _neterr(e: Exception) -> str:
    msg = str(e).lower()
    if "refused" in msg or "timed out" in msg or "unreachable" in msg or "urlopen" in msg:
        return "PC/Plataforma offline"
    return str(e)[:40]


# --------------------------------------------------------------------------- #
#  Adaptador de BOARD (drop-in do TodoistService)                            #
# --------------------------------------------------------------------------- #

class PlataformaBoard:
    """Mesma interface pública do TodoistService, backed pela Plataforma."""

    def __init__(self, service: PlataformaService) -> None:
        self._svc = service

    def get(self) -> BoardSnapshot:
        return self._svc.board_snapshot()

    def by_section(self) -> dict[str, list[BoardTask]]:
        snap = self.get()
        out: dict[str, list[BoardTask]] = {k: [] for k in SECTION_NAMES}
        for t in snap.tasks:
            out.setdefault(t.section_key, []).append(t)
        return out

    def move(self, task_id: str, target_key: str) -> bool:
        if target_key not in SECTION_TO_STATUS:
            return False
        # move otimista local (UI reage na hora), depois PATCH + refresh
        snap = self._svc.board_snapshot()
        for t in snap.tasks:
            if t.id == task_id:
                t.section_key = target_key
                break
        return self._svc.patch_status(task_id, SECTION_TO_STATUS[target_key])

    def create(self, content: str, section_key: str = "to-do") -> bool:
        return self._svc.create_task(content, SECTION_TO_STATUS.get(section_key, "todo"))

    def trigger_refresh(self) -> None:
        self._svc.trigger_refresh()


# --------------------------------------------------------------------------- #
#  Adaptador de AGENDA (drop-in do CalendarService)                          #
# --------------------------------------------------------------------------- #

class PlataformaCalendar:
    """Mesma interface pública do CalendarService, backed pela Plataforma."""

    def __init__(self, service: PlataformaService) -> None:
        self._svc = service

    def get(self) -> EventsSnapshot:
        return self._svc.events_snapshot()

    def trigger_refresh(self) -> None:
        self._svc.trigger_refresh()

    def can_write(self) -> bool:
        return bool(_token())

    def create_event(self, title: str, date: str, time: str = "",
                     duration_min: int = 60) -> dict:
        return self._svc.create_event(title, date, time, duration_min)


# --------------------------------------------------------------------------- #
#  Agenda MESCLADA (Plataforma + Google) — sem duplicar o espelho             #
# --------------------------------------------------------------------------- #

class MergedCalendar:
    """Une eventos de HOJE de várias fontes (Plataforma + Google). A Plataforma
    já espelha os eventos dela no Google, então deduplicamos por (título, início
    no minuto) pra o mesmo compromisso não aparecer duas vezes. Escrita e
    can_write vão pra fonte primária (Plataforma)."""

    def __init__(self, primary, extras: list) -> None:
        self._primary = primary
        self._extras = [e for e in extras if e is not None]

    def _dedupe_key(self, ev: CalEvent) -> tuple:
        return (ev.title.strip().lower(), ev.start.strftime("%Y-%m-%d %H:%M"))

    def get(self) -> EventsSnapshot:
        seen: set[tuple] = set()
        events: list[CalEvent] = []
        any_ok = False
        first_error = ""
        for src in [self._primary, *self._extras]:
            snap = src.get()
            if getattr(snap, "ok", False):
                any_ok = True
            elif not first_error:
                first_error = getattr(snap, "error", "") or ""
            for ev in getattr(snap, "events", []) or []:
                k = self._dedupe_key(ev)
                if k in seen:
                    continue
                seen.add(k)
                events.append(ev)
        events.sort(key=lambda ev: (ev.all_day, ev.start))
        return EventsSnapshot(
            ok=any_ok, error="" if any_ok else (first_error or "sem conexao"),
            events=events, fetched_at=time.time())

    def trigger_refresh(self) -> None:
        self._primary.trigger_refresh()
        for e in self._extras:
            try:
                e.trigger_refresh()
            except Exception:
                pass

    def can_write(self) -> bool:
        if self._primary.can_write():
            return True
        return any(getattr(e, "can_write", lambda: False)() for e in self._extras)

    def create_event(self, title: str, date: str, time: str = "",
                     duration_min: int = 60) -> dict:
        return self._primary.create_event(title, date, time, duration_min)


# --------------------------------------------------------------------------- #
#  Assinante ntfy — avisos da Plataforma em tempo real                       #
# --------------------------------------------------------------------------- #

class PlataformaNotify:
    """Assina o tópico ntfy da Plataforma (stream JSON) e acumula os avisos
    numa fila. O frame_hook do main dá `pop()` (main thread) e vira AlertScreen
    + voz. Só entrega mensagens que CHEGAM depois de conectar (nada de replay).
    Reconecta sozinho com backoff quando a conexão cai."""

    def __init__(self) -> None:
        self._topic = _cfg("PLATAFORMA_NTFY_TOPIC", "plataforma_ntfy_topic")
        self._server = _cfg("PLATAFORMA_NTFY_SERVER", "plataforma_ntfy_server",
                            "https://ntfy.sh").rstrip("/")
        self._queue: list[dict] = []
        self._lock = threading.Lock()
        self.enabled = bool(self._topic)
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        backoff = 2
        while True:
            try:
                self._stream()
                backoff = 2   # conectou e leu — reseta o backoff
            except Exception:
                pass
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def _stream(self) -> None:
        # since=0 traria histórico; sem since o ntfy entrega só o que chega agora.
        url = f"{self._server}/{urllib_quote(self._topic)}/json"
        req = urllib.request.Request(url, headers={"Accept": "application/x-ndjson"})
        # timeout alto: é um stream longo; keepalives chegam a cada ~30-45s.
        with urllib.request.urlopen(req, timeout=90) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "ignore").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                if msg.get("event") != "message":
                    continue   # open / keepalive / poll_request
                title = (msg.get("title") or "Plataforma").strip()
                body = (msg.get("message") or "").strip()
                if not body:
                    continue
                with self._lock:
                    self._queue.append({"title": title, "body": body})
                    self._queue = self._queue[-20:]

    def pop(self) -> dict | None:
        with self._lock:
            return self._queue.pop(0) if self._queue else None


def urllib_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe="")
