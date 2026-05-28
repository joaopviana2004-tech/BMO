"""Widgets retrô do BMO OS: header, tile, carrossel, menu de lista."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import pygame

from .theme import Colors, LOGICAL_SIZE, render_text

# Paleta P&B usada nas telas no estilo CRT.
# São pygame.Color (mutáveis) propositalmente: theme_state.apply_theme() faz
# .update() nelas in-place, então qualquer screen que importou
# `from widgets import CRT_BLACK` segue vendo a cor atual sem re-importar.
CRT_BLACK  = pygame.Color(0, 0, 0)
CRT_WHITE  = pygame.Color(235, 235, 235)
CRT_DIM    = pygame.Color(95, 95, 95)
CRT_SCAN   = pygame.Color(10, 10, 10)

# Zona morta em torno da tela inteira: o frame físico do BMO cobre uns 14px
# nas bordas. Telas CRT empurram corners e conteúdo pra dentro desse valor.
SAFE_INSET = 14


def draw_scanlines(surface: pygame.Surface) -> None:
    w, h = surface.get_size()
    for y in range(0, h, 2):
        pygame.draw.line(surface, CRT_SCAN, (0, y), (w - 1, y))


def draw_crt_corners(surface: pygame.Surface, length: int = 14, margin: int = 4, color=None) -> None:
    if color is None:
        color = CRT_WHITE
    w, h = surface.get_size()
    t = 2
    m = margin
    # sup-esq
    pygame.draw.rect(surface, color, (m, m, length, t))
    pygame.draw.rect(surface, color, (m, m, t, length))
    # sup-dir
    pygame.draw.rect(surface, color, (w - m - length, m, length, t))
    pygame.draw.rect(surface, color, (w - m - t, m, t, length))
    # inf-esq
    pygame.draw.rect(surface, color, (m, h - m - t, length, t))
    pygame.draw.rect(surface, color, (m, h - m - length, t, length))
    # inf-dir
    pygame.draw.rect(surface, color, (w - m - length, h - m - t, length, t))
    pygame.draw.rect(surface, color, (w - m - t, h - m - length, t, length))


def draw_dashed_rect(
    surf: pygame.Surface,
    color,
    rect: pygame.Rect,
    *,
    dash: int = 4,
    gap: int = 3,
    width: int = 2,
) -> None:
    """Borda tracejada (estilo seleção do BMO)."""
    x, y, w, h = rect
    step = dash + gap

    def draw_h(y_pos: int) -> None:
        cx = x
        while cx < x + w:
            end = min(cx + dash, x + w)
            pygame.draw.line(surf, color, (cx, y_pos), (end, y_pos), width)
            cx += step

    def draw_v(x_pos: int) -> None:
        cy = y
        while cy < y + h:
            end = min(cy + dash, y + h)
            pygame.draw.line(surf, color, (x_pos, cy), (x_pos, end), width)
            cy += step

    draw_h(y)
    draw_h(y + h - width)
    draw_v(x)
    draw_v(x + w - width)


def draw_header(surf: pygame.Surface, title: str, color=Colors.CYAN) -> None:
    """Header estilo '. * BMO OS * .' centralizado."""
    text = f". * {title.upper()} * ."
    img = render_text(text, 10, color)
    rect = img.get_rect(midtop=(surf.get_width() // 2, 6))
    surf.blit(img, rect)


@dataclass
class Tile:
    """Quadrado com ícone/preview em cima e label embaixo."""
    label: str
    rect: pygame.Rect
    draw_icon: Callable[[pygame.Surface, pygame.Rect], None]
    selected: bool = False

    def draw(self, surf: pygame.Surface) -> None:
        if self.selected:
            outer = self.rect.inflate(10, 10)
            draw_dashed_rect(surf, Colors.YELLOW, outer)
        pygame.draw.rect(surf, Colors.BG_GREEN, self.rect)
        pygame.draw.rect(surf, Colors.CYAN_DIM, self.rect, 1)
        self.draw_icon(surf, self.rect)
        label = render_text(self.label, 8, Colors.CYAN)
        lr = label.get_rect(midtop=(self.rect.centerx, self.rect.bottom + 4))
        surf.blit(label, lr)


@dataclass
class CarouselItem:
    label: str
    draw_icon: Callable[[pygame.Surface, pygame.Rect], None]
    on_select: Callable[[], None] | None = None


class Carousel:
    """Carrossel horizontal estilo home do BMO (DISPLAY MODE / GAMES / SETTINGS).

    Setas tocáveis nos lados e ícone grande no centro.
    """

    def __init__(self, items: list[CarouselItem], center_y: int = 110) -> None:
        self.items = items
        self.index = 0
        self.center_y = center_y
        self._anim = 0.0

    @property
    def current(self) -> CarouselItem:
        return self.items[self.index]

    def next(self) -> None:
        self.index = (self.index + 1) % len(self.items)

    def prev(self) -> None:
        self.index = (self.index - 1) % len(self.items)

    def update(self, dt: float) -> None:
        self._anim += dt

    @property
    def _left_arrow_rect(self) -> pygame.Rect:
        return pygame.Rect(20, self.center_y - 12, 24, 24)

    @property
    def _right_arrow_rect(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] - 44, self.center_y - 12, 24, 24)

    def handle_tap(self, pos: tuple[int, int]) -> bool:
        """Retorna True se consumiu o toque."""
        if self._left_arrow_rect.collidepoint(pos):
            self.prev()
            return True
        if self._right_arrow_rect.collidepoint(pos):
            self.next()
            return True
        center = pygame.Rect(0, 0, 70, 70)
        center.center = (LOGICAL_SIZE[0] // 2, self.center_y)
        if center.collidepoint(pos):
            if self.current.on_select:
                self.current.on_select()
            return True
        return False

    def draw(self, surf: pygame.Surface) -> None:
        bob = int(math.sin(self._anim * 3) * 2)

        bob_arrow = int(math.sin(self._anim * 4) * 2)
        self._draw_arrow(surf, self._left_arrow_rect.move(-bob_arrow, 0), pointing_left=True)
        self._draw_arrow(surf, self._right_arrow_rect.move(bob_arrow, 0), pointing_left=False)

        icon_rect = pygame.Rect(0, 0, 56, 56)
        icon_rect.center = (LOGICAL_SIZE[0] // 2, self.center_y + bob)
        self.current.draw_icon(surf, icon_rect)

        label = render_text(self.current.label.upper(), 14, Colors.CYAN)
        lr = label.get_rect(midtop=(LOGICAL_SIZE[0] // 2, self.center_y + 36))
        surf.blit(label, lr)

    @staticmethod
    def _draw_arrow(surf: pygame.Surface, rect: pygame.Rect, *, pointing_left: bool) -> None:
        if pointing_left:
            pts = [(rect.right, rect.top), (rect.right, rect.bottom), (rect.left, rect.centery)]
        else:
            pts = [(rect.left, rect.top), (rect.left, rect.bottom), (rect.right, rect.centery)]
        pygame.draw.polygon(surf, Colors.YELLOW, pts)


@dataclass
class MenuItem:
    label: str
    on_select: Callable[[], None] | None = None


class ListMenu:
    """Lista vertical, item selecionado vira barra branca com seta amarela."""

    def __init__(self, items: list[MenuItem], top: int = 36, row_h: int = 26) -> None:
        self.items = items
        self.index = 0
        self.top = top
        self.row_h = row_h

    def move(self, delta: int) -> None:
        if not self.items:
            return
        self.index = (self.index + delta) % len(self.items)

    def activate(self) -> None:
        if self.items and self.items[self.index].on_select:
            self.items[self.index].on_select()

    def handle_tap(self, pos: tuple[int, int]) -> bool:
        for i, _ in enumerate(self.items):
            row = pygame.Rect(12, self.top + i * self.row_h, 376, self.row_h - 4)
            if row.collidepoint(pos):
                if i == self.index:
                    self.activate()
                else:
                    self.index = i
                return True
        return False

    def draw(self, surf: pygame.Surface) -> None:
        for i, item in enumerate(self.items):
            row = pygame.Rect(12, self.top + i * self.row_h, 376, self.row_h - 4)
            if i == self.index:
                pygame.draw.rect(surf, Colors.WHITE, row)
                arrow = [(row.left + 8, row.centery - 6), (row.left + 8, row.centery + 6), (row.left + 18, row.centery)]
                pygame.draw.polygon(surf, Colors.YELLOW, arrow)
                color = Colors.BLACK
                pad_x = 28
            else:
                color = Colors.CYAN
                pad_x = 14
            label = render_text(item.label.upper(), 11, color)
            lr = label.get_rect(midleft=(row.left + pad_x, row.centery))
            surf.blit(label, lr)
