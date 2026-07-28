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
from ..services import audio

GRID_COLS = 3
ICON_SIZE = 56
ICON_GAP_X = 28
ICON_GAP_Y = 18
LABEL_GAP = 12
GRID_TOP = SAFE_INSET + 32


class GamesScreen:
    voice_announce = "Arcade aberto. Escolhe aí."   # BMO anuncia ao abrir (cacheado)

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
            audio.play("back")
            self.on_back()
            return
        if action == bmo_input.Action.LEFT:
            self._index = max(0, self._index - 1)
            audio.play("tick")
        elif action == bmo_input.Action.RIGHT:
            self._index = min(len(self.games) - 1, self._index + 1)
            audio.play("tick")
        elif action == bmo_input.Action.UP:
            self._index = max(0, self._index - GRID_COLS)
            audio.play("tick")
        elif action == bmo_input.Action.DOWN:
            self._index = min(len(self.games) - 1, self._index + GRID_COLS)
            audio.play("tick")
        elif action == bmo_input.Action.A:
            self._launch_current()
        elif action == bmo_input.Action.TAP and pos is not None:
            if self._back_btn().collidepoint(pos):
                audio.play("back")
                self.on_back()
                return
            for i, rect in enumerate(self._icon_rects()):
                if rect.collidepoint(pos):
                    self._index = i
                    self._launch_current()
                    return

    def _launch_current(self) -> None:
        if 0 <= self._index < len(self.games):
            audio.play("select")
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


def draw_pong_icon(surface: pygame.Surface, rect: pygame.Rect) -> None:
    """Mini cena de Pong: 2 paddles + bola + linha tracejada."""
    cx, cy = rect.center
    # paddle player (ciano) à esquerda
    pygame.draw.rect(surface, (90, 200, 220), (cx - 20, cy - 10, 3, 20))
    # paddle bot (vermelho) à direita
    pygame.draw.rect(surface, (230, 90, 90), (cx + 17, cy - 10, 3, 20))
    # linha tracejada do meio
    for dy in range(-14, 15, 6):
        pygame.draw.rect(surface, (90, 100, 120), (cx - 1, cy + dy, 2, 3))
    # bola no centro
    pygame.draw.rect(surface, (255, 255, 255), (cx - 3, cy - 3, 6, 6))


def draw_flappy_icon(surface: pygame.Surface, rect: pygame.Rect) -> None:
    """Passarinho amarelo entre dois canos verdes."""
    cx, cy = rect.center
    pipe = (90, 200, 120)
    # cano esquerdo (de baixo) e direito (de cima)
    pygame.draw.rect(surface, pipe, (cx - 20, cy + 2, 8, 16))
    pygame.draw.rect(surface, pipe, (cx + 12, cy - 18, 8, 16))
    # passarinho
    pygame.draw.rect(surface, (250, 210, 70), (cx - 5, cy - 5, 10, 10))
    pygame.draw.rect(surface, (20, 20, 30), (cx + 1, cy - 3, 2, 2))      # olho
    pygame.draw.rect(surface, (230, 120, 40), (cx + 5, cy, 3, 2))        # bico


def draw_snake_icon(surface: pygame.Surface, rect: pygame.Rect) -> None:
    """Cobrinha verde em L + maçãzinha vermelha."""
    cx, cy = rect.center
    g = (120, 220, 130)
    for i in range(4):                       # corpo horizontal
        pygame.draw.rect(surface, g, (cx - 18 + i * 7, cy + 4, 6, 6))
    for i in range(2):                       # sobe (cabeça)
        pygame.draw.rect(surface, (180, 250, 180), (cx + 3, cy - 3 - i * 7, 6, 6))
    pygame.draw.rect(surface, (240, 110, 110), (cx - 14, cy - 12, 6, 6))  # comida


def draw_haxball_icon(surface: pygame.Surface, rect: pygame.Rect) -> None:
    """Mini campo top-down: bola no centro + discos vermelho/azul + linha do meio."""
    cx, cy = rect.center
    pygame.draw.rect(surface, (18, 62, 34), (cx - 20, cy - 13, 40, 26))
    pygame.draw.rect(surface, (96, 156, 116), (cx - 20, cy - 13, 40, 26), 1)
    pygame.draw.line(surface, (96, 156, 116), (cx, cy - 13), (cx, cy + 13), 1)
    pygame.draw.circle(surface, (232, 84, 72), (cx - 12, cy), 4)     # disco vermelho
    pygame.draw.circle(surface, (92, 152, 240), (cx + 12, cy), 4)    # disco azul
    pygame.draw.circle(surface, (245, 245, 245), (cx, cy), 3)        # bola
