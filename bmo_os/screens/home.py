"""Tela home — carrossel de modos.

Estilo CRT P&B: fundo preto, scanlines, brackets nos cantos.
Auto-volta pro relógio depois de 10s sem input.
"""
from __future__ import annotations

import math

import pygame

from ..core import config, theme_state
from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)
from ..services import audio

ITEMS = ["SLEEP", "SUSPEND", "GAMES", "TASKS", "AGENDA", "FOCO", "PHOTO", "SISTEMA", "TESTE", "SETTINGS"]
ICONS = ["sleep", "suspend", "games", "tasks", "agenda", "pomodoro", "photo", "sysinfo", "aitest", "settings"]


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


def _icon_suspend(surf: pygame.Surface, cx: int, cy: int) -> None:
    # crescente lunar (mais limpo que face dormindo do _icon_sleep)
    pygame.draw.circle(surf, CRT_WHITE, (cx - 2, cy), 14)
    pygame.draw.circle(surf, CRT_BLACK, (cx + 4, cy - 3), 14)
    # estrelinhas em volta
    for sx, sy in [(cx - 16, cy - 14), (cx + 14, cy + 10), (cx + 12, cy - 12)]:
        pygame.draw.rect(surf, CRT_WHITE, (sx, sy, 2, 2))


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


def _icon_photo(surf: pygame.Surface, cx: int, cy: int) -> None:
    # corpo da câmera
    body = pygame.Rect(0, 0, 38, 26)
    body.center = (cx, cy + 1)
    pygame.draw.rect(surf, CRT_WHITE, body, 2, border_radius=3)
    # visor em cima
    pygame.draw.rect(surf, CRT_WHITE, (cx - 6, body.top - 4, 12, 4))
    # lente
    pygame.draw.circle(surf, CRT_WHITE, (cx, body.centery + 1), 7, 2)
    pygame.draw.circle(surf, CRT_DIM, (cx, body.centery + 1), 3)
    # flash
    pygame.draw.rect(surf, CRT_WHITE, (body.right - 6, body.top + 3, 3, 3))


def _icon_tasks(surf: pygame.Surface, cx: int, cy: int) -> None:
    # 3 colunas com mini-cards (representa kanban)
    col_w, col_h, gap = 12, 30, 3
    total_w = 3 * col_w + 2 * gap
    start_x = cx - total_w // 2
    top_y = cy - col_h // 2
    for i in range(3):
        x = start_x + i * (col_w + gap)
        pygame.draw.rect(surf, CRT_WHITE, (x, top_y, col_w, col_h), 1)
        pygame.draw.rect(surf, CRT_WHITE, (x + 2, top_y + 4, col_w - 4, 3))
        pygame.draw.rect(surf, CRT_WHITE, (x + 2, top_y + 11, col_w - 4, 3))
        if i < 2:
            pygame.draw.rect(surf, CRT_DIM, (x + 2, top_y + 18, col_w - 4, 3))


def _icon_agenda(surf: pygame.Surface, cx: int, cy: int) -> None:
    # folhinha de calendário com argolas e um dia marcado
    body = pygame.Rect(0, 0, 36, 32)
    body.center = (cx, cy + 2)
    pygame.draw.rect(surf, CRT_WHITE, body, 2, border_radius=3)
    # faixa do topo
    pygame.draw.rect(surf, CRT_WHITE, (body.left, body.top, body.width, 7))
    # argolas
    pygame.draw.rect(surf, CRT_BLACK, (body.left + 8, body.top - 4, 2, 5))
    pygame.draw.rect(surf, CRT_BLACK, (body.right - 10, body.top - 4, 2, 5))
    pygame.draw.rect(surf, CRT_WHITE, (body.left + 8, body.top - 5, 2, 4))
    pygame.draw.rect(surf, CRT_WHITE, (body.right - 10, body.top - 5, 2, 4))
    # grade de dias
    for r in range(2):
        for c in range(3):
            x = body.left + 6 + c * 9
            y = body.top + 12 + r * 8
            on = (r == 1 and c == 1)   # um dia destacado
            pygame.draw.rect(surf, CRT_WHITE if on else CRT_DIM, (x, y, 5, 4))


def _icon_pomodoro(surf: pygame.Surface, cx: int, cy: int) -> None:
    # tomate: corpo redondo + folhinha/cabinho em cima
    pygame.draw.circle(surf, CRT_WHITE, (cx, cy + 4), 15, 2)
    # brilho
    pygame.draw.arc(surf, CRT_DIM, pygame.Rect(cx - 9, cy - 3, 10, 10),
                    math.pi * 0.6, math.pi * 1.1, 2)
    # cabinho
    pygame.draw.rect(surf, CRT_WHITE, (cx - 1, cy - 14, 2, 5))
    # folhas
    pygame.draw.line(surf, CRT_WHITE, (cx, cy - 11), (cx - 6, cy - 13), 2)
    pygame.draw.line(surf, CRT_WHITE, (cx, cy - 11), (cx + 6, cy - 13), 2)


def _icon_sysinfo(surf: pygame.Surface, cx: int, cy: int) -> None:
    # chip/processador: corpo quadrado, die interno e perninhas nos 4 lados
    body = pygame.Rect(0, 0, 26, 26)
    body.center = (cx, cy)
    pygame.draw.rect(surf, CRT_WHITE, body, 2)
    pygame.draw.rect(surf, CRT_DIM, body.inflate(-12, -12))
    for off in (-7, 0, 7):
        pygame.draw.line(surf, CRT_WHITE, (body.left + 13 + off, body.top - 4), (body.left + 13 + off, body.top), 2)
        pygame.draw.line(surf, CRT_WHITE, (body.left + 13 + off, body.bottom), (body.left + 13 + off, body.bottom + 4), 2)
        pygame.draw.line(surf, CRT_WHITE, (body.left - 4, body.top + 13 + off), (body.left, body.top + 13 + off), 2)
        pygame.draw.line(surf, CRT_WHITE, (body.right, body.top + 13 + off), (body.right + 4, body.top + 13 + off), 2)


def _icon_aitest(surf: pygame.Surface, cx: int, cy: int) -> None:
    # microfone: cápsula + haste + base, com ondinhas de som
    cap = pygame.Rect(0, 0, 14, 22)
    cap.center = (cx, cy - 4)
    pygame.draw.rect(surf, CRT_WHITE, cap, 2, border_radius=7)
    # arco do suporte
    pygame.draw.arc(surf, CRT_WHITE, pygame.Rect(cx - 12, cy - 10, 24, 26), math.pi, 2 * math.pi, 2)
    # haste + base
    pygame.draw.line(surf, CRT_WHITE, (cx, cy + 12), (cx, cy + 18), 2)
    pygame.draw.line(surf, CRT_WHITE, (cx - 7, cy + 18), (cx + 7, cy + 18), 2)
    # ondinhas
    pygame.draw.arc(surf, CRT_DIM, pygame.Rect(cx + 10, cy - 12, 10, 18), -1.0, 1.0, 2)


_DRAW_ICON = [
    _icon_sleep, _icon_suspend, _icon_games, _icon_tasks,
    _icon_agenda, _icon_pomodoro, _icon_photo, _icon_sysinfo, _icon_aitest, _icon_settings,
]


class HomeScreen:
    def __init__(self, *, on_back, on_open_sleep, on_open_suspend, on_open_games,
                 on_open_tasks, on_open_agenda, on_open_pomodoro,
                 on_open_photo, on_open_sysinfo, on_open_teste, on_open_settings) -> None:
        self.on_back = on_back
        self._on_select = [
            on_open_sleep, on_open_suspend, on_open_games, on_open_tasks,
            on_open_agenda, on_open_pomodoro, on_open_photo, on_open_sysinfo,
            on_open_teste, on_open_settings,
        ]
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
            audio.play("tick")
        elif action == bmo_input.Action.RIGHT:
            self._index = (self._index + 1) % len(ITEMS)
            audio.play("tick")
        elif action == bmo_input.Action.A:
            audio.play("select")
            self._on_select[self._index]()
        elif action == bmo_input.Action.B:
            audio.play("back")
            self.on_back()
        elif action == bmo_input.Action.TAP and event.pos is not None:
            self._handle_tap(event.pos)

    def _handle_tap(self, pos: tuple[int, int]) -> None:
        cx, cy = LOGICAL_SIZE[0] // 2, 110
        # zona de toque BEM maior que a seta (visualmente continua pequena)
        # pra ficar fácil acertar no touch
        if pygame.Rect(0, cy - 36, 80, 72).collidepoint(pos):
            self._index = (self._index - 1) % len(ITEMS)
            audio.play("tick")
            return
        if pygame.Rect(LOGICAL_SIZE[0] - 80, cy - 36, 80, 72).collidepoint(pos):
            self._index = (self._index + 1) % len(ITEMS)
            audio.play("tick")
            return
        # ícone central
        if pygame.Rect(0, 0, 80, 80).move(cx - 40, cy - 40).collidepoint(pos):
            audio.play("select")
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
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
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
        # barra de progresso do timeout (vai sumindo) — dentro da zona segura
        timeout = float(config.get("idle_timeout_s") or 10)
        idle_frac = min(self._idle / timeout, 1.0) if timeout > 0 else 0.0
        x = SAFE_INSET + 8
        max_w = LOGICAL_SIZE[0] - 2 * x
        bar_w = int(max_w * (1.0 - idle_frac))
        if bar_w > 0:
            pygame.draw.rect(surface, CRT_DIM, (x, LOGICAL_SIZE[1] - SAFE_INSET - 4, bar_w, 2))
