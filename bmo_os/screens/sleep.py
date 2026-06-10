"""Tela 'HOW BMO RESTS' — escolha do modo ambient.

Estilo CRT P&B. Selecionar um tile grava em config e dispara
o callback on_select_mode (em geral troca o ambient agora mesmo).
"""
from __future__ import annotations

import datetime as dt
import math

import pygame

from ..core import config, theme_state
from ..core import input as bmo_input
from ..core.theme import render_text
from ..services import audio
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)

MODES = ["clock", "face", "devhub", "pong", "invaders", "shuffle"]
LABELS = {
    "clock": "CLOCK",
    "face": "BMO FACE",
    "devhub": "DEV HUB",
    "pong": "PONG",
    "invaders": "INVADERS",
    "shuffle": "VARIADO",
}


class SleepScreen:
    def __init__(self, on_back, on_select_mode=None) -> None:
        self.on_back = on_back
        self.on_select_mode = on_select_mode
        current = config.get("ambient_mode")
        try:
            self.index = MODES.index(current)
        except ValueError:
            self.index = 0
        self._t = 0.0

    def enter(self) -> None:
        current = config.get("ambient_mode")
        try:
            self.index = MODES.index(current)
        except ValueError:
            self.index = 0

    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        if action in (bmo_input.Action.LEFT, bmo_input.Action.RIGHT):
            self.index = (self.index + 1) % len(MODES)
            audio.play("tick")
        elif action == bmo_input.Action.B:
            audio.play("back")
            self.on_back()
        elif action == bmo_input.Action.A:
            self._select()
        elif action == bmo_input.Action.TAP and event.pos is not None:
            for i, rect in enumerate(self._tile_rects()):
                if rect.collidepoint(event.pos):
                    if i == self.index:
                        self._select()
                    else:
                        self.index = i
                        audio.play("tick")
                    return

    def _select(self) -> None:
        audio.play("select")
        mode = MODES[self.index]
        config.set_value("ambient_mode", mode)
        if self.on_select_mode is not None:
            self.on_select_mode(mode)
        else:
            self.on_back()

    def update(self, dt_: float) -> None:
        self._t += dt_

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_title(surface)
        self._draw_tiles(surface)
        self._draw_hint(surface)

    def _tile_rects(self):
        # 3x2 grid — 6 modos de descanso
        tile_w, tile_h = 58, 44
        gap_x, gap_y = 8, 10
        cols = 3
        grid_w = cols * tile_w + (cols - 1) * gap_x
        start_x = (LOGICAL_SIZE[0] - grid_w) // 2
        start_y = 58
        rects = []
        for i in range(len(MODES)):
            row, col = divmod(i, cols)
            x = start_x + col * (tile_w + gap_x)
            y = start_y + row * (tile_h + gap_y + 16)
            rects.append(pygame.Rect(x, y, tile_w, tile_h))
        return rects

    def _draw_title(self, surface: pygame.Surface) -> None:
        img = render_text("HOW BMO RESTS", 10, CRT_DIM)
        surface.blit(img, img.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 6)))

    def _draw_tiles(self, surface: pygame.Surface) -> None:
        for i, rect in enumerate(self._tile_rects()):
            mode = MODES[i]
            selected = (i == self.index)
            color = CRT_WHITE if selected else CRT_DIM
            pygame.draw.rect(surface, color, rect, 2)
            if mode == "clock":
                self._draw_clock_preview(surface, rect, selected)
            elif mode == "face":
                self._draw_face_preview(surface, rect, selected)
            elif mode == "pong":
                self._draw_pong_preview(surface, rect, selected)
            elif mode == "invaders":
                self._draw_invaders_preview(surface, rect, selected)
            elif mode == "devhub":
                self._draw_devhub_preview(surface, rect, selected)
            else:
                self._draw_shuffle_preview(surface, rect, selected)
            lbl = render_text(LABELS[mode], 8, color)
            surface.blit(lbl, lbl.get_rect(midtop=(rect.centerx, rect.bottom + 5)))
            if selected:
                pygame.draw.rect(surface, CRT_WHITE, rect.inflate(6, 6), 1)
            # marca "ATUAL" se for o ambient atual
            if mode == config.get("ambient_mode"):
                tag = render_text("ATUAL", 7, CRT_DIM)
                surface.blit(tag, tag.get_rect(midtop=(rect.centerx, rect.bottom + 16)))

    def _draw_clock_preview(self, surface: pygame.Surface, rect: pygame.Rect, bright: bool) -> None:
        now = dt.datetime.now()
        text = render_text(now.strftime("%H:%M"), 12, CRT_WHITE if bright else CRT_DIM)
        surface.blit(text, text.get_rect(center=rect.center))

    def _draw_pong_preview(self, surface: pygame.Surface, rect: pygame.Rect, bright: bool) -> None:
        c = CRT_WHITE if bright else CRT_DIM
        # 2 paddles
        pygame.draw.rect(surface, c, (rect.left + 5, rect.centery - 7, 2, 14))
        pygame.draw.rect(surface, c, (rect.right - 7, rect.centery - 7, 2, 14))
        # linha tracejada do meio
        for y in range(rect.top + 6, rect.bottom - 4, 6):
            pygame.draw.rect(surface, c, (rect.centerx - 1, y, 2, 3))
        # bola animada
        usable = rect.width - 16
        phase = (math.sin(self._t * 1.6) + 1) / 2
        bx = rect.left + 8 + int(usable * phase)
        pygame.draw.rect(surface, c, (bx - 1, rect.centery - 1, 3, 3))

    def _draw_invaders_preview(self, surface: pygame.Surface, rect: pygame.Rect, bright: bool) -> None:
        c = CRT_WHITE if bright else CRT_DIM
        # alien em cima
        cx = rect.centerx
        ay = rect.top + 12
        pygame.draw.rect(surface, c, (cx - 6, ay, 12, 5))
        pygame.draw.rect(surface, c, (cx - 8, ay + 2, 2, 2))
        pygame.draw.rect(surface, c, (cx + 6, ay + 2, 2, 2))
        # bala subindo
        bullet_y = rect.bottom - 14 - int((self._t * 30) % 22)
        pygame.draw.rect(surface, c, (cx - 1, bullet_y, 2, 4))
        # nave embaixo
        sy = rect.bottom - 10
        pygame.draw.polygon(surface, c, [
            (cx - 8, sy + 4), (cx - 6, sy), (cx + 6, sy), (cx + 8, sy + 4),
        ])
        pygame.draw.rect(surface, c, (cx - 1, sy - 2, 2, 2))

    def _draw_devhub_preview(self, surface: pygame.Surface, rect: pygame.Rect, bright: bool) -> None:
        c = CRT_WHITE if bright else CRT_DIM
        # mini barras de atividade
        bars = [2, 4, 6, 5, 3, 7, 4]
        bx = rect.left + 8
        by = rect.bottom - 10
        for i, h in enumerate(bars):
            pygame.draw.rect(surface, c, (bx + i * 6, by - h, 4, h))
        # linha de commit
        pygame.draw.circle(surface, c, (rect.left + 10, rect.top + 12), 2)
        line = render_text("> git", 7, c, pixel=False)
        surface.blit(line, (rect.left + 14, rect.top + 8))

    def _draw_shuffle_preview(self, surface: pygame.Surface, rect: pygame.Rect, bright: bool) -> None:
        c = CRT_WHITE if bright else CRT_DIM
        # 2 setas curvas cruzadas (ícone de shuffle universal)
        m = 8
        pygame.draw.line(surface, c, (rect.left + m, rect.top + m + 2),
                         (rect.right - m, rect.bottom - m - 2), 2)
        pygame.draw.line(surface, c, (rect.left + m, rect.bottom - m - 2),
                         (rect.right - m, rect.top + m + 2), 2)
        # pontas de seta
        for end_x, end_y, dx, dy in (
            (rect.right - m, rect.bottom - m - 2, -4, -1),
            (rect.right - m, rect.bottom - m - 2, -1, -4),
            (rect.right - m, rect.top + m + 2, -4, 1),
            (rect.right - m, rect.top + m + 2, -1, 4),
        ):
            pygame.draw.line(surface, c, (end_x, end_y), (end_x + dx, end_y + dy), 2)

    def _draw_face_preview(self, surface: pygame.Surface, rect: pygame.Rect, bright: bool) -> None:
        c = CRT_WHITE if bright else CRT_DIM
        # rosto inset
        face = rect.inflate(-14, -14)
        pygame.draw.rect(surface, c, face, 1, border_radius=4)
        # piscar de vez em quando no preview
        blink = (self._t % 3.0) > 2.8
        # olhos
        ex_l = face.left + 11
        ex_r = face.right - 11
        ey = face.centery - 4
        if blink:
            pygame.draw.line(surface, c, (ex_l - 3, ey), (ex_l + 3, ey), 2)
            pygame.draw.line(surface, c, (ex_r - 3, ey), (ex_r + 3, ey), 2)
        else:
            pygame.draw.circle(surface, c, (ex_l, ey), 3)
            pygame.draw.circle(surface, c, (ex_r, ey), 3)
        # boca curvinha sorrindo
        smile = pygame.Rect(face.centerx - 8, face.bottom - 18, 16, 8)
        pygame.draw.arc(surface, c, smile, math.pi, 2 * math.pi, 2)

    def _draw_hint(self, surface: pygame.Surface) -> None:
        hint = render_text("A = selecionar  B = voltar", 7, CRT_DIM)
        surface.blit(hint, hint.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 4)))
