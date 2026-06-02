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
    "idle_timeout_s": 10,           # quanto tempo a home espera sem input pra voltar
    "ambient_mode": "clock",        # "clock" | "face" | "pong" | "invaders" | "shuffle"
    "theme": "auto",                # "auto" | "dark" | "light" — auto = claro 6h-18h
    "brightness": 100,              # 0-100 — overlay de dimming no canvas
    "volume": 100,                  # 0-100 — multiplicado em cada Sound.play()
    "camera_face_tracking": False,  # BMO Face usa câmera pra seguir rosto? (off por padrão p/ não esquentar)
    "todoist_token": "",            # token da REST API v2 do Todoist (env TODOIST_TOKEN ganha)
    "todoist_project": "BMO",       # nome do projeto que vira o board
    "gcal_ics_urls": "",            # URLs secretas iCal (env GCAL_ICS_URLS ganha) — "Rotulo=url,url2"
    "event_warning_min": 10,        # antecedência (min) do aviso de evento próximo (tela AGENDA)
    "voice_enabled": False,         # "BMO me Ouve" — wake word + comando de voz (Whisper)
    "mic_device": "",               # nome (ou trecho) do microfone de entrada; "" = padrão do sistema
    "tts_volume": 100,              # 0-100 — volume da voz do BMO (eSpeak-NG), separado do volume dos efeitos
    # --- LLM do chat (BMO responde) — escolhível em SETTINGS -> IA ---
    "llm_provider": "openrouter",   # "openrouter" | "nvidia" (ambos OpenAI-compatíveis)
    # modelo por provedor (o cycler do SETTINGS grava aqui). Env *_MODEL semeia o default.
    "openrouter_model": os.environ.get("OPENROUTER_MODEL", "").strip()
        or "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia_model": os.environ.get("NVIDIA_MODEL", "").strip()
        or "meta/llama-3.3-70b-instruct",
}

IDLE_TIMEOUT_OPTIONS = [5, 10, 15, 30, 60, 120]
AMBIENT_MODE_OPTIONS = ["clock", "face", "pong", "invaders", "shuffle"]
AMBIENT_MODE_LABELS = {
    "clock": "RELOGIO",
    "face": "BMO FACE",
    "pong": "PONG",
    "invaders": "INVADERS",
    "shuffle": "VARIADO",
}
BRIGHTNESS_OPTIONS = [20, 40, 60, 80, 100]
VOLUME_OPTIONS = [0, 25, 50, 75, 100]
EVENT_WARNING_OPTIONS = [1, 5, 10, 15, 30, 60]   # minutos de antecedência

# --- LLM: provedores e modelos de troca rápida (SETTINGS -> IA) ---
# Edite à vontade. Os IDs são os esperados por cada API (OpenAI-compatível).
LLM_PROVIDERS = ["openrouter", "nvidia"]
LLM_PROVIDER_LABELS = {"openrouter": "OPENROUTER", "nvidia": "NVIDIA"}
LLM_MODELS = {
    # OpenRouter (openrouter.ai/models) — modelos free; troque por pagos se quiser
    "openrouter": [
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "google/gemini-2.0-flash-exp:free",
        "deepseek/deepseek-chat-v3-0324:free",
    ],
    # NVIDIA NIM cloud (build.nvidia.com) — integrate.api.nvidia.com
    "nvidia": [
        "meta/llama-3.3-70b-instruct",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "meta/llama-3.1-8b-instruct",
        "qwen/qwen2.5-7b-instruct",
    ],
}

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
