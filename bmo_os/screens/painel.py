"""PAINEL — abre o painel web da Plataforma (Secretaria) em tela cheia.

Quadro kanban e contas do mes vem da mesma Plataforma que a tela TASKS ja
consome, mas aqui na interface web dela (rota /mini), desenhada para os
800x480 desta tela. Sobe o Chromium por cima do pygame e o mata ao voltar.

Por que Chromium e nao mais uma tela em pygame: TASKS ja e a versao nativa e
resumida. Este app existe justamente para dar a visao completa — colunas com
prazo, contas do mes com fatura de cartao — sem reimplementar tudo aqui.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)
from ..services.plataforma import _base_url

# Ordem de preferencia: o Raspberry Pi OS instala como "chromium".
NAVEGADORES = ("chromium", "chromium-browser")


def _navegador() -> str | None:
    for nome in NAVEGADORES:
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    return None


class PainelScreen:
    """Enquanto o navegador esta aberto esta tela fica atras, so esperando.

    `preferred_fps = 5` porque redesenhar 30x por segundo uma tela coberta
    seria disputar CPU com o Chromium — que e justamente quem precisa dela.
    """

    preferred_fps = 5

    def __init__(self, on_back, url: str | None = None) -> None:
        self.on_back = on_back
        self.url = url or f"{_base_url()}/mini"
        self.proc: subprocess.Popen | None = None
        self.erro: str | None = None

    # -- ciclo de vida ------------------------------------------------------
    def enter(self) -> None:
        exe = _navegador()
        if not exe:
            self.erro = "CHROMIUM NAO ENCONTRADO"
            return
        # Sem isto o Chromium tenta o backend X11 e morre com "Missing X server
        # or $DISPLAY" — o Pi OS boota Wayland (labwc). Condicional para nao
        # quebrar quem rodar o BMO sob X11.
        ozone = ["--ozone-platform=wayland"] if os.environ.get("WAYLAND_DISPLAY") else []
        try:
            self.proc = subprocess.Popen(
                [
                    exe,
                    *ozone,
                    "--kiosk",
                    # --app tira toda a barra de navegacao; --kiosk garante o
                    # fullscreen sobre a janela do pygame.
                    f"--app={self.url}",
                    "--noerrdialogs",
                    "--disable-infobars",
                    "--disable-session-crashed-bubble",
                    "--check-for-update-interval=31536000",
                    # A tela e touch: sem isto o Chromium fica esperando um
                    # mouse e o toque nao rola as colunas.
                    "--touch-events=enabled",
                    "--overscroll-history-navigation=0",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:  # navegador quebrado, permissao, etc.
            self.erro = str(e)[:40].upper()

    def exit(self) -> None:
        self._fechar()

    def _fechar(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Chromium as vezes ignora o SIGTERM se estiver num dialogo;
                # deixar processo orfao roubaria a tela do BMO para sempre.
                self.proc.kill()
        self.proc = None

    # -- eventos ------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        if event.action in (bmo_input.Action.B, bmo_input.Action.TAP):
            self._fechar()
            self.on_back()

    def update(self, dt: float) -> None:
        # O usuario pode ter fechado o navegador por fora: sem isto o BMO
        # ficaria preso nesta tela de aviso com nada por cima.
        if self.proc is not None and self.proc.poll() is not None:
            self.proc = None
            self.on_back()

    # -- desenho ------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)

        cx = LOGICAL_SIZE[0] // 2
        titulo = render_text("PAINEL", 10, CRT_DIM)
        surface.blit(titulo, titulo.get_rect(midtop=(cx, SAFE_INSET + 6)))

        if self.erro:
            msg = render_text(self.erro, 10, CRT_WHITE)
            surface.blit(msg, msg.get_rect(center=(cx, LOGICAL_SIZE[1] // 2 - 8)))
        else:
            msg = render_text("PAINEL ABERTO", 16, CRT_WHITE)
            surface.blit(msg, msg.get_rect(center=(cx, LOGICAL_SIZE[1] // 2 - 8)))

        hint = render_text("TOQUE = VOLTAR AO BMO", 8, CRT_DIM)
        surface.blit(hint, hint.get_rect(midbottom=(cx, LOGICAL_SIZE[1] - SAFE_INSET - 4)))
