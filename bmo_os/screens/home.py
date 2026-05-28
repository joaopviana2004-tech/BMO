"""Tela home — replica img_0472.

Carrossel central com modos (DISPLAY MODE, HOW BMO RESTS, GAMES, SETTINGS).
Footer com atalhos GAMES (esq) e SETTINGS (dir).
"""
from __future__ import annotations

import pygame

from ..core import input as bmo_input
from ..core.theme import Colors, render_text
from ..core.widgets import Carousel, CarouselItem, draw_header


def _icon_display(surf: pygame.Surface, rect: pygame.Rect) -> None:
    body = rect.inflate(-6, -16)
    body.move_ip(0, -4)
    pygame.draw.rect(surf, Colors.CYAN, body, 2)
    pygame.draw.rect(surf, Colors.BG_DARK, body.inflate(-6, -6))
    foot = pygame.Rect(0, 0, 18, 6)
    foot.midtop = (rect.centerx, body.bottom + 1)
    pygame.draw.rect(surf, Colors.CYAN, foot)


def _icon_sleep(surf: pygame.Surface, rect: pygame.Rect) -> None:
    # cara dormindo do BMO
    body = rect.inflate(-6, -10)
    pygame.draw.rect(surf, Colors.BMO_BLUE, body, border_radius=6)
    pygame.draw.rect(surf, Colors.CYAN, body, 2, border_radius=6)
    # olho fechado ~
    pygame.draw.line(surf, Colors.BG_DARK, (body.left + 12, body.centery - 4), (body.left + 22, body.centery - 4), 2)
    pygame.draw.line(surf, Colors.BG_DARK, (body.right - 22, body.centery - 4), (body.right - 12, body.centery - 4), 2)
    # boca
    pygame.draw.line(surf, Colors.BG_DARK, (body.centerx - 6, body.centery + 8), (body.centerx + 6, body.centery + 8), 2)


def _icon_games(surf: pygame.Surface, rect: pygame.Rect) -> None:
    pad = rect.inflate(-4, -16)
    pygame.draw.rect(surf, Colors.CYAN, pad, border_radius=8)
    # botões
    pygame.draw.circle(surf, Colors.RED, (pad.right - 10, pad.centery), 4)
    pygame.draw.circle(surf, Colors.YELLOW, (pad.right - 22, pad.centery), 4)
    # dpad
    dp = pygame.Rect(0, 0, 14, 14)
    dp.center = (pad.left + 14, pad.centery)
    pygame.draw.rect(surf, Colors.BG_DARK, dp)
    pygame.draw.line(surf, Colors.CYAN, (dp.left, dp.centery), (dp.right, dp.centery), 2)
    pygame.draw.line(surf, Colors.CYAN, (dp.centerx, dp.top), (dp.centerx, dp.bottom), 2)


def _icon_settings(surf: pygame.Surface, rect: pygame.Rect) -> None:
    cx, cy = rect.center
    pygame.draw.circle(surf, Colors.CYAN, (cx, cy), 18, 2)
    pygame.draw.circle(surf, Colors.CYAN, (cx, cy), 6, 2)
    for i in range(8):
        import math
        ang = i * math.pi / 4
        x1 = cx + int(math.cos(ang) * 20)
        y1 = cy + int(math.sin(ang) * 20)
        x2 = cx + int(math.cos(ang) * 26)
        y2 = cy + int(math.sin(ang) * 26)
        pygame.draw.line(surf, Colors.CYAN, (x1, y1), (x2, y2), 3)


class HomeScreen:
    def __init__(self, *, on_back, on_open_sleep, on_open_games, on_open_settings) -> None:
        self.on_back = on_back
        self.carousel = Carousel(
            [
                CarouselItem("display mode", _icon_display, on_select=lambda: None),
                CarouselItem("how bmo rests", _icon_sleep, on_select=on_open_sleep),
                CarouselItem("games", _icon_games, on_select=on_open_games),
                CarouselItem("settings", _icon_settings, on_select=on_open_settings),
            ],
            center_y=110,
        )
        self.on_open_games = on_open_games
        self.on_open_settings = on_open_settings

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        if action == bmo_input.Action.LEFT:
            self.carousel.prev()
        elif action == bmo_input.Action.RIGHT:
            self.carousel.next()
        elif action == bmo_input.Action.A:
            if self.carousel.current.on_select:
                self.carousel.current.on_select()
        elif action == bmo_input.Action.B:
            self.on_back()
        elif action == bmo_input.Action.TAP and event.pos is not None:
            if self.carousel.handle_tap(event.pos):
                return
            self._tap_footer(event.pos)

    def update(self, dt: float) -> None:
        self.carousel.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(Colors.BG_DARK)
        draw_header(surface, "BMO OS", Colors.CYAN)
        self.carousel.draw(surface)
        self._draw_footer(surface)

    def _draw_footer(self, surface: pygame.Surface) -> None:
        games = render_text("GAMES", 10, Colors.CYAN_DIM)
        settings = render_text("SETTINGS", 10, Colors.CYAN_DIM)
        surface.blit(games, games.get_rect(bottomleft=(12, surface.get_height() - 8)))
        surface.blit(settings, settings.get_rect(bottomright=(surface.get_width() - 12, surface.get_height() - 8)))

    def _tap_footer(self, pos: tuple[int, int]) -> bool:
        h = 240
        if pos[1] >= h - 24:
            if pos[0] < 100:
                self.on_open_games()
                return True
            if pos[0] > 300:
                self.on_open_settings()
                return True
        return False
