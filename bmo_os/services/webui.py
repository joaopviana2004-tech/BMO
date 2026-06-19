"""Painel web do BMO — sobe sozinho num localhost temático.

Um servidor HTTP leve (em thread daemon, igual ao PairingServer) que serve um
site com a carinha do BMO onde o dono, do navegador do PC/celular na mesma
rede, pode:

  - AJUSTES        — mexer nas configurações (mesmas do SETTINGS na telinha)
  - ESPAÇO INTERNO — espiar o "mundo interno" do BMO: humor/energia/afeto/streak,
                     o que ele lembra de você (nome + fatos) e a telemetria da Pi
  - CONVERSAR      — falar com o BMO por texto (mesmo caminho do push-to-talk:
                     o LLM responde, pode abrir telas/criar tarefas e FALAR no
                     próprio aparelho)

Tudo é estático + uma API JSON: a página não interpola nada no servidor (sem
.format no HTML), os dados descem por fetch(/api/...). Sem dependência externa
(http.server da stdlib) e sem CDN — funciona offline no Pi.

Endpoints:
    GET  /                -> a página (SPA temática)
    GET  /assets/font     -> a fonte pixel (se existir em assets/fonts), senão 404
    GET  /api/state       -> snapshot do espaço interno (pet/memória/sistema/cérebro)
    GET  /api/config      -> esquema das configs editáveis + valores atuais
    POST /api/config      -> {"key","value"} aplica uma config (espelha o SETTINGS)
    POST /api/chat        -> {"text"} conversa com o BMO (bloqueia até o LLM)
    POST /api/memory      -> edita a memória ({"action": set_name|add_fact|clear})

Segurança: bind em 0.0.0.0 (pra abrir do PC), mesmo modelo de confiança da
rede local da casa que o PairingServer já adota. Porta via BMO_WEB_PORT.
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..core import config

DEFAULT_PORT = int(os.environ.get("BMO_WEB_PORT", "8000") or "8000")

# Fonte pixel opcional (mesma que a telinha usa). Serve via @font-face; sem ela
# o CSS cai num monospace e o site continua funcionando.
FONT_PATH = config.REPO_ROOT / "bmo_os" / "assets" / "fonts" / "PressStart2P.ttf"


# ============================================================
# Esquema das configurações (espelha as categorias do SETTINGS)
# ============================================================

def _pct_opts(values):
    return [{"value": v, "label": f"{v}%"} for v in values]


def _opts(values, labels=None):
    labels = labels or {}
    return [{"value": v, "label": labels.get(v, str(v).upper())} for v in values]


def _config_schema(list_mics) -> list:
    """Monta os grupos de config que o painel renderiza. As chaves de modelo
    dependem do provedor ativo (ex.: openrouter_model / nvidia_vision_model),
    então resolvemos aqui — o front só manda {key, value} de volta."""
    provider = config.get("llm_provider")
    vprovider = config.get("vision_provider")
    model_key = f"{provider}_model"
    vmodel_key = f"{vprovider}_vision_model"

    mics = [{"value": "", "label": "(padrão)"}]
    try:
        mics += [{"value": m, "label": m} for m in (list_mics() or [])]
    except Exception:
        pass

    return [
        {"group": "SOM", "items": [
            {"key": "volume", "label": "Volume", "type": "select",
             "value": config.get("volume"), "options": _pct_opts(config.VOLUME_OPTIONS)},
        ]},
        {"group": "TELA", "items": [
            {"key": "brightness", "label": "Brilho", "type": "select",
             "value": config.get("brightness"), "options": _pct_opts(config.BRIGHTNESS_OPTIONS)},
            {"key": "theme", "label": "Tema", "type": "select", "value": config.get("theme"),
             "options": [{"value": "auto", "label": "AUTO"},
                         {"value": "dark", "label": "ESCURO"},
                         {"value": "light", "label": "CLARO"}]},
        ]},
        {"group": "SISTEMA", "items": [
            {"key": "idle_timeout_s", "label": "Standby", "type": "select",
             "value": config.get("idle_timeout_s"),
             "options": [{"value": v, "label": f"{v}s"} for v in config.IDLE_TIMEOUT_OPTIONS]},
            {"key": "ambient_mode", "label": "Tela de descanso", "type": "select",
             "value": config.get("ambient_mode"),
             "options": _opts(config.AMBIENT_MODE_OPTIONS, config.AMBIENT_MODE_LABELS)},
            {"key": "event_warning_min", "label": "Aviso de evento", "type": "select",
             "value": config.get("event_warning_min"),
             "options": [{"value": v, "label": f"{v} min"} for v in config.EVENT_WARNING_OPTIONS]},
            {"key": "cooler_enabled", "label": "Coolers (manual)", "type": "toggle",
             "value": bool(config.get("cooler_enabled"))},
            {"key": "pet_proactive", "label": "BMO fala sozinho", "type": "toggle",
             "value": bool(config.get("pet_proactive"))},
        ]},
        {"group": "IA", "items": [
            {"key": "llm_provider", "label": "Provedor (chat)", "type": "select",
             "value": provider, "options": _opts(config.LLM_PROVIDERS, config.LLM_PROVIDER_LABELS)},
            {"key": model_key, "label": "Modelo (chat)", "type": "select",
             "value": config.get(model_key),
             "options": [{"value": m, "label": m} for m in config.LLM_MODELS.get(provider, [])]},
            {"key": "vision_provider", "label": "Provedor (visão)", "type": "select",
             "value": vprovider, "options": _opts(config.LLM_PROVIDERS, config.LLM_PROVIDER_LABELS)},
            {"key": vmodel_key, "label": "Modelo (visão)", "type": "select",
             "value": config.get(vmodel_key),
             "options": [{"value": m, "label": m} for m in config.LLM_VISION_MODELS.get(vprovider, [])]},
            {"key": "voice_enabled", "label": "BMO me ouve", "type": "toggle",
             "value": bool(config.get("voice_enabled"))},
            {"key": "mic_button_enabled", "label": "Botão de fala", "type": "toggle",
             "value": bool(config.get("mic_button_enabled"))},
            {"key": "mic_device", "label": "Microfone", "type": "select",
             "value": config.get("mic_device") or "", "options": mics},
            {"key": "tts_volume", "label": "Voz do BMO", "type": "select",
             "value": config.get("tts_volume"), "options": _pct_opts(config.VOLUME_OPTIONS)},
            {"key": "camera_face_tracking", "label": "BMO te vê", "type": "toggle",
             "value": bool(config.get("camera_face_tracking"))},
        ]},
    ]


# ============================================================
# Servidor
# ============================================================

class WebUIServer:
    """Painel web em thread daemon. Os callbacks rodam NA THREAD do request
    (cada request tem a sua), então on_chat pode bloquear no LLM sem travar
    o resto. Quem mexe em estado da UI (abrir tela) já enfileira pro main
    thread lá no main.py (mesma ponte do chat remoto)."""

    def __init__(self, *, on_chat=None, get_state=None, list_mics=None,
                 on_set_config=None, on_memory=None, port: int | None = None) -> None:
        self.on_chat = on_chat
        self.get_state = get_state
        self.list_mics = list_mics or (lambda: [])
        self.on_set_config = on_set_config
        self.on_memory = on_memory
        self.port = port or DEFAULT_PORT
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def url(self) -> str:
        return f"http://localhost:{self.port}"

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:   # sem ruído no stdout
                pass

            def _send(self, code, body, ctype="application/json", raw=False):
                data = body if raw else json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except Exception:
                    pass

            def _read_json(self) -> dict:
                n = int(self.headers.get("Content-Length", "0") or "0")
                if n <= 0:
                    return {}
                return json.loads(self.rfile.read(n) or b"{}")

            # ---------- GET ----------
            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8", raw=True)
                elif path == "/assets/font":
                    self._serve_font()
                elif path == "/api/state":
                    self._api_state()
                elif path == "/api/config":
                    self._send(200, {"groups": _config_schema(srv.list_mics)})
                else:
                    self._send(404, {"error": "not found"})

            def _serve_font(self) -> None:
                try:
                    if FONT_PATH.exists():
                        self._send(200, FONT_PATH.read_bytes(), "font/ttf", raw=True)
                        return
                except Exception:
                    pass
                self._send(404, {"error": "sem fonte"})

            def _api_state(self) -> None:
                if srv.get_state is None:
                    self._send(503, {"error": "estado indisponivel"})
                    return
                try:
                    self._send(200, srv.get_state() or {})
                except Exception as e:
                    self._send(500, {"error": str(e)[:80]})

            # ---------- POST ----------
            def do_POST(self) -> None:
                path = self.path.split("?", 1)[0]
                if path == "/api/chat":
                    self._api_chat()
                elif path == "/api/config":
                    self._api_config()
                elif path == "/api/memory":
                    self._api_memory()
                else:
                    self._send(404, {"error": "not found"})

            def _api_chat(self) -> None:
                if srv.on_chat is None:
                    self._send(503, {"error": "chat indisponivel"})
                    return
                try:
                    text = str(self._read_json().get("text", "")).strip()
                    assert text
                except Exception:
                    self._send(400, {"error": "texto vazio"})
                    return
                try:
                    self._send(200, srv.on_chat(text) or {})   # bloqueia até o LLM
                except Exception as e:
                    self._send(500, {"error": str(e)[:80]})

            def _api_config(self) -> None:
                if srv.on_set_config is None:
                    self._send(503, {"error": "config indisponivel"})
                    return
                try:
                    data = self._read_json()
                    key = str(data.get("key", "")).strip()
                    assert key
                except Exception:
                    self._send(400, {"error": "payload invalido"})
                    return
                try:
                    self._send(200, srv.on_set_config(key, data.get("value")) or {})
                except Exception as e:
                    self._send(500, {"error": str(e)[:80]})

            def _api_memory(self) -> None:
                if srv.on_memory is None:
                    self._send(503, {"error": "memoria indisponivel"})
                    return
                try:
                    data = self._read_json()
                except Exception:
                    self._send(400, {"error": "payload invalido"})
                    return
                try:
                    self._send(200, srv.on_memory(data) or {})
                except Exception as e:
                    self._send(500, {"error": str(e)[:80]})

        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        except OSError:
            return False   # porta ocupada (outra instância) — segue sem painel
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            self._httpd = None


# ============================================================
# A página (estática; todo dado dinâmico vem por fetch /api/*)
# ============================================================

PAGE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta name="theme-color" content="#0e2724">
<title>BMO</title>
<style>
  @font-face{ font-family:'BMOPixel'; src:url('/assets/font') format('truetype'); font-display:swap; }
  :root{
    --teal:#54bfae; --teal-d:#3a9c8d; --ink:#143029; --mint:#cdeede; --mint-d:#a9dcc9;
    --bg:#0e2724; --red:#e0533d; --blue:#4a7fd0; --green:#62b24b; --yellow:#f2c64c;
    --pix:'BMOPixel', ui-monospace, 'Consolas', monospace;
  }
  *{ box-sizing:border-box; }
  html,body{ margin:0; height:100%; }
  body{
    background:
      radial-gradient(circle at 50% -10%, #18423b 0%, var(--bg) 60%),
      var(--bg);
    color:var(--ink); font-family:var(--pix); letter-spacing:.5px;
    -webkit-font-smoothing:none; image-rendering:pixelated;
    display:flex; justify-content:center; padding:18px 12px 40px;
  }
  .device{
    width:min(560px,100%); background:linear-gradient(180deg,var(--teal),var(--teal-d));
    border:5px solid var(--ink); border-radius:26px;
    box-shadow:0 14px 0 rgba(0,0,0,.25), inset 0 4px 0 rgba(255,255,255,.25);
    padding:18px 16px 22px;
  }
  /* --- cabeçalho: a carinha do BMO --- */
  .head{ display:flex; gap:14px; align-items:center; }
  .screen{
    flex:0 0 128px; height:96px; background:var(--mint);
    border:4px solid var(--ink); border-radius:14px; position:relative; overflow:hidden;
    box-shadow:inset 0 0 0 3px var(--mint-d);
  }
  .screen svg{ position:absolute; inset:0; width:100%; height:100%; }
  .zzz{ position:absolute; right:8px; top:6px; font-size:11px; color:var(--ink); opacity:.7; }
  .head .meta{ flex:1; }
  .head h1{ margin:0; font-size:26px; color:var(--ink); text-shadow:2px 2px 0 rgba(255,255,255,.3); }
  .chip{
    display:inline-block; margin-top:8px; background:var(--ink); color:var(--mint);
    font-size:10px; padding:5px 9px; border-radius:8px;
  }
  /* --- abas (botões do BMO) --- */
  .tabs{ display:flex; gap:8px; margin:18px 0 14px; }
  .tabs button{
    flex:1; font-family:var(--pix); font-size:10px; color:var(--ink); cursor:pointer;
    background:var(--mint); border:3px solid var(--ink); border-radius:12px;
    padding:11px 6px; box-shadow:0 4px 0 rgba(0,0,0,.25); transition:transform .05s;
  }
  .tabs button:active{ transform:translateY(2px); box-shadow:0 2px 0 rgba(0,0,0,.25); }
  .tabs button.on{ background:var(--yellow); }
  .tabs button .dot{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:5px; border:2px solid var(--ink); vertical-align:-1px; }
  .panel{
    background:var(--mint); border:4px solid var(--ink); border-radius:16px;
    padding:14px; min-height:280px;
  }
  .hidden{ display:none !important; }
  h2{ font-size:12px; margin:2px 0 12px; color:var(--ink); }
  .muted{ color:#4f6b62; font-size:10px; }

  /* --- AJUSTES --- */
  .grp{ margin-bottom:16px; }
  .grp .gtitle{ font-size:10px; color:var(--teal-d); border-bottom:2px dashed var(--ink); padding-bottom:4px; margin-bottom:8px; }
  .row{ display:flex; align-items:center; gap:8px; margin:7px 0; }
  .row .lbl{ flex:1; font-size:10px; }
  select, input[type=text]{
    font-family:var(--pix); font-size:10px; color:var(--ink); background:#fff;
    border:3px solid var(--ink); border-radius:8px; padding:6px 8px; max-width:62%;
  }
  .tog{ width:54px; height:26px; border:3px solid var(--ink); border-radius:13px; background:#c14b3a; position:relative; cursor:pointer; }
  .tog.on{ background:var(--green); }
  .tog::after{ content:''; position:absolute; top:1px; left:1px; width:18px; height:18px; border-radius:50%; background:#fff; border:2px solid var(--ink); transition:left .12s; }
  .tog.on::after{ left:27px; }

  /* --- ESPAÇO INTERNO --- */
  .cards{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  .card{ background:#fff; border:3px solid var(--ink); border-radius:12px; padding:10px; }
  .card.full{ grid-column:1 / -1; }
  .card .k{ font-size:9px; color:var(--teal-d); }
  .card .v{ font-size:18px; margin-top:3px; }
  .bar{ height:10px; border:2px solid var(--ink); border-radius:6px; background:#e7f4ee; margin-top:7px; overflow:hidden; }
  .bar > i{ display:block; height:100%; background:var(--teal); }
  .facts{ list-style:none; margin:6px 0 0; padding:0; }
  .facts li{ font-size:10px; background:#eef8f2; border:2px solid var(--ink); border-radius:8px; padding:5px 7px; margin:5px 0; display:flex; justify-content:space-between; gap:6px; }
  .facts li button{ border:none; background:var(--red); color:#fff; border-radius:5px; cursor:pointer; font-family:var(--pix); font-size:9px; padding:2px 6px; }
  .mini{ display:flex; gap:6px; margin-top:8px; }
  .mini input{ flex:1; max-width:none; }
  .btn{ font-family:var(--pix); font-size:10px; color:#fff; background:var(--ink); border:none; border-radius:8px; padding:8px 10px; cursor:pointer; box-shadow:0 3px 0 rgba(0,0,0,.3); }
  .btn:active{ transform:translateY(2px); box-shadow:0 1px 0 rgba(0,0,0,.3); }
  .btn.red{ background:var(--red); }
  .btn.green{ background:var(--green); }

  /* --- CONVERSAR --- */
  #log{ height:300px; overflow-y:auto; display:flex; flex-direction:column; gap:8px; padding:4px; }
  .msg{ max-width:82%; font-size:11px; padding:8px 10px; border:3px solid var(--ink); border-radius:12px; line-height:1.45; word-wrap:break-word; }
  .msg.me{ align-self:flex-end; background:var(--blue); color:#fff; }
  .msg.bmo{ align-self:flex-start; background:#fff; }
  .msg.sys{ align-self:center; background:transparent; border:none; color:#4f6b62; font-size:9px; }
  .composer{ display:flex; gap:8px; margin-top:10px; }
  .composer input{ flex:1; max-width:none; }
  .composer .btn{ background:var(--green); }
</style>
</head>
<body>
<div class="device">
  <div class="head">
    <div class="screen"><svg id="face" viewBox="0 0 128 96"></svg><span id="zzz" class="zzz hidden">z z z</span></div>
    <div class="meta">
      <h1>BMO</h1>
      <span id="chip" class="chip">conectando...</span>
    </div>
  </div>

  <div class="tabs">
    <button id="tab-chat" class="on" onclick="showTab('chat')"><span class="dot" style="background:var(--green)"></span>CONVERSAR</button>
    <button id="tab-estado" onclick="showTab('estado')"><span class="dot" style="background:var(--blue)"></span>ESPAÇO INTERNO</button>
    <button id="tab-ajustes" onclick="showTab('ajustes')"><span class="dot" style="background:var(--red)"></span>AJUSTES</button>
  </div>

  <!-- CONVERSAR -->
  <div id="panel-chat" class="panel">
    <div id="log"><div class="msg sys">Fale com o BMO — ele responde, abre telas e cria tarefas.</div></div>
    <div class="composer">
      <input id="chatInput" type="text" placeholder="Escreva pro BMO..." onkeydown="if(event.key==='Enter')sendChat()">
      <button class="btn" onclick="sendChat()">ENVIAR</button>
    </div>
  </div>

  <!-- ESPAÇO INTERNO -->
  <div id="panel-estado" class="panel hidden">
    <h2>MUNDO INTERNO</h2>
    <div class="cards" id="petCards"></div>
    <div class="card full" style="margin-top:10px">
      <div class="k">O QUE O BMO LEMBRA DE VOCÊ</div>
      <div class="mini">
        <input id="nameInput" type="text" placeholder="seu nome">
        <button class="btn green" onclick="saveName()">SALVAR</button>
      </div>
      <ul id="facts" class="facts"></ul>
      <div class="mini">
        <input id="factInput" type="text" placeholder="ensinar um fato (ex: gosto de café)" onkeydown="if(event.key==='Enter')addFact()">
        <button class="btn" onclick="addFact()">+ FATO</button>
      </div>
      <button class="btn red" style="margin-top:8px" onclick="clearMem()">ESQUECER TUDO</button>
    </div>
    <div class="card full" style="margin-top:10px">
      <div class="k">TELEMETRIA DA PI</div>
      <div id="sys" class="muted" style="margin-top:6px">--</div>
    </div>
  </div>

  <!-- AJUSTES -->
  <div id="panel-ajustes" class="panel hidden">
    <h2>AJUSTES</h2>
    <div id="cfg"><span class="muted">carregando...</span></div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
let TAB = 'chat';

async function api(path, opts){
  try{ const r = await fetch(path, opts); return await r.json(); }
  catch(e){ return {error:'sem conexão com o BMO'}; }
}

function showTab(name){
  TAB = name;
  for(const t of ['chat','estado','ajustes']){
    $('#panel-'+t).classList.toggle('hidden', t!==name);
    $('#tab-'+t).classList.toggle('on', t===name);
  }
  if(name==='estado') refreshState();
  if(name==='ajustes') refreshConfig();
}

/* ---------- carinha do BMO ---------- */
const MOOD_PT = { loving:'apaixonado', excited:'animado', happy:'feliz',
  sleepy:'sonolento', lonely:'carente', bored:'entediado', neutral:'neutro' };

function faceSVG(mood){
  const eyeY = 40, lx = 42, rx = 86;
  let eyes, mouth;
  const dotEye = (x)=>`<circle cx="${x}" cy="${eyeY}" r="7" fill="#143029"/>`;
  const arcEye = (x)=>`<path d="M${x-9} ${eyeY+3} Q${x} ${eyeY-9} ${x+9} ${eyeY+3}" stroke="#143029" stroke-width="5" fill="none" stroke-linecap="round"/>`;
  const lineEye = (x)=>`<rect x="${x-9}" y="${eyeY-1}" width="18" height="4" rx="2" fill="#143029"/>`;
  const bigEye = (x)=>`<circle cx="${x}" cy="${eyeY}" r="9" fill="#143029"/><circle cx="${x+3}" cy="${eyeY-3}" r="2.4" fill="#cdeede"/>`;
  const smile = `<path d="M48 64 Q64 78 80 64" stroke="#143029" stroke-width="5" fill="none" stroke-linecap="round"/>`;
  const bigSmile = `<path d="M44 62 Q64 84 84 62" stroke="#143029" stroke-width="5" fill="none" stroke-linecap="round"/>`;
  const flat = `<rect x="52" y="66" width="24" height="4" rx="2" fill="#143029"/>`;
  const openMouth = `<ellipse cx="64" cy="67" rx="11" ry="8" fill="#143029"/>`;
  const smallMouth = `<rect x="58" y="66" width="12" height="3.5" rx="1.5" fill="#143029"/>`;
  switch(mood){
    case 'loving':  eyes=arcEye(lx)+arcEye(rx); mouth=bigSmile; break;
    case 'excited': eyes=bigEye(lx)+bigEye(rx); mouth=openMouth; break;
    case 'sleepy':  eyes=lineEye(lx)+lineEye(rx); mouth=smallMouth; break;
    case 'lonely':  eyes=dotEye(lx)+dotEye(rx); mouth=`<path d="M50 70 Q64 60 78 70" stroke="#143029" stroke-width="5" fill="none" stroke-linecap="round"/>`; break;
    case 'bored':   eyes=lineEye(lx)+lineEye(rx); mouth=flat; break;
    case 'neutral': eyes=dotEye(lx)+dotEye(rx); mouth=flat; break;
    default:        eyes=dotEye(lx)+dotEye(rx); mouth=smile;
  }
  return eyes + mouth;
}
function setFace(mood){
  $('#face').innerHTML = faceSVG(mood||'happy');
  $('#zzz').classList.toggle('hidden', mood!=='sleepy');
}

/* ---------- ESPAÇO INTERNO ---------- */
function pct(x){ return Math.max(0, Math.min(100, Math.round(x))); }
function bar(label, value, sub){
  return `<div class="card"><div class="k">${label}</div><div class="v">${sub}</div>
    <div class="bar"><i style="width:${pct(value)}%"></i></div></div>`;
}
async function refreshState(){
  const s = await api('/api/state');
  if(s.error){ $('#chip').textContent = s.error; return; }
  const p = s.pet||{}, m = s.memory||{}, sy = s.sys||{}, k = s.knowledge||{};
  setFace(p.mood);
  let chip = 'humor: ' + (MOOD_PT[p.mood]||p.mood||'?');
  if(sy.temp!=null) chip += ' · ' + Math.round(sy.temp) + '°C';
  $('#chip').textContent = chip;

  $('#petCards').innerHTML =
    bar('AFETO', p.affection, (Math.round(p.affection||0)) + '/100') +
    bar('ENERGIA', (p.energy||0)*100, Math.round((p.energy||0)*100) + '%') +
    `<div class="card"><div class="k">STREAK</div><div class="v">${p.streak||0} dia(s)</div></div>` +
    `<div class="card"><div class="k">CÉREBRO</div><div class="v">${k.notes||0} nota(s)</div><div class="muted">${k.links||0} ligações</div></div>`;

  // memória (só sobrescreve os inputs se o usuário não estiver digitando)
  if(document.activeElement!==$('#nameInput')) $('#nameInput').value = m.name||'';
  $('#facts').innerHTML = (m.facts||[]).map((f,i)=>
    `<li><span>${escapeHtml(f)}</span><button onclick="delFact(${i})">x</button></li>`).join('')
    || '<li class="muted" style="border:none;background:none">ele ainda não sabe nada sobre você</li>';
  window._facts = m.facts||[];

  // telemetria
  const fmt = (v,suf)=> v==null ? '--' : (Math.round(v)+suf);
  $('#sys').innerHTML = sy.ok===false || sy.cpu==null && sy.temp==null
    ? 'rodando no PC (sem telemetria de hardware)'
    : `CPU ${fmt(sy.cpu,'%')} · TEMP ${fmt(sy.temp,'°C')} · RAM ${fmt(sy.ram_pct,'%')} · GPU ${fmt(sy.gpu,'%')}`;
}
function escapeHtml(s){ return (s||'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

async function saveName(){ await api('/api/memory',{method:'POST',headers:JSONH,body:JSON.stringify({action:'set_name',name:$('#nameInput').value})}); refreshState(); }
async function addFact(){ const f=$('#factInput').value.trim(); if(!f)return; $('#factInput').value=''; await api('/api/memory',{method:'POST',headers:JSONH,body:JSON.stringify({action:'add_fact',fact:f})}); refreshState(); }
async function delFact(i){ const f=(window._facts||[])[i]; await api('/api/memory',{method:'POST',headers:JSONH,body:JSON.stringify({action:'del_fact',fact:f})}); refreshState(); }
async function clearMem(){ if(!confirm('Apagar tudo que o BMO lembra de você?'))return; await api('/api/memory',{method:'POST',headers:JSONH,body:JSON.stringify({action:'clear'})}); refreshState(); }

/* ---------- AJUSTES ---------- */
const JSONH = {'Content-Type':'application/json'};
async function refreshConfig(){
  const c = await api('/api/config');
  if(c.error){ $('#cfg').innerHTML = '<span class="muted">'+c.error+'</span>'; return; }
  $('#cfg').innerHTML = (c.groups||[]).map(g=>{
    const rows = g.items.map(it=>{
      if(it.type==='toggle'){
        return `<div class="row"><span class="lbl">${it.label}</span>
          <div class="tog ${it.value?'on':''}" onclick="setCfg('${it.key}', ${!it.value}, this)"></div></div>`;
      }
      const opts = (it.options||[]).map(o=>
        `<option value="${attr(o.value)}" ${String(o.value)===String(it.value)?'selected':''}>${escapeHtml(o.label)}</option>`).join('');
      return `<div class="row"><span class="lbl">${it.label}</span>
        <select onchange="setCfg('${it.key}', this.value, this)">${opts}</select></div>`;
    }).join('');
    return `<div class="grp"><div class="gtitle">${g.group}</div>${rows}</div>`;
  }).join('');
}
function attr(s){ return escapeHtml(String(s)).replace(/'/g,'&#39;'); }
async function setCfg(key, value, el){
  const r = await api('/api/config',{method:'POST',headers:JSONH,body:JSON.stringify({key,value})});
  // provedor/modelo mudam as opções de outros campos -> recarrega o esquema todo
  await refreshConfig();
  if(r && r.error) flashChip(r.error);
}

/* ---------- CONVERSAR ---------- */
function addMsg(cls, text){
  const d = document.createElement('div'); d.className='msg '+cls; d.textContent=text;
  $('#log').appendChild(d); $('#log').scrollTop = $('#log').scrollHeight; return d;
}
async function sendChat(){
  const inp = $('#chatInput'); const text = inp.value.trim(); if(!text) return;
  inp.value=''; addMsg('me', text);
  const thinking = addMsg('sys', 'BMO pensando...');
  const r = await api('/api/chat',{method:'POST',headers:JSONH,body:JSON.stringify({text})});
  thinking.remove();
  if(r.error){ addMsg('sys', '⚠ '+r.error); return; }
  if(r.msg) addMsg('bmo', r.msg);
  const extra = [];
  if(r.screen && r.screen!=='none' && r.screen!=='') extra.push('abriu: '+r.screen);
  if(r.task) extra.push('tarefa criada: '+r.task);
  if(r.notes && r.notes.length) extra.push('nota salva');
  if(extra.length) addMsg('sys', extra.join(' · '));
  if(!r.msg && !extra.length) addMsg('bmo', '(ok)');
}

function flashChip(t){ const c=$('#chip'); const old=c.textContent; c.textContent=t; setTimeout(()=>c.textContent=old, 2500); }

/* ---------- boot ---------- */
setFace('happy');
refreshState();
setInterval(()=>{ if(TAB==='estado' || TAB==='chat') refreshState(); }, 4000);
</script>
</body>
</html>
"""
