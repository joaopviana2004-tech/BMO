"""Configuração persistente do BMO OS.

Carrega/salva um JSON na raiz do repo (bmo_config.json). Pensado pra ter
poucas chaves — preferências do usuário que sobrevivem entre boots.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "bmo_config.json"

DEFAULTS: dict = {
    "idle_timeout_s": 10,      # quanto tempo a home espera sem input pra voltar
    "ambient_mode": "clock",   # "clock" | "face" — tela ociosa
}

IDLE_TIMEOUT_OPTIONS = [5, 10, 15, 30, 60, 120]
AMBIENT_MODE_OPTIONS = ["clock", "face"]
AMBIENT_MODE_LABELS = {"clock": "RELOGIO", "face": "BMO FACE"}

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
