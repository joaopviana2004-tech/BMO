"""Controle dos coolers (fans) via GPIO — refrigeração ativa do BMO.

Dois coolers ligados aos GPIO 17 (pino físico 11) e GPIO 23 (pino físico 16).
Cada pino aciona um transistor/MOSFET (ou módulo de relé) que chaveia o 5V do
cooler — NUNCA ligue o motor direto no pino do GPIO (3.3V / ~16mA não dão conta
e queimam a Pi). Troque os pinos com as envs COOLER_GPIO_1 / COOLER_GPIO_2.

Liga em dois casos (OR):
  - manual: o usuário ativa pelo atalho da tela SISTEMA (config cooler_enabled).
  - automático: a temperatura passou do limite (>= ON_TEMP_C). Histerese
    (só desliga o automático abaixo de OFF_TEMP_C) evita o cooler pisca-pisca.

Estado efetivo = manual OR automático — é ele que move os pinos e o ícone que
gira na tela. Degrada com elegância: sem gpiozero ou fora do Pi, ok=False e o
estado vira só visual (o ícone ainda gira, mas nenhum pino é acionado).
"""
from __future__ import annotations

import os
import threading

try:
    from gpiozero import OutputDevice
    HAS_GPIO = True
except Exception:  # pragma: no cover - só roda no Pi
    OutputDevice = None  # type: ignore
    HAS_GPIO = False

# GPIO BCM dos dois coolers (pinos físicos 11 e 16)
COOLER_PINS = (
    int(os.environ.get("COOLER_GPIO_1", "17")),
    int(os.environ.get("COOLER_GPIO_2", "23")),
)
ON_TEMP_C = 60.0    # liga sozinho a partir desta temperatura
OFF_TEMP_C = 55.0   # histerese: só desliga o automático abaixo disso
POLL_S = 2.0        # de quanto em quanto relê a temperatura


class CoolerService:
    """Aciona os dois coolers conforme o override manual + a temperatura.

    get_temp: callable que devolve a temp em °C (ou None no dev/sem leitura).
              Tipicamente `lambda: sysinfo.get().temp_c`.
    """

    def __init__(self, get_temp=None) -> None:
        self.ok = False
        self.error = ""
        self._get_temp = get_temp
        self._devices: list = []
        self._lock = threading.Lock()
        self._manual = False     # override do atalho (liga/desliga)
        self._auto = False       # ligado pela temperatura (histerese)
        self._on = False         # estado efetivo (o que está nos pinos)
        self._init_gpio()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _init_gpio(self) -> None:
        if not HAS_GPIO:
            self.error = "gpiozero indisponivel"
            return
        try:
            self._devices = [
                OutputDevice(p, active_high=True, initial_value=False)
                for p in COOLER_PINS
            ]
            self.ok = True
        except Exception as e:
            self.error = f"gpio: {str(e)[:50]}"
            self._devices = []

    # ---------- controle manual (atalho da tela SISTEMA) ----------

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._manual = bool(value)
            self._drive_locked()

    def toggle(self) -> bool:
        """Inverte o override manual e devolve o novo valor (pra persistir)."""
        with self._lock:
            self._manual = not self._manual
            self._drive_locked()
            return self._manual

    # ---------- estado (lido pela tela; bool simples = sem lock) ----------

    @property
    def enabled(self) -> bool:
        """Override manual ligado?"""
        return self._manual

    @property
    def auto_on(self) -> bool:
        """Ligado pela temperatura (acima de 60°C)?"""
        return self._auto

    @property
    def on(self) -> bool:
        """Estado efetivo — é o que faz o ícone girar."""
        return self._on

    # ---------- loop de temperatura ----------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._tick()
            self._stop.wait(POLL_S)

    def _tick(self) -> None:
        temp = None
        if self._get_temp is not None:
            try:
                temp = self._get_temp()
            except Exception:
                temp = None
        with self._lock:
            if temp is not None:
                if temp >= ON_TEMP_C:
                    self._auto = True
                elif temp <= OFF_TEMP_C:
                    self._auto = False
                # entre OFF e ON: mantém o último estado (histerese)
            self._drive_locked()

    def _drive_locked(self) -> None:
        """Aplica manual OR automático aos pinos. Pressupõe o lock já tomado
        (evita reentrância e chamadas concorrentes ao gpiozero)."""
        target = self._manual or self._auto
        if target == self._on:
            return
        self._on = target
        for d in self._devices:
            try:
                d.on() if target else d.off()
            except Exception:
                pass

    def close(self) -> None:
        """Desliga e libera os pinos. Necessário antes do execv do restart: o
        lgpio deixa o fd aberto e o processo novo não reivindica o pino."""
        self._stop.set()
        with self._lock:
            for d in self._devices:
                try:
                    d.off()
                    d.close()
                except Exception:
                    pass
            self._devices = []
            self._on = False
        self.ok = False
