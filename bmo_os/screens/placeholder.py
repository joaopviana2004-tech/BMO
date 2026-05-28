"""Stubs visuais pra Games / Settings — V2 substitui."""
from __future__ import annotations

import pygame

from ..core import input as bmo_input
from ..core.theme import Colors, render_text
from ..core.widgets import draw_header


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
        surface.fill(Colors.BG_DARK)
        draw_header(surface, self.title)
        msg = render_text("em breve...", 14, Colors.CYAN_DIM)
        surface.blit(msg, msg.get_rect(center=(surface.get_width() // 2, surface.get_height() // 2)))
        hint = render_text("toque para voltar", 8, Colors.CYAN_DIM)
        surface.blit(hint, hint.get_rect(midbottom=(surface.get_width() // 2, surface.get_height() - 12)))
