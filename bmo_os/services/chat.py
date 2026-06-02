"""BMO conversa via LLM (OpenRouter — compatível com OpenAI).

Recebe o texto transcrito (do Whisper) e devolve a resposta do BMO. Pede ao
modelo um JSON {"msg": "..."} e extrai o campo `msg`. urllib puro, degrada
sem chave (available=False).

Env:
    OPENROUTER_API_KEY   chave (openrouter.ai/keys)
    OPENROUTER_MODEL     default nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from ..core import config  # noqa: F401 — importar dispara o _load_dotenv (.env)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
).strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

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
    "- configuracoes: ajustes (volume, brilho, tema, etc.).\n"
    "- relogio: tela de descanso com o relogio (modo ambiente).\n"
    "- home: o menu principal do BMO.\n"
    "- atualizar: baixa a ultima versao do BMO e reinicia (so se pedirem).\n"
)

SYSTEM_PROMPT = (
    "Voce e o BMO, o consolinho fofo e prestativo de Hora de Aventura. "
    "Responda em portugues do Brasil, curto (1-2 frases), simpatico e direto.\n"
    + SCREENS_DOC +
    'Voce tambem pode CRIAR uma tarefa no Todoist: preencha "task" com o texto '
    'da tarefa (ex.: "comprar pao"); senao deixe "task" vazio "".\n'
    'Responda SEMPRE apenas com um JSON valido no formato '
    '{"msg": "sua resposta", "screen": "uma das chaves acima", "task": ""}. '
    'Use "screen" diferente de "none" SO quando o usuario pedir ou fizer claro '
    'sentido abrir aquela tela; em conversa normal use "none". '
    "Nada alem do JSON."
)


class ChatService:
    def __init__(self) -> None:
        self.last_error = ""
        self.last_msg = ""       # última resposta do BMO (pra UI ler)
        self.last_screen = ""    # tela que o BMO pediu pra abrir ("" = nenhuma)
        self.last_task = ""      # tarefa que o BMO pediu pra criar ("" = nenhuma)

    @property
    def available(self) -> bool:
        return bool(OPENROUTER_API_KEY)

    def ask(self, text: str) -> str:
        """Manda o texto pro LLM e retorna a msg do BMO (ou "" + last_error).
        Atualiza self.last_msg ("..." enquanto pensa) pra UI exibir."""
        self.last_error = ""
        self.last_screen = ""
        self.last_task = ""
        if not OPENROUTER_API_KEY:
            self.last_error = "falta OPENROUTER_API_KEY"
            return ""
        if not (text or "").strip():
            return ""
        self.last_msg = "..."
        body = json.dumps({
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.6,
            # modelos de reasoning gastam MUITOS tokens "pensando" antes do
            # texto final; com pouco teto o content volta vazio. Folga grande.
            "max_tokens": 4096,
        }).encode("utf-8")
        req = urllib.request.Request(OPENROUTER_URL, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {OPENROUTER_API_KEY}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "BMO-OS/1.0")
        req.add_header("HTTP-Referer", "https://bmo.local")
        req.add_header("X-Title", "BMO OS")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            msg_obj = data["choices"][0]["message"]
            content = msg_obj.get("content")
            self.last_msg, self.last_screen, self.last_task = self._parse(content)
            if not self.last_msg:
                # content veio vazio: típico de modelo reasoning que estourou o
                # max_tokens só pensando. Sinaliza pra UI em vez de mostrar "—".
                finish = data["choices"][0].get("finish_reason", "")
                self.last_error = (
                    "resposta vazia"
                    + (f" ({finish})" if finish else "")
                    + " - troque OPENROUTER_MODEL p/ um nao-reasoning"
                )
            return self.last_msg
        except urllib.error.HTTPError as e:
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
            self.last_error = f"HTTP {e.code}: {(msg or '').strip()[:90]}"
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

    # chaves de tela aceitas (espelha SCREENS_DOC e o registro do main.py)
    _SCREENS = {"agenda", "tarefas", "foco", "sistema", "foto", "jogos",
                "pong", "invaders", "configuracoes", "relogio", "home", "atualizar"}

    def _parse(self, content: str) -> tuple[str, str, str]:
        """Extrai (msg, screen, task) do JSON. Tolerante: tenta o JSON inteiro,
        depois um objeto no meio do texto. screen vira "" se ausente/invalido."""
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
            return (msg or content), screen, task
        return content, "", ""
