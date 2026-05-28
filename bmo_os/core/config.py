"""Configuração persistente do BMO OS.

Carrega/salva um JSON na raiz do repo (bmo_config.json). Pensado pra ter
poucas chaves — preferências do usuário que sobrevivem entre boots.

Também carrega `.env` da raiz no os.environ na importação (sem dep extra).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO_ROOT / "bmo_config.json"
DOTENV_PATH = REPO_ROOT / ".env"


def _load_dotenv() -> None:
    """Lê .env e popula os.environ (sem sobrescrever vars já definidas)."""
    if not DOTENV_PATH.exists():
        return
    try:
        for raw in DOTENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)
    except Exception:
        pass


_load_dotenv()

DEFAULTS: dict = {
    "idle_timeout_s": 10,      # quanto tempo a home espera sem input pra voltar
    "ambient_mode": "clock",   # "clock" | "face" — tela ociosa
    "theme": "auto",           # "auto" | "dark" | "light" — auto = claro 6h-18h
    "brightness": 100,         # 0-100 — overlay de dimming no canvas
    "todoist_token": "",       # token da REST API v2 do Todoist (env TODOIST_TOKEN ganha)
    "todoist_project": "BMO",  # nome do projeto que vira o board
}

IDLE_TIMEOUT_OPTIONS = [5, 10, 15, 30, 60, 120]
AMBIENT_MODE_OPTIONS = ["clock", "face"]
AMBIENT_MODE_LABELS = {"clock": "RELOGIO", "face": "BMO FACE"}
BRIGHTNESS_OPTIONS = [20, 40, 60, 80, 100]

_lock = Lock()
_data: dict | None = None


def _load_unlocked() -> dict:
    global _data
    if _data is None:
        merged = dict(DEFAULTS)
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    user = json.load(f)
                if isinstance(user, dict):
                    merged.update({k: v for k, v in user.items() if k in DEFAULTS})
            except Exception:
                pass
        _data = merged
    return _data


def get(key: str):
    with _lock:
        return _load_unlocked().get(key, DEFAULTS.get(key))


def set_value(key: str, value) -> None:
    with _lock:
        d = _load_unlocked()
        d[key] = value
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)
        except Exception:
            pass
