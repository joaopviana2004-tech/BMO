"""Sessão multiusuário do Bimo: perfis locais + ciclo Wipe & Load.

Cada usuário logado (via QR/OAuth Google) vira uma pasta em profiles/<sub>/:
    profile.json     — identidade (sub, email, nome, logged_at)
    tokens.json      — refresh/access token do Google (gitignored com a pasta)
    bmo_config.json  — preferências DESTE usuário (volume, brilho, tema...)

profiles/_active guarda o id da sessão corrente — sobrevive a reboot, então
o dono não refaz login toda vez que liga o Bimo. O WIPE acontece no logout
explícito ("Trocar usuário" no SETTINGS): a pasta inteira do perfil é
destruída depois do upload final pro Drive.

Perfil especial "guest": modo sem conta (sem sync). Não é destruído no
logout — é o estado neutro do aparelho.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import config

PROFILES_DIR = config.REPO_ROOT / "profiles"
ACTIVE_PATH = PROFILES_DIR / "_active"
GUEST_ID = "guest"

_current: dict | None = None   # profile.json carregado da sessão ativa


def profile_dir(user_id: str) -> Path:
    return PROFILES_DIR / user_id


def tokens_path(user_id: str) -> Path:
    return profile_dir(user_id) / "tokens.json"


def current() -> dict | None:
    """Perfil ativo ({"sub","email","name",...}) ou None (sem sessão)."""
    return _current


def recordings_dir() -> Path:
    """Pasta dos áudios offline-first DO PERFIL ativo (some no wipe do logout).

    Sem sessão (modo legado), cai em <repo>/recordings."""
    if _current is not None:
        return profile_dir(_current["sub"]) / "recordings"
    return config.REPO_ROOT / "recordings"


def knowledge_dir() -> Path:
    """Espelho local das notas .md do Segundo Cérebro (Drive Bimo/Conhecimento).

    É por perfil — a base de conhecimento É o dado mais pessoal que existe,
    então some no wipe do logout. Sem sessão, <repo>/knowledge."""
    if _current is not None:
        return profile_dir(_current["sub"]) / "knowledge"
    return config.REPO_ROOT / "knowledge"


def is_guest() -> bool:
    return _current is not None and _current.get("sub") == GUEST_ID


def restore() -> dict | None:
    """No boot: reativa a sessão gravada em profiles/_active (se íntegra).

    Redireciona o config pro bmo_config.json do perfil. Retorna o perfil
    ativo ou None (vai pra tela de LOGIN).
    """
    global _current
    _current = None
    try:
        uid = ACTIVE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        uid = ""
    if uid:
        meta = profile_dir(uid) / "profile.json"
        try:
            _current = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            _current = None
    if _current is not None:
        config.set_profile_path(profile_dir(_current["sub"]) / "bmo_config.json")
    return _current


def login(user: dict, tokens: dict) -> dict:
    """Cria/ativa o perfil de um usuário autenticado (pós device flow).

    Semeia o bmo_config.json do perfil com o config legado da raiz (migração
    do tempo single-user), grava tokens e marca a sessão ativa.
    """
    profile = {
        "sub": user["sub"],
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "logged_at": time.time(),
    }
    return _activate(profile, tokens=tokens)


def login_guest() -> dict:
    """Modo sem conta: perfil local 'guest', sem tokens nem sync."""
    profile = {"sub": GUEST_ID, "email": "", "name": "Convidado",
               "logged_at": time.time()}
    return _activate(profile, tokens=None)


def _activate(profile: dict, *, tokens: dict | None) -> dict:
    global _current
    pdir = profile_dir(profile["sub"])
    pdir.mkdir(parents=True, exist_ok=True)
    # migração: config single-user antigo (raiz) vira a semente do perfil novo
    cfg = pdir / "bmo_config.json"
    if not cfg.exists() and config.LEGACY_CONFIG_PATH.exists():
        try:
            shutil.copyfile(config.LEGACY_CONFIG_PATH, cfg)
        except Exception:
            pass
    (pdir / "profile.json").write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    if tokens is not None:
        (pdir / "tokens.json").write_text(json.dumps(tokens, indent=2),
                                          encoding="utf-8")
    ACTIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_PATH.write_text(profile["sub"], encoding="utf-8")
    _current = profile
    config.set_profile_path(cfg)
    return profile


def logout() -> None:
    """Encerra a sessão: WIPE da pasta do perfil (tokens, config, caches).

    O upload final pro Drive deve acontecer ANTES (main chama o flush do
    drive_sync). O perfil guest não é destruído — só desativado.
    """
    global _current
    uid = _current.get("sub") if _current else ""
    _current = None
    try:
        ACTIVE_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    if uid and uid != GUEST_ID:
        shutil.rmtree(profile_dir(uid), ignore_errors=True)
    # sem sessão: config volta pro arquivo legado da raiz (defaults do aparelho)
    config.set_profile_path(None)
