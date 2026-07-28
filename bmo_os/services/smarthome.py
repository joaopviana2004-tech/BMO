"""Smart House — controle local das tomadas Tuya/JWcom (sem nuvem).

Liga/desliga tomadas inteligentes Tuya falando DIRETO com elas na rede local
(protocolo Tuya LAN 3.4, via tinytuya) — sem nuvem, sem Home Assistant. A
`local_key` de cada tomada (o segredo que criptografa os comandos) é baixada
UMA vez fora do BMO (login estilo Home Assistant) e fica guardada no `.env`.

Config no `.env` da raiz — uma tomada por índice (T1, T2, ...):

    SMARTHOME_T1_NAME=Tomada 1
    SMARTHOME_T1_ID=eb9ee0b5867f260c61hvbq
    SMARTHOME_T1_IP=192.168.0.107
    SMARTHOME_T1_KEY=<local_key>
    SMARTHOME_T1_VER=3.4            # opcional (default 3.4)

Segue o padrão dos services do BMO: uma thread daemon faz polling do estado e
guarda um snapshot lock-guarded, então o render loop NUNCA bloqueia no I/O de
rede (que pode travar segundos quando a tomada está offline). Os comandos
(on/off/toggle) são otimistas — atualizam o snapshot na hora pra UI responder —
e são executados na thread de trabalho. Degrada sozinho: sem `tinytuya` (PC de
dev) ou sem tomadas no `.env`, `available=False` e a tela mostra offline.

AUTO-RECUPERAÇÃO DE IP (DHCP): se o IP do `.env` parar de responder, a tomada
provavelmente só trocou de IP no roteador (o app da Tuya não percebe porque vai
pela nuvem). Em vez de marcar 'offline' pra sempre, o serviço faz uma varredura
broadcast Tuya (`tinytuya.deviceScan`), acha a tomada pelo ID e atualiza o IP em
memória sozinho — sem precisar editar o `.env` nem reiniciar. Ver `_rediscover`.
"""
from __future__ import annotations

import os
import queue
import threading
import time

try:
    import tinytuya
    HAS_TINYTUYA = True
except Exception:  # noqa: BLE001 — lib opcional; no PC nem sempre está instalada
    tinytuya = None  # type: ignore
    HAS_TINYTUYA = False

SWITCH_DP = "1"          # DP do relé principal (quase sempre "1" nas tomadas Tuya)
POLL_INTERVAL = 6.0      # s entre leituras de estado em background
SOCKET_TIMEOUT = 4       # s de timeout por chamada à tomada
MAX_DEVICES = 8          # quantos slots SMARTHOME_T{i}_* procurar no .env
REDISCOVER_COOLDOWN = 30.0   # s mínimos entre varreduras de redescoberta (DHCP)
SCAN_SECONDS = 5         # tempo da varredura broadcast Tuya na redescoberta


def _load_devices() -> list[dict]:
    """Lê as tomadas configuradas no os.environ (semeado pelo .env)."""
    out: list[dict] = []
    for i in range(1, MAX_DEVICES + 1):
        dev_id = os.environ.get(f"SMARTHOME_T{i}_ID", "").strip()
        ip = os.environ.get(f"SMARTHOME_T{i}_IP", "").strip()
        key = os.environ.get(f"SMARTHOME_T{i}_KEY", "").strip()
        if not (dev_id and ip and key):
            continue
        try:
            ver = float(os.environ.get(f"SMARTHOME_T{i}_VER", "3.4") or 3.4)
        except ValueError:
            ver = 3.4
        out.append({
            "key": f"t{i}",
            "name": os.environ.get(f"SMARTHOME_T{i}_NAME", "").strip() or f"Tomada {i}",
            "id": dev_id, "ip": ip, "local_key": key, "ver": ver,
        })
    return out


class SmartHomeService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._devices = _load_devices()
        self._conns: dict = {}                # key -> tinytuya.OutletDevice (cache)
        self._cmd_q: "queue.Queue" = queue.Queue()
        self._wake = threading.Event()        # acorda a thread (comando novo)
        self._last_scan = 0.0                 # throttle da redescoberta (monotonic)
        self._scan_cache: dict = {}           # último resultado do deviceScan
        # snapshot por tomada (o que a tela lê)
        self._state = {
            d["key"]: {"key": d["key"], "name": d["name"], "ip": d["ip"],
                       "on": None, "online": False, "err": ""}
            for d in self._devices
        }
        self.available = HAS_TINYTUYA and bool(self._devices)
        if not HAS_TINYTUYA:
            self.status = "sem tinytuya"
        elif not self._devices:
            self.status = "sem tomadas no .env"
        else:
            self.status = "ok"

        if self.available:
            threading.Thread(target=self._loop, daemon=True).start()

    # ---------- leitura pro render loop (snapshot, não bloqueia) ----------

    def get_devices(self) -> list[dict]:
        """Cópia do estado de cada tomada, na ordem do .env."""
        with self._lock:
            return [dict(self._state[d["key"]]) for d in self._devices]

    def count(self) -> int:
        return len(self._devices)

    def all_on(self):
        """True/False se TODAS conhecidas estão ligadas; None se nenhuma sabida."""
        sts = [s["on"] for s in self.get_devices() if s["on"] is not None]
        return all(sts) if sts else None

    # ---------- comandos (otimistas; executam na thread) ----------

    def set(self, key: str, on: bool) -> None:
        with self._lock:
            st = self._state.get(key)
            if st is None:
                return
            st["on"] = bool(on)       # otimista: a UI reflete na hora
            st["err"] = ""
        self._cmd_q.put((key, bool(on)))
        self._wake.set()

    def toggle(self, key: str) -> None:
        with self._lock:
            st = self._state.get(key)
            cur = bool(st["on"]) if (st and st["on"] is not None) else False
        self.set(key, not cur)

    def set_all(self, on: bool) -> None:
        for d in self._devices:
            self.set(d["key"], on)

    def refresh(self) -> None:
        self._wake.set()

    # ---------- thread de trabalho (polling + comandos) ----------

    def _conn(self, dev: dict):
        c = self._conns.get(dev["key"])
        if c is None:
            c = tinytuya.OutletDevice(dev["id"], dev["ip"], dev["local_key"])
            c.set_version(float(dev.get("ver", 3.4)))
            c.set_socketPersistent(True)
            try:
                c.set_socketTimeout(SOCKET_TIMEOUT)
            except Exception:  # noqa: BLE001 — versões antigas do tinytuya
                pass
            self._conns[dev["key"]] = c
        return c

    def _drop_conn(self, key: str) -> None:
        c = self._conns.pop(key, None)
        if c is not None:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass

    def _rediscover(self, dev: dict) -> bool:
        """Acha o IP ATUAL da tomada pelo ID via broadcast Tuya quando o IP do
        .env parou de responder — típico de troca de IP por DHCP (a tomada some
        do IP velho mas continua na rede). Auto-recuperação: sem isso, mudar o
        roteador/lease deixava as tomadas 'offline' embora o app funcionasse.

        Varredura é cara (~SCAN_SECONDS, broadcast): throttle por
        REDISCOVER_COOLDOWN e cache do resultado pra todas as tomadas do ciclo.
        Atualiza dev['ip'] + snapshot e dropa a conexão velha. True se mudou."""
        if tinytuya is None:
            return False
        now = time.monotonic()
        if now - self._last_scan >= REDISCOVER_COOLDOWN:
            self._last_scan = now
            try:
                self._scan_cache = tinytuya.deviceScan(False, SCAN_SECONDS) or {}
            except Exception:  # noqa: BLE001
                self._scan_cache = {}
        for ip, info in (self._scan_cache or {}).items():
            gw = info.get("gwId") or info.get("id") or ""
            if gw == dev["id"] and ip and ip != dev["ip"]:
                dev["ip"] = ip
                self._drop_conn(dev["key"])
                with self._lock:
                    self._state[dev["key"]]["ip"] = ip
                print(f"[smarthome] {dev['key']} IP atualizado p/ {ip} (DHCP)", flush=True)
                return True
        return False

    def _try_read(self, dev: dict) -> bool:
        """Lê o estado uma vez. True se online; marca offline e False se falhou."""
        try:
            data = self._conn(dev).status()
            if not isinstance(data, dict) or "dps" not in data:
                err = data.get("Error", "sem resposta") if isinstance(data, dict) else "sem resposta"
                raise RuntimeError(err)
            on = bool(data["dps"].get(SWITCH_DP))
            with self._lock:
                self._state[dev["key"]].update(on=on, online=True, err="")
            return True
        except Exception as e:  # noqa: BLE001 — rede/tomada offline: marca e segue
            self._drop_conn(dev["key"])
            with self._lock:
                self._state[dev["key"]].update(online=False, err=str(e)[:40])
            return False

    def _read(self, dev: dict) -> None:
        # falhou no IP atual? pode ter trocado de IP (DHCP): redescobre e tenta de novo
        if not self._try_read(dev) and self._rediscover(dev):
            self._try_read(dev)

    def _try_switch(self, dev: dict, on: bool) -> bool:
        try:
            c = self._conn(dev)
            if on:
                c.turn_on(switch=SWITCH_DP)
            else:
                c.turn_off(switch=SWITCH_DP)
            with self._lock:
                self._state[dev["key"]].update(on=on, online=True, err="")
            return True
        except Exception as e:  # noqa: BLE001
            self._drop_conn(dev["key"])
            with self._lock:
                self._state[dev["key"]].update(err=str(e)[:40])
            return False

    def _apply(self, key: str, on: bool) -> None:
        dev = next((d for d in self._devices if d["key"] == key), None)
        if dev is None:
            return
        # comando falhou? redescobre o IP (DHCP) e reenvia, pra não perder o toque
        if not self._try_switch(dev, on) and self._rediscover(dev):
            self._try_switch(dev, on)

    def _loop(self) -> None:
        for d in self._devices:        # leitura inicial
            self._read(d)
        while True:
            try:                       # comandos primeiro (responsivo)
                while True:
                    key, on = self._cmd_q.get_nowait()
                    self._apply(key, on)
            except queue.Empty:
                pass
            for d in self._devices:    # poll do estado real
                self._read(d)
            self._wake.wait(POLL_INTERVAL)
            self._wake.clear()
