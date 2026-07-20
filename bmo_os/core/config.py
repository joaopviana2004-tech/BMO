"""Configuração persistente do BMO OS — POR PERFIL.

Carrega/salva um JSON de preferências. Sem sessão ativa, usa o arquivo
legado da raiz (bmo_config.json); com usuário logado, core/session.py
redireciona pra profiles/<user>/bmo_config.json via set_profile_path().

on_change (módulo) é um hook opcional: drive_sync registra aqui pra marcar
o config como "dirty" e subir pro Drive quando o usuário mexe no SETTINGS.

Também carrega `.env` da raiz no os.environ na importação (sem dep extra).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEGACY_CONFIG_PATH = REPO_ROOT / "bmo_config.json"
DOTENV_PATH = REPO_ROOT / ".env"

# Hook chamado após cada set_value(key, value) — fora do lock.
# drive_sync usa pra agendar o upload do config (debounce).
on_change = None


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
    "ambient_mode": "clock",        # clock | face | brain | devhub | pong | invaders | shuffle
    "theme": "auto",                # "auto" | "dark" | "light" — auto = claro 6h-18h
    "brightness": 100,              # 0-100 — overlay de dimming no canvas
    "volume": 100,                  # 0-100 — multiplicado em cada Sound.play()
    "camera_face_tracking": False,  # BMO Face usa câmera pra seguir rosto? (off por padrão p/ não esquentar)
    "todoist_token": "",            # token da REST API v2 do Todoist (env TODOIST_TOKEN ganha) — legado
    "todoist_project": "BMO",       # nome do projeto que vira o board — legado
    # --- Plataforma Central (Secretaria Pessoal no PC) — fonte de tarefas+agenda ---
    # Substitui o Todoist como board e alimenta a agenda. Env PLATAFORMA_* ganha.
    "plataforma_url": "",           # ex "http://192.168.0.10:8080" ("" = http://localhost:8080)
    "plataforma_token": "",         # Bearer da Plataforma (.store/mcp-config.json)
    "plataforma_assunto": "pessoal",  # assunto default ao criar tarefa/evento pelo BMO
    "plataforma_ntfy_topic": "",    # tópico ntfy p/ avisos em tempo real (.store/notify.json)
    "plataforma_ntfy_server": "",   # servidor ntfy ("" = https://ntfy.sh)
    "gcal_ics_urls": "",            # URLs secretas iCal (env GCAL_ICS_URLS ganha) — "Rotulo=url,url2"
    "event_warning_min": 10,        # antecedência (min) do aviso de evento próximo (tela AGENDA)
    "cooler_enabled": False,        # override manual dos coolers (GPIO 17/23) — auto >60°C sempre vale
    "voice_enabled": False,         # "BMO me Ouve" — wake word + comando de voz (Whisper)
    "mic_button_enabled": True,     # botão de mic virtual nas telas (descanso/foco/kanban/agenda)
    "mic_device": "",               # nome (ou trecho) do microfone de entrada; "" = padrão do sistema
    "tts_volume": 100,              # 0-100 — volume da voz do BMO (eSpeak-NG), separado do volume dos efeitos
    "pet_proactive": True,          # BMO puxa conversa sozinho (falas espontâneas por humor/contexto)
    "webui_enabled": True,          # painel web no localhost (ajustes/espaço interno/chat) — porta via BMO_WEB_PORT
    "briefing_enabled": True,       # secretária: briefing matinal + cutucadas de prazo/rotina (aba HOJE)
    "briefing_time": "08:00",       # horário do briefing diário (HH:MM, 24h)
    # RAG: nível de heading que QUEBRA a nota em chunks (2 = "##"). O chunk vira
    # a unidade de busca e vai pro LLM com a SEÇÃO + o nome da memória. 0 =
    # desliga (nota inteira, comportamento antigo). Configurável no painel.
    "rag_chunk_level": 2,
    # --- RAG HÍBRIDO (vetorial + léxico + grafo) ---
    # Embeddings são gerados no PC (caro) e o índice pronto vai pra Rasp (leve:
    # só cosseno). A query (1 embedding) a Rasp pede ao endpoint do PC.
    "rag_hybrid": True,             # liga a busca densa + expansão de grafo (cai pro léxico se faltar índice/endpoint)
    "embed_model": os.environ.get("EMBED_MODEL", "").strip() or "bge-m3",
    # endpoint /v1/embeddings (OpenAI-compatível: Ollama 11434 / llama.cpp).
    # "" = AUTO: env EMBED_URL > padrão 127.0.0.1:11434. Na Rasp, aponta pro PC.
    "embed_url": "",
    "rag_dense_k": 6,               # quantos chunks a busca densa traz pra fusão
    "rag_graph_hops": 1,            # quantos saltos de [[link]] expandir a partir das sementes
    # --- LLM do chat (BMO responde) — escolhível em SETTINGS -> IA ---
    # provedor: "openrouter" | "nvidia" | "grok" | "local" (todos OpenAI-compatíveis)
    "llm_provider": "openrouter",
    # modelo por provedor (o cycler do SETTINGS grava aqui). Env *_MODEL semeia o default.
    "openrouter_model": os.environ.get("OPENROUTER_MODEL", "").strip()
        or "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia_model": os.environ.get("NVIDIA_MODEL", "").strip()
        or "moonshotai/kimi-k2.6",
    "grok_model": os.environ.get("GROK_MODEL", "").strip()
        or "grok-3",
    # LLM local no PC (llama.cpp/Ollama). O endpoint sai daqui (editável na UI),
    # do .env (LOCAL_LLM_URL/HOST) ou cai no padrão llama.cpp 127.0.0.1:8080.
    # "" = AUTO (padrão/.env). Aceita URL completa, "host" ou "host:porta".
    "local_llm_url": "",
    # nome do modelo local. O llama-server serve um único modelo e IGNORA esse
    # campo; no Ollama ele precisa bater com o `ollama list`.
    "local_model": os.environ.get("LOCAL_LLM_MODEL", "").strip()
        or "local-model",
    # --- Visão (teste de câmera -> LLM descreve a imagem) — escolha PRÓPRIA ---
    # (separada do chat porque só modelos multimodais enxergam imagem)
    "vision_provider": "openrouter",
    "openrouter_vision_model": os.environ.get("OPENROUTER_VISION_MODEL", "").strip()
        or "google/gemini-2.0-flash-exp:free",
    "nvidia_vision_model": os.environ.get("NVIDIA_VISION_MODEL", "").strip()
        or "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "grok_vision_model": os.environ.get("GROK_VISION_MODEL", "").strip()
        or "grok-2-vision-1212",
    "local_vision_model": os.environ.get("LOCAL_LLM_VISION_MODEL", "").strip()
        or "llava",
    # --- Edição de notas com o BMO (painel) — provedor/modelo PRÓPRIOS ---
    # (separado do chat/fala e da visão; o usuário pede pra editar a nota e o
    # BMO reescreve. Texto livre como os outros, escolhível no editor.)
    "noteedit_provider": "openrouter",
    "openrouter_noteedit_model": os.environ.get("OPENROUTER_NOTEEDIT_MODEL", "").strip()
        or "meta-llama/llama-3.3-70b-instruct:free",
    "nvidia_noteedit_model": os.environ.get("NVIDIA_NOTEEDIT_MODEL", "").strip()
        or "moonshotai/kimi-k2.6",
    "grok_noteedit_model": os.environ.get("GROK_NOTEEDIT_MODEL", "").strip()
        or "grok-3",
    "local_noteedit_model": os.environ.get("LOCAL_LLM_NOTEEDIT_MODEL", "").strip()
        or "local-model",
    # --- Modelo PERSONALIZADO (digitado livremente no painel web) por slot ---
    # O painel do PC deixa escrever QUALQUER nome de modelo; o último digitado
    # fica guardado aqui por provedor+tipo, pra o cycler do device oferecer ele
    # junto dos presets (SETTINGS -> IA). "" = sem personalizado ainda.
    "openrouter_model_custom": "",
    "nvidia_model_custom": "",
    "grok_model_custom": "",
    "local_model_custom": "",
    "openrouter_vision_model_custom": "",
    "nvidia_vision_model_custom": "",
    "grok_vision_model_custom": "",
    "local_vision_model_custom": "",
    "openrouter_noteedit_model_custom": "",
    "nvidia_noteedit_model_custom": "",
    "grok_noteedit_model_custom": "",
    "local_noteedit_model_custom": "",
}

IDLE_TIMEOUT_OPTIONS = [5, 10, 15, 30, 60, 120]
AMBIENT_MODE_OPTIONS = ["clock", "face", "brain", "devhub", "pong", "invaders", "shuffle"]
AMBIENT_MODE_LABELS = {
    "clock": "RELOGIO",
    "face": "BMO FACE",
    "brain": "CEREBRO",
    "devhub": "DEV HUB",
    "pong": "PONG",
    "invaders": "INVADERS",
    "shuffle": "VARIADO",
}
BRIGHTNESS_OPTIONS = [20, 40, 60, 80, 100]
VOLUME_OPTIONS = [0, 25, 50, 75, 100]
EVENT_WARNING_OPTIONS = [1, 5, 10, 15, 30, 60]   # minutos de antecedência
BRIEFING_TIME_OPTIONS = ["06:00", "07:00", "07:30", "08:00", "08:30",
                         "09:00", "10:00", "12:00"]   # horário do briefing matinal

# --- LLM: provedores e modelos de troca rápida (SETTINGS -> IA) ---
# Edite à vontade. Os IDs são os esperados por cada API (OpenAI-compatível).
LLM_PROVIDERS = ["openrouter", "nvidia", "grok", "local"]
LLM_PROVIDER_LABELS = {"openrouter": "OPENROUTER", "nvidia": "NVIDIA",
                       "grok": "GROK", "local": "LOCAL (PC)"}
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
        "moonshotai/kimi-k2.6",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "google/gemma-3n-e4b-it",
    ],
    # xAI Grok (api.x.ai) — chave XAI_API_KEY
    "grok": [
        "grok-4",
        "grok-3",
        "grok-3-mini",
        "grok-2-vision-1212",
    ],
    # LLM no SEU PC (llama.cpp/Ollama). No llama-server o nome é ignorado
    # (use "local-model"); no Ollama use os nomes do `ollama list`.
    "local": [
        "local-model",
        "llama3.2",
        "qwen2.5:7b",
        "mistral",
    ],
}

# Presets do endpoint do LLM local pro cycler do SETTINGS (texto livre fica no
# painel web). "" = AUTO: usa o .env ou o padrão llama.cpp (127.0.0.1:8080).
LOCAL_LLM_URL_OPTIONS = ["", "127.0.0.1:8080", "127.0.0.1:11434"]
LOCAL_LLM_URL_LABELS = {
    "": "AUTO",
    "127.0.0.1:8080": "LLAMACPP",
    "127.0.0.1:11434": "OLLAMA",
}

# Modelos de VISÃO (multimodais) por provedor — usados no teste de visão.
# Só entram aqui IDs que aceitam imagem; edite conforme disponibilidade.
LLM_VISION_MODELS = {
    "openrouter": [
        "google/gemini-2.0-flash-exp:free",
        "meta-llama/llama-3.2-11b-vision-instruct:free",
        "qwen/qwen2.5-vl-72b-instruct:free",
    ],
    "nvidia": [
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "google/gemma-3n-e4b-it",
        "meta/llama-3.2-90b-vision-instruct",
    ],
    "grok": [
        "grok-2-vision-1212",
        "grok-4",
    ],
    "local": [
        "llava",
        "llama3.2-vision",
    ],
}

# Chaves de modelo ATIVO (o que o chat.py lê) por provedor — chat, visão e
# edição de notas (todas usam os mesmos provedores).
_KIND_SUFFIX = {"chat": "_model", "vision": "_vision_model", "noteedit": "_noteedit_model"}
MODEL_KEYS = {f"{p}{sfx}" for p in LLM_PROVIDERS for sfx in _KIND_SUFFIX.values()}


def custom_model_key(model_key: str) -> str:
    """Slot que guarda o último modelo digitado livremente no painel web pra
    a mesma chave de modelo. Ex.: 'openrouter_model' -> 'openrouter_model_custom',
    'nvidia_vision_model' -> 'nvidia_vision_model_custom'."""
    return f"{model_key}_custom"


def _split_model_key(model_key: str) -> tuple[str, str]:
    """('openrouter_vision_model') -> ('openrouter', 'vision'). Checa os
    sufixos mais longos primeiro (noteedit/vision antes de model)."""
    for kind in ("noteedit", "vision", "chat"):
        sfx = _KIND_SUFFIX[kind]
        if model_key.endswith(sfx):
            return model_key[: -len(sfx)], kind
    return model_key, "chat"


def _presets_for(provider: str, kind: str = "chat") -> list:
    # visão tem lista própria; chat e edição de notas reutilizam os mesmos presets
    table = LLM_VISION_MODELS if kind == "vision" else LLM_MODELS
    return list(table.get(provider, []))


def model_options(provider: str, kind: str = "chat") -> list:
    """Opções do cycler de modelo no device: o modelo personalizado (digitado
    no painel web, se houver) PRIMEIRO + os presets, sem duplicar.
    kind = 'chat' | 'vision' | 'noteedit'."""
    custom = (get(custom_model_key(f"{provider}{_KIND_SUFFIX.get(kind, '_model')}")) or "").strip()
    opts = _presets_for(provider, kind)
    if custom and custom not in opts:
        opts = [custom] + opts
    return opts


def remember_custom_model(model_key: str, value) -> None:
    """Guarda `value` como o 'modelo personalizado' do slot, pra o cycler do
    device oferecer ele junto dos presets. No-op se model_key não for uma chave
    de modelo, se o valor for vazio, ou se já for um preset (aí preserva o
    personalizado anterior). Chamado pelo painel web ao trocar o modelo."""
    if model_key not in MODEL_KEYS:
        return
    value = (value or "").strip()
    if not value:
        return
    provider, kind = _split_model_key(model_key)
    if value in _presets_for(provider, kind):
        return
    set_value(custom_model_key(model_key), value)


_lock = Lock()
_data: dict | None = None
_path: Path = LEGACY_CONFIG_PATH   # trocado por set_profile_path() na sessão


def set_profile_path(path: Path | None) -> None:
    """Aponta o config pro arquivo do perfil ativo (None = legado da raiz).

    Reseta o cache: o próximo get() já lê as preferências do novo usuário.
    """
    global _path, _data
    with _lock:
        _path = Path(path) if path is not None else LEGACY_CONFIG_PATH
        _data = None


def get_path() -> Path:
    with _lock:
        return _path


def reload() -> None:
    """Força reler o arquivo (ex: drive_sync acabou de baixar do Drive)."""
    global _data
    with _lock:
        _data = None


def _load_unlocked() -> dict:
    global _data
    if _data is None:
        merged = dict(DEFAULTS)
        if _path.exists():
            try:
                with open(_path, "r", encoding="utf-8") as f:
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
            _path.parent.mkdir(parents=True, exist_ok=True)
            with open(_path, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)
        except Exception:
            pass
    if on_change is not None:
        try:
            on_change(key, value)
        except Exception:
            pass
