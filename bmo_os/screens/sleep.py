"""Tela 'HOW BMO RESTS' — replica img_0473.

Dois tiles (CLOCK e AMBIENT). Toque seleciona; A confirma.
"""
from __future__ import annotations

import datetime as dt

import pygame

from ..core import input as bmo_input
from ..core.theme import Colors, render_text
from ..core.widgets import Tile, draw_header


def _draw_clock_preview(surf: pygame.Surface, rect: pygame.Rect) -> None:
    inner = rect.inflate(-4, -4)
    pygame.draw.rect(surf, Colors.BG_GREEN, inner)
    text = render_text(dt.datetime.now().strftime("%H:%M"), 18, Colors.CYAN)
    surf.blit(text, text.get_rect(center=inner.center))


def _draw_ambient_preview(surf: pygame.Surface, rect: pygame.Rect) -> None:
    inner = rect.inflate(-4, -4)
    pygame.draw.rect(surf, Colors.BG_DARK, inner)
    face = inner.inflate(-14, -14)
    pygame.draw.rect(surf, Colors.BMO_BLUE, face, border_radius=4)
    # olhos
    pygame.draw.rect(surf, Colors.BG_DARK, (face.left + 8, face.centery - 4, 4, 6))
    pygame.draw.rect(surf, Colors.BG_DARK, (face.right - 12, face.centery - 4, 4, 6))
    # boca
    pygame.draw.line(surf, Colors.BG_DARK, (face.centerx - 4, face.bottom - 6), (face.centerx + 4, face.bottom - 6), 2)


class SleepScreen:
    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self.index = 0
        self.tiles = [
            Tile("clock", pygame.Rect(80, 70, 80, 80), _draw_clock_preview),
            Tile("ambient", pygame.Rect(240, 70, 80, 80), _draw_ambient_preview),
        ]
        self._refresh_selection()

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def _refresh_selection(self) -> None:
        for i, t in enumerate(self.tiles):
            t.selected = (i == self.index)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        if action == bmo_input.Action.LEFT:
            self.index = (self.index - 1) % len(self.tiles)
            self._refresh_selection()
        elif action == bmo_input.Action.RIGHT:
            self.index = (self.index + 1) % len(self.tiles)
            self._refresh_selection()
        elif action == bmo_input.Action.B:
            self.on_back()
        elif action == bmo_input.Action.A:
            # placeholder — futuramente troca modo de descanso
            pass
        elif action == bmo_input.Action.TAP and event.pos is not None:
            for i, t in enumerate(self.tiles):
                if t.rect.inflate(10, 10).collidepoint(event.pos):
                    if i == self.index:
                        # confirmar: por enquanto volta
                        self.on_back()
                    else:
                        self.index = i
                        self._refresh_selection()
                    return

    def update(self, dt: float) -> None: ...

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(Colors.BG_DARK)
        draw_header(surface, "HOW BMO RESTS")
        for t in self.tiles:
            t.draw(surface)
