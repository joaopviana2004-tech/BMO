"""Pareamento pelo PC — Drive COMPLETO pro Bimo.

O login por QR (device flow) é limitado pelo Google ao escopo drive.file
(o app só vê arquivos criados por ele mesmo). Pra o Bimo enxergar o Drive
INTEIRO (ex: a vault do Obsidian sincada pelo "Google Drive para Desktop"),
o caminho é parear pelo PC:

    PC: python scripts/bimo_drive_login.py <ip-do-bimo>
        -> abre o navegador, você loga com escopo completo do Drive
        -> o script manda os tokens pro Bimo pela rede local

    Bimo: este servidor (porta 8377) recebe POST /pair com
        {"user": {...}, "tokens": {...}} e chama on_pair(user, tokens).
        O main thread troca/atualiza a sessão e religa o DriveSync.

Segurança: rede local da casa, mesmo modelo de confiança do SSH que o dono
já usa. O servidor só aceita o POST /pair e morre junto com o processo.
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8377


def local_ip() -> str:
    """IP do Bimo na LAN (pra mostrar na tela de login). "" se sem rede."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))   # não envia nada; só resolve a rota
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


class PairingServer:
    """Servidor de pareamento em thread. on_pair(user, tokens) é chamado na
    THREAD DO SERVIDOR — quem registra deve enfileirar pro main thread."""

    def __init__(self, on_pair) -> None:
        self.on_pair = on_pair
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        on_pair = self.on_pair

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:   # sem ruído no stdout
                pass

            def _reply(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                self._reply(200, {"app": "bimo", "pair": "POST /pair"})

            def do_POST(self) -> None:
                if self.path != "/pair":
                    self._reply(404, {"error": "not found"})
                    return
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    data = json.loads(self.rfile.read(n))
                    user = data["user"]
                    tokens = data["tokens"]
                    assert user.get("sub") and tokens.get("refresh_token")
                except Exception:
                    self._reply(400, {"error": "payload invalido"})
                    return
                try:
                    on_pair(user, tokens)
                except Exception:
                    self._reply(500, {"error": "falha ao aplicar"})
                    return
                self._reply(200, {"ok": True,
                                  "msg": f"pareado como {user.get('email', '?')}"})

        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
        except OSError:
            return   # porta ocupada (outra instância); segue sem pareamento
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            self._httpd = None
