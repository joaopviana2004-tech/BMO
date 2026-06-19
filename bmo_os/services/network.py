"""Conectividade + WiFi do BMO.

Duas frentes, ambas degradando sozinhas no PC de dev:

1. DETECCAO DE INTERNET (qualquer plataforma): uma thread daemon testa a cada
   poucos segundos uma conexao TCP rapida (porta 53/DNS, sem resolver nome) a
   hosts publicos. `online` vira o snapshot lock-guarded que a status bar le
   pra mostrar o icone de "sem internet". Socket puro -> funciona no PC e no Pi.

2. WIFI (so Linux/Pi com NetworkManager): scan e conexao via `nmcli`. No
   Windows/dev o `nmcli` nao existe -> `wifi_available=False` e a tela de
   Internet so mostra o status (sem lista/conectar). No Raspberry Pi OS Bookworm
   (NetworkManager por padrao) o usuario do console controla o WiFi sem sudo.

Nada bloqueia o render loop: scan e connect rodam em threads proprias e a tela
le os flags (scanning / connect_status / networks) por frame.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import threading
import time

# hosts pra testar internet (porta 53 = DNS; abre TCP sem precisar resolver nome)
_PROBE_HOSTS = [("1.1.1.1", 53), ("8.8.8.8", 53), ("9.9.9.9", 53)]
_CHECK_OK_INTERVAL = 6.0     # online: relaxa
_CHECK_FAIL_INTERVAL = 3.0   # offline: tenta voltar mais rapido


def _terse_split(line: str) -> list[str]:
    """Divide uma linha terse do nmcli (-t) nos ':' NAO escapados, desescapando
    '\\:' e '\\\\' (o nmcli escapa ':' e '\\' dentro dos campos)."""
    out: list[str] = []
    cur: list[str] = []
    esc = False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _split_keep_esc(s: str, delim: str) -> list[str]:
    """Divide em `delim` nao escapado, MANTENDO as barras (pra desescapar depois)."""
    out: list[str] = []
    cur: list[str] = []
    esc = False
    for ch in s:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            cur.append(ch)
            esc = True
        elif ch == delim:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _unescape(s: str) -> str:
    out: list[str] = []
    esc = False
    for ch in s:
        if esc:
            out.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        else:
            out.append(ch)
    return "".join(out)


def parse_wifi_qr(data: str) -> dict | None:
    """Decodifica um QR de WiFi 'WIFI:S:ssid;T:WPA;P:senha;;' ->
    {ssid, password, secure}. None se nao for um QR de WiFi.

    O padrao escapa '\\', ';', ',' e ':' com barra invertida — tratado aqui."""
    if not data or not data.strip().upper().startswith("WIFI:"):
        return None
    body = data.strip()[5:]
    out = {"ssid": "", "password": "", "secure": True}
    for field in _split_keep_esc(body, ";"):
        if not field:
            continue
        kv = _split_keep_esc(field, ":")
        if len(kv) < 2:
            continue
        key = kv[0].strip().upper()
        val = _unescape(":".join(kv[1:]))
        if key == "S":
            out["ssid"] = val
        elif key == "P":
            out["password"] = val
        elif key == "T":
            out["secure"] = val.strip().upper() not in ("", "NOPASS")
    return out if out["ssid"] else None


class NetworkService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._online = False
        # nmcli so faz sentido no Linux/Pi; no Windows nem procuramos
        self._nmcli = shutil.which("nmcli") if sys.platform != "win32" else None
        self.wifi_available = bool(self._nmcli)
        # estado do wifi (snapshot, lido pela tela por frame)
        self._networks: list[dict] = []
        self._current_ssid = ""
        self.scanning = False
        self.scan_error = ""
        self.connect_status = ""    # "" | "conectando" | "ok" | mensagem de erro
        self._connecting = False
        # thread de conectividade (sempre ligada)
        self._stop = False
        self._thread = threading.Thread(target=self._online_loop, daemon=True)
        self._thread.start()

    # ---------- conectividade ----------

    @property
    def online(self) -> bool:
        with self._lock:
            return self._online

    @staticmethod
    def _probe_once() -> bool:
        for host in _PROBE_HOSTS:
            try:
                with socket.create_connection(host, timeout=2.0):
                    return True
            except OSError:
                continue
        return False

    def _online_loop(self) -> None:
        while not self._stop:
            ok = self._probe_once()
            with self._lock:
                self._online = ok
            time.sleep(_CHECK_OK_INTERVAL if ok else _CHECK_FAIL_INTERVAL)

    def check_now(self) -> None:
        """Forca um teste imediato (ex.: ao abrir a tela de Internet)."""
        ok = self._probe_once()
        with self._lock:
            self._online = ok

    def stop(self) -> None:
        self._stop = True

    # ---------- wifi (nmcli) ----------

    def networks(self) -> list[dict]:
        with self._lock:
            return list(self._networks)

    @property
    def current_ssid(self) -> str:
        with self._lock:
            return self._current_ssid

    def _nmcli_run(self, args, timeout=40) -> subprocess.CompletedProcess:
        return subprocess.run([self._nmcli, *args], capture_output=True,
                              text=True, timeout=timeout, check=False)

    def scan_async(self) -> None:
        """Dispara um rescan + list em background (no-op se ja escaneando)."""
        if not self.wifi_available or self.scanning:
            return
        self.scanning = True
        self.scan_error = ""
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self) -> None:
        try:
            try:
                self._nmcli_run(["dev", "wifi", "rescan"], timeout=20)
            except Exception:
                pass  # "scanning not allowed" logo apos outro scan — ignora
            r = self._nmcli_run(
                ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
                timeout=20)
            seen: dict[str, dict] = {}
            current = ""
            for line in (r.stdout or "").splitlines():
                if not line.strip():
                    continue
                parts = _terse_split(line)
                if len(parts) < 4:
                    continue
                in_use, ssid, signal, security = parts[0], parts[1], parts[2], parts[3]
                if not ssid:
                    continue  # rede oculta sem SSID anunciado
                try:
                    sig = int(signal)
                except ValueError:
                    sig = 0
                is_cur = in_use.strip() == "*"
                if is_cur:
                    current = ssid
                # dedupe por SSID: fica o AP de sinal mais forte
                prev = seen.get(ssid)
                if prev is None or sig > prev["signal"]:
                    seen[ssid] = {"ssid": ssid, "signal": sig,
                                  "secure": bool(security.strip()),
                                  "in_use": is_cur}
                elif is_cur:
                    prev["in_use"] = True
            nets = sorted(seen.values(),
                          key=lambda n: (not n["in_use"], -n["signal"]))
            with self._lock:
                self._networks = nets
                if current:
                    self._current_ssid = current
            if r.returncode != 0 and not nets:
                self.scan_error = ((r.stderr or "falha no scan").strip()
                                   .split("\n")[0][:50])
        except Exception as e:  # noqa: BLE001 — nmcli indisponivel/sem permissao
            self.scan_error = str(e)[:50]
        finally:
            self.scanning = False

    def connect_async(self, ssid: str, password: str = "") -> None:
        """Conecta a uma rede em background. A tela le `connect_status`."""
        if not self.wifi_available or self._connecting or not ssid:
            return
        self._connecting = True
        self.connect_status = "conectando"
        threading.Thread(target=self._do_connect, args=(ssid, password),
                         daemon=True).start()

    def _do_connect(self, ssid: str, password: str) -> None:
        try:
            args = ["dev", "wifi", "connect", ssid]
            if password:
                args += ["password", password]
            r = self._nmcli_run(args, timeout=45)
            if r.returncode == 0:
                self.connect_status = "ok"
                with self._lock:
                    self._current_ssid = ssid
                self.check_now()
                self.scan_async()
            else:
                msg = (r.stderr or r.stdout or "falha").strip().split("\n")[-1]
                self.connect_status = msg[:60] or "falha ao conectar"
        except subprocess.TimeoutExpired:
            self.connect_status = "tempo esgotado"
        except Exception as e:  # noqa: BLE001
            self.connect_status = str(e)[:60]
        finally:
            self._connecting = False

    @property
    def connecting(self) -> bool:
        return self._connecting
