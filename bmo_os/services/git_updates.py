"""Detector de atualizações pendentes no git remoto.

Em thread daemon, faz `git fetch` periodicamente e conta commits novos do
upstream em relação ao HEAD local. Quando `snapshot.available == True`, a
tela do relógio mostra um alerta de triângulo + 'ATUALIZACAO DISPONIVEL'.

Silenciosamente vira False/erro sem rede, sem upstream configurado, ou
fora de um repo git.
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
    count: int = 0
    fetched_at: float = 0.0
    error: str = ""


class GitUpdatesService:
    def __init__(self) -> None:
        self.snapshot = UpdateSnapshot()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        # espera um pouco antes do primeiro fetch pra não competir com boot
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
            # fetch silencioso (não merge nada local)
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "fetch", "--quiet"],
                capture_output=True, timeout=FETCH_TIMEOUT_S, check=False,
            )
            # conta commits que o upstream tem além do HEAD local
            r = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-list", "--count", "HEAD..@{u}"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if r.returncode != 0:
                self._set(UpdateSnapshot(
                    available=False, count=0,
                    fetched_at=time.time(),
                    error=(r.stderr or r.stdout).strip()[:60],
                ))
                return
            count = int((r.stdout or "0").strip())
            self._set(UpdateSnapshot(
                available=count > 0, count=count,
                fetched_at=time.time(),
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
