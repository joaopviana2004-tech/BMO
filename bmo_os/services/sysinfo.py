"""Telemetria de hardware da Raspberry Pi (CPU, GPU, RAM, temp, tensão).

Roda em thread (igual weather/todoist) e expõe um snapshot + histórico de
temperatura pro gráfico. Tudo é lido de /proc, /sys e vcgencmd — cada leitura
é embrulhada em try/except e vira None no PC de dev (sem Pi), então a tela
mostra "--" sem quebrar (mesma filosofia da câmera offline).

Notas:
- "GPU": a Pi não expõe uso real da GPU de forma simples. Usamos o clock do
  V3D (vcgencmd measure_clock v3d) como PROXY de atividade — o valor exibido
  é o clock em MHz; a barra é clock/GPU_MAX_MHZ.
- throttled: bitmask do `vcgencmd get_throttled` (sub-tensão / throttling).
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass

POLL_S = 2.0
HISTORY_LEN = 150            # 5 min de histórico de temperatura a 2s
GPU_MAX_MHZ = 600.0          # nominal pra estimar "uso" do V3D (proxy)

# bits do get_throttled que indicam problema ACONTECENDO agora
THROTTLE_NOW_MASK = 0x7      # bit0 sub-tensão, bit1 freq capada, bit2 throttling


@dataclass
class SysSnapshot:
    cpu_pct: float | None = None
    gpu_mhz: float | None = None
    gpu_pct: float | None = None
    ram_pct: float | None = None
    ram_used_mb: float | None = None
    ram_total_mb: float | None = None
    temp_c: float | None = None
    volts: float | None = None
    throttled: int | None = None
    ok: bool = False
    fetched_at: float = 0.0


class SysInfoService:
    def __init__(self) -> None:
        self.snapshot = SysSnapshot()
        self._lock = threading.Lock()
        self._temp_hist: deque = deque(maxlen=HISTORY_LEN)
        self._prev_cpu: tuple[float, float] | None = None   # (idle, total)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            self._poll()
            time.sleep(POLL_S)

    def _poll(self) -> None:
        cpu = self._read_cpu()
        temp = self._read_temp()
        ram_used, ram_total = self._read_ram()
        volts = self._read_volts()
        gpu_mhz = self._read_gpu_clock()
        throttled = self._read_throttled()

        ram_pct = (ram_used / ram_total * 100) if (ram_used and ram_total) else None
        gpu_pct = min(100.0, gpu_mhz / GPU_MAX_MHZ * 100) if gpu_mhz else None
        ok = any(v is not None for v in (cpu, temp, ram_pct))

        with self._lock:
            if temp is not None:
                self._temp_hist.append(temp)
            self.snapshot = SysSnapshot(
                cpu_pct=cpu, gpu_mhz=gpu_mhz, gpu_pct=gpu_pct,
                ram_pct=ram_pct, ram_used_mb=ram_used, ram_total_mb=ram_total,
                temp_c=temp, volts=volts, throttled=throttled,
                ok=ok, fetched_at=time.time(),
            )

    # ---------- leituras (None no dev) ----------

    def _read_cpu(self) -> float | None:
        try:
            with open("/proc/stat") as f:
                parts = [float(x) for x in f.readline().split()[1:]]
            idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
            total = sum(parts)
            prev = self._prev_cpu
            self._prev_cpu = (idle, total)
            if prev is None:
                return None
            d_idle = idle - prev[0]
            d_total = total - prev[1]
            if d_total <= 0:
                return None
            return max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0))
        except Exception:
            return None

    def _read_temp(self) -> float | None:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return int(f.read().strip()) / 1000.0
        except Exception:
            pass
        out = self._vcgencmd("measure_temp")     # temp=45.6'C
        if out:
            m = re.search(r"([\d.]+)", out)
            if m:
                return float(m.group(1))
        return None

    def _read_ram(self) -> tuple[float | None, float | None]:
        try:
            info: dict[str, str] = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, _, rest = line.partition(":")
                    info[k.strip()] = rest.strip()
            total_kb = float(info["MemTotal"].split()[0])
            avail_kb = float(info.get("MemAvailable", info.get("MemFree", "0")).split()[0])
            return (total_kb - avail_kb) / 1024.0, total_kb / 1024.0
        except Exception:
            return None, None

    def _read_volts(self) -> float | None:
        out = self._vcgencmd("measure_volts core")   # volt=0.8625V
        if out:
            m = re.search(r"([\d.]+)", out)
            if m:
                return float(m.group(1))
        return None

    def _read_gpu_clock(self) -> float | None:
        out = self._vcgencmd("measure_clock v3d")     # frequency(46)=500000000
        if out:
            m = re.search(r"=(\d+)", out)
            if m:
                return int(m.group(1)) / 1e6
        return None

    def _read_throttled(self) -> int | None:
        out = self._vcgencmd("get_throttled")          # throttled=0x0
        if out:
            m = re.search(r"0x([0-9a-fA-F]+)", out)
            if m:
                return int(m.group(1), 16)
        return None

    @staticmethod
    def _vcgencmd(args: str) -> str | None:
        try:
            res = subprocess.run(
                ["vcgencmd", *args.split()],
                capture_output=True, text=True, timeout=2, check=False,
            )
            return res.stdout.strip()
        except Exception:
            return None

    # ---------- acesso ----------

    def get(self) -> SysSnapshot:
        with self._lock:
            return self.snapshot

    def temp_history(self) -> list:
        with self._lock:
            return list(self._temp_hist)
