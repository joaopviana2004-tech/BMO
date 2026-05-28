"""Tela home — carrossel de modos.

Estilo CRT P&B: fundo preto, scanlines, brackets nos cantos.
Auto-volta pro relógio depois de 10s sem input.
"""
from __future__ import annotations

import math

import pygame

from ..core import config
from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)

ITEMS = ["DISPLAY", "SLEEP", "GAMES", "SETTINGS"]
ICONS = ["display", "sleep", "games", "settings"]


def _icon_display(surf: pygame.Surface, cx: int, cy: int) -> None:
    body = pygame.Rect(0, 0, 44, 30)
    body.center = (cx, cy - 4)
    pygame.draw.rect(surf, CRT_WHITE, body, 2)
    foot = pygame.Rect(0, 0, 16, 5)
    foot.midtop = (cx, body.bottom + 1)
    pygame.draw.rect(surf, CRT_WHITE, foot)
    base = pygame.Rect(0, 0, 24, 2)
    base.midtop = (cx, foot.bottom)
    pygame.draw.rect(surf, CRT_WHITE, base)


def _icon_sleep(surf: pygame.Surface, cx: int, cy: int) -> None:
    body = pygame.Rect(0, 0, 36, 28)
    body.center = (cx, cy - 2)
    pygame.draw.rect(surf, CRT_WHITE, body, 2, border_radius=5)
    # olho fechado (linha)
    pygame.draw.line(surf, CRT_DIM, (body.left + 8, body.centery - 3), (body.left + 14, body.centery - 3), 2)
    pygame.draw.line(surf, CRT_DIM, (body.right - 14, body.centery - 3), (body.right - 8, body.centery - 3), 2)
    # boca
    pygame.draw.line(surf, CRT_DIM, (cx - 5, body.centery + 6), (cx + 5, body.centery + 6), 2)
    # z z z
    for i, ch in enumerate(["z", "z"]):
        img = render_text(ch, 8, CRT_DIM)
        surf.blit(img, (body.right + 2 + i * 6, body.top + 2 + i * 5))


def _icon_games(surf: pygame.Surface, cx: int, cy: int) -> None:
    pad = pygame.Rect(0, 0, 42, 26)
    pad.center = (cx, cy - 2)
    pygame.draw.rect(surf, CRT_WHITE, pad, 2, border_radius=6)
    # dpad
    dx, dy = pad.left + 10, pad.centery
    pygame.draw.line(surf, CRT_WHITE, (dx - 5, dy), (dx + 5, dy), 2)
    pygame.draw.line(surf, CRT_WHITE, (dx, dy - 5), (dx, dy + 5), 2)
    # botões
    pygame.draw.circle(surf, CRT_WHITE, (pad.right - 12, pad.centery - 3), 3, 2)
    pygame.draw.circle(surf, CRT_WHITE, (pad.right - 5, pad.centery + 3), 3, 2)


def _icon_settings(surf: pygame.Surface, cx: int, cy: int) -> None:
    pygame.draw.circle(surf, CRT_WHITE, (cx, cy - 2), 12, 2)
    pygame.draw.circle(surf, CRT_WHITE, (cx, cy - 2), 4, 2)
    for i in range(6):
        ang = i * math.pi / 3
        x1 = cx + int(math.cos(ang) * 13)
        y1 = (cy - 2) + int(math.sin(ang) * 13)
        x2 = cx + int(math.cos(ang) * 17)
        y2 = (cy - 2) + int(math.sin(ang) * 17)
        pygame.draw.line(surf, CRT_WHITE, (x1, y1), (x2, y2), 3)


_DRAW_ICON = [_icon_display, _icon_sleep, _icon_games, _icon_settings]


class HomeScreen:
    def __init__(self, *, on_back, on_open_sleep, on_open_games, on_open_settings) -> None:
        self.on_back = on_back
        self._on_select = [lambda: None, on_open_sleep, on_open_games, on_open_settings]
        self.on_open_games = on_open_games
        self.on_open_settings = on_open_settings
        self._index = 0
        self._idle = 0.0
        self._timed_out = False
        self._t = 0.0

    def enter(self) -> None:
        self._idle = 0.0
        self._timed_out = False

    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        self._idle = 0.0
        action = event.action
        if action == bmo_input.Action.LEFT:
            self._index = (self._index - 1) % len(ITEMS)
        elif action == bmo_input.Action.RIGHT:
            self._index = (self._index + 1) % len(ITEMS)
        elif action == bmo_input.Action.A:
            self._on_select[self._index]()
        elif action == bmo_input.Action.B:
            self.on_back()
        elif action == bmo_input.Action.TAP and event.pos is not None:
            self._handle_tap(event.pos)

    def _handle_tap(self, pos: tuple[int, int]) -> None:
        cx, cy = LOGICAL_SIZE[0] // 2, 110
        # seta esq
        if pygame.Rect(16, cy - 12, 24, 24).collidepoint(pos):
            self._index = (self._index - 1) % len(ITEMS)
            return
        # seta dir
        if pygame.Rect(LOGICAL_SIZE[0] - 40, cy - 12, 24, 24).collidepoint(pos):
            self._index = (self._index + 1) % len(ITEMS)
            return
        # ícone central
        if pygame.Rect(0, 0, 60, 60).move(cx - 30, cy - 30).collidepoint(pos):
            self._on_select[self._index]()

    def update(self, dt: float) -> None:
        self._t += dt
        self._idle += dt
        timeout = float(config.get("idle_timeout_s") or 10)
        if self._idle >= timeout and not self._timed_out:
            self._timed_out = True
            self.on_back()

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface)
        self._draw_carousel(surface)
        self._draw_hint(surface)

    def _draw_carousel(self, surface: pygame.Surface) -> None:
        cx = LOGICAL_SIZE[0] // 2
        cy = 110
        bob = int(math.sin(self._t * 3) * 2)
        bob_arr = int(math.sin(self._t * 4) * 2)

        # seta esq
        lx = 28 - bob_arr
        pts_l = [(lx + 10, cy - 10), (lx + 10, cy + 10), (lx, cy)]
        pygame.draw.polygon(surface, CRT_WHITE, pts_l)

        # seta dir
        rx = LOGICAL_SIZE[0] - 28 + bob_arr
        pts_r = [(rx - 10, cy - 10), (rx - 10, cy + 10), (rx, cy)]
        pygame.draw.polygon(surface, CRT_WHITE, pts_r)

        # ícone
        _DRAW_ICON[self._index](surface, cx, cy + bob)

        # label atual
        label = render_text(ITEMS[self._index], 12, CRT_WHITE)
        surface.blit(label, label.get_rect(midtop=(cx, cy + 38)))

        # indicadores de paginação (pontinhos)
        total = len(ITEMS)
        dot_w = 6
        total_w = total * dot_w + (total - 1) * 4
        sx = cx - total_w // 2
        for i in range(total):
            color = CRT_WHITE if i == self._index else CRT_DIM
            pygame.draw.rect(surface, color, (sx + i * (dot_w + 4), cy + 58, dot_w, 2))

    def _draw_hint(self, surface: pygame.Surface) -> None:
        # barra de progresso do timeout (vai sumindo)
        timeout = float(config.get("idle_timeout_s") or 10)
        idle_frac = min(self._idle / timeout, 1.0) if timeout > 0 else 0.0
        bar_w = int((LOGICAL_SIZE[0] - 32) * (1.0 - idle_frac))
        if bar_w > 0:
            pygame.draw.rect(surface, CRT_DIM, (16, LOGICAL_SIZE[1] - 8, bar_w, 2))
