#!/usr/bin/env python3
"""Autoriza uma conta Google pro BMO ler o Calendar (read-only via OAuth).

Use isso pra calendário PRIVADO — inclusive Google Workspace (@suaempresa)
onde o admin bloqueia o compartilhamento/endereço secreto e a opção iCal
privada some. Você loga com a sua própria conta e o BMO lê os SEUS eventos.

Rode no PC (precisa de navegador), uma vez por conta:

    python scripts/gcal_auth.py

Pré-requisitos no .env (raiz do repo):
    GCAL_CLIENT_ID=...
    GCAL_CLIENT_SECRET=...

Como obter as credenciais (uma vez só):
  1. console.cloud.google.com -> crie/usa um projeto.
  2. "APIs e serviços" -> "Ativar APIs" -> ative a "Google Calendar API".
  3. "Tela de permissão OAuth": tipo Externo; em "Usuários de teste" NÃO é o
     ideal (refresh token expira em 7 dias). Clique "PUBLICAR APP" / deixe o
     status "Em produção" pra o login não vencer toda semana (vai aparecer um
     aviso de "app não verificado" — é só clicar em Avançado -> Continuar).
  4. "Credenciais" -> "Criar credenciais" -> "ID do cliente OAuth" ->
     tipo "App para computador (Desktop)". Copie Client ID e Client Secret
     pro .env.

O refresh token fica em gcal_tokens.json (gitignored). Rode de novo logando
em outra conta pra adicionar mais agendas (multi-conta).
"""
from __future__ import annotations

import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bmo_os.core import config  # noqa: E402  (importa só pra disparar o _load_dotenv)

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PRIMARY_URL = "https://www.googleapis.com/calendar/v3/calendars/primary"
TOKENS_PATH = ROOT / "gcal_tokens.json"


def main() -> int:
    cid = os.environ.get("GCAL_CLIENT_ID", "").strip()
    csec = os.environ.get("GCAL_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        print("ERRO: defina GCAL_CLIENT_ID e GCAL_CLIENT_SECRET no .env primeiro.")
        print("Veja as instruções no topo deste arquivo.")
        return 1

    holder: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            holder["code"] = (q.get("code") or [None])[0]
            holder["state"] = (q.get("state") or [None])[0]
            holder["error"] = (q.get("error") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<h2>BMO: autorizado! Pode fechar esta aba e voltar pro terminal.</h2>"
                .encode("utf-8")
            )

        def log_message(self, *a):  # silencia o log do servidor
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    redirect = f"http://127.0.0.1:{port}/"
    state = secrets.token_urlsafe(16)

    params = urllib.parse.urlencode({
        "client_id": cid,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",   # pede refresh token
        "prompt": "consent",        # garante que o refresh token venha
        "state": state,
    })
    url = f"{AUTH_URL}?{params}"

    print("\nAbra esta URL no navegador (logue na conta que você quer integrar):\n")
    print(url + "\n")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    threading.Thread(target=srv.handle_request, daemon=True).start()
    print("Esperando a autorização no navegador...")
    for _ in range(600):  # ~5 min
        if holder.get("code") or holder.get("error"):
            break
        time.sleep(0.5)

    if holder.get("error"):
        print(f"ERRO no consentimento: {holder['error']}")
        return 1
    code = holder.get("code")
    if not code or holder.get("state") != state:
        print("ERRO: não recebi o código de autorização (timeout ou state inválido).")
        return 1

    # troca o code por tokens
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": cid,
        "client_secret": csec,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            tok = json.load(resp)
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        print("ERRO ao trocar o código:", e.read().decode("utf-8", "ignore")[:300])
        return 1

    refresh = tok.get("refresh_token")
    access = tok.get("access_token")
    if not refresh:
        print("ERRO: não veio refresh_token. Revogue o acesso antigo do app em")
        print("https://myaccount.google.com/permissions e rode de novo.")
        return 1

    # descobre o e-mail (id do calendário primário) pra usar de rótulo
    label = "conta"
    try:
        rq = urllib.request.Request(PRIMARY_URL, headers={"Authorization": f"Bearer {access}"})
        with urllib.request.urlopen(rq, timeout=20) as resp:
            cal = json.load(resp)
        label = cal.get("id") or cal.get("summary") or label
    except Exception:
        pass

    # salva (merge por rótulo pra não duplicar a mesma conta)
    data = {"accounts": []}
    if TOKENS_PATH.exists():
        try:
            data = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {"accounts": []}
    accounts = [a for a in data.get("accounts", []) if a.get("label") != label]
    accounts.append({"label": label, "refresh_token": refresh, "calendar_id": "primary"})
    data["accounts"] = accounts
    TOKENS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nOK! Conta '{label}' salva em {TOKENS_PATH.name}.")
    print(f"Total de contas OAuth: {len(accounts)}.")
    print("Dica: pra um calendário secundário/compartilhado, edite o "
          "'calendar_id' dessa conta no gcal_tokens.json (o padrão é 'primary').")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
