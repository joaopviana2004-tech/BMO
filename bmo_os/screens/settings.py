"""Tela de Settings — estilo CRT P&B.

Lista vertical com:
- Standby (timer de auto-volta da home, em segundos)
- Ambient (modo do bloqueio: RELOGIO ou BMO FACE)
- Atualizar (git pull + restart)
- Desligar (shutdown — exige confirmação dupla em 3s)
- Voltar

Itens 'cycle' giram o valor com LEFT/RIGHT (ou TAP cicla pra frente).
Itens 'action' disparam com A/TAP.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pygame

from ..core import config, theme_state
from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _fmt_timeout(v) -> str:
    return f"{int(v)}S"


def _fmt_ambient(v) -> str:
    return config.AMBIENT_MODE_LABELS.get(v, str(v).upper())


def _fmt_theme(v) -> str:
    return theme_state.THEME_LABELS.get(v, str(v).upper())


ITEMS = [
    {
        "type": "cycle",
        "key": "idle_timeout_s",
        "label": "Standby",
        "options": config.IDLE_TIMEOUT_OPTIONS,
        "format": _fmt_timeout,
    },
    {
        "type": "cycle",
        "key": "ambient_mode",
        "label": "Ambient",
        "options": config.AMBIENT_MODE_OPTIONS,
        "format": _fmt_ambient,
    },
    {
        "type": "cycle",
        "key": "theme",
        "label": "Tema",
        "options": theme_state.THEME_OPTIONS,
        "format": _fmt_theme,
    },
    {"type": "action", "key": "update", "label": "Atualizar"},
    {"type": "action", "key": "shutdown", "label": "Desligar"},
    {"type": "action", "key": "back", "label": "Voltar"},
]

SHUTDOWN_CONFIRM_S = 3.0


class SettingsScreen:
    def __init__(self, on_back, on_ambient_changed=None) -> None:
        self.on_back = on_back
        self.on_ambient_changed = on_ambient_changed
        self._index = 0
        self._status = ""
        self._action: str | None = None
        self._delay_until = 0.0
        self._shutdown_confirm_until = 0.0
        self._t = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        if self._action is not None:
            return
        action = event.action
        if action == bmo_input.Action.UP:
            self._index = (self._index - 1) % len(ITEMS)
        elif action == bmo_input.Action.DOWN:
            self._index = (self._index + 1) % len(ITEMS)
        elif action == bmo_input.Action.LEFT:
            self._cycle_current(-1)
        elif action == bmo_input.Action.RIGHT:
            self._cycle_current(+1)
        elif action == bmo_input.Action.A:
            self._activate()
        elif action == bmo_input.Action.B:
            self.on_back()
        elif action == bmo_input.Action.TAP and event.pos is not None:
            self._handle_tap(event.pos)

    def _handle_tap(self, pos: tuple[int, int]) -> None:
        # toque na seta esq/dir do item selecionado
        rect = self._row_rects()[self._index]
        if self._left_arrow_rect(rect).collidepoint(pos):
            self._cycle_current(-1)
            return
        if self._right_arrow_rect(rect).collidepoint(pos):
            self._cycle_current(+1)
            return
        for i, r in enumerate(self._row_rects()):
            if r.collidepoint(pos):
                if i == self._index:
                    self._activate()
                else:
                    self._index = i
                return

    def _cycle_current(self, direction: int) -> None:
        item = ITEMS[self._index]
        if item["type"] != "cycle":
            return
        current = config.get(item["key"])
        options = item["options"]
        try:
            idx = options.index(current)
        except ValueError:
            idx = 0
        new_idx = (idx + direction) % len(options)
        new_val = options[new_idx]
        config.set_value(item["key"], new_val)
        if item["key"] == "ambient_mode" and self.on_ambient_changed is not None:
            self.on_ambient_changed(new_val)

    def _activate(self) -> None:
        item = ITEMS[self._index]
        if item["type"] == "cycle":
            self._cycle_current(+1)
            return
        if item["key"] == "update":
            self._status = "Atualizando..."
            self._action = "pull"
        elif item["key"] == "shutdown":
            if self._t < self._shutdown_confirm_until:
                self._status = "Desligando..."
                self._action = "shutdown"
            else:
                self._shutdown_confirm_until = self._t + SHUTDOWN_CONFIRM_S
                self._status = "Toque DESLIGAR de novo p/ confirmar"
        elif item["key"] == "back":
            self.on_back()

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        if self._action == "pull":
            self._action = None
            self._do_pull()
        elif self._action == "restart" and self._t >= self._delay_until:
            self._action = None
            self._restart()
        elif self._action == "shutdown":
            self._action = None
            self._do_shutdown()
        # cancela confirmação de shutdown se expirou
        if (
            self._shutdown_confirm_until > 0
            and self._t >= self._shutdown_confirm_until
            and self._status.startswith("Toque DESLIGAR")
        ):
            self._shutdown_confirm_until = 0.0
            self._status = ""

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface)
        theme_state.draw_status_bar(surface)
        self._draw_title(surface)
        self._draw_menu(surface)
        if self._status:
            bright = "OK" in self._status or "Atualizando" in self._status
            color = CRT_WHITE if bright else CRT_DIM
            msg = render_text(self._status, 9, color)
            surface.blit(msg, msg.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - 12)))

    def _row_rects(self):
        top = 38
        step = 26
        return [pygame.Rect(20, top + i * step, LOGICAL_SIZE[0] - 40, 22) for i in range(len(ITEMS))]

    def _left_arrow_rect(self, row: pygame.Rect) -> pygame.Rect:
        return pygame.Rect(row.right - 38, row.top, 16, row.height)

    def _right_arrow_rect(self, row: pygame.Rect) -> pygame.Rect:
        return pygame.Rect(row.right - 16, row.top, 16, row.height)

    def _draw_title(self, surface: pygame.Surface) -> None:
        img = render_text("SETTINGS", 10, CRT_DIM)
        surface.blit(img, img.get_rect(midtop=(LOGICAL_SIZE[0] // 2, 18)))

    def _draw_menu(self, surface: pygame.Surface) -> None:
        for i, (item, rect) in enumerate(zip(ITEMS, self._row_rects())):
            selected = (i == self._index)
            fg = CRT_BLACK if selected else CRT_DIM
            if selected:
                pygame.draw.rect(surface, CRT_WHITE, rect)
                arrow = [
                    (rect.left + 5, rect.centery - 4),
                    (rect.left + 5, rect.centery + 4),
                    (rect.left + 11, rect.centery),
                ]
                pygame.draw.polygon(surface, CRT_BLACK, arrow)
                label_x = rect.left + 16
            else:
                label_x = rect.left + 8

            label_txt = item["label"].upper()
            if item.get("key") == "shutdown" and self._t < self._shutdown_confirm_until:
                label_txt = "DESLIGAR?"
            label = render_text(label_txt, 9, fg)
            surface.blit(label, label.get_rect(midleft=(label_x, rect.centery)))

            if item["type"] == "cycle":
                val = item["format"](config.get(item["key"]))
                val_img = render_text(val, 9, fg)
                # valor à direita; setas só quando selecionado
                if selected:
                    val_x = rect.right - 28
                    surface.blit(val_img, val_img.get_rect(midright=(val_x, rect.centery)))
                    # < >
                    la = self._left_arrow_rect(rect)
                    ra = self._right_arrow_rect(rect)
                    pygame.draw.polygon(surface, CRT_BLACK, [
                        (la.right - 3, la.centery - 4),
                        (la.right - 3, la.centery + 4),
                        (la.left + 3, la.centery),
                    ])
                    pygame.draw.polygon(surface, CRT_BLACK, [
                        (ra.left + 3, ra.centery - 4),
                        (ra.left + 3, ra.centery + 4),
                        (ra.right - 3, ra.centery),
                    ])
                else:
                    surface.blit(val_img, val_img.get_rect(midright=(rect.right - 8, rect.centery)))

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

    def _do_shutdown(self) -> None:
        pygame.quit()
        if sys.platform == "win32":
            os.system("shutdown /s /t 0")
        else:
            # Pi: precisa de passwordless sudo pra shutdown
            # (`sudo visudo` -> `gravae ALL=(ALL) NOPASSWD: /sbin/shutdown`)
            rc = os.system("sudo -n shutdown -h now")
            if rc != 0:
                os.system("shutdown -h now")
        sys.exit(0)
