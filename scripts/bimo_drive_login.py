#!/usr/bin/env python3
"""Dá ao Bimo acesso COMPLETO ao seu Google Drive (pareamento pelo PC).

O login por QR Code na telinha usa o "device flow" do Google, que é limitado
ao escopo drive.file (o Bimo só vê o que ele mesmo criou). Este script faz o
login AQUI NO PC (navegador), com o escopo completo do Drive, e entrega os
tokens pro Bimo pela rede local. Depois disso o Bimo enxerga qualquer pasta
do seu Drive — inclusive a vault do Obsidian sincada pelo
"Google Drive para Desktop".

Uso (na raiz do repo):
    python scripts/bimo_drive_login.py 192.168.0.109
    python scripts/bimo_drive_login.py            # só salva local, não envia

Pré-requisito no .env (uma vez): credencial OAuth do tipo "App para
computador" (Desktop) no MESMO projeto do console.cloud.google.com:
    GOOGLE_DESKTOP_CLIENT_ID=...
    GOOGLE_DESKTOP_CLIENT_SECRET=...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bmo_os.core import config  # noqa: E402,F401  (carrega o .env)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
SCOPES = "openid email profile https://www.googleapis.com/auth/drive"
PAIR_PORT = 8377


def desktop_client() -> tuple[str, str]:
    cid = os.environ.get("GOOGLE_DESKTOP_CLIENT_ID", "").strip()
    csec = os.environ.get("GOOGLE_DESKTOP_CLIENT_SECRET", "").strip()
    if not (cid and csec):
        print("ERRO: defina GOOGLE_DESKTOP_CLIENT_ID e GOOGLE_DESKTOP_CLIENT_SECRET"
              " no .env.\nCrie em console.cloud.google.com -> Credenciais ->"
              " ID do cliente OAuth -> tipo 'App para computador'.")
        raise SystemExit(1)
    return cid, csec


def browser_login() -> dict:
    """Authorization code flow com loopback: navegador -> localhost -> tokens."""
    cid, csec = desktop_client()
    result: dict = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a) -> None:
            pass

        def do_GET(self) -> None:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result["code"] = (qs.get("code") or [""])[0]
            result["error"] = (qs.get("error") or [""])[0]
            body = ("<html><body style='font-family:sans-serif'>"
                    "<h2>Bimo conectado! Pode fechar esta aba.</h2>"
                    "</body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    redirect = f"http://127.0.0.1:{port}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    params = urllib.parse.urlencode({
        "client_id": cid,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",   # garante refresh_token
        "prompt": "consent",
    })
    url = f"{AUTH_URL}?{params}"
    print("Abrindo o navegador pra você autorizar (escopo: Drive completo)...")
    if not webbrowser.open(url):
        print(f"Abra manualmente:\n{url}")

    if not done.wait(timeout=300):
        print("ERRO: tempo esgotado esperando a autorizacao.")
        raise SystemExit(1)
    httpd.shutdown()
    if not result.get("code"):
        print(f"ERRO: autorizacao negada ({result.get('error') or '?'}).")
        raise SystemExit(1)

    body = urllib.parse.urlencode({
        "client_id": cid,
        "client_secret": csec,
        "code": result["code"],
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }).encode()
    with urllib.request.urlopen(
            urllib.request.Request(TOKEN_URL, data=body, method="POST"),
            timeout=20) as resp:
        tok = json.load(resp)

    req = urllib.request.Request(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {tok['access_token']}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        info = json.load(resp)

    user = {"sub": info.get("sub", ""),
            "email": info.get("email", ""),
            "name": info.get("name", "") or info.get("given_name", "")}
    # client embutido: o Bimo renova o token com a credencial que o emitiu
    tokens = {"access_token": tok.get("access_token", ""),
              "refresh_token": tok.get("refresh_token", ""),
              "expires_at": time.time() + int(tok.get("expires_in", 3600)),
              "scope": tok.get("scope", SCOPES),
              "client_id": cid,
              "client_secret": csec}
    return {"user": user, "tokens": tokens}


def send_to_bimo(host: str, payload: dict) -> bool:
    url = f"http://{host}:{PAIR_PORT}/pair"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.load(resp)
        print(f"Bimo respondeu: {res.get('msg') or res}")
        return bool(res.get("ok"))
    except Exception as e:
        print(f"ERRO ao falar com o Bimo em {host}:{PAIR_PORT} — {e}")
        print("O Bimo esta ligado e na mesma rede?")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Login Google com Drive completo + envio pro Bimo.")
    parser.add_argument("bimo", nargs="?", default="",
                        help="IP do Bimo na rede local (ex: 192.168.0.109)")
    args = parser.parse_args()

    payload = browser_login()
    email = payload["user"]["email"]
    print(f"\nLogado como {email} (Drive completo).")

    out = ROOT / "bimo_pc_tokens.json"
    out.write_text(json.dumps(payload["tokens"], indent=2), encoding="utf-8")
    print(f"Tokens salvos em {out.name} (uso local/backup).")

    if args.bimo:
        ok = send_to_bimo(args.bimo, payload)
        if ok:
            print("\nPronto! O Bimo agora enxerga o seu Drive inteiro.")
            return 0
        return 1
    print("\n(nenhum IP informado — nada foi enviado pro Bimo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
