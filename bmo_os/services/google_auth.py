"""Google OAuth 2.0 Device Flow ("TVs and Limited Input Devices") + tokens.

O Bimo não tem teclado: a tela LOGIN mostra um QR Code apontando pra
google.com/device com o user_code; o dono autoriza no celular e o Pi recebe
os tokens direto do Google via polling — zero servidor intermediário.

Pré-requisito (.env):
    GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET — credencial OAuth do tipo
    "TVs and Limited Input devices" (console.cloud.google.com, Drive API on).

Escopos: openid/email/profile (identidade do perfil) + drive.file (pasta
Bimo/ no Drive do usuário — preferências hoje; áudios/.md no futuro).

Duas peças:
    DeviceFlow   — thread do fluxo de login (request_code -> polling).
    Credentials  — tokens.json de um perfil; renova o access_token sozinho.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

SCOPES = "openid email profile https://www.googleapis.com/auth/drive.file"


def client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def available() -> bool:
    """Tem credencial de app configurada? (sem ela a tela LOGIN só oferece convidado)"""
    return bool(client_id() and client_secret())


def _post(url: str, fields: dict, timeout: int = 15) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        # erros OAuth vêm como JSON no corpo (authorization_pending etc.)
        try:
            return json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            return {"error": f"http_{e.code}"}


def _get(url: str, access_token: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


class DeviceFlow:
    """Fluxo de login em thread. A tela LOGIN lê os campos públicos por frame.

    Estados (self.state): "idle" -> "requesting" -> "waiting" -> "success"
    ou "error" (self.error com motivo curto pra exibir).
    """

    def __init__(self) -> None:
        self.state = "idle"
        self.error = ""
        self.user_code = ""          # ex: "ABCD-EFGH" — mostrado em fonte grande
        self.verification_url = ""   # ex: "https://www.google.com/device"
        self.user: dict | None = None     # {"sub","email","name"} após sucesso
        self.tokens: dict | None = None   # {"access_token","refresh_token","expires_at"}
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def qr_url(self) -> str:
        """URL pro QR Code — verification_url com o código pré-preenchido."""
        if not self.verification_url:
            return ""
        sep = "&" if "?" in self.verification_url else "?"
        return f"{self.verification_url}{sep}user_code={urllib.parse.quote(self.user_code)}"

    def start(self) -> None:
        """(Re)inicia o fluxo. Idempotente enquanto um fluxo está vivo."""
        if self._thread is not None and self._thread.is_alive():
            return
        self.state = "requesting"
        self.error = ""
        self.user = None
        self.tokens = None
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    # ---------- thread ----------

    def _run(self) -> None:
        if not available():
            self.state = "error"
            self.error = "GOOGLE_CLIENT_ID nao configurado"
            return
        try:
            data = _post(DEVICE_CODE_URL, {"client_id": client_id(), "scope": SCOPES})
        except Exception:
            self.state = "error"
            self.error = "sem internet?"
            return
        if "device_code" not in data:
            self.state = "error"
            self.error = (data.get("error") or "falha ao pedir codigo")[:40]
            return

        self.user_code = data.get("user_code", "")
        self.verification_url = data.get("verification_url") or "https://www.google.com/device"
        device_code = data["device_code"]
        interval = max(int(data.get("interval", 5)), 2)
        deadline = time.time() + int(data.get("expires_in", 1800))
        self.state = "waiting"

        while not self._cancel.is_set() and time.time() < deadline:
            time.sleep(interval)
            if self._cancel.is_set():
                break
            try:
                tok = _post(TOKEN_URL, {
                    "client_id": client_id(),
                    "client_secret": client_secret(),
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                })
            except Exception:
                continue   # rede oscilou; tenta de novo no próximo tick
            err = tok.get("error", "")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 2
                continue
            if err in ("access_denied", "expired_token"):
                self.state = "error"
                self.error = "negado no celular" if err == "access_denied" else "codigo expirou"
                return
            if "access_token" in tok:
                self._finish(tok)
                return
            # erro inesperado (invalid_client etc.)
            self.state = "error"
            self.error = (err or "erro no login")[:40]
            return

        if self.state == "waiting":
            self.state = "error"
            self.error = "codigo expirou"

    def _finish(self, tok: dict) -> None:
        tokens = {
            "access_token": tok.get("access_token", ""),
            "refresh_token": tok.get("refresh_token", ""),
            "expires_at": time.time() + int(tok.get("expires_in", 3600)),
        }
        try:
            info = _get(USERINFO_URL, tokens["access_token"])
        except Exception:
            info = {}
        sub = (info.get("sub") or "").strip()
        if not sub:
            self.state = "error"
            self.error = "falha ao identificar a conta"
            return
        self.user = {
            "sub": sub,
            "email": info.get("email", ""),
            "name": info.get("name", "") or info.get("given_name", ""),
        }
        self.tokens = tokens
        self.state = "success"


class Credentials:
    """Tokens de um perfil (tokens.json na pasta do perfil), com refresh.

    get_access_token() devolve um token válido ou "" (sem rede / revogado).
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict = {}
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}

    @staticmethod
    def save_initial(path: Path, tokens: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tokens, indent=2), encoding="utf-8")

    @property
    def ok(self) -> bool:
        return bool(self._data.get("refresh_token"))

    def get_access_token(self) -> str:
        with self._lock:
            if not self._data.get("refresh_token"):
                return ""
            if time.time() < float(self._data.get("expires_at", 0)) - 60:
                return self._data.get("access_token", "")
            return self._refresh_unlocked()

    def _refresh_unlocked(self) -> str:
        try:
            tok = _post(TOKEN_URL, {
                "client_id": client_id(),
                "client_secret": client_secret(),
                "refresh_token": self._data["refresh_token"],
                "grant_type": "refresh_token",
            })
        except Exception:
            return ""
        if "access_token" not in tok:
            return ""
        self._data["access_token"] = tok["access_token"]
        self._data["expires_at"] = time.time() + int(tok.get("expires_in", 3600))
        try:
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception:
            pass
        return self._data["access_token"]
