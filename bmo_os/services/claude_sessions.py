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

# Sem config explícita, tenta nesta ordem. O nome mDNS vem primeiro de
# propósito: o IP do PC muda quando o DHCP resolve mudar, o nome não.
# O IP fica como rede de segurança pra quando o mDNS não estiver de pé.
DEFAULT_URLS = (
    "http://NBK-JP.local:4747",
    "http://192.168.0.109:4747",
)

# Status que o servidor manda -> rótulo curto pra tela (ASCII, cabe em 400px)
LABELS = {
    "idle": "ociosa",
    "working": "trabalhando",
    "waiting": "PRECISA DE VOCE",
    "done": "concluida",
    "error": "erro",
    "ended": "encerrada",
}


# Ferramentas que MUDAM alguma coisa vs. as que só olham. A distinção é o que
# dá pra ler nos pontinhos de longe: "essa sessão está escrevendo" contra
# "essa sessão só está vasculhando o repo".
FERRAMENTAS_ACAO = {
    "write", "edit", "multiedit", "notebookedit",
    "bash", "powershell", "killshell",
}


def classificar_ferramenta(nome: str) -> str:
    n = (nome or "").strip().lower()
    if n.startswith("mcp__"):
        return "acao"   # tool externa: assume efeito colateral
    return "acao" if n in FERRAMENTAS_ACAO else "leitura"


@dataclass
class ToolTick:
    """Uma ferramenta executada — vira um pontinho na tela."""
    name: str = "?"
    kind: str = "leitura"   # "acao" | "leitura"
    failed: bool = False


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
    ticks: list[ToolTick] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS.get(self.status, self.status)

    @property
    def acoes(self) -> int:
        return sum(1 for t in self.ticks if t.kind == "acao" and not t.failed)


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
        self._url_ok = ""   # última URL que respondeu (evita re-varrer a lista)
        self._lock = threading.Lock()
        # Acorda o loop na hora quando a tela pede refresh (botão SYNC).
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ---------- config ----------

    def candidatos(self) -> tuple[str, ...]:
        """URLs a tentar. Config explícita manda; senão, os defaults em ordem."""
        import os
        url = (os.environ.get("CLAUDE_PAINEL_URL")
               or config.get("claude_painel_url"))
        if url:
            return (str(url).strip().rstrip("/"),)
        return DEFAULT_URLS

    def base_url(self) -> str:
        """A que está funcionando (ou a primeira da fila, pra exibir na tela)."""
        return self._url_ok or self.candidatos()[0]

    # ---------- thread ----------

    def _loop(self) -> None:
        while True:
            self._fetch()
            self._wake.wait(POLL_INTERVAL_S)
            self._wake.clear()

    def trigger_refresh(self) -> None:
        self._wake.set()

    def _fetch(self) -> None:
        # Tenta a que funcionou da última vez primeiro; só varre a lista quando
        # ela falha. Assim o caso normal é uma requisição só.
        fila = list(self.candidatos())
        if self._url_ok in fila:
            fila.remove(self._url_ok)
            fila.insert(0, self._url_ok)

        raw = None
        erro = "painel offline"
        for base in fila:
            try:
                with urllib.request.urlopen(f"{base}/estado", timeout=TIMEOUT_S) as resp:
                    raw = json.load(resp)
                self._url_ok = base
                break
            except urllib.error.URLError as exc:
                erro = f"sem resposta ({getattr(exc, 'reason', exc)})"
            except Exception as exc:
                erro = str(exc)[:60] or "falha na leitura"
        if raw is None:
            self._url_ok = ""
            self._fail(erro)
            return

        if not isinstance(raw, list):
            self._fail("resposta inesperada do painel")
            return

        sessions = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            tools = item.get("tools") or []
            ticks = []
            for t in tools:
                if not isinstance(t, dict):
                    continue
                nome = str(t.get("name", "?"))
                ticks.append(ToolTick(
                    name=nome,
                    kind=classificar_ferramenta(nome),
                    failed=bool(t.get("failed")),
                ))
            sessions.append(ClaudeSession(
                ticks=ticks,
                id=str(item.get("id", "")),
                folder=_folder_of(str(item.get("cwd", ""))),
                status=str(item.get("status", "idle")),
                prompt=str(item.get("prompt", "")).strip(),
                notice=str(item.get("notice", "")).strip(),
                current_tool=str(item.get("currentTool") or "").strip(),
                tool_count=int(item.get("toolCount") or 0),
                fail_count=sum(1 for t in ticks if t.failed),
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
