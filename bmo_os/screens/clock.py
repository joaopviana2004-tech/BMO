"""Tela do relógio — preto e branco, estilo terminal/videogame retro.

Sem header/footer com título. Canto sup. esquerdo: clima (temp, umid).
Centro: HH:MM gigante com dois-pontos piscando + segundos pequenos abaixo.
Brackets nos quatro cantos e scanlines sutis pra dar cara de CRT.
Zona morta SAFE_TOP/SAFE_BOTTOM compensa o frame físico do BMO que cobre
~12px nas bordas sup/inf da tela.
Toque/A/MENU -> abre o home.
"""
from __future__ import annotations

import datetime as dt
import math
import unicodedata

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import render_text
from ..services import audio  # noqa: F401  (usado abaixo no handle_event)
from ..core.widgets import (
    CRT_BLACK as BLACK, CRT_WHITE as WHITE, CRT_DIM as DIM,
    SAFE_INSET, draw_scanlines, draw_crt_corners,
)
from ..services.weather import WeatherService

PT_WEEKDAYS = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]
PT_MONTHS = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]

SCANLINE = (10, 10, 10)


def _ascii_upper(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").upper()


class ClockScreen:
    show_mic_button = True
    # canto inf-ESQ: a data fica no inf-dir, então o mic vai pra esquerda
    mic_btn_rect = (14, 200, 28, 26)

    def __init__(self, on_open_home, git_updates=None) -> None:
        self.on_open_home = on_open_home
        self.weather = WeatherService()
        self.git_updates = git_updates
        self._t = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == bmo_input.ACTION_EVENT:
            action = event.action
            if action in (bmo_input.Action.TAP, bmo_input.Action.A, bmo_input.Action.MENU):
                audio.play("select")
                self.on_open_home()

    def update(self, dt_: float) -> None:
        self._t += dt_

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BLACK)
        draw_scanlines(surface)
        # Corners empurrados pra dentro pra ficar visíveis abaixo do frame
        draw_crt_corners(surface, margin=SAFE_INSET)
        # Status bar logo abaixo do corner top-direito, com folga horizontal
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_weather(surface)
        self._draw_time(surface)
        self._draw_date(surface)
        self._draw_update_alert(surface)

    # ---------- conteúdo ----------

    def _draw_weather(self, surface: pygame.Surface) -> None:
        snap = self.weather.get()
        temp = f"{snap.temp_c:.0f}C" if snap.ok and snap.temp_c is not None else "--C"
        hum = f"{snap.humidity}%" if snap.ok and snap.humidity is not None else "--%"

        x = SAFE_INSET + 8   # deixa folga pro corner top-esquerdo
        rows = [
            ("TEMP", temp),
            ("UMID", hum),
        ]
        for i, (label, value) in enumerate(rows):
            y = SAFE_INSET + 22 + i * 16
            surface.blit(render_text(label, 8, DIM), (x, y + 1))
            surface.blit(render_text(value, 10, WHITE), (x + 48, y))

    def _draw_time(self, surface: pygame.Surface) -> None:
        now = dt.datetime.now()
        blink = (self._t % 1.0) < 0.5
        sep = ":" if blink else " "
        hh_mm = f"{now.hour:02d}{sep}{now.minute:02d}"
        big = render_text(hh_mm, 72, WHITE)
        cx = surface.get_width() // 2
        cy = surface.get_height() // 2 + 6
        rect = big.get_rect(center=(cx, cy))
        surface.blit(big, rect)

        ss = f"{now.second:02d}"
        small = render_text(ss, 14, DIM)
        sr = small.get_rect(midtop=(cx, rect.bottom + 6))
        surface.blit(small, sr)

    def _draw_update_alert(self, surface: pygame.Surface) -> None:
        if self.git_updates is None:
            return
        snap = self.git_updates.get()
        if not snap.available:
            return
        # blink lento (~2.4s período) pra não distrair, mas indica algo pendente
        blink = (self._t % 2.4) < 1.6
        color = WHITE if blink else DIM

        # canto sup-direito, à esquerda do status bar (sol/sinal/bateria)
        cx = surface.get_width() - 92
        cy = SAFE_INSET + 8

        # ícone de refresh: arco circular + ponta de seta
        rect = pygame.Rect(cx - 5, cy - 5, 11, 11)
        pygame.draw.arc(surface, color, rect, -math.pi / 2, math.pi, 2)
        pygame.draw.polygon(surface, color, [
            (cx + 1, cy - 7),
            (cx + 5, cy - 3),
            (cx, cy - 3),
        ])

    def _draw_date(self, surface: pygame.Surface) -> None:
        now = dt.datetime.now()
        weekday = PT_WEEKDAYS[now.weekday()]
        month = PT_MONTHS[now.month - 1]
        line1 = f"{weekday} {now.day:02d}"
        line2 = month
        x = surface.get_width() - SAFE_INSET - 8   # folga do corner inf-direito
        y = surface.get_height() - SAFE_INSET - 22
        img1 = render_text(line1, 8, WHITE)
        img2 = render_text(line2, 8, DIM)
        surface.blit(img1, img1.get_rect(topright=(x, y)))
        surface.blit(img2, img2.get_rect(topright=(x, y + 10)))
