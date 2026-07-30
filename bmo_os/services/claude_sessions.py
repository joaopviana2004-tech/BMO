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
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from ..core import config

POLL_INTERVAL_S = 2.0
TIMEOUT_S = 3.0
DNS_TIMEOUT_S = 2.0

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
    # relógio do PAINEL (ms), não o da Raspberry. Só serve pra comparar sessões
    # entre si — nunca contra time.time() daqui (os relógios divergem).
    updated_at: float = 0.0
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


def resolver_ip(host: str, timeout_s: float = 2.0) -> str:
    """Resolve um nome em IP com prazo de verdade.

    O `timeout` do urlopen cobre só o socket, NÃO a resolução de nome: um
    getaddrinfo em cima de mDNS pode travar sem limite e pendurar a thread
    de consulta pra sempre — a tela congelaria em dados velhos, calada.
    Resolvemos numa thread descartável; se ela não responder a tempo, o
    candidato fica de fora desta rodada e o ciclo segue vivo.
    """
    try:
        socket.inet_aton(host)
        return host          # já é IPv4, não há o que resolver
    except OSError:
        pass

    achado: dict[str, str] = {}

    def alvo() -> None:
        try:
            achado["ip"] = socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
        except Exception:
            achado["ip"] = ""

    t = threading.Thread(target=alvo, daemon=True)
    t.start()
    t.join(timeout_s)
    return achado.get("ip", "")


def _folder_of(cwd: str) -> str:
    """basename do cwd — o painel manda caminho do Windows ou do Linux."""
    parts = [p for p in cwd.replace("\\", "/").split("/") if p]
    return parts[-1] if parts else "?"


# O painel guarda TODA sessão que já passou por ele e nunca descarta as
# encerradas — abrir três vezes o mesmo repo deixa três linhas iguais na tela.
# Isto aqui é um monitor do AGORA, não um histórico: sessão morta velha sai.
ENDED_TTL_MS = 10 * 60 * 1000.0

# Estados que sempre aparecem: ou pedem ação, ou acabaram de acontecer.
VIVOS = frozenset({"waiting", "error", "working", "done"})

# Ordem de urgência — quem cobra ação primeiro, pra "PRECISA DE VOCE" nunca
# nascer fora da área visível.
ORDEM_STATUS = {
    "waiting": 0, "error": 1, "working": 2, "done": 3, "idle": 4, "ended": 5,
}


def organizar(sessions: list[ClaudeSession]) -> list[ClaudeSession]:
    """Tira as repetições e ordena por urgência.

    Três regras, nesta ordem:
      1. id repetido some (defesa — o painel não deveria repetir, mas repete);
      2. sessão morta (idle/ended) some se estiver velha, se a pasta já tem
         sessão viva, ou se é a mais antiga entre as mortas daquela pasta;
      3. o que sobra é ordenado por urgência e, dentro dela, pela mais recente.

    A idade é medida contra o relógio do PRÓPRIO painel (o updatedAt mais novo
    do lote), nunca contra o da Raspberry — os dois relógios divergem e usar o
    daqui faria sessão viva sumir ou sessão velha ficar pra sempre.
    """
    unicas: dict[str, ClaudeSession] = {}
    for s in sessions:
        chave = s.id or f"_{len(unicas)}"
        anterior = unicas.get(chave)
        if anterior is None or s.updated_at >= anterior.updated_at:
            unicas[chave] = s
    itens = list(unicas.values())
    if not itens:
        return []

    agora = max((s.updated_at for s in itens), default=0.0)
    pastas_vivas = {s.folder for s in itens if s.status in VIVOS}

    mantidas: list[ClaudeSession] = []
    melhor_morta: dict[str, ClaudeSession] = {}
    for s in itens:
        if s.status in VIVOS:
            mantidas.append(s)
            continue
        if agora and s.updated_at and (agora - s.updated_at) > ENDED_TTL_MS:
            continue                      # encerrada e velha: é histórico
        if s.folder in pastas_vivas:
            continue                      # a pasta já tem sessão de verdade
        atual = melhor_morta.get(s.folder)
        if atual is None or s.updated_at > atual.updated_at:
            melhor_morta[s.folder] = s    # uma linha por pasta, a mais nova

    mantidas.extend(melhor_morta.values())
    mantidas.sort(key=lambda s: (ORDEM_STATUS.get(s.status, 9), -s.updated_at))
    return mantidas


class ClaudeSessionsService:
    def __init__(self) -> None:
        self.snapshot = ClaudeSnapshot()
        self._url_ok = ""   # última URL que respondeu (evita re-varrer a lista)
        self._lock = threading.Lock()
        # Acorda o loop na hora quando a tela pede refresh (botão SYNC).
        self._wake = threading.Event()
        # Pedido de reset (botão RESET). A tela só levanta a bandeira; a thread
        # é que fala com a rede — no frame não entra I/O.
        self._reset_pedido = False
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
            # Esta thread NAO pode morrer: se ela cai, a tela congela em dados
            # velhos sem avisar ninguem — o pior comportamento possivel num
            # monitor. Qualquer excecao vira estado de erro visivel e o ciclo
            # continua.
            try:
                if self._reset_pedido:
                    self._reset_pedido = False
                    self._zerar_painel()
                self._fetch()
            except Exception as exc:
                self._fail(f"erro interno: {exc}"[:60])
            self._wake.wait(POLL_INTERVAL_S)
            self._wake.clear()

    def trigger_refresh(self) -> None:
        self._wake.set()

    def pedir_reset(self) -> None:
        """Botão RESET: manda o painel esquecer TODAS as sessões.

        Só marca a bandeira e acorda a thread — quem faz a requisição é ela.
        As sessões vivas voltam no próximo hook (segundos, se estiverem
        trabalhando); as fantasmas não voltam, que é o motivo do botão existir.
        """
        self._reset_pedido = True
        self._wake.set()

    def _zerar_painel(self) -> None:
        base = self._url_ok or self.candidatos()[0]
        partes = urllib.parse.urlsplit(base)
        ip = resolver_ip(partes.hostname or "", DNS_TIMEOUT_S)
        if not ip:
            return                       # sem painel não há o que zerar
        porta = f":{partes.port}" if partes.port else ""
        alvo = f"{partes.scheme}://{ip}{porta}/limpar?tudo=1"
        try:
            with urllib.request.urlopen(alvo, timeout=TIMEOUT_S):
                pass
        except Exception:
            # Falhou? O _fetch logo abaixo mostra o estado real de qualquer
            # jeito; engolir aqui é melhor que derrubar a thread de consulta.
            pass
        with self._lock:
            # Limpa já, sem esperar o próximo fetch: o toque tem que responder
            # na hora, senão o botão parece quebrado.
            self.snapshot = ClaudeSnapshot(sessions=[], fetched_at=time.time(),
                                           ok=self.snapshot.ok)

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
            partes = urllib.parse.urlsplit(base)
            ip = resolver_ip(partes.hostname or "", DNS_TIMEOUT_S)
            if not ip:
                erro = f"nome nao resolve ({partes.hostname})"
                continue
            # conecta pelo IP já resolvido: assim o timeout do urlopen cobre
            # de ponta a ponta, sem DNS escondido no meio do caminho
            porta = f":{partes.port}" if partes.port else ""
            try:
                with urllib.request.urlopen(f"{partes.scheme}://{ip}{porta}/estado",
                                            timeout=TIMEOUT_S) as resp:
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
                updated_at=float(item.get("updatedAt") or item.get("endedAt") or 0),
            ))

        snap = ClaudeSnapshot(sessions=organizar(sessions),
                              fetched_at=time.time(), ok=True)
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
