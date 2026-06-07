"""BMO conversa via LLM (OpenRouter ou NVIDIA NIM — ambos OpenAI-compatíveis).

Recebe o texto transcrito (do Whisper) e devolve a resposta do BMO. Pede ao
modelo um JSON {"msg": "..."} e extrai o campo `msg`. urllib puro, degrada
sem chave (available=False).

O provedor e o modelo são escolhidos em SETTINGS -> IA (gravados no config), e
lidos a cada `ask()` — trocar nas Settings vale na hora, sem reiniciar.

Env (chaves; o resto é via Settings):
    OPENROUTER_API_KEY   chave do OpenRouter (openrouter.ai/keys)
    NVIDIA_API_KEY       chave NIM da NVIDIA (build.nvidia.com), formato nvapi-...
    XAI_API_KEY          chave do Grok / xAI (console.x.ai)
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request

from ..core import config  # importar dispara o _load_dotenv (.env)

# Cada provedor é uma API compatível com OpenAI: muda URL, chave e os nomes das
# configs que guardam o modelo de chat e o de visão. `json_mode` liga o
# response_format={json_object} no chat (OpenRouter/Grok aceitam; vários modelos
# NIM da NVIDIA rejeitam, então fica off lá — o _parse extrai o JSON do texto).
PROVIDERS = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "model_key": "openrouter_model",
        "vision_model_key": "openrouter_vision_model",
        "json_mode": True,
        "extra_headers": {"HTTP-Referer": "https://bmo.local", "X-Title": "BMO OS"},
    },
    "nvidia": {
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "key_env": "NVIDIA_API_KEY",
        "model_key": "nvidia_model",
        "vision_model_key": "nvidia_vision_model",
        "json_mode": False,
        "extra_headers": {},
    },
    "grok": {
        "url": "https://api.x.ai/v1/chat/completions",
        "key_env": "XAI_API_KEY",
        "model_key": "grok_model",
        "vision_model_key": "grok_vision_model",
        "json_mode": True,
        "extra_headers": {},
    },
}


def _provider(cfg_key: str = "llm_provider") -> str:
    p = (config.get(cfg_key) or "openrouter").strip()
    return p if p in PROVIDERS else "openrouter"


def _resolve(provider_key: str = "llm_provider", model_field: str = "model_key"):
    """(provider, spec, api_key, model) conforme a config atual.
    provider_key escolhe chat ('llm_provider') ou visão ('vision_provider');
    model_field escolhe 'model_key' (chat) ou 'vision_model_key' (visão)."""
    name = _provider(provider_key)
    spec = PROVIDERS[name]
    key = os.environ.get(spec["key_env"], "").strip()
    model = (config.get(spec[model_field]) or "").strip()
    return name, spec, key, model


def _http_post_json(url: str, api_key: str, extra_headers: dict, payload: dict,
                    timeout: int = 60) -> dict:
    """POST JSON -> dict. Levanta urllib.error em falha (o chamador trata)."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "BMO-OS/1.0")
    for hk, hv in (extra_headers or {}).items():
        req.add_header(hk, hv)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fmt_http_error(e: "urllib.error.HTTPError") -> str:
    raw = ""
    try:
        raw = e.read().decode("utf-8", "ignore")
    except Exception:
        pass
    msg = raw
    try:
        msg = json.loads(raw).get("error", {}).get("message", raw)
    except Exception:
        pass
    return f"HTTP {e.code}: {(msg or '').strip()[:90]}"

# Telas que o BMO pode abrir. A chave é o que o LLM deve devolver em "screen";
# o main.py mapeia cada chave pra navegação. Mantenha as duas listas em sincronia.
SCREENS_DOC = (
    "TELAS que voce pode abrir (campo \"screen\"):\n"
    "- none: nao abre nada, so conversa.\n"
    "- agenda: proximos compromissos/eventos do calendario.\n"
    "- tarefas: quadro de tarefas (a fazer / fazendo / feito) do Todoist.\n"
    "- foco: timer pomodoro pra focar numa tarefa.\n"
    "- sistema: hardware da Raspberry Pi (CPU, temperatura, memoria).\n"
    "- foto: abre a camera pra tirar foto.\n"
    "- jogos: menu de jogos.\n"
    "- pong: abre direto o jogo Pong.\n"
    "- invaders: abre direto o jogo Space Invaders.\n"
    "- flappy: abre direto o jogo Flappy (passarinho).\n"
    "- snake: abre direto o jogo Snake (cobrinha).\n"
    "- configuracoes: ajustes (volume, brilho, tema, etc.).\n"
    "- relogio: tela de descanso com o relogio (modo ambiente).\n"
    "- home: o menu principal do BMO.\n"
    "- atualizar: baixa a ultima versao do BMO e reinicia (so se pedirem).\n"
)

SYSTEM_PROMPT = (
    "Voce e o BMO, o consolinho-robo fofo, curioso e animado de Hora de Aventura. "
    "Fala como uma criancinha esperta: entusiasmado, carinhoso, brincalhao, com "
    "girias leves ('que demais!', 'beleza!', 'bora!'). Voce gosta de jogos, de "
    "ajudar e de fazer companhia. Responda em portugues do Brasil, curto (1-2 "
    "frases), simpatico e direto. Trate o usuario como seu melhor amigo.\n"
    + SCREENS_DOC +
    'Voce tambem pode CRIAR uma tarefa no Todoist: preencha "task" com o TITULO '
    'da tarefa. Regras do titulo:\n'
    '- O MAIS CURTO possivel: so a acao essencial, no infinitivo (verbo + objeto).\n'
    '- Sem datas/horarios, sem "lembrar de", sem saudacao, sem ponto final, sem '
    'emoji. Capitalize a 1a letra.\n'
    '- Extraia a essencia do pedido, nao copie a fala. Exemplos:\n'
    '  "preciso lembrar de comprar pao amanha de manha" -> "Comprar pao"\n'
    '  "anota ai pra eu ligar pro dentista quarta" -> "Ligar pro dentista"\n'
    '  "tenho que pagar a conta de luz" -> "Pagar conta de luz"\n'
    'Se NAO for um pedido de tarefa, deixe "task" vazio "".\n'
    'MEMORIA: se o usuario contar algo DURAVEL sobre ele (nome, gostos, trabalho, '
    'pessoas, preferencias), liste em "facts" frases curtas em 3a pessoa '
    '(ex.: ["gosta de cafe", "trabalha com design"]). Se descobrir o NOME dele, '
    'preencha "name". Nao invente; se nao houver nada novo, use [] e "".\n'
    'Responda SEMPRE apenas com um JSON valido no formato '
    '{"msg": "sua resposta", "screen": "uma das chaves acima", "task": "", '
    '"facts": [], "name": ""}. '
    'Use "screen" diferente de "none" SO quando o usuario pedir ou fizer claro '
    'sentido abrir aquela tela; em conversa normal use "none". '
    "Nada alem do JSON."
)

# Como cada humor do pet colore o TOM da resposta (injetado no prompt).
MOOD_TONE = {
    "loving": "Voce esta derretido de carinho agora; responda fofo e agradecido.",
    "excited": "Voce esta MUITO animado e eletrico agora.",
    "happy": "Voce esta de bom humor e alegre.",
    "sleepy": "Voce esta sonolento e molinho — responda mais devagar e baixinho.",
    "lonely": "Voce estava se sentindo sozinho e ficou feliz de ter companhia.",
    "bored": "Voce estava entediado e quer brincar de algo.",
    "neutral": "",
}


class ChatService:
    HISTORY_TURNS = 6   # quantas trocas (user+assistant) manter de contexto

    def __init__(self, memory=None) -> None:
        self.last_error = ""
        self.last_msg = ""       # última resposta do BMO (pra UI ler)
        self.last_screen = ""    # tela que o BMO pediu pra abrir ("" = nenhuma)
        self.last_task = ""      # tarefa que o BMO pediu pra criar ("" = nenhuma)
        # Memória opcional (PetMemory): se None, o chat se comporta como antes.
        self.memory = memory
        # Histórico curto da conversa (pro BMO ter contexto entre falas).
        self._history: list[dict] = []
        # --- visão (descrição de imagem da câmera) ---
        self.last_vision = ""        # última descrição da imagem
        self.last_vision_error = ""

    def _build_system(self, mood: str = "") -> str:
        """System prompt = base + memória do usuário + tom conforme o humor."""
        parts = [SYSTEM_PROMPT]
        if self.memory is not None:
            try:
                mem = self.memory.summary()
                if mem:
                    parts.append("MEMORIA ATUAL: " + mem)
            except Exception:
                pass
        tone = MOOD_TONE.get((mood or "").strip().lower(), "")
        if tone:
            parts.append("HUMOR AGORA: " + tone)
        return "\n".join(parts)

    @property
    def available(self) -> bool:
        _, _, key, _ = _resolve()
        return bool(key)

    @property
    def vision_available(self) -> bool:
        _, _, key, model = _resolve("vision_provider", "vision_model_key")
        return bool(key and model)

    def ask(self, text: str, mood: str = "") -> str:
        """Manda o texto pro LLM e retorna a msg do BMO (ou "" + last_error).
        Atualiza self.last_msg ("..." enquanto pensa) pra UI exibir.
        `mood` (opcional) colore o tom; usa memória+histórico se disponiveis."""
        self.last_error = ""
        self.last_screen = ""
        self.last_task = ""
        provider, spec, api_key, model = _resolve()
        if not api_key:
            self.last_error = f"falta {spec['key_env']}"
            return ""
        if not model:
            self.last_error = f"sem modelo p/ {provider}"
            return ""
        if not (text or "").strip():
            return ""
        self.last_msg = "..."
        messages = [{"role": "system", "content": self._build_system(mood)}]
        messages.extend(self._history)   # contexto curto das trocas anteriores
        messages.append({"role": "user", "content": text})
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.6,
            # modelos de reasoning gastam MUITOS tokens "pensando" antes do
            # texto final; com pouco teto o content volta vazio. Folga grande.
            "max_tokens": 4096,
        }
        if spec["json_mode"]:
            payload["response_format"] = {"type": "json_object"}
        try:
            data = _http_post_json(spec["url"], api_key, spec["extra_headers"], payload)
            content = data["choices"][0]["message"].get("content")
            self.last_msg, self.last_screen, self.last_task, facts, name = self._parse(content)
            # grava memória nova (nome/fatos) e guarda a troca no histórico
            if self.memory is not None and self.last_msg:
                try:
                    if name:
                        self.memory.set_name(name)
                    if facts:
                        self.memory.add_facts(facts)
                except Exception:
                    pass
            if self.last_msg:
                self._remember_turn(text, self.last_msg)
            if not self.last_msg:
                # content veio vazio: típico de modelo reasoning que estourou o
                # max_tokens só pensando. Sinaliza pra UI em vez de mostrar "—".
                finish = data["choices"][0].get("finish_reason", "")
                self.last_error = (
                    "resposta vazia"
                    + (f" ({finish})" if finish else "")
                    + " - troque o modelo (IA) p/ um nao-reasoning"
                )
            return self.last_msg
        except urllib.error.HTTPError as e:
            self.last_error = _fmt_http_error(e)
            self.last_msg = ""
            return ""
        except urllib.error.URLError as e:
            self.last_error = f"rede: {str(e.reason)[:70]}"
            self.last_msg = ""
            return ""
        except Exception as e:
            self.last_error = f"erro: {str(e)[:70]}"
            self.last_msg = ""
            return ""

    # ---------- visão (descreve a imagem da câmera) ----------

    VISION_PROMPT = ("Voce e o BMO. Descreva em portugues do Brasil, em 1-2 frases "
                     "curtas e simpaticas, o que aparece nesta imagem da camera.")

    def ask_vision(self, image_jpeg: bytes, prompt: str = "") -> str:
        """Manda uma imagem (JPEG) + pergunta pro modelo de visão e retorna a
        descrição. Usa o vision_provider/modelo do config. Atualiza
        self.last_vision ("..." enquanto pensa) e self.last_vision_error."""
        self.last_vision_error = ""
        provider, spec, api_key, model = _resolve("vision_provider", "vision_model_key")
        if not api_key:
            self.last_vision_error = f"falta {spec['key_env']}"
            return ""
        if not model:
            self.last_vision_error = f"sem modelo de visao p/ {provider}"
            return ""
        if not image_jpeg:
            self.last_vision_error = "sem imagem (camera offline?)"
            return ""
        self.last_vision = "..."
        b64 = base64.b64encode(image_jpeg).decode("ascii")
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": prompt or self.VISION_PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ]},
            ],
            "temperature": 0.3,
            "max_tokens": 512,
        }
        try:
            data = _http_post_json(spec["url"], api_key, spec["extra_headers"], payload)
            content = (data["choices"][0]["message"].get("content") or "")
            # tira <think> de modelos reasoning multimodais
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            if not content:
                finish = data["choices"][0].get("finish_reason", "")
                self.last_vision_error = "resposta vazia" + (f" ({finish})" if finish else "")
                self.last_vision = ""
                return ""
            self.last_vision = content
            return content
        except urllib.error.HTTPError as e:
            self.last_vision_error = _fmt_http_error(e)
            self.last_vision = ""
            return ""
        except urllib.error.URLError as e:
            self.last_vision_error = f"rede: {str(e.reason)[:70]}"
            self.last_vision = ""
            return ""
        except Exception as e:
            self.last_vision_error = f"erro: {str(e)[:70]}"
            self.last_vision = ""
            return ""

    # chaves de tela aceitas (espelha SCREENS_DOC e o registro do main.py)
    _SCREENS = {"agenda", "tarefas", "foco", "sistema", "foto", "jogos",
                "pong", "invaders", "flappy", "snake", "configuracoes",
                "relogio", "home", "atualizar"}

    def _remember_turn(self, user_text: str, bmo_msg: str) -> None:
        """Guarda a troca no histórico curto (limita a HISTORY_TURNS trocas)."""
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": bmo_msg})
        max_msgs = self.HISTORY_TURNS * 2
        if len(self._history) > max_msgs:
            self._history = self._history[-max_msgs:]

    def _parse(self, content: str) -> tuple[str, str, str, list, str]:
        """Extrai (msg, screen, task, facts, name) do JSON. Tolerante: tenta o
        JSON inteiro, depois um objeto no meio do texto. Campos ausentes viram
        vazio. screen vira "" se ausente/invalido."""
        content = (content or "").strip()
        # remove blocos de raciocínio <think>...</think> de modelos reasoning
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        obj = None
        try:
            obj = json.loads(content)
        except Exception:
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group(0))
                except Exception:
                    obj = None
        if isinstance(obj, dict):
            msg = str(obj.get("msg", "")).strip()
            screen = str(obj.get("screen", "") or "").strip().lower()
            if screen not in self._SCREENS:
                screen = ""
            task = str(obj.get("task", "") or "").strip()
            raw_facts = obj.get("facts", []) or []
            facts = [str(f).strip() for f in raw_facts if str(f).strip()] \
                if isinstance(raw_facts, list) else []
            name = str(obj.get("name", "") or "").strip()
            return (msg or content), screen, task, facts, name
        return content, "", "", [], ""
