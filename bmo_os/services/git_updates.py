"""Detector de "código no disco mais novo que o processo rodando".

No __init__, grava o SHA do HEAD (`startup_sha`). Periodicamente:
- `git fetch` (atualiza refs do origin)
- compara HEAD atual no disco com startup_sha → drift local detectado
- compara HEAD com @{u} → commits novos no remoto

`snapshot.available` vira True nos dois casos. Isso pega tanto "alguém
pushou de outra máquina" quanto "a hook do Claude commitou aqui e o BMO
ainda tá rodando código antigo" — em ambos basta Atualizar (que dá
`git pull` + restart) pra limpar.

Silenciosamente vira False/erro sem rede, sem upstream ou fora de um repo.
"""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FETCH_INTERVAL_S = 5 * 60   # 5 min
STARTUP_DELAY_S = 5         # espera curta antes do primeiro fetch
FETCH_TIMEOUT_S = 30


@dataclass
class UpdateSnapshot:
    available: bool = False
    count: int = 0            # commits behind do upstream (0 se só houve drift local)
    drift: bool = False       # HEAD no disco != SHA capturado no startup
    fetched_at: float = 0.0
    error: str = ""


def _git_head_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""


class GitUpdatesService:
    def __init__(self) -> None:
        self.snapshot = UpdateSnapshot()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        # captura o SHA antes do thread começar pra evitar race
        self.startup_sha = _git_head_sha()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        self._wake.wait(STARTUP_DELAY_S)
        self._wake.clear()
        while True:
            self._check()
            self._wake.wait(FETCH_INTERVAL_S)
            self._wake.clear()

    def trigger_check(self) -> None:
        """Acorda o loop pra refazer fetch agora."""
        self._wake.set()

    def _check(self) -> None:
        try:
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "fetch", "--quiet"],
                capture_output=True, timeout=FETCH_TIMEOUT_S, check=False,
            )

            current_sha = _git_head_sha()
            drift = bool(self.startup_sha) and bool(current_sha) and current_sha != self.startup_sha

            r = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-list", "--count", "HEAD..@{u}"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            behind = int((r.stdout or "0").strip()) if r.returncode == 0 else 0
            err = "" if r.returncode == 0 else (r.stderr or r.stdout).strip()[:60]

            self._set(UpdateSnapshot(
                available=drift or behind > 0,
                count=behind,
                drift=drift,
                fetched_at=time.time(),
                error=err,
            ))
        except FileNotFoundError:
            self._set(UpdateSnapshot(error="git nao instalado", fetched_at=time.time()))
        except Exception as e:
            self._set(UpdateSnapshot(error=str(e)[:60], fetched_at=time.time()))

    def _set(self, snap: UpdateSnapshot) -> None:
        with self._lock:
            self.snapshot = snap

    def get(self) -> UpdateSnapshot:
        with self._lock:
            return self.snapshot
