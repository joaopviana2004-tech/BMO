"""Tela 'GAMES' — grid de ícones estilo home screen de celular.

Cada jogo é um dict com {label, draw_icon(surf, rect), launch()}.
Tap num ícone abre o jogo. HOME button no canto sup-esq pra voltar.
"""
from __future__ import annotations

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)

GRID_COLS = 3
ICON_SIZE = 56
ICON_GAP_X = 28
ICON_GAP_Y = 18
LABEL_GAP = 12
GRID_TOP = SAFE_INSET + 32


class GamesScreen:
    def __init__(self, *, on_back, games: list[dict]) -> None:
        self.on_back = on_back
        self.games = games
        self._index = 0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def update(self, dt: float) -> None: ...

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        pos = getattr(event, "pos", None)
        if action == bmo_input.Action.B:
            self.on_back()
            return
        if action == bmo_input.Action.LEFT:
            self._index = max(0, self._index - 1)
        elif action == bmo_input.Action.RIGHT:
            self._index = min(len(self.games) - 1, self._index + 1)
        elif action == bmo_input.Action.UP:
            self._index = max(0, self._index - GRID_COLS)
        elif action == bmo_input.Action.DOWN:
            self._index = min(len(self.games) - 1, self._index + GRID_COLS)
        elif action == bmo_input.Action.A:
            self._launch_current()
        elif action == bmo_input.Action.TAP and pos is not None:
            if self._back_btn().collidepoint(pos):
                self.on_back()
                return
            for i, rect in enumerate(self._icon_rects()):
                if rect.collidepoint(pos):
                    self._index = i
                    self._launch_current()
                    return

    def _launch_current(self) -> None:
        if 0 <= self._index < len(self.games):
            self.games[self._index]["launch"]()

    # ---------- layout ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def _icon_rects(self) -> list[pygame.Rect]:
        rects: list[pygame.Rect] = []
        if not self.games:
            return rects
        grid_w = GRID_COLS * ICON_SIZE + (GRID_COLS - 1) * ICON_GAP_X
        start_x = (LOGICAL_SIZE[0] - grid_w) // 2
        for i in range(len(self.games)):
            r = i // GRID_COLS
            c = i % GRID_COLS
            x = start_x + c * (ICON_SIZE + ICON_GAP_X)
            y = GRID_TOP + r * (ICON_SIZE + ICON_GAP_Y + LABEL_GAP)
            rects.append(pygame.Rect(x, y, ICON_SIZE, ICON_SIZE))
        return rects

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_back_btn(surface)
        self._draw_title(surface)

        if not self.games:
            msg = render_text("nenhum jogo ainda", 10, CRT_DIM, pixel=False)
            surface.blit(msg, msg.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2)))
            return

        for i, rect in enumerate(self._icon_rects()):
            game = self.games[i]
            selected = (i == self._index)
            # moldura do ícone
            if selected:
                pygame.draw.rect(surface, CRT_WHITE, rect.inflate(6, 6), 2)
            pygame.draw.rect(surface, CRT_BLACK, rect)
            pygame.draw.rect(surface, CRT_DIM, rect, 1)
            game["draw_icon"](surface, rect)
            # label embaixo
            color = CRT_WHITE if selected else CRT_DIM
            label = render_text(game["label"].upper(), 8, color, pixel=False)
            surface.blit(label, label.get_rect(midtop=(rect.centerx, rect.bottom + 4)))

    def _draw_back_btn(self, surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        pygame.draw.polygon(surface, CRT_WHITE, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        img = render_text("HOME", 8, CRT_WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _draw_title(self, surface) -> None:
        img = render_text("GAMES", 10, CRT_DIM)
        surface.blit(img, img.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 6)))


# ---------- ícones dos jogos ----------

def draw_space_invaders_icon(surface: pygame.Surface, rect: pygame.Rect) -> None:
    """Alien colorido — body cyan, olhos pretos, perninhas."""
    cx, cy = rect.center
    body = (90, 200, 220)
    pygame.draw.rect(surface, body, (cx - 14, cy - 8, 28, 14))
    # olhos
    pygame.draw.rect(surface, (0, 0, 0), (cx - 9, cy - 4, 3, 4))
    pygame.draw.rect(surface, (0, 0, 0), (cx + 6, cy - 4, 3, 4))
    # boca / faixa
    pygame.draw.rect(surface, (0, 0, 0), (cx - 6, cy + 3, 12, 2))
    # braços/perninhas
    pygame.draw.rect(surface, body, (cx - 18, cy - 4, 4, 4))
    pygame.draw.rect(surface, body, (cx + 14, cy - 4, 4, 4))
    pygame.draw.rect(surface, body, (cx - 10, cy + 6, 4, 4))
    pygame.draw.rect(surface, body, (cx - 2, cy + 6, 4, 4))
    pygame.draw.rect(surface, body, (cx + 6, cy + 6, 4, 4))
