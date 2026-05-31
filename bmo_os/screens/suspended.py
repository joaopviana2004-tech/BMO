"""Tela SUSPENSO — desliga o display e reduz processamento até o user tocar.

Diferente do ambient (lock screen mas tela ligada), suspended:
- Desliga o display via `vcgencmd display_power 0` (Pi) ou backlight sysfs
- Reduz o FPS pra ~5 (App lê `preferred_fps`)
- Libera a câmera automaticamente (vem do enter→exit padrão do screen stack)
- Qualquer toque/tecla acorda → on_wake() → display volta + ambient

No Windows dev (ou se vcgencmd falhar), só fica preto sem desligar nada —
ainda assim economiza um cadinho de CPU pela queda de FPS.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE


_BACKLIGHT_GLOB = "/sys/class/backlight"


def _toggle_display(on: bool) -> None:
    """Liga/desliga o display físico. Tenta vcgencmd primeiro, depois sysfs."""
    state = "1" if on else "0"
    # Pi: vcgencmd display_power 0/1
    try:
        subprocess.run(
            ["vcgencmd", "display_power", state],
            check=False, timeout=2, capture_output=True,
        )
    except Exception:
        pass
    # Fallback: sysfs backlight (bl_power: 0=ON, 1=OFF — convenção FB_BLANK)
    try:
        for p in Path(_BACKLIGHT_GLOB).glob("*/bl_power"):
            try:
                p.write_text("0" if on else "1")
            except Exception:
                continue
    except Exception:
        pass


class SuspendedScreen:
    """Display OFF + FPS baixo. Toque acorda."""

    # App.run lê isso pra dropar o tick_rate enquanto suspended
    preferred_fps = 5

    def __init__(self, on_wake) -> None:
        self.on_wake = on_wake
        self._waking = False

    def enter(self) -> None:
        _toggle_display(False)

    def exit(self) -> None:
        # garantia: liga display ao sair, caso enter() de outra screen
        # demore a desenhar
        _toggle_display(True)

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._waking:
            return
        # qualquer ACTION (TAP/A/B/MENU/seta) acorda
        if event.type == bmo_input.ACTION_EVENT:
            self._waking = True
            self.on_wake()

    def update(self, dt: float) -> None: ...

    def draw(self, surface: pygame.Surface) -> None:
        # display tá desligado então não importa muito, mas preenche preto
        # caso o display ainda esteja ligado (vcgencmd falhou no Windows)
        surface.fill((0, 0, 0))
