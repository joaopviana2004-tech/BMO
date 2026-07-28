"""Cliente leve da API do Todoist pro Kanban do BMO OS.

- Lê de um projeto (default 'BMO') com 3 seções: 'To-Do', 'Doing', 'Done'
- Roda em thread, faz refresh a cada 60s
- Move tarefa entre seções via POST /api/v1/tasks/{id}/move

Usa a API v1 unificada (https://api.todoist.com/api/v1/...). A antiga
REST v2 e Sync v9 foram aposentadas em 2025.

Token: env TODOIST_TOKEN > config['todoist_token']
Sem token: snapshot.ok = False, screen mostra mensagem amigável.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from ..core import config

API_BASE = "https://api.todoist.com/api/v1"
UPDATE_INTERVAL_S = 60
HTTP_TIMEOUT = 10

# Nomes esperados das seções (case-insensitive)
SECTION_NAMES = ["to-do", "doing", "done"]
SECTION_LABELS = {"to-do": "TO-DO", "doing": "DOING", "done": "DONE"}


@dataclass
class Task:
    id: str
    content: str
    section_key: str  # "to-do" | "doing" | "done"
    due: str = ""     # data de vencimento "YYYY-MM-DD" ("" = sem prazo)


@dataclass
class TodoistSnapshot:
    ok: bool = False
    error: str = ""
    project_id: str = ""                                     # id do projeto BMO
    sections: dict[str, str] = field(default_factory=dict)  # key -> section_id
    tasks: list[Task] = field(default_factory=list)
    fetched_at: float = 0.0


def _resolve_token() -> str:
    env = os.environ.get("TODOIST_TOKEN", "").strip()
    if env:
        return env
    return (config.get("todoist_token") or "").strip()


def _list(data) -> list:
    """A API v1 envolve listas em {'results': [...], 'next_cursor': ...}."""
    if isinstance(data, dict) and "results" in data:
        return data["results"] or []
    if isinstance(data, list):
        return data
    return []


def _request(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        try:
            body_txt = e.read().decode("utf-8")
        except Exception:
            body_txt = ""
        return e.code, body_txt


class TodoistService:
    def __init__(self) -> None:
        self.snapshot = TodoistSnapshot()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        token = _resolve_token()
        if not token:
            self.snapshot = TodoistSnapshot(ok=False, error="sem TODOIST_TOKEN")
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
        """Acorda o loop pra refazer fetch agora (depois de um move otimista)."""
        self._wake.set()

    # ---------- fetch ----------

    def _fetch(self) -> None:
        token = _resolve_token()
        if not token:
            with self._lock:
                self.snapshot = TodoistSnapshot(ok=False, error="sem TODOIST_TOKEN")
            return

        project_name = (
            os.environ.get("TODOIST_PROJECT", "").strip()
            or (config.get("todoist_project") or "BMO").strip()
        )
        try:
            # 1) projeto
            status, body = _request("GET", f"{API_BASE}/projects", token)
            if status != 200:
                self._set_error(f"projects HTTP {status}")
                return
            projects = _list(json.loads(body))
            project = next(
                (p for p in projects if p.get("name", "").lower() == project_name.lower()),
                None,
            )
            if project is None:
                self._set_error(f"projeto '{project_name}' nao encontrado")
                return
            project_id = project["id"]

            # 2) seções
            params = urllib.parse.urlencode({"project_id": str(project_id)})
            status, body = _request("GET", f"{API_BASE}/sections?{params}", token)
            if status != 200:
                self._set_error(f"sections HTTP {status}")
                return
            sections_raw = _list(json.loads(body))
            sections: dict[str, str] = {}
            for s in sections_raw:
                key = (s.get("name") or "").strip().lower()
                if key in SECTION_NAMES:
                    sections[key] = str(s["id"])
            missing = [n for n in SECTION_NAMES if n not in sections]
            if missing:
                self._set_error("falta secao: " + ", ".join(missing))
                return

            # 3) tarefas ativas
            status, body = _request("GET", f"{API_BASE}/tasks?{params}", token)
            if status != 200:
                self._set_error(f"tasks HTTP {status}")
                return
            tasks_raw = _list(json.loads(body))
            tasks: list[Task] = []
            for t in tasks_raw:
                section_id = str(t.get("section_id") or "")
                key = next((k for k, v in sections.items() if v == section_id), None)
                if key is None:
                    continue
                due_raw = t.get("due") or {}
                due = (due_raw.get("date") or "")[:10] if isinstance(due_raw, dict) else ""
                tasks.append(Task(
                    id=str(t["id"]),
                    content=(t.get("content") or "").strip(),
                    section_key=key,
                    due=due,
                ))

            with self._lock:
                self.snapshot = TodoistSnapshot(
                    ok=True,
                    error="",
                    project_id=str(project_id),
                    sections=sections,
                    tasks=tasks,
                    fetched_at=time.time(),
                )
        except Exception as e:
            self._set_error(str(e)[:60])

    def _set_error(self, msg: str) -> None:
        with self._lock:
            self.snapshot = TodoistSnapshot(
                ok=False,
                error=msg,
                project_id=self.snapshot.project_id,
                sections=self.snapshot.sections,
                tasks=self.snapshot.tasks,
                fetched_at=time.time(),
            )

    # ---------- snapshot ----------

    def get(self) -> TodoistSnapshot:
        with self._lock:
            return self.snapshot

    def by_section(self) -> dict[str, list[Task]]:
        snap = self.get()
        out: dict[str, list[Task]] = {k: [] for k in SECTION_NAMES}
        for t in snap.tasks:
            out.setdefault(t.section_key, []).append(t)
        return out

    # ---------- move ----------

    def move(self, task_id: str, target_key: str) -> bool:
        """Move (otimista) localmente e dispara sync. Retorna False se não rolou."""
        if target_key not in SECTION_NAMES:
            return False
        token = _resolve_token()
        if not token:
            return False

        # atualiza local pra UI reagir na hora
        with self._lock:
            snap = self.snapshot
            target_section_id = snap.sections.get(target_key)
            if target_section_id is None:
                return False
            for t in snap.tasks:
                if t.id == task_id:
                    t.section_key = target_key
                    break

        # dispara em thread pra não travar o frame
        threading.Thread(
            target=self._send_move,
            args=(token, task_id, target_section_id),
            daemon=True,
        ).start()
        return True

    def _send_move(self, token: str, task_id: str, section_id: str) -> None:
        url = f"{API_BASE}/tasks/{task_id}/move"
        status, _ = _request("POST", url, token, body={"section_id": section_id})
        if status not in (200, 201, 204):
            self.trigger_refresh()
        else:
            time.sleep(2)
            self.trigger_refresh()

    # ---------- create ----------

    def create(self, content: str, section_key: str = "to-do") -> bool:
        """Cria uma tarefa no projeto BMO (seção 'to-do' por padrão). Roda em
        thread pra não travar o frame. Retorna False se não dá pra criar."""
        content = (content or "").strip()
        if not content:
            return False
        token = _resolve_token()
        if not token:
            return False
        snap = self.get()
        body: dict = {"content": content}
        section_id = snap.sections.get(section_key)
        if section_id:
            body["section_id"] = section_id   # section_id já define o projeto
        elif snap.project_id:
            body["project_id"] = snap.project_id
        # senão, vai pra Inbox (fallback) — melhor criar lá do que falhar

        def work():
            status, _ = _request("POST", f"{API_BASE}/tasks", token, body=body)
            if status in (200, 201):
                time.sleep(1)
                self.trigger_refresh()

        threading.Thread(target=work, daemon=True).start()
        return True
