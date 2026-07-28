"""Central de lembretes proativos do BMO — a 'secretária'.

Uma fila simples de avisos que as duas saídas consomem:
  - a TELINHA (voz + rodapé), que fala os lembretes ainda não falados quando o
    BMO não está ocupado (mesma regra de parcimônia da proatividade);
  - o PAINEL WEB (aba HOJE + sino com badge), que lista tudo e marca como lido.

Quem DECIDE o que entra (briefing matinal, prazos de task, rotinas) é o
`secretary_tick` no main — este módulo é só o armazém: thread-safe, persistido
por perfil (sobrevive a restart) e com **dedupe 1x/dia** por chave, pra o mesmo
aviso não repetir o dia todo.

Item: {id, text, area, kind, when, created, read, spoke}
  kind: "briefing" | "task" | "routine" | "info"
"""
from __future__ import annotations

import datetime as dt
import json
import threading

from ..core import config


def _today() -> str:
    return dt.date.today().isoformat()


class ReminderService:
    MAX_KEEP = 60   # poda: guarda os N lembretes mais recentes

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self._fired: dict[str, str] = {}   # chave de dedupe -> data (YYYY-MM-DD)
        self._seq = 0
        # mesmo arquivo do perfil ativo (some no wipe do logout, igual ao config)
        self._path = config.get_path().parent / "bmo_reminders.json"
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._items = list(data.get("items", []) or [])
                    self._fired = dict(data.get("fired", {}) or {})
                    self._seq = int(data.get("seq", 0) or 0)
        except Exception:
            pass

    def _persist_unlocked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({
                "items": self._items[-self.MAX_KEEP:],
                "fired": self._fired,
                "seq": self._seq,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ---------- escrita ----------

    def fired_today(self, key: str) -> bool:
        with self._lock:
            return self._fired.get(key) == _today()

    def add(self, text: str, *, area: str = "", kind: str = "info",
            when: str = "", key: str | None = None) -> bool:
        """Adiciona um lembrete. Se `key` já disparou hoje, ignora (dedupe).
        Retorna True se realmente adicionou."""
        text = (text or "").strip()
        if not text:
            return False
        today = _today()
        with self._lock:
            if key is not None and self._fired.get(key) == today:
                return False
            if key is not None:
                self._fired[key] = today
            self._seq += 1
            self._items.append({
                "id": f"r{self._seq}",
                "text": text, "area": area, "kind": kind, "when": when,
                "created": dt.datetime.now().isoformat(timespec="seconds"),
                "read": False, "spoke": False,
            })
            # esquece chaves de dedupe de dias anteriores (não cresce pra sempre)
            self._fired = {k: v for k, v in self._fired.items() if v == today}
            if len(self._items) > self.MAX_KEEP:
                self._items = self._items[-self.MAX_KEEP:]
            self._persist_unlocked()
        return True

    def unspoken(self) -> list[dict]:
        """Lembretes ainda não falados em voz (o tick fala um de cada vez)."""
        with self._lock:
            return [dict(i) for i in self._items if not i.get("spoke")]

    def mark_spoke(self, rid: str) -> None:
        with self._lock:
            for i in self._items:
                if i["id"] == rid:
                    i["spoke"] = True
            self._persist_unlocked()

    def mark_read(self, rid: str = "", *, every: bool = False) -> None:
        with self._lock:
            for i in self._items:
                if every or i["id"] == rid:
                    i["read"] = True
            self._persist_unlocked()

    # ---------- leitura ----------

    def snapshot(self) -> dict:
        """Pro painel: itens (mais novos primeiro) + contagem de não-lidos."""
        with self._lock:
            items = [dict(i) for i in reversed(self._items)]
            unread = sum(1 for i in self._items if not i.get("read"))
            return {"items": items, "unread": unread}
