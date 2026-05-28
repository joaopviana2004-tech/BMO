"""Tela de Settings — estilo CRT P&B.

Botão de atualizar (git pull + restart). Lista vertical.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pygame

from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

MENU_ITEMS = ["Atualizar (git pull)", "Voltar"]


class SettingsScreen:
    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self._index = 0
        self._status = ""
        self._action: str | None = None
        self._delay_until = 0.0
        self._t = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        if self._action is not None:
            return
        action = event.action
        if action == bmo_input.Action.UP:
            self._index = (self._index - 1) % len(MENU_ITEMS)
        elif action == bmo_input.Action.DOWN:
            self._index = (self._index + 1) % len(MENU_ITEMS)
        elif action == bmo_input.Action.A:
            self._activate()
        elif action == bmo_input.Action.B:
            self.on_back()
        elif action == bmo_input.Action.TAP and event.pos is not None:
            self._handle_tap(event.pos)

    def _handle_tap(self, pos: tuple[int, int]) -> None:
        for i, rect in enumerate(self._row_rects()):
            if rect.collidepoint(pos):
                if i == self._index:
                    self._activate()
                else:
                    self._index = i
                return

    def _activate(self) -> None:
        if self._index == 0:
            self._status = "Atualizando..."
            self._action = "pull"
        else:
            self.on_back()

    def update(self, dt: float) -> None:
        self._t += dt
        if self._action == "pull":
            self._action = None
            self._do_pull()
        elif self._action == "restart" and self._t >= self._delay_until:
            self._action = None
            self._restart()

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface)
        self._draw_title(surface)
        self._draw_menu(surface)
        if self._status:
            bright = "OK" in self._status or "Atualizando" in self._status
            color = CRT_WHITE if bright else CRT_DIM
            msg = render_text(self._status, 9, color)
            surface.blit(msg, msg.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - 12)))

    def _row_rects(self):
        top = 48
        return [pygame.Rect(24, top + i * 30, LOGICAL_SIZE[0] - 48, 24) for i in range(len(MENU_ITEMS))]

    def _draw_title(self, surface: pygame.Surface) -> None:
        img = render_text("SETTINGS", 10, CRT_DIM)
        surface.blit(img, img.get_rect(midtop=(LOGICAL_SIZE[0] // 2, 20)))

    def _draw_menu(self, surface: pygame.Surface) -> None:
        for i, (label, rect) in enumerate(zip(MENU_ITEMS, self._row_rects())):
            selected = (i == self._index)
            if selected:
                pygame.draw.rect(surface, CRT_WHITE, rect)
                # seta
                arrow = [
                    (rect.left + 6, rect.centery - 5),
                    (rect.left + 6, rect.centery + 5),
                    (rect.left + 14, rect.centery),
                ]
                pygame.draw.polygon(surface, CRT_BLACK, arrow)
                txt = render_text(label.upper(), 10, CRT_BLACK)
                surface.blit(txt, txt.get_rect(midleft=(rect.left + 20, rect.centery)))
            else:
                txt = render_text(label.upper(), 10, CRT_DIM)
                surface.blit(txt, txt.get_rect(midleft=(rect.left + 8, rect.centery)))

    # ----- ações -----

    def _do_pull(self) -> None:
        try:
            result = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "pull", "--ff-only"],
                capture_output=True, text=True, timeout=60, check=False,
            )
        except FileNotFoundError:
            self._status = "git nao instalado"
            return
        except Exception as e:
            self._status = ("Erro: " + str(e))[:36]
            return

        output = (result.stdout + " " + result.stderr).lower()
        if result.returncode != 0:
            first = (result.stderr or result.stdout).strip().split("\n", 1)[0]
            self._status = ("Falhou: " + first)[:36]
            return
        if "already up to date" in output or "ja atualizado" in output:
            self._status = "Ja na versao mais nova!"
            return
        self._status = "OK! Reiniciando..."
        self._delay_until = self._t + 1.5
        self._action = "restart"

    def _restart(self) -> None:
        pygame.quit()
        os.execv(sys.executable, [sys.executable, *sys.argv])
