"""Tela de ALERTA — pop-up de evento próximo, empilhado sobre a tela atual.

É empurrada pelo frame_hook do App (main.py) quando o EventAlerter detecta
um evento prestes a começar. Toca a voz do BMO, mostra "EM X MIN", título e
horário. Some sozinha depois de AUTO_DISMISS_S ou no primeiro toque/botão.

Como entra via push, ao dispensar dá pop e volta exatamente pra tela de baixo
(relógio, jogo, etc.). Empurrada sobre o SUSPENDED, o display religa sozinho
(SuspendedScreen.exit liga o backlight).
"""
from __future__ import annotations

import datetime as dt
import math

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)
from ..services import audio
from ..services.gcalendar import CalEvent

AUTO_DISMISS_S = 30.0


def _local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


class AlertScreen:
    def __init__(self, *, event: CalEvent, on_dismiss) -> None:
        self.event = event
        self.on_dismiss = on_dismiss
        self._t = 0.0
        self._dismissed = False

    def enter(self) -> None:
        audio.play("plim")

    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._dismissed:
            return
        if event.type == bmo_input.ACTION_EVENT:
            self._dismiss()

    def _dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        audio.play("back")
        self.on_dismiss()

    def update(self, dt_: float) -> None:
        self._t += dt_
        if self._t >= AUTO_DISMISS_S:
            self._dismiss()

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        # borda piscante pra chamar atenção
        blink = (self._t % 1.0) < 0.5
        draw_crt_corners(surface, margin=SAFE_INSET,
                         color=CRT_WHITE if blink else CRT_DIM)

        cx = LOGICAL_SIZE[0] // 2
        self._draw_bell(surface, cx, 46, blink)

        # quanto falta
        mins = self._minutes_left()
        when = "AGORA" if mins <= 0 else f"EM {mins} MIN"
        big = render_text(when, 16, CRT_WHITE)
        surface.blit(big, big.get_rect(midtop=(cx, 74)))

        # título do evento (consolas pra caber acento/títulos longos)
        title = self._fit(self.event.title, 34)
        timg = render_text(title, 13, CRT_WHITE, pixel=False)
        surface.blit(timg, timg.get_rect(midtop=(cx, 104)))

        # horário + rótulo da conta (com bolinha colorida)
        hh = self.event.start.strftime("%H:%M")
        him = render_text(hh, 12, CRT_DIM, pixel=False)
        surface.blit(him, him.get_rect(midtop=(cx, 128)))

        label = self.event.cal_label.upper()
        lbl = render_text(label, 9, CRT_DIM, pixel=False)
        total_w = 8 + 4 + lbl.get_width()
        lx = cx - total_w // 2
        ly = 150
        pygame.draw.rect(surface, self.event.color, (lx, ly + 1, 6, 6))
        surface.blit(lbl, (lx + 10, ly))

        hint = render_text("toque pra dispensar", 8, CRT_DIM, pixel=False)
        surface.blit(hint, hint.get_rect(midbottom=(cx, LOGICAL_SIZE[1] - SAFE_INSET - 4)))

    def _minutes_left(self) -> int:
        delta = (self.event.start - _local_now()).total_seconds()
        return max(0, int(round(delta / 60)))

    def _draw_bell(self, surface, cx: int, cy: int, ring: bool) -> None:
        # balança a sineta no ritmo do blink
        sway = int(math.sin(self._t * 8) * 3) if ring else 0
        cx += sway
        # corpo da sineta
        pygame.draw.arc(surface, CRT_WHITE, pygame.Rect(cx - 12, cy - 12, 24, 26),
                        0, math.pi, 3)
        pygame.draw.line(surface, CRT_WHITE, (cx - 12, cy + 1), (cx + 12, cy + 1), 3)
        # base / badalo
        pygame.draw.line(surface, CRT_WHITE, (cx - 14, cy + 3), (cx + 14, cy + 3), 2)
        pygame.draw.circle(surface, CRT_WHITE, (cx, cy + 6), 2)
        # cabinho em cima
        pygame.draw.rect(surface, CRT_WHITE, (cx - 1, cy - 14, 2, 3))

    @staticmethod
    def _fit(text: str, max_chars: int) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return text[: max(1, max_chars - 1)] + "."
