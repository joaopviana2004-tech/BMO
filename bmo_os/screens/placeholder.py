"""Stub genérico pra telas ainda não implementadas (ex: GAMES)."""
from __future__ import annotations

import pygame

from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)


class PlaceholderScreen:
    def __init__(self, title: str, on_back) -> None:
        self.title = title
        self.on_back = on_back

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        if event.action in (bmo_input.Action.B, bmo_input.Action.TAP):
            self.on_back()

    def update(self, dt: float) -> None: ...

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface)

        title = render_text(self.title, 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, 20)))

        msg = render_text("EM BREVE", 16, CRT_WHITE)
        surface.blit(msg, msg.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2 - 8)))

        hint = render_text("B = voltar", 8, CRT_DIM)
        surface.blit(hint, hint.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - 12)))
