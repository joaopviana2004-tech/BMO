"""Sincronização do perfil com o Google Drive — o Bimo GERENCIA esta árvore:

    Bimo/
    ├── Conhecimento/    notas .md do Segundo Cérebro (espelhadas pro Bimo)
    ├── Multimidia/
    │   └── Audios/      gravações offline-first (Sync & Destroy)
    └── Preferencias/    bmo_config.json (tema/volume/brilho por perfil)

1) PREFERÊNCIAS (Bimo/Preferencias/bmo_config.json):
    - start(): thread de background. Primeiro PULL (se o arquivo do Drive é
      mais novo que o local, baixa e recarrega o config — volume/brilho/tema
      aplicam na hora, pois as telas leem config.get() a cada frame).
    - mark_dirty(): chamado pelo hook config.on_change a cada ajuste no
      SETTINGS; o upload sobe com debounce (~10s) pra não floodar a API.

2) ÁUDIOS OFFLINE-FIRST "Sync & Destroy" (Bimo/Multimidia/Audios): a thread
   varre a pasta de gravações do perfil; cada .wav fechado sobe, o
   md5Checksum devolvido pelo Drive é conferido contra o arquivo local e,
   batendo, o LOCAL É DESTRUÍDO — memória do Bimo sempre livre. Sem rede,
   os arquivos esperam quietos. on_event(msg) avisa a UI.

3) SEGUNDO CÉREBRO (espelho Bimo/Conhecimento -> knowledge/ local): baixa
   só o que mudou (md5); remove local o que sumiu do Drive — o Drive é a
   fonte da verdade. A tela CEREBRO lê daí. Quem ALIMENTA a pasta é o
   scripts/bimo_pc_sync.py rodando no PC (espelha a vault do Obsidian).
   OBS (escopo drive.file): o app só enxerga arquivos criados pelo PRÓPRIO
   app — por isso o uploader do PC usa o mesmo GOOGLE_CLIENT_ID.

4) flush(): sync síncrono de tudo — usado no logout (backup final antes
   do wipe) e no desligamento.

Tudo via REST v3 com urllib (sem SDK do Google) e degradação silenciosa:
sem internet o Bimo segue 100% funcional com os dados locais.
"""
from __future__ import annotations

import hashlib
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
KNOWLEDGE_FOLDER_NAME = "Conhecimento"
MEDIA_FOLDER_NAME = "Multimidia"
AUDIO_FOLDER_NAME = "Audios"          # dentro de Multimidia/
PREFS_FOLDER_NAME = "Preferencias"
FOLDER_MIME = "application/vnd.google-apps.folder"
CONFIG_NAME = "bmo_config.json"

DEBOUNCE_S = 10.0
POLL_S = 0.5
AUDIO_SCAN_S = 15.0
KNOWLEDGE_SCAN_S = 300.0   # 5 min — notas mudam devagar; tela pode forçar


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
                 on_pulled=None, recordings_dir: Path | None = None,
                 knowledge_dir: Path | None = None, on_event=None) -> None:
        self.creds = creds
        self.config_path = Path(config_path) if config_path else config.get_path()
        self.on_pulled = on_pulled   # callback após baixar config (ex: reaplicar volume)
        self.recordings_dir = Path(recordings_dir) if recordings_dir else None
        self.knowledge_dir = Path(knowledge_dir) if knowledge_dir else None
        self.on_event = on_event     # toast não-intrusivo na UI (msg curta)
        self.status = ""          # última mensagem curta (pra UI, se quiser)
        self.last_sync = 0.0
        self.audio_uploads = 0    # total de áudios sincronizados+destruídos
        self.knowledge_sync_at = 0.0   # epoch do último espelho de notas OK
        self.knowledge_status = ""     # "12 notas" / "sem rede" — pra tela CEREBRO
        self._folder_ids: dict = {}    # cache "Bimo/Multimidia/Audios" -> id
        self._config_file_id = ""
        self._dirty_at = 0.0      # epoch do último set_value (0 = limpo)
        self._audio_scan_at = 0.0
        self._knowledge_scan_at = 0.0   # 0 = sincroniza no próximo tick
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

    def request_knowledge_sync(self) -> None:
        """Pede um espelho das notas JÁ (a tela CEREBRO chama no botão SYNC)."""
        self._knowledge_scan_at = 0.0

    def flush(self, timeout_s: float = 15.0) -> bool:
        """Sync final SÍNCRONO (logout/desligar): config + áudios pendentes.

        True se nada ficou pra trás (config no Drive e fila de áudio vazia)."""
        deadline = time.time() + timeout_s
        with self._lock:
            dirty = self._dirty_at > 0
        ok = True
        if dirty or self.last_sync == 0:
            ok = self._push()
            while not ok and time.time() < deadline:
                time.sleep(1.0)
                ok = self._push()
        self._sync_recordings()
        return ok and not self._pending_recordings()

    # ---------- thread ----------

    def _ensure_tree(self) -> None:
        """Cria/garante a árvore gerenciada no Drive (mesmo vazia) — o usuário
        já enxerga as pastas e sabe onde cada coisa mora."""
        self._folder(FOLDER_NAME, KNOWLEDGE_FOLDER_NAME)
        self._folder(FOLDER_NAME, MEDIA_FOLDER_NAME, AUDIO_FOLDER_NAME)
        self._folder(FOLDER_NAME, PREFS_FOLDER_NAME)

    def _loop(self) -> None:
        # estrutura primeiro, depois o pull das preferências
        self._ensure_tree()
        self._pull()
        while not self._stop.is_set():
            time.sleep(POLL_S)
            now = time.time()
            with self._lock:
                dirty_at = self._dirty_at
            if dirty_at and now - dirty_at >= DEBOUNCE_S:
                self._push()
            # Sync & Destroy dos áudios (varre a cada AUDIO_SCAN_S; barato
            # quando a fila está vazia — um glob e nada de rede)
            if now - self._audio_scan_at >= AUDIO_SCAN_S:
                self._audio_scan_at = now
                if self._pending_recordings():
                    self._sync_recordings()
            # espelho das notas do Segundo Cérebro (Drive -> local)
            if self.knowledge_dir is not None and \
                    now - self._knowledge_scan_at >= KNOWLEDGE_SCAN_S:
                self._knowledge_scan_at = now
                self._sync_knowledge()

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

    def _find_or_create_folder(self, name: str, parent_id: str = "") -> str:
        """Acha (ou cria) UMA pasta pelo nome, opcionalmente dentro de parent_id."""
        q = f"name='{name}' and mimeType='{FOLDER_MIME}' and trashed=false"
        if parent_id:
            q += f" and '{parent_id}' in parents"
        found = self._request(f"{FILES_URL}?q={urllib.parse.quote(q)}&fields=files(id)")
        if found is None:
            return ""
        files = found.get("files", [])
        if files:
            return files[0]["id"]
        meta: dict = {"name": name, "mimeType": FOLDER_MIME}
        if parent_id:
            meta["parents"] = [parent_id]
        created = self._request(FILES_URL, method="POST",
                                data=json.dumps(meta).encode(),
                                content_type="application/json")
        return (created or {}).get("id", "")

    def _folder(self, *names: str) -> str:
        """Garante um CAMINHO de pastas no Drive (ex: Bimo/Multimidia/Audios)
        e devolve o id da última. Cacheado — só consulta a API uma vez."""
        parent = ""
        path = []
        for name in names:
            path.append(name)
            key = "/".join(path)
            fid = self._folder_ids.get(key)
            if not fid:
                fid = self._find_or_create_folder(name, parent)
                if not fid:
                    return ""
                self._folder_ids[key] = fid
            parent = fid
        return parent

    def _ensure_folder(self) -> str:
        """Raiz gerenciada Bimo/ (escopo drive.file só enxerga o que criamos)."""
        return self._folder(FOLDER_NAME)

    def _find_config(self) -> dict | None:
        """{'id','modifiedTime'} do Bimo/Preferencias/bmo_config.json, ou None.

        Migração: se o config estiver na raiz Bimo/ (estrutura antiga), move
        ele pra Preferencias/ via addParents/removeParents."""
        prefs = self._folder(FOLDER_NAME, PREFS_FOLDER_NAME)
        if not prefs:
            return None
        q = urllib.parse.quote(
            f"name='{CONFIG_NAME}' and '{prefs}' in parents and trashed=false")
        found = self._request(f"{FILES_URL}?q={q}&fields=files(id,modifiedTime)")
        files = (found or {}).get("files", [])
        if files:
            self._config_file_id = files[0]["id"]
            return files[0]
        # legado: config solto na raiz Bimo/ -> move pra Preferencias/
        root = self._ensure_folder()
        if root:
            q = urllib.parse.quote(
                f"name='{CONFIG_NAME}' and '{root}' in parents and trashed=false")
            found = self._request(f"{FILES_URL}?q={q}&fields=files(id,modifiedTime)")
            files = (found or {}).get("files", [])
            if files:
                moved = self._request(
                    f"{FILES_URL}/{files[0]['id']}?addParents={prefs}"
                    f"&removeParents={root}&fields=id,modifiedTime",
                    method="PATCH", data=b"{}", content_type="application/json")
                if moved and moved.get("id"):
                    self._config_file_id = moved["id"]
                    return {"id": moved["id"],
                            "modifiedTime": moved.get("modifiedTime",
                                                      files[0].get("modifiedTime", ""))}
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
            folder = self._folder(FOLDER_NAME, PREFS_FOLDER_NAME)
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

    # ---------- áudios offline-first (Sync & Destroy) ----------

    def _pending_recordings(self) -> list[Path]:
        if self.recordings_dir is None:
            return []
        try:
            return sorted(self.recordings_dir.glob("*.wav"))
        except OSError:
            return []

    def _ensure_audio_folder(self) -> str:
        """Garante Bimo/Multimidia/Audios/ no Drive."""
        return self._folder(FOLDER_NAME, MEDIA_FOLDER_NAME, AUDIO_FOLDER_NAME)

    def _sync_recordings(self) -> None:
        """Upload de cada .wav fechado + verificação md5 + destruição local."""
        pending = self._pending_recordings()
        if not pending:
            return
        folder = self._ensure_audio_folder()
        if not folder:
            return
        synced = 0
        for path in pending:
            try:
                body = path.read_bytes()
            except OSError:
                continue
            local_md5 = hashlib.md5(body).hexdigest()
            boundary = "bimo-audio-boundary"
            meta = json.dumps({"name": path.name, "parents": [folder]})
            payload = (
                f"--{boundary}\r\n"
                "Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{meta}\r\n"
                f"--{boundary}\r\n"
                "Content-Type: audio/wav\r\n\r\n"
            ).encode() + body + f"\r\n--{boundary}--".encode()
            res = self._request(
                f"{UPLOAD_URL}?uploadType=multipart&fields=id,md5Checksum",
                method="POST", data=payload,
                content_type=f"multipart/related; boundary={boundary}")
            if res is None:
                self.status = "audio: upload falhou (sem rede?)"
                return   # sem rede; os demais esperam o próximo ciclo
            if res.get("md5Checksum") != local_md5:
                # corrompeu no caminho: apaga a cópia remota e tenta de novo depois
                self._request(f"{FILES_URL}/{res.get('id', '')}", method="DELETE")
                self.status = "audio: checksum divergente, vou tentar de novo"
                continue
            # upload íntegro confirmado -> DESTRÓI o arquivo local
            try:
                path.unlink()
            except OSError:
                pass
            synced += 1
            self.audio_uploads += 1
        if synced:
            self.last_sync = time.time()
            self.status = f"{synced} audio(s) no Drive"
            if self.on_event is not None:
                try:
                    self.on_event("Sincronizacao com o Drive concluida")
                except Exception:
                    pass

    # ---------- Segundo Cérebro (espelho Drive -> knowledge/) ----------

    def _ensure_knowledge_folder(self) -> str:
        """Garante Bimo/Conhecimento/ no Drive (o bimo_pc_sync.py deposita os .md lá)."""
        return self._folder(FOLDER_NAME, KNOWLEDGE_FOLDER_NAME)

    def _list_remote_notes(self, folder: str) -> list[dict] | None:
        """Todos os .md de Bimo/Conhecimento ({id,name,md5Checksum}). Paginado."""
        out: list[dict] = []
        token = ""
        while True:
            q = urllib.parse.quote(f"'{folder}' in parents and trashed=false")
            url = (f"{FILES_URL}?q={q}&pageSize=1000"
                   "&fields=nextPageToken,files(id,name,md5Checksum)")
            if token:
                url += f"&pageToken={token}"
            page = self._request(url)
            if page is None:
                return None
            out.extend(f for f in page.get("files", [])
                       if f.get("name", "").endswith(".md"))
            token = page.get("nextPageToken", "")
            if not token:
                return out

    def _sync_knowledge(self) -> None:
        """Espelha o Drive na pasta local: baixa novo/mudado, apaga o que sumiu.

        O Drive é a fonte da verdade (Obsidian do usuário mora lá); a pasta
        local é só um cache de leitura pra tela CEREBRO e o futuro RAG."""
        folder = self._ensure_knowledge_folder()
        if not folder:
            self.knowledge_status = "sem rede"
            return
        remote = self._list_remote_notes(folder)
        if remote is None:
            self.knowledge_status = "sem rede"
            return
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        token = self.creds.get_access_token()
        if not token:
            return
        changed = 0
        remote_names = set()
        for f in remote:
            name = f["name"]
            remote_names.add(name)
            local = self.knowledge_dir / name
            if local.exists():
                try:
                    if hashlib.md5(local.read_bytes()).hexdigest() == f.get("md5Checksum"):
                        continue   # já espelhado
                except OSError:
                    pass
            req = urllib.request.Request(
                f"{FILES_URL}/{f['id']}?alt=media",
                headers={"Authorization": f"Bearer {token}"})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    local.write_bytes(resp.read())
                changed += 1
            except Exception:
                self.knowledge_status = "sem rede"
                return
        # mirror: o que sumiu do Drive sai do cache local
        try:
            for local in self.knowledge_dir.glob("*.md"):
                if local.name not in remote_names:
                    local.unlink()
                    changed += 1
        except OSError:
            pass
        self.knowledge_sync_at = time.time()
        self.knowledge_status = f"{len(remote_names)} nota(s)"
        if changed and self.on_event is not None:
            try:
                self.on_event("Conhecimento sincronizado")
            except Exception:
                pass
