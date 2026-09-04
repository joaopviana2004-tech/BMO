"""Configuracao persistente (config.json na raiz do projeto, ignorado pelo git)."""
import json
import os

from . import settings as S

DEFAULTS = dict(music=6, sfx=8, fullscreen=False, aim=True)


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(S.CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in DEFAULTS:
            if k in data:
                cfg[k] = data[k]
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg):
    try:
        with open(S.CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
    except OSError as exc:
        print("nao foi possivel salvar config:", exc)
