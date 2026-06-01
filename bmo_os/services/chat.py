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

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
).strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

SYSTEM_PROMPT = (
    "Voce e o BMO, o consolinho fofo e prestativo de Hora de Aventura. "
    "Responda em portugues do Brasil, curto (1-2 frases), simpatico e direto. "
    'Responda SEMPRE apenas com um JSON valido no formato {"msg": "sua resposta"} '
    "e absolutamente nada alem do JSON."
)


class ChatService:
    def __init__(self) -> None:
        self.last_error = ""
        self.last_msg = ""       # última resposta do BMO (pra UI ler)

    @property
    def available(self) -> bool:
        return bool(OPENROUTER_API_KEY)

    def ask(self, text: str) -> str:
        """Manda o texto pro LLM e retorna a msg do BMO (ou "" + last_error).
        Atualiza self.last_msg ("..." enquanto pensa) pra UI exibir."""
        self.last_error = ""
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
            "max_tokens": 1024,   # modelo de reasoning gasta tokens "pensando"
        }).encode("utf-8")
        req = urllib.request.Request(OPENROUTER_URL, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {OPENROUTER_API_KEY}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "BMO-OS/1.0")
        req.add_header("HTTP-Referer", "https://bmo.local")
        req.add_header("X-Title", "BMO OS")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            self.last_msg = self._extract_msg(content)
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

    @staticmethod
    def _extract_msg(content: str) -> str:
        """Extrai o campo 'msg' do JSON. Tolerante: tenta o JSON inteiro, depois
        um objeto no meio do texto, e por fim usa o texto cru."""
        content = (content or "").strip()
        # remove blocos de raciocínio <think>...</think> de modelos reasoning
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        try:
            return str(json.loads(content).get("msg", "")).strip() or content
        except Exception:
            pass
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            try:
                return str(json.loads(m.group(0)).get("msg", "")).strip() or content
            except Exception:
                pass
        return content
