"""Painel web do BMO — sobe sozinho num localhost temático.

Um servidor HTTP leve (em thread daemon, igual ao PairingServer) que serve o
painel do BMO (SPA Vite+Preact buildada no PC -> `bmo_os/webui_dist/`) onde o
dono, do navegador do PC/celular na mesma rede, pode controlar TUDO:

  - CONVERSAR      — falar com o BMO por texto (mesmo caminho do push-to-talk)
  - AJUSTES        — TODAS as configurações (mesmas do SETTINGS na telinha)
  - ESPAÇO INTERNO — humor/energia/afeto/streak + o que ele lembra de você
  - CÉREBRO        — RAG do Obsidian (notas, ligações, busca, última consulta)
  - CÂMERA         — feed ao vivo (MJPEG) da câmera do BMO
  - TAREFAS        — o Kanban (Todoist): listar / criar / mover
  - AGENDA         — eventos de hoje (Google Calendar)
  - CASA           — tomadas smart (liga/desliga/toggle)
  - MIC            — aciona o microfone do aparelho (push-to-talk remoto)
  - ATUALIZAR      — git reset --hard origin/main + restart, igual à telinha

O front é 100% estático (build no PC) e os dados sobem por fetch(/api/...). Sem
dependência externa no Pi (http.server da stdlib) e sem CDN — funciona offline.

Endpoints (GET):
    /                     -> a SPA (index.html do build); fallback p/ SPA
    /assets/*             -> assets do build (js/css/img/fontes)
    /api/state            -> snapshot do espaço interno (pet/memória/sistema/cérebro)
    /api/config           -> esquema das configs editáveis + valores atuais
    /api/brain            -> snapshot do cérebro (RAG) + última consulta
    /api/brain/search?q=  -> roda knowledge.search pro painel
    /api/tasks            -> colunas do Kanban (Todoist)
    /api/agenda           -> eventos de hoje (Calendar)
    /api/smarthome        -> estado das tomadas smart
    /api/camera/stream    -> MJPEG multipart (feed ao vivo)
    /api/camera/snapshot  -> 1 frame JPEG
Endpoints (POST):
    /api/chat             -> {"text"} conversa com o BMO (bloqueia até o LLM)
    /api/config           -> {"key","value"} aplica uma config
    /api/memory           -> edita a memória ({"action": set_name|add_fact|del_fact|clear})
    /api/tasks            -> {"action": create|move, ...}
    /api/smarthome        -> {"action": set|toggle|all, "key", "on"}
    /api/mic              -> {"action": start|stop} push-to-talk remoto
    /api/update           -> baixa a última versão do git e reinicia

Segurança: bind em 0.0.0.0 (pra abrir do PC), mesmo modelo de confiança da
rede local da casa que o PairingServer já adota. Porta via BMO_WEB_PORT.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..core import config

DEFAULT_PORT = int(os.environ.get("BMO_WEB_PORT", "8000") or "8000")

# Build estático da SPA (Vite+Preact), gerado no PC e commitado no repo pra o
# Pi servir sem Node. Ver ai-chat-refresh (fonte) -> `bun run build`.
WEBUI_DIST = config.REPO_ROOT / "bmo_os" / "webui_dist"

# Fonte pixel opcional (legado): alguns assets antigos pediam /assets/font.
FONT_PATH = config.REPO_ROOT / "bmo_os" / "assets" / "fonts" / "PressStart2P.ttf"

# Tipos de conteúdo dos arquivos estáticos do build.
_CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}

_FALLBACK_HTML = (
    b"<!doctype html><meta charset=utf-8>"
    b"<body style='font-family:monospace;background:#0a0a0a;color:#10b981;padding:40px'>"
    b"<h1>BMO // painel nao buildado</h1>"
    b"<p>Rode <code>bun install &amp;&amp; bun run build</code> em "
    b"<code>ai-chat-refresh</code> para gerar <code>bmo_os/webui_dist/</code>.</p></body>"
)


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
            {"key": "briefing_enabled", "label": "Briefing diário", "type": "toggle",
             "value": bool(config.get("briefing_enabled"))},
            {"key": "briefing_time", "label": "Hora do briefing", "type": "select",
             "value": config.get("briefing_time"),
             "options": [{"value": t, "label": t} for t in config.BRIEFING_TIME_OPTIONS]},
        ]},
        {"group": "IA", "items": [
            {"key": "llm_provider", "label": "Provedor (chat)", "type": "select",
             "value": provider, "options": _opts(config.LLM_PROVIDERS, config.LLM_PROVIDER_LABELS)},
            # combo: digite QUALQUER nome de modelo (vale na hora) ou escolha um
            # preset da lista. O que for digitado vira o "personalizado" e
            # aparece no cycler do device junto dos presets.
            {"key": model_key, "label": "Modelo (chat)", "type": "combo",
             "value": config.get(model_key),
             "placeholder": "digite o modelo ou escolha um preset",
             "options": [{"value": m, "label": m} for m in config.LLM_MODELS.get(provider, [])]},
            # LLM no PC (llama.cpp/Ollama): host/URL editável. Vazio = padrão
            # llama.cpp no mesmo PC (127.0.0.1:8080). Só relevante p/ provedor LOCAL.
            {"key": "local_llm_url", "label": "LLM local (host/URL)", "type": "text",
             "value": config.get("local_llm_url") or "",
             "placeholder": "vazio = 127.0.0.1:8080 (llama.cpp)"},
            {"key": "vision_provider", "label": "Provedor (visão)", "type": "select",
             "value": vprovider, "options": _opts(config.LLM_PROVIDERS, config.LLM_PROVIDER_LABELS)},
            {"key": vmodel_key, "label": "Modelo (visão)", "type": "combo",
             "value": config.get(vmodel_key),
             "placeholder": "modelo multimodal — digite ou escolha um preset",
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
    o resto. Quem mexe em estado da UI (abrir tela / atualizar) já enfileira
    pro main thread lá no main.py (mesma ponte do chat remoto)."""

    def __init__(self, *, on_chat=None, get_state=None, list_mics=None,
                 on_set_config=None, on_memory=None, get_brain=None,
                 on_brain_search=None, on_brain_note=None, camera=None, on_mic=None,
                 get_tasks=None, on_tasks=None, get_agenda=None, on_agenda_create=None,
                 get_smarthome=None, on_smarthome=None, on_update=None,
                 get_notifications=None, on_notification_read=None,
                 port: int | None = None) -> None:
        self.on_chat = on_chat
        self.get_state = get_state
        self.list_mics = list_mics or (lambda: [])
        self.on_set_config = on_set_config
        self.on_memory = on_memory
        self.get_brain = get_brain            # snapshot do cérebro (RAG/notas)
        self.on_brain_search = on_brain_search  # roda knowledge.search pro painel
        self.on_brain_note = on_brain_note    # conteúdo integral de 1 nota (.md)
        self.camera = camera                  # serviço de câmera (acquire/jpeg/release)
        self.on_mic = on_mic                  # push-to-talk remoto (start/stop)
        self.get_tasks = get_tasks            # snapshot do Kanban (Todoist)
        self.on_tasks = on_tasks              # create/move tarefa
        self.get_agenda = get_agenda          # eventos de hoje (Calendar)
        self.on_agenda_create = on_agenda_create  # cria evento na agenda (pessoal)
        self.get_smarthome = get_smarthome    # estado das tomadas
        self.on_smarthome = on_smarthome      # liga/desliga/toggle
        self.on_update = on_update            # git update + restart
        self.get_notifications = get_notifications      # central de lembretes (aba HOJE)
        self.on_notification_read = on_notification_read  # marca aviso(s) como lido
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
                if path == "/api/state":
                    self._api_state()
                elif path == "/api/config":
                    self._send(200, {"groups": _config_schema(srv.list_mics)})
                elif path == "/api/brain":
                    self._call_get(srv.get_brain, "cerebro")
                elif path == "/api/brain/search":
                    self._api_brain_search()
                elif path == "/api/brain/note":
                    self._api_brain_note()
                elif path == "/api/tasks":
                    self._call_get(srv.get_tasks, "tarefas")
                elif path == "/api/agenda":
                    self._call_get(srv.get_agenda, "agenda")
                elif path == "/api/smarthome":
                    self._call_get(srv.get_smarthome, "casa")
                elif path == "/api/notifications":
                    self._call_get(srv.get_notifications, "avisos")
                elif path == "/api/camera/stream":
                    self._api_camera_stream()
                elif path == "/api/camera/snapshot":
                    self._api_camera_snapshot()
                elif path == "/assets/font":
                    self._serve_font()
                elif path.startswith("/api/"):
                    self._send(404, {"error": "not found"})
                else:
                    self._serve_static(path)

            # ---------- POST ----------
            def do_POST(self) -> None:
                path = self.path.split("?", 1)[0]
                if path == "/api/chat":
                    self._api_chat()
                elif path == "/api/config":
                    self._api_config()
                elif path == "/api/memory":
                    self._call_post(srv.on_memory, "memoria")
                elif path == "/api/tasks":
                    self._call_post(srv.on_tasks, "tarefas")
                elif path == "/api/agenda":
                    self._call_post(srv.on_agenda_create, "agenda")
                elif path == "/api/smarthome":
                    self._call_post(srv.on_smarthome, "casa")
                elif path == "/api/notifications/read":
                    self._call_post(srv.on_notification_read, "avisos")
                elif path == "/api/mic":
                    self._api_mic()
                elif path == "/api/update":
                    self._api_update()
                else:
                    self._send(404, {"error": "not found"})

            # ---------- estáticos ----------
            def _serve_static(self, path: str) -> None:
                rel = path.lstrip("/")
                if not rel or rel.endswith("/"):
                    rel = "index.html"
                try:
                    base = WEBUI_DIST.resolve()
                    target = (WEBUI_DIST / rel).resolve()
                    target.relative_to(base)          # barra path traversal
                except (ValueError, OSError):
                    self._send(404, {"error": "not found"})
                    return
                if not target.is_file():
                    # SPA fallback: rota desconhecida -> index.html
                    target = WEBUI_DIST / "index.html"
                    if not target.is_file():
                        self._send(503, _FALLBACK_HTML, "text/html; charset=utf-8", raw=True)
                        return
                ctype = _CTYPES.get(target.suffix.lower(), "application/octet-stream")
                try:
                    self._send(200, target.read_bytes(), ctype, raw=True)
                except Exception:
                    self._send(500, {"error": "io"})

            def _serve_font(self) -> None:
                try:
                    if FONT_PATH.exists():
                        self._send(200, FONT_PATH.read_bytes(), "font/ttf", raw=True)
                        return
                except Exception:
                    pass
                self._send(404, {"error": "sem fonte"})

            # ---------- helpers genéricos de API ----------
            def _call_get(self, fn, name: str) -> None:
                if fn is None:
                    self._send(503, {"error": name + " indisponivel"})
                    return
                try:
                    self._send(200, fn() or {})
                except Exception as e:
                    self._send(500, {"error": str(e)[:80]})

            def _call_post(self, fn, name: str) -> None:
                if fn is None:
                    self._send(503, {"error": name + " indisponivel"})
                    return
                try:
                    data = self._read_json()
                except Exception:
                    self._send(400, {"error": "payload invalido"})
                    return
                try:
                    self._send(200, fn(data) or {})
                except Exception as e:
                    self._send(500, {"error": str(e)[:80]})

            def _api_state(self) -> None:
                self._call_get(srv.get_state, "estado")

            def _api_brain_search(self) -> None:
                if srv.on_brain_search is None:
                    self._send(503, {"error": "busca indisponivel"})
                    return
                q = (parse_qs(urlparse(self.path).query).get("q", [""]) or [""])[0]
                try:
                    self._send(200, srv.on_brain_search(q) or {})
                except Exception as e:
                    self._send(500, {"error": str(e)[:80]})

            def _api_brain_note(self) -> None:
                if srv.on_brain_note is None:
                    self._send(503, {"error": "nota indisponivel"})
                    return
                nid = (parse_qs(urlparse(self.path).query).get("id", [""]) or [""])[0]
                try:
                    self._send(200, srv.on_brain_note(nid) or {})
                except Exception as e:
                    self._send(500, {"error": str(e)[:80]})

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

            def _api_mic(self) -> None:
                if srv.on_mic is None:
                    self._send(503, {"error": "mic indisponivel"})
                    return
                try:
                    action = str(self._read_json().get("action", "")).strip()
                except Exception:
                    self._send(400, {"error": "payload invalido"})
                    return
                try:
                    self._send(200, srv.on_mic(action) or {})
                except Exception as e:
                    self._send(500, {"error": str(e)[:80]})

            def _api_update(self) -> None:
                if srv.on_update is None:
                    self._send(503, {"error": "update indisponivel"})
                    return
                try:
                    self._send(200, srv.on_update() or {})
                except Exception as e:
                    self._send(500, {"error": str(e)[:80]})

            # ---------- câmera ----------
            def _camera_or_503(self):
                cam = srv.camera
                if cam is None or not getattr(cam, "is_available", False):
                    self._send(503, {"error": "camera indisponivel"})
                    return None
                return cam

            def _api_camera_snapshot(self) -> None:
                cam = self._camera_or_503()
                if cam is None:
                    return
                jpg = None
                try:
                    cam.acquire()
                    for _ in range(20):            # espera a câmera esquentar
                        jpg = cam.capture_jpeg(quality=75)
                        if jpg:
                            break
                        time.sleep(0.05)
                finally:
                    try:
                        cam.release()
                    except Exception:
                        pass
                if not jpg:
                    self._send(503, {"error": "sem frame"})
                    return
                self._send(200, jpg, "image/jpeg", raw=True)

            def _api_camera_stream(self) -> None:
                cam = self._camera_or_503()
                if cam is None:
                    return
                boundary = "bmoframe"
                try:
                    cam.acquire()
                except Exception:
                    self._send(503, {"error": "camera off"})
                    return
                try:
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        f"multipart/x-mixed-replace; boundary={boundary}")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    bnd = ("--" + boundary + "\r\n").encode()
                    while True:
                        jpg = cam.capture_jpeg(quality=70)
                        if jpg:
                            self.wfile.write(bnd)
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(
                                ("Content-Length: %d\r\n\r\n" % len(jpg)).encode())
                            self.wfile.write(jpg)
                            self.wfile.write(b"\r\n")
                        time.sleep(0.1)            # ~10 fps: economiza CPU/calor
                except Exception:
                    pass                           # cliente fechou a aba
                finally:
                    try:
                        cam.release()
                    except Exception:
                        pass

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
