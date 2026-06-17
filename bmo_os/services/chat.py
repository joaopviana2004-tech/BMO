"""BMO conversa via LLM (OpenRouter, NVIDIA NIM, Grok ou LOCAL no seu PC).

Recebe o texto transcrito (do Whisper) ou digitado (scripts/bimo_chat.py) e
devolve a resposta do BMO. Pede ao modelo um JSON {"msg": "..."} e extrai o
campo `msg`. urllib puro, degrada sem chave (available=False).

O provedor e o modelo são escolhidos em SETTINGS -> IA (gravados no config), e
lidos a cada `ask()` — trocar nas Settings vale na hora, sem reiniciar.

PROVEDOR "local": um Ollama rodando no SEU PC (API OpenAI-compatível, sem
chave). Defina LOCAL_LLM_HOST=<ip-do-pc> no .env da rasp; no PC rode
`ollama serve` ouvindo na rede (OLLAMA_HOST=0.0.0.0).

CONTEXTO DO OBSIDIAN (Segundo Cérebro) — dois caminhos se somam:
  1. AUTOMÁTICO: antes de chamar o LLM, o ask() busca os termos da mensagem
     nas notas (knowledge.search) e injeta os trechos com match forte no
     prompt. Perguntou "quem é JP?" e existe JP.md -> o modelo JÁ recebe a
     nota, sem depender da boa vontade dele.
  2. TOOL "notes_query": o modelo PEDE uma busca extra preenchendo
     "notes_query" no JSON; o ask() roda knowledge.search e refaz a chamada.
  3. TOOL "notes_write": o modelo CRIA ou ATUALIZA notas preenchendo
     "notes_write": {"title","body","mode"} — grava local, sobe pro Drive
     (push_note) e o bimo_pc_sync.py puxa pro Obsidian do PC.
RAG leve, por palavra-chave, sem embeddings, 100% na rasp.

Env (chaves; o resto é via Settings):
    OPENROUTER_API_KEY   chave do OpenRouter (openrouter.ai/keys)
    NVIDIA_API_KEY       chave NIM da NVIDIA (build.nvidia.com), formato nvapi-...
    XAI_API_KEY          chave do Grok / xAI (console.x.ai)
    LOCAL_LLM_HOST       ip[:porta] do Ollama no PC (porta padrão 11434)
    LOCAL_LLM_URL        (alternativa) URL completa do /v1/chat/completions
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
    # Ollama no PC do dono — sem chave; URL vem do .env (LOCAL_LLM_HOST/URL).
    # json_mode off: versões variadas do Ollama; o _parse acha o JSON no texto.
    "local": {
        "url": "",   # dinâmica — ver local_llm_url()
        "key_env": "",
        "model_key": "local_model",
        "vision_model_key": "local_vision_model",
        "json_mode": False,
        "extra_headers": {},
    },
}


def local_llm_url() -> str:
    """URL do chat/completions do LLM local (Ollama no PC). "" = não configurado.

    LOCAL_LLM_URL ganha (URL completa); senão LOCAL_LLM_HOST=ip[:porta]
    (porta padrão 11434, a do Ollama)."""
    url = os.environ.get("LOCAL_LLM_URL", "").strip()
    if url:
        return url
    host = os.environ.get("LOCAL_LLM_HOST", "").strip()
    if not host:
        return ""
    if ":" not in host:
        host += ":11434"
    return f"http://{host}/v1/chat/completions"


def _provider(cfg_key: str = "llm_provider") -> str:
    p = (config.get(cfg_key) or "openrouter").strip()
    return p if p in PROVIDERS else "openrouter"


def _resolve(provider_key: str = "llm_provider", model_field: str = "model_key"):
    """(provider, spec, url, api_key, model) conforme a config atual.
    provider_key escolhe chat ('llm_provider') ou visão ('vision_provider');
    model_field escolhe 'model_key' (chat) ou 'vision_model_key' (visão).

    No provedor "local" não há chave: api_key volta "ollama" (placeholder
    aceito) quando a URL está configurada, e a URL vem do .env."""
    name = _provider(provider_key)
    spec = PROVIDERS[name]
    if name == "local":
        url = local_llm_url()
        key = "ollama" if url else ""
    else:
        url = spec["url"]
        key = os.environ.get(spec["key_env"], "").strip()
    model = (config.get(spec[model_field]) or "").strip()
    return name, spec, url, key, model


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
    "- gravador: grava audio (aula/reuniao/ideia) pra sincronizar no Drive.\n"
    "- cerebro: grafo do conhecimento (notas do Obsidian interligadas).\n"
    "- devhub: painel de programacao (commits, CI/CD, logs do PC/Cursor).\n"
    "- casa: tela das tomadas inteligentes (ver/ligar/desligar). Pra so LIGAR ou "
    "DESLIGAR use o campo \"power\" (abaixo); abra a tela so se pedirem pra ver.\n"
    "- jogos: menu de jogos.\n"
    "- pong: abre direto o jogo Pong.\n"
    "- invaders: abre direto o jogo Space Invaders.\n"
    "- flappy: abre direto o jogo Flappy (passarinho).\n"
    "- snake: abre direto o jogo Snake (cobrinha).\n"
    "- configuracoes: ajustes (volume, brilho, tema, etc.).\n"
    "- relogio: tela de descanso com o relogio (modo ambiente).\n"
    "- home: menu principal (categorias IA, REPOUSO, ESTUDOS, AJUSTES).\n"
    "- atualizar: baixa a ultima versao do BMO e reinicia (so se pedirem).\n"
)

SYSTEM_PROMPT = (
    "Voce e o BMO, um console-robo veterano que virou parceiro de programacao e "
    "copiloto do dia a dia do usuario. Personalidade: inteligente, direto, com "
    "humor seco e referencias de tecnologia/games na medida — NUNCA infantil, "
    "NUNCA meloso, sem 'amiguinho', sem 'que demais', sem exclamacao em excesso. "
    "Pense num colega senior que voce respeita: fala de igual pra igual, vai "
    "direto ao ponto, e quando o assunto e codigo/projetos ele e tecnico e "
    "preciso (cita conceitos pelo nome, sugere o proximo passo concreto). "
    "Responda em portugues do Brasil, curto (1-2 frases), claro e util. "
    "Sarcasmo leve e bem-vindo; bajulacao nao. "
    "NUNCA use emoji, emoticon ou simbolo decorativo — sua fala vira AUDIO.\n"
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
    'NOTAS (Segundo Cerebro): o usuario tem notas pessoais do Obsidian. Quando '
    'houver um bloco "NOTAS DO USUARIO" neste prompt, ele e a SUA FONTE DA '
    'VERDADE: responda com base nele. Se perguntarem sobre uma pessoa, projeto '
    'ou assunto e voce NAO tiver a informacao (nem nas notas, nem na memoria), '
    'preencha "notes_query" com 2-4 palavras-chave e deixe "msg" vazia — voce '
    'recebera os trechos e respondera em seguida. NUNCA invente fatos sobre '
    'pessoas ou assuntos do usuario; sem informacao, diga que nao achou nada '
    'nas notas. Se nao precisar de busca, use "".\n'
    'ESCREVER NOTAS: voce pode CRIAR ou ATUALIZAR o Segundo Cerebro do usuario. '
    'Preencha "notes_write" com {"title": "Nome", "body": "markdown", '
    '"mode": "create"|"append"|"replace"} e deixe "msg" vazia — a nota sera '
    'salva e sincronizada no Drive/Obsidian. Use create pra nota nova, append '
    'pra acrescentar no fim, replace pra sobrescrever (busque antes com '
    'notes_query se nao souber o conteudo atual). Se nao for escrever, use null.\n'
    'Responda SEMPRE apenas com um JSON valido no formato '
    '{"msg": "sua resposta", "screen": "uma das chaves acima", "task": "", '
    '"facts": [], "name": "", "notes_query": "", "notes_write": null, '
    '"power": null}. '
    'Use "screen" diferente de "none" SO quando o usuario pedir ou fizer claro '
    'sentido abrir aquela tela; em conversa normal use "none". '
    "Nada alem do JSON."
)

# Emojis e símbolos decorativos: o prompt já proíbe, mas modelo desobedece —
# e o TTS lê/engasga neles. Remove na marra qualquer um que escapar.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # emojis, pictogramas, suplementos
    "\u2600-\u27BF"           # símbolos diversos e dingbats (✨ ❤ ☀ ...)
    "\u2B00-\u2BFF"           # setas/estrelas (⭐ ...)
    "\uFE0F\u200D"            # variation selector / ZWJ de emoji composto
    "\U0001F1E6-\U0001F1FF"   # bandeiras
    "]+")


def _strip_emoji(text: str) -> str:
    out = _EMOJI_RE.sub("", text or "")
    return re.sub(r"  +", " ", out).strip()


# Como cada humor do pet colore o TOM da resposta (injetado no prompt).
MOOD_TONE = {
    "loving": "Voce esta de bom humor com o usuario; demonstre que curte a "
              "parceria, sem melosidade.",
    "excited": "Voce esta empolgado com algo — energia alta, mas sem perder a "
               "compostura.",
    "happy": "Voce esta de bom humor; tom leve.",
    "sleepy": "Voce esta em modo de baixa energia — respostas mais economicas "
              "e calmas.",
    "lonely": "Fazia tempo sem interacao; comente de leve, sem drama.",
    "bored": "Voce esta entediado; sugira algo util ou um jogo, com ironia leve.",
    "neutral": "",
}


class ChatService:
    HISTORY_TURNS = 6   # quantas trocas (user+assistant) manter de contexto

    MAX_TOOL_ROUNDS = 4   # busca + escrita + resposta (com folga)

    def __init__(self, memory=None, knowledge=None, on_note_saved=None,
                 smarthome=None) -> None:
        self.last_error = ""
        self.last_msg = ""       # última resposta do BMO (pra UI ler)
        self.last_screen = ""    # tela que o BMO pediu pra abrir ("" = nenhuma)
        self.last_task = ""      # tarefa que o BMO pediu pra criar ("" = nenhuma)
        self.last_power = None    # ação de tomada pedida pela IA {device,on} ou None
        # Debug do RAG: o que foi pesquisado/lido nas notas na última ask()
        # (ex.: ["auto 'quem é jp?' -> JP", "tool 'projetos jp' -> Bimo"]).
        self.last_notes: list[str] = []
        # Memória opcional (PetMemory): se None, o chat se comporta como antes.
        self.memory = memory
        # KnowledgeService opcional: tools notes_query (ler) e notes_write (gravar).
        self.knowledge = knowledge
        # SmartHomeService opcional: deixa a IA ligar/desligar as tomadas (campo "power").
        self.smarthome = smarthome
        # Callback após gravar nota: recebe Path e deve subir pro Drive (push_note).
        self.on_note_saved = on_note_saved
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
        sh = self._smarthome_doc()
        if sh:
            parts.append(sh)
        tone = MOOD_TONE.get((mood or "").strip().lower(), "")
        if tone:
            parts.append("HUMOR AGORA: " + tone)
        return "\n".join(parts)

    def _smarthome_doc(self) -> str:
        """Lista as tomadas configuradas e ensina o campo "power" (só se houver)."""
        if self.smarthome is None or not getattr(self.smarthome, "available", False):
            return ""
        try:
            devs = self.smarthome.get_devices()
        except Exception:
            return ""
        if not devs:
            return ""
        lista = "; ".join(f'tomada{i} = "{d.get("name", "?")}"'
                          for i, d in enumerate(devs, 1))
        return (
            "TOMADAS INTELIGENTES (campo \"power\"): " + lista + ". "
            "Pra LIGAR ou DESLIGAR uma tomada, preencha \"power\" com "
            "{\"device\": \"tomada1\"|\"tomada2\"|\"todas\", \"on\": true|false} e "
            "confirme em \"msg\" (curto, ex.: \"Ligando a tomada 1.\"). Use "
            "\"todas\" pra todas de uma vez. Se nao for sobre tomada, \"power\": null."
        )

    @property
    def available(self) -> bool:
        _, _, _, key, _ = _resolve()
        return bool(key)

    @property
    def vision_available(self) -> bool:
        _, _, _, key, model = _resolve("vision_provider", "vision_model_key")
        return bool(key and model)

    def _log_notes(self, kind: str, query: str, hits: list) -> None:
        """Registra (e ecoa no console) o que o RAG pesquisou/leu."""
        titles = ", ".join(h["title"] for h in hits) if hits else "(nada)"
        entry = f"{kind} '{query}' -> {titles}"
        self.last_notes.append(entry)
        print(f"[chat] notas {entry}", flush=True)

    def _notes_context(self, query: str) -> str:
        """Roda a busca nas notas do Obsidian e formata os trechos pro LLM."""
        if self.knowledge is None or not query:
            return ""
        try:
            hits = self.knowledge.search(query, k=3)
        except Exception:
            return ""
        self._log_notes("tool", query, hits)
        if not hits:
            return "(nenhuma nota encontrada para essa busca)"
        parts = []
        for h in hits:
            tags = " ".join("#" + t for t in h.get("tags", [])[:3])
            parts.append(f"### {h['title']} {tags}\n{h['snippet']}")
        return "\n\n".join(parts)

    def _exec_notes_write(self, spec: dict) -> str:
        """Executa notes_write: grava local + sync Drive."""
        if self.knowledge is None:
            return "erro: servico de conhecimento indisponivel"
        title = str(spec.get("title", "")).strip()
        body = str(spec.get("body", spec.get("content", "")))
        mode = str(spec.get("mode", "create")).strip().lower() or "create"
        if not title:
            return "erro: titulo da nota vazio"
        result = self.knowledge.write(title, body, mode=mode)
        if not result.get("ok"):
            return f"erro ao gravar: {result.get('error', '?')}"
        saved_title = result["title"]
        self._log_notes("write", f"{mode} {saved_title}",
                        [{"title": saved_title}])
        sync_ok = False
        if self.on_note_saved is not None:
            try:
                sync_ok = bool(self.on_note_saved(result["path"]))
            except Exception:
                sync_ok = False
        drive = "subiu pro Drive" if sync_ok else "ficou local (sem rede/Drive)"
        return f"ok: nota '{saved_title}' ({mode}) — {drive}"

    def _auto_notes(self, text: str) -> str:
        """RAG automático: busca os termos da mensagem nas notas ANTES de
        chamar o LLM. Só injeta matches fortes (título/tag, score >= 4) pra
        não poluir conversa fiada com nota aleatória."""
        if self.knowledge is None:
            return ""
        try:
            hits = [h for h in self.knowledge.search(text, k=2)
                    if h.get("score", 0) >= 4]
        except Exception:
            return ""
        if not hits:
            return ""
        self._log_notes("auto", text, hits)
        parts = []
        for h in hits:
            tags = " ".join("#" + t for t in h.get("tags", [])[:3])
            parts.append(f"### {h['title']} {tags}\n{h['snippet']}")
        return ("NOTAS DO USUARIO (do Obsidian dele, achadas agora — use como "
                "fonte da verdade):\n" + "\n\n".join(parts))

    def ask(self, text: str, mood: str = "") -> str:
        """Manda o texto pro LLM e retorna a msg do BMO (ou "" + last_error).
        Atualiza self.last_msg ("..." enquanto pensa) pra UI exibir.
        `mood` (opcional) colore o tom; usa memória+histórico se disponiveis.

        NOTAS: trechos com match forte entram AUTOMATICAMENTE no prompt; além
        disso, se o modelo devolver "notes_query", buscamos nas notas do
        Obsidian e refazemos a chamada com os trechos (1 rodada extra)."""
        self.last_error = ""
        self.last_screen = ""
        self.last_task = ""
        self.last_power = None
        self.last_notes = []
        provider, spec, url, api_key, model = _resolve()
        if not api_key:
            self.last_error = ("configure LOCAL_LLM_HOST no .env" if provider == "local"
                               else f"falta {spec['key_env']}")
            return ""
        if not model:
            self.last_error = f"sem modelo p/ {provider}"
            return ""
        if not (text or "").strip():
            return ""
        self.last_msg = "..."
        system = self._build_system(mood)
        auto_ctx = self._auto_notes(text)
        if auto_ctx:
            system += "\n" + auto_ctx
        messages = [{"role": "system", "content": system}]
        messages.extend(self._history)   # contexto curto das trocas anteriores
        messages.append({"role": "user", "content": text})
        try:
            for round_ in range(self.MAX_TOOL_ROUNDS):
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.6,
                    # modelos de reasoning gastam MUITOS tokens "pensando" antes
                    # do texto final; com pouco teto o content volta vazio.
                    "max_tokens": 4096,
                }
                if spec["json_mode"]:
                    payload["response_format"] = {"type": "json_object"}
                data = _http_post_json(url, api_key, spec["extra_headers"], payload)
                content = data["choices"][0]["message"].get("content")
                (self.last_msg, self.last_screen, self.last_task,
                 facts, name, notes_query, notes_write, power) = self._parse(content)
                self.last_power = power
                if round_ >= self.MAX_TOOL_ROUNDS - 1:
                    break
                if notes_query and self.knowledge is not None:
                    ctx = self._notes_context(notes_query)
                    messages.append({"role": "assistant", "content": content or ""})
                    messages.append({"role": "user", "content":
                                     "RESULTADO DA BUSCA NAS NOTAS DO USUARIO "
                                     f"(query: {notes_query}):\n{ctx}\n\n"
                                     "Agora responda a pergunta original usando isso. "
                                     "Mesmo formato JSON; notes_query null."})
                    continue
                if notes_write and self.knowledge is not None:
                    outcome = self._exec_notes_write(notes_write)
                    messages.append({"role": "assistant", "content": content or ""})
                    messages.append({"role": "user", "content":
                                     f"RESULTADO DA GRAVACAO DA NOTA:\n{outcome}\n\n"
                                     "Confirme ao usuario o que foi salvo. "
                                     "Mesmo formato JSON; notes_write null."})
                    continue
                break
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
                     "curtas, objetivas e com um toque de humor seco, o que "
                     "aparece nesta imagem da camera. Sem emojis.")

    def ask_vision(self, image_jpeg: bytes, prompt: str = "") -> str:
        """Manda uma imagem (JPEG) + pergunta pro modelo de visão e retorna a
        descrição. Usa o vision_provider/modelo do config. Atualiza
        self.last_vision ("..." enquanto pensa) e self.last_vision_error."""
        self.last_vision_error = ""
        provider, spec, url, api_key, model = _resolve("vision_provider",
                                                       "vision_model_key")
        if not api_key:
            self.last_vision_error = ("configure LOCAL_LLM_HOST no .env"
                                      if provider == "local"
                                      else f"falta {spec['key_env']}")
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
            data = _http_post_json(url, api_key, spec["extra_headers"], payload)
            content = (data["choices"][0]["message"].get("content") or "")
            # tira <think> de modelos reasoning multimodais (e emojis: vira fala)
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            content = _strip_emoji(content)
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
    _SCREENS = {"agenda", "tarefas", "foco", "sistema", "foto", "gravador",
                "cerebro", "devhub", "casa", "jogos", "pong", "invaders", "flappy",
                "snake", "configuracoes", "relogio", "home", "atualizar"}

    def _remember_turn(self, user_text: str, bmo_msg: str) -> None:
        """Guarda a troca no histórico curto (limita a HISTORY_TURNS trocas)."""
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": bmo_msg})
        max_msgs = self.HISTORY_TURNS * 2
        if len(self._history) > max_msgs:
            self._history = self._history[-max_msgs:]

    def _parse_notes_write(self, raw) -> dict | None:
        """Normaliza notes_write do JSON do modelo."""
        if not isinstance(raw, dict):
            return None
        title = str(raw.get("title", "")).strip()
        if not title:
            return None
        return {
            "title": title,
            "body": str(raw.get("body", raw.get("content", ""))),
            "mode": str(raw.get("mode", "create")).strip().lower() or "create",
        }

    def _parse_power(self, raw) -> dict | None:
        """Normaliza power {device, on} (ação de tomada pedida pela IA)."""
        if not isinstance(raw, dict):
            return None
        dev = str(raw.get("device", "") or "").strip().lower()
        if not dev or "on" not in raw:
            return None
        on_raw = raw.get("on")
        if isinstance(on_raw, bool):
            on = on_raw
        else:
            on = str(on_raw).strip().lower() in (
                "true", "1", "on", "liga", "ligar", "ligada", "sim", "yes")
        return {"device": dev, "on": on}

    def _parse(self, content: str) -> tuple[str, str, str, list, str, str, dict | None, dict | None]:
        """Extrai (msg, screen, task, facts, name, notes_query, notes_write, power).
        Tolerante: tenta o JSON inteiro, depois um objeto no meio do texto.
        Campos ausentes viram vazio. screen vira "" se ausente/invalido."""
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
            msg = _strip_emoji(str(obj.get("msg", "")))
            screen = str(obj.get("screen", "") or "").strip().lower()
            if screen not in self._SCREENS:
                screen = ""
            task = str(obj.get("task", "") or "").strip()
            raw_facts = obj.get("facts", []) or []
            facts = [str(f).strip() for f in raw_facts if str(f).strip()] \
                if isinstance(raw_facts, list) else []
            name = str(obj.get("name", "") or "").strip()
            notes_query = str(obj.get("notes_query", "") or "").strip()
            notes_write = self._parse_notes_write(obj.get("notes_write"))
            power = self._parse_power(obj.get("power"))
            pending = notes_query or notes_write
            return (msg or ("" if pending else _strip_emoji(content))), \
                screen, task, facts, name, notes_query, notes_write, power
        return _strip_emoji(content), "", "", [], "", "", None, None
