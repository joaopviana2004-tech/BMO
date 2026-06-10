#!/usr/bin/env python3
"""Espelha sua vault do Obsidian no Drive do Bimo (Bimo/Conhecimento).

POR QUE ESTE SCRIPT (e não o "Google Drive para Desktop")?
O Bimo loga por QR Code (OAuth de dispositivo) com o escopo `drive.file`,
que por segurança SÓ enxerga arquivos criados pelo próprio app. O que o
Drive Desktop sobe é de outro app — invisível pro Bimo. Este script usa o
MESMO GOOGLE_CLIENT_ID do Bimo, então tudo que ele sobe o Bimo vê.

Fluxo automático completo:
    Obsidian (PC) --salvou--> este script (watch) --upload--> Drive
    Bimo/Conhecimento --pull a cada 5 min (ou ao abrir CEREBRO)--> tela

Uso (PowerShell/terminal, na raiz do repo):
    python scripts/bimo_pc_sync.py "C:\\caminho\\da\\vault"            # vigia pra sempre
    python scripts/bimo_pc_sync.py "C:\\caminho\\da\\vault" --once     # 1 sync e sai
    python scripts/bimo_pc_sync.py "C:\\caminho\\da\\vault" --interval 60

1º uso: mostra um código e o link google.com/device — autorize com a MESMA
conta Google que você usa no Bimo. O token fica em bimo_pc_tokens.json
(gitignored) e os próximos syncs são silenciosos.

Pré-requisito no .env (raiz do repo): GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
(os mesmos do Bimo).

Espelho BIDIRECIONAL vault <-> Drive:
    - SOBE: notas novas/alteradas no Obsidian (md5) -> Bimo/Conhecimento/
    - BAIXA: notas que o Bimo criou/alterou no Drive -> vault local
      (notas novas vão pra vault/Bimo/; existentes atualizam no lugar)
    - REMOVE do Drive só o que sumiu da vault (deleção no Obsidian)
    - nomes achatados no Drive (estilo Obsidian: nome único na vault)

Deixe rodando em background / inicialização do Windows:
    pythonw scripts/bimo_pc_sync.py "C:\\caminho\\da\\vault"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bmo_os.services import google_auth                      # noqa: E402
from bmo_os.services.drive_sync import (                     # noqa: E402
    FILES_URL, UPLOAD_URL, FOLDER_MIME,
    FOLDER_NAME, KNOWLEDGE_FOLDER_NAME,
)

TOKENS_PATH = ROOT / "bimo_pc_tokens.json"
SKIP_DIRS = {".obsidian", ".trash", ".git", ".smart-env", "node_modules"}
BIMO_INBOX = "Bimo"   # subpasta da vault pra notas novas vindas do agente


def _parse_rfc3339(ts: str) -> float:
    try:
        return datetime.fromisoformat(
            ts.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except Exception:
        return 0.0


# ---------- auth (device flow, mesmo client do Bimo) ----------

def get_credentials() -> google_auth.Credentials:
    creds = google_auth.Credentials(TOKENS_PATH)
    if creds.ok:
        return creds
    if not google_auth.available():
        print("ERRO: defina GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no .env "
              "(os mesmos do Bimo).")
        raise SystemExit(1)
    flow = google_auth.DeviceFlow()
    flow.start()
    shown = False
    while flow.state in ("requesting", "waiting", "idle"):
        if flow.state == "waiting" and not shown:
            shown = True
            print("\n=== Autorize o Bimo PC Sync (uma vez só) ===")
            print(f"1. Abra:   {flow.verification_url}")
            print(f"2. Codigo: {flow.user_code}")
            print("3. Logue com a MESMA conta Google do Bimo.\n")
            print("Esperando autorizacao...")
        time.sleep(1.0)
    if flow.state != "success" or not flow.tokens:
        print(f"ERRO no login: {flow.error or flow.state}")
        raise SystemExit(1)
    google_auth.Credentials.save_initial(TOKENS_PATH, flow.tokens)
    email = (flow.user or {}).get("email", "?")
    print(f"OK! Logado como {email} (token salvo em {TOKENS_PATH.name}).\n")
    return google_auth.Credentials(TOKENS_PATH)


# ---------- Drive REST (mínimo necessário) ----------

class Drive:
    def __init__(self, creds: google_auth.Credentials) -> None:
        self.creds = creds

    def _request(self, url: str, *, method: str = "GET", data: bytes | None = None,
                 content_type: str = "") -> dict | None:
        token = self.creds.get_access_token()
        if not token:
            return None
        headers = {"Authorization": f"Bearer {token}"}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
            return json.loads(body) if body else {}
        except Exception as e:
            print(f"  ! rede/API: {str(e)[:80]}")
            return None

    def ensure_folder(self, name: str, parent: str = "") -> str:
        q = f"name='{name}' and mimeType='{FOLDER_MIME}' and trashed=false"
        if parent:
            q += f" and '{parent}' in parents"
        found = self._request(f"{FILES_URL}?q={urllib.parse.quote(q)}&fields=files(id)")
        if found is None:
            return ""
        files = found.get("files", [])
        if files:
            return files[0]["id"]
        meta: dict = {"name": name, "mimeType": FOLDER_MIME}
        if parent:
            meta["parents"] = [parent]
        created = self._request(FILES_URL, method="POST",
                                data=json.dumps(meta).encode(),
                                content_type="application/json")
        return (created or {}).get("id", "")

    def list_md_recursive(self, folder: str) -> dict | None:
        """name -> {id, md5Checksum, modifiedTime} — recursivo nas subpastas."""
        out: dict = {}
        queue = [folder]
        seen: set = set()
        while queue:
            fid = queue.pop(0)
            if fid in seen:
                continue
            seen.add(fid)
            token = ""
            while True:
                q = urllib.parse.quote(f"'{fid}' in parents and trashed=false")
                url = (f"{FILES_URL}?q={q}&pageSize=1000"
                       "&fields=nextPageToken,files(id,name,md5Checksum,"
                       "mimeType,modifiedTime)")
                if token:
                    url += f"&pageToken={token}"
                page = self._request(url)
                if page is None:
                    return None
                for f in page.get("files", []):
                    name = f.get("name", "")
                    if f.get("mimeType") == FOLDER_MIME:
                        if not name.startswith("."):
                            queue.append(f["id"])
                    elif name.endswith(".md") and name not in out:
                        out[name] = f
                token = page.get("nextPageToken", "")
                if not token:
                    break
        return out

    def download(self, file_id: str) -> bytes | None:
        token = self.creds.get_access_token()
        if not token:
            return None
        req = urllib.request.Request(
            f"{FILES_URL}/{file_id}?alt=media",
            headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception:
            return None

    def upload(self, folder: str, name: str, body: bytes, file_id: str = "") -> bool:
        if file_id:
            res = self._request(f"{UPLOAD_URL}/{file_id}?uploadType=media",
                                method="PATCH", data=body, content_type="text/markdown")
            return res is not None
        boundary = "bimo-pc-sync-boundary"
        meta = json.dumps({"name": name, "parents": [folder]})
        payload = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{meta}\r\n"
            f"--{boundary}\r\n"
            "Content-Type: text/markdown\r\n\r\n"
        ).encode() + body + f"\r\n--{boundary}--".encode()
        res = self._request(f"{UPLOAD_URL}?uploadType=multipart",
                            method="POST", data=payload,
                            content_type=f"multipart/related; boundary={boundary}")
        return res is not None

    def delete(self, file_id: str) -> None:
        self._request(f"{FILES_URL}/{file_id}", method="DELETE")


# ---------- espelho vault -> Drive ----------

def scan_vault(vault: Path) -> dict:
    """name.md -> Path. Achatado (nome de nota é único na vault do Obsidian)."""
    notes: dict = {}
    for p in vault.rglob("*.md"):
        if any(part in SKIP_DIRS or part.startswith(".") for part in p.parts):
            continue
        if p.name in notes:
            print(f"  ! nome duplicado na vault, mantendo o primeiro: {p.name}")
            continue
        notes[p.name] = p
    return notes


def sync_once(drive: Drive, vault: Path, folder: str) -> bool:
    """Um ciclo bidirecional. True se concluiu (mesmo sem mudanças)."""
    local = scan_vault(vault)
    remote = drive.list_md_recursive(folder)
    if remote is None:
        return False
    up = down = rm = 0
    inbox = vault / BIMO_INBOX
    inbox.mkdir(exist_ok=True)

    # PULL: Drive -> vault (notas do agente Bimo ou edits remotos)
    for name, entry in sorted(remote.items()):
        body = drive.download(entry["id"])
        if body is None:
            return False
        remote_md5 = entry.get("md5Checksum") or hashlib.md5(body).hexdigest()
        remote_mtime = _parse_rfc3339(entry.get("modifiedTime", ""))
        path = local.get(name)
        if path is not None:
            try:
                local_body = path.read_bytes()
                local_md5 = hashlib.md5(local_body).hexdigest()
                if local_md5 == remote_md5:
                    continue
                local_mtime = path.stat().st_mtime
                if local_mtime > remote_mtime:
                    continue   # vault mais nova — sobe no push abaixo
            except OSError:
                pass
            dest = path
        else:
            dest = inbox / name
        try:
            if dest.exists():
                if hashlib.md5(dest.read_bytes()).hexdigest() == remote_md5:
                    continue
            dest.write_bytes(body)
            down += 1
            tag = "atualizado" if path else "novo"
            print(f"  v {name} ({tag})")
            local[name] = dest
        except OSError:
            continue

    # PUSH: vault -> Drive
    for name, path in sorted(local.items()):
        try:
            body = path.read_bytes()
            local_md5 = hashlib.md5(body).hexdigest()
            local_mtime = path.stat().st_mtime
        except OSError:
            continue
        entry = remote.get(name)
        if entry:
            if entry.get("md5Checksum") == local_md5:
                continue
            remote_mtime = _parse_rfc3339(entry.get("modifiedTime", ""))
            if remote_mtime > local_mtime:
                continue   # já puxamos acima
            if drive.upload(folder, name, body, entry["id"]):
                up += 1
                print(f"  ^ {name}")
        elif drive.upload(folder, name, body):
            up += 1
            print(f"  ^ {name} (novo)")

    # REMOVE do Drive o que sumiu da vault (deleção no Obsidian)
    for name, entry in sorted(remote.items()):
        if name not in local:
            drive.delete(entry["id"])
            rm += 1
            print(f"  x {name} (removido do Drive)")

    if up or down or rm:
        print(f"  = {up} enviado(s), {down} baixado(s), {rm} removido(s), "
              f"{len(local)} nota(s) na vault")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Espelha a vault do Obsidian "
                                     "em Bimo/Conhecimento no Drive.")
    parser.add_argument("vault", help="pasta da vault do Obsidian")
    parser.add_argument("--once", action="store_true",
                        help="um sync e sai (padrao: vigia pra sempre)")
    parser.add_argument("--interval", type=int, default=30,
                        help="segundos entre varreduras no modo watch (padrao 30)")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"ERRO: pasta nao existe: {vault}")
        return 1

    creds = get_credentials()
    drive = Drive(creds)
    print(f"Vault:  {vault}")
    root = drive.ensure_folder(FOLDER_NAME)
    folder = drive.ensure_folder(KNOWLEDGE_FOLDER_NAME, root) if root else ""
    if not folder:
        print("ERRO: nao consegui garantir Bimo/Conhecimento no Drive (sem rede?).")
        return 1
    print(f"Drive:  {FOLDER_NAME}/{KNOWLEDGE_FOLDER_NAME}/\n")

    last_sig = None
    while True:
        # assinatura barata da vault: só mexe na rede quando algo mudou
        local = scan_vault(vault)
        try:
            sig = tuple(sorted((n, p.stat().st_mtime) for n, p in local.items()))
        except OSError:
            sig = None
        if sig != last_sig:
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] sincronizando...")
            if sync_once(drive, vault, folder):
                last_sig = sig
                print(f"[{stamp}] ok — vigiando (Ctrl+C para sair)" if not args.once
                      else f"[{stamp}] ok")
        if args.once:
            return 0
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ntchau!")
        raise SystemExit(0)
