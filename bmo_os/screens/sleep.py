"""Tela 'HOW BMO RESTS' — seleção de modo de sleep.

Estilo CRT P&B.
"""
from __future__ import annotations

import datetime as dt

import pygame

from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)


class SleepScreen:
    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self.index = 0
        self._labels = ["CLOCK", "AMBIENT"]
        self._t = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        if action in (bmo_input.Action.LEFT, bmo_input.Action.RIGHT):
            self.index = (self.index + 1) % 2
        elif action == bmo_input.Action.B:
            self.on_back()
        elif action == bmo_input.Action.A:
            self.on_back()
        elif action == bmo_input.Action.TAP and event.pos is not None:
            for i, rect in enumerate(self._tile_rects()):
                if rect.collidepoint(event.pos):
                    if i == self.index:
                        self.on_back()
                    else:
                        self.index = i
                    return

    def update(self, dt_: float) -> None:
        self._t += dt_

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface)
        self._draw_title(surface)
        self._draw_tiles(surface)
        self._draw_hint(surface)

    def _tile_rects(self):
        cx = LOGICAL_SIZE[0] // 2
        return [
            pygame.Rect(cx - 90, 68, 72, 72),
            pygame.Rect(cx + 18, 68, 72, 72),
        ]

    def _draw_title(self, surface: pygame.Surface) -> None:
        img = render_text("HOW BMO RESTS", 10, CRT_DIM)
        surface.blit(img, img.get_rect(midtop=(LOGICAL_SIZE[0] // 2, 20)))

    def _draw_tiles(self, surface: pygame.Surface) -> None:
        for i, (rect, label) in enumerate(zip(self._tile_rects(), self._labels)):
            selected = (i == self.index)
            color = CRT_WHITE if selected else CRT_DIM
            pygame.draw.rect(surface, color, rect, 2)
            # conteúdo interno
            if i == 0:
                self._draw_clock_preview(surface, rect)
            else:
                self._draw_ambient_preview(surface, rect, selected)
            # label
            lbl = render_text(label, 8, color)
            surface.blit(lbl, lbl.get_rect(midtop=(rect.centerx, rect.bottom + 5)))
            # cursor de seleção
            if selected:
                pygame.draw.rect(surface, CRT_WHITE, rect.inflate(6, 6), 1)

    def _draw_clock_preview(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        now = dt.datetime.now()
        text = render_text(now.strftime("%H:%M"), 16, CRT_WHITE)
        surface.blit(text, text.get_rect(center=rect.center))

    def _draw_ambient_preview(self, surface: pygame.Surface, rect: pygame.Rect, bright: bool) -> None:
        c = CRT_WHITE if bright else CRT_DIM
        face = rect.inflate(-16, -16)
        pygame.draw.rect(surface, c, face, 1, border_radius=4)
        # olhos
        pygame.draw.rect(surface, c, (face.left + 9, face.centery - 6, 4, 6))
        pygame.draw.rect(surface, c, (face.right - 13, face.centery - 6, 4, 6))
        # boca
        pygame.draw.line(surface, c, (face.centerx - 5, face.bottom - 8), (face.centerx + 5, face.bottom - 8), 2)

    def _draw_hint(self, surface: pygame.Surface) -> None:
        hint = render_text("B = voltar", 8, CRT_DIM)
        surface.blit(hint, hint.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - 10)))
