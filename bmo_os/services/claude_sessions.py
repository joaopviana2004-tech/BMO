"""Sessões do Claude Code — lê o painel que roda no PC pela rede local.

O PC roda `claude-painel/server.mjs` (porta 4747), que recebe os hooks do
Claude Code de todas as janelas do VS Code e mantém um objeto por sessão.
Aqui a gente só consome `GET /estado` de tempos em tempos, numa thread — o
frame nunca bloqueia (mesmo padrão da WeatherService).

Configure a URL do painel:
    CLAUDE_PAINEL_URL   env var (ex: "http://192.168.0.109:4747")
ou `bmo_config.json["claude_painel_url"]`. Precedência: env > config > default.

O servidor precisa estar escutando na rede, não só em loopback:
    HOST=0.0.0.0 node server.mjs
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..core import config

POLL_INTERVAL_S = 2.0
TIMEOUT_S = 3.0
DEFAULT_URL = "http://192.168.0.109:4747"

# Status que o servidor manda -> rótulo curto pra tela (ASCII, cabe em 400px)
LABELS = {
    "idle": "ociosa",
    "working": "trabalhando",
    "waiting": "PRECISA DE VOCE",
    "done": "concluida",
    "error": "erro",
    "ended": "encerrada",
}


@dataclass
class ClaudeSession:
    id: str
    folder: str = "?"
    status: str = "idle"
    prompt: str = ""
    notice: str = ""
    current_tool: str = ""
    tool_count: int = 0
    fail_count: int = 0
    last_message: str = ""
    elapsed_s: float = 0.0
    running: bool = False

    @property
    def label(self) -> str:
        return LABELS.get(self.status, self.status)


@dataclass
class ClaudeSnapshot:
    sessions: list[ClaudeSession] = field(default_factory=list)
    fetched_at: float = 0.0
    ok: bool = False
    error: str = ""

    def count(self, status: str) -> int:
        return sum(1 for s in self.sessions if s.status == status)


def _folder_of(cwd: str) -> str:
    """basename do cwd — o painel manda caminho do Windows ou do Linux."""
    parts = [p for p in cwd.replace("\\", "/").split("/") if p]
    return parts[-1] if parts else "?"


class ClaudeSessionsService:
    def __init__(self) -> None:
        self.snapshot = ClaudeSnapshot()
        self._lock = threading.Lock()
        # Acorda o loop na hora quando a tela pede refresh (botão SYNC).
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ---------- config ----------

    def base_url(self) -> str:
        import os
        url = (os.environ.get("CLAUDE_PAINEL_URL")
               or config.get("claude_painel_url")
               or DEFAULT_URL)
        return str(url).strip().rstrip("/")

    # ---------- thread ----------

    def _loop(self) -> None:
        while True:
            self._fetch()
            self._wake.wait(POLL_INTERVAL_S)
            self._wake.clear()

    def trigger_refresh(self) -> None:
        self._wake.set()

    def _fetch(self) -> None:
        url = f"{self.base_url()}/estado"
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
                raw = json.load(resp)
        except urllib.error.URLError as exc:
            self._fail(f"painel offline ({getattr(exc, 'reason', exc)})")
            return
        except Exception as exc:
            self._fail(str(exc)[:60] or "falha na leitura")
            return

        if not isinstance(raw, list):
            self._fail("resposta inesperada do painel")
            return

        sessions = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            tools = item.get("tools") or []
            sessions.append(ClaudeSession(
                id=str(item.get("id", "")),
                folder=_folder_of(str(item.get("cwd", ""))),
                status=str(item.get("status", "idle")),
                prompt=str(item.get("prompt", "")).strip(),
                notice=str(item.get("notice", "")).strip(),
                current_tool=str(item.get("currentTool") or "").strip(),
                tool_count=int(item.get("toolCount") or 0),
                fail_count=sum(1 for t in tools if isinstance(t, dict) and t.get("failed")),
                last_message=str(item.get("lastMessage", "")).strip(),
                # elapsedMs vem calculado pelo relógio do PC de propósito:
                # a Raspberry pode estar com o relógio adiantado/atrasado e o
                # cronômetro sairia errado se fosse calculado aqui.
                elapsed_s=float(item.get("elapsedMs") or 0) / 1000.0,
                running=bool(item.get("running")),
            ))

        snap = ClaudeSnapshot(sessions=sessions, fetched_at=time.time(), ok=True)
        with self._lock:
            self.snapshot = snap

    def _fail(self, error: str) -> None:
        # Mantém as sessões do último fetch bom — uma falha de rede de um
        # segundo não deve limpar a tela inteira. Só marca o erro.
        with self._lock:
            self.snapshot.ok = False
            self.snapshot.error = error
            self.snapshot.fetched_at = time.time()

    # ---------- leitura (main thread) ----------

    def get(self) -> ClaudeSnapshot:
        with self._lock:
            return self.snapshot

    def needs_attention(self) -> int:
        """Quantas sessões estão travadas esperando o usuário."""
        with self._lock:
            return self.snapshot.count("waiting")
