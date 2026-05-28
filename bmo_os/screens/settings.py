"""Tela de Settings (V1.1) — botão de atualizar (git pull + restart).

Lista vertical estilo BMO. Selecionar "Atualizar" faz:
    1. git pull --ff-only na raiz do repo
    2. mostra mensagem de resultado
    3. se houve update OK, re-executa o processo (os.execv)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pygame

from ..core import input as bmo_input
from ..core.theme import Colors, render_text
from ..core.widgets import ListMenu, MenuItem, draw_header

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class SettingsScreen:
    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self.menu = ListMenu(
            [
                MenuItem("Atualizar (git pull)", on_select=self._request_update),
                MenuItem("Voltar", on_select=on_back),
            ],
            top=46,
            row_h=28,
        )
        self._status = ""
        # state machine: None -> "pull" -> "restart"
        # pull e restart rodam no update() seguinte pra dar tempo de renderizar
        self._action: str | None = None
        self._delay_until = 0.0
        self._t = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        if self._action is not None:
            # bloqueia input enquanto atualiza / espera restart
            return
        action = event.action
        if action == bmo_input.Action.UP:
            self.menu.move(-1)
        elif action == bmo_input.Action.DOWN:
            self.menu.move(1)
        elif action == bmo_input.Action.A:
            self.menu.activate()
        elif action == bmo_input.Action.B:
            self.on_back()
        elif action == bmo_input.Action.TAP and event.pos is not None:
            self.menu.handle_tap(event.pos)

    def update(self, dt: float) -> None:
        self._t += dt
        if self._action == "pull":
            self._action = None
            self._do_pull()
        elif self._action == "restart" and self._t >= self._delay_until:
            self._action = None
            self._restart()

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(Colors.BG_DARK)
        draw_header(surface, "SETTINGS")
        self.menu.draw(surface)
        if self._status:
            color = Colors.YELLOW if "OK" in self._status or "Atualizando" in self._status else Colors.CYAN_DIM
            msg = render_text(self._status, 9, color)
            surface.blit(msg, msg.get_rect(midbottom=(surface.get_width() // 2, surface.get_height() - 12)))

    # ----- ações -----

    def _request_update(self) -> None:
        self._status = "Atualizando..."
        self._action = "pull"

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
            first_line = (result.stderr or result.stdout).strip().split("\n", 1)[0]
            self._status = ("Falhou: " + first_line)[:36]
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
