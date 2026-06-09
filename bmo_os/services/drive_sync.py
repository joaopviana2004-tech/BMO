"""Sincronização das preferências do perfil com o Google Drive (pasta Bimo/).

As configurações acompanham o USUÁRIO, não o aparelho: o bmo_config.json do
perfil ativo é espelhado em Bimo/bmo_config.json no Drive da conta logada.

Fluxo:
    - start(): thread de background. Primeiro PULL (se o arquivo do Drive é
      mais novo que o local, baixa e recarrega o config — volume/brilho/tema
      aplicam na hora, pois as telas leem config.get() a cada frame).
    - mark_dirty(): chamado pelo hook config.on_change a cada ajuste no
      SETTINGS; o upload sobe com debounce (~10s) pra não floodar a API.
    - flush(): upload síncrono imediato — usado no logout (backup final
      antes do wipe) e no desligamento.

Tudo via REST v3 com urllib (sem SDK do Google) e degradação silenciosa:
sem internet o Bimo segue 100% funcional com o config local.

A base aqui (pasta Bimo/, upload/download por nome) é o alicerce das
próximas frentes: áudios offline-first e .md do Obsidian.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..core import config
from .google_auth import Credentials

FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"

FOLDER_NAME = "Bimo"
FOLDER_MIME = "application/vnd.google-apps.folder"
CONFIG_NAME = "bmo_config.json"

DEBOUNCE_S = 10.0
POLL_S = 0.5


def _parse_rfc3339(ts: str) -> float:
    """'2026-06-09T18:00:00.000Z' -> epoch. 0.0 se inválido."""
    try:
        from datetime import datetime, timezone
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts).astimezone(timezone.utc).timestamp()
    except Exception:
        return 0.0


class DriveSync:
    def __init__(self, creds: Credentials, *, config_path: Path | None = None,
                 on_pulled=None) -> None:
        self.creds = creds
        self.config_path = Path(config_path) if config_path else config.get_path()
        self.on_pulled = on_pulled   # callback após baixar config (ex: reaplicar volume)
        self.status = ""          # última mensagem curta (pra UI, se quiser)
        self.last_sync = 0.0
        self._folder_id = ""
        self._config_file_id = ""
        self._dirty_at = 0.0      # epoch do último set_value (0 = limpo)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------- API pública ----------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def mark_dirty(self, *_a) -> None:
        """Hook pro config.on_change — assina (key, value), ignora ambos."""
        with self._lock:
            self._dirty_at = time.time()

    def flush(self, timeout_s: float = 15.0) -> bool:
        """Upload final SÍNCRONO (logout/desligar). True se subiu (ou nada a subir)."""
        with self._lock:
            dirty = self._dirty_at > 0
        if not dirty and self.last_sync > 0:
            return True
        deadline = time.time() + timeout_s
        ok = self._push()
        while not ok and time.time() < deadline:
            time.sleep(1.0)
            ok = self._push()
        return ok

    # ---------- thread ----------

    def _loop(self) -> None:
        # pull inicial: preferências do usuário vindas de outro aparelho/sessão
        self._pull()
        while not self._stop.is_set():
            time.sleep(POLL_S)
            with self._lock:
                dirty_at = self._dirty_at
            if dirty_at and time.time() - dirty_at >= DEBOUNCE_S:
                self._push()

    # ---------- REST helpers ----------

    def _request(self, url: str, *, method: str = "GET", data: bytes | None = None,
                 content_type: str = "") -> dict | None:
        token = self.creds.get_access_token()
        if not token:
            self.status = "sem credencial"
            return None
        headers = {"Authorization": f"Bearer {token}"}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read()
            return json.loads(body) if body else {}
        except Exception:
            return None

    def _ensure_folder(self) -> str:
        """Garante a pasta Bimo/ no Drive (escopo drive.file só enxerga o que criamos)."""
        if self._folder_id:
            return self._folder_id
        q = urllib.parse.quote(
            f"name='{FOLDER_NAME}' and mimeType='{FOLDER_MIME}' and trashed=false")
        found = self._request(f"{FILES_URL}?q={q}&fields=files(id)")
        if found is None:
            return ""
        files = found.get("files", [])
        if files:
            self._folder_id = files[0]["id"]
            return self._folder_id
        created = self._request(
            FILES_URL, method="POST",
            data=json.dumps({"name": FOLDER_NAME, "mimeType": FOLDER_MIME}).encode(),
            content_type="application/json")
        self._folder_id = (created or {}).get("id", "")
        return self._folder_id

    def _find_config(self) -> dict | None:
        """{'id','modifiedTime'} do Bimo/bmo_config.json no Drive, ou None."""
        folder = self._ensure_folder()
        if not folder:
            return None
        q = urllib.parse.quote(
            f"name='{CONFIG_NAME}' and '{folder}' in parents and trashed=false")
        found = self._request(f"{FILES_URL}?q={q}&fields=files(id,modifiedTime)")
        files = (found or {}).get("files", [])
        if files:
            self._config_file_id = files[0]["id"]
            return files[0]
        return None

    # ---------- pull / push ----------

    def _pull(self) -> None:
        remote = self._find_config()
        if not remote:
            return
        remote_mtime = _parse_rfc3339(remote.get("modifiedTime", ""))
        try:
            local_mtime = self.config_path.stat().st_mtime
        except OSError:
            local_mtime = 0.0
        if remote_mtime <= local_mtime:
            return   # local é igual ou mais novo; quem manda é o aparelho
        token = self.creds.get_access_token()
        if not token:
            return
        req = urllib.request.Request(
            f"{FILES_URL}/{remote['id']}?alt=media",
            headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read()
            json.loads(body)   # valida antes de gravar por cima
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_bytes(body)
        except Exception:
            return
        config.reload()
        self.last_sync = time.time()
        self.status = "config baixado do Drive"
        if self.on_pulled is not None:
            try:
                self.on_pulled()
            except Exception:
                pass

    def _push(self) -> bool:
        try:
            body = self.config_path.read_bytes()
        except OSError:
            return False
        if not self._config_file_id:
            self._find_config()
        if self._config_file_id:
            # update do conteúdo (media upload simples)
            res = self._request(
                f"{UPLOAD_URL}/{self._config_file_id}?uploadType=media",
                method="PATCH", data=body, content_type="application/json")
        else:
            folder = self._ensure_folder()
            if not folder:
                return False
            # criação em multipart (metadata + conteúdo numa request)
            boundary = "bimo-sync-boundary"
            meta = json.dumps({"name": CONFIG_NAME, "parents": [folder]})
            payload = (
                f"--{boundary}\r\n"
                "Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{meta}\r\n"
                f"--{boundary}\r\n"
                "Content-Type: application/json\r\n\r\n"
            ).encode() + body + f"\r\n--{boundary}--".encode()
            res = self._request(
                f"{UPLOAD_URL}?uploadType=multipart",
                method="POST", data=payload,
                content_type=f"multipart/related; boundary={boundary}")
            if res and res.get("id"):
                self._config_file_id = res["id"]
        if res is None:
            self.status = "upload falhou (sem rede?)"
            return False
        with self._lock:
            self._dirty_at = 0.0
        self.last_sync = time.time()
        self.status = "sincronizado com o Drive"
        return True
