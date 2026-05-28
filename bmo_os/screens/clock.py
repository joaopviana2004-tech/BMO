"""Tela do relógio — preto e branco, estilo terminal/videogame retro.

Sem header/footer com título. Canto sup. esquerdo: clima (temp, umid, ceu).
Centro: HH:MM gigante com dois-pontos piscando + segundos pequenos abaixo.
Brackets nos quatro cantos e scanlines sutis pra dar cara de CRT.
Toque/A/MENU -> abre o home.
"""
from __future__ import annotations

import datetime as dt
import unicodedata

import pygame

from ..core import input as bmo_input
from ..core.theme import render_text
from ..services.weather import WeatherService

PT_WEEKDAYS = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]
PT_MONTHS = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]

BLACK = (0, 0, 0)
WHITE = (235, 235, 235)
DIM = (95, 95, 95)
SCANLINE = (10, 10, 10)


def _ascii_upper(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").upper()


class ClockScreen:
    def __init__(self, on_open_home) -> None:
        self.on_open_home = on_open_home
        self.weather = WeatherService()
        self._t = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == bmo_input.ACTION_EVENT:
            action = event.action
            if action in (bmo_input.Action.TAP, bmo_input.Action.A, bmo_input.Action.MENU):
                self.on_open_home()

    def update(self, dt_: float) -> None:
        self._t += dt_

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BLACK)
        self._draw_scanlines(surface)
        self._draw_corners(surface)
        self._draw_status_dot(surface)
        self._draw_weather(surface)
        self._draw_time(surface)
        self._draw_date(surface)

    # ---------- decoração ----------

    def _draw_scanlines(self, surface: pygame.Surface) -> None:
        w, h = surface.get_size()
        for y in range(0, h, 2):
            pygame.draw.line(surface, SCANLINE, (0, y), (w - 1, y))

    def _draw_corners(self, surface: pygame.Surface) -> None:
        w, h = surface.get_size()
        length = 14
        thick = 2
        m = 4
        # sup-esq
        pygame.draw.rect(surface, WHITE, (m, m, length, thick))
        pygame.draw.rect(surface, WHITE, (m, m, thick, length))
        # sup-dir
        pygame.draw.rect(surface, WHITE, (w - m - length, m, length, thick))
        pygame.draw.rect(surface, WHITE, (w - m - thick, m, thick, length))
        # inf-esq
        pygame.draw.rect(surface, WHITE, (m, h - m - thick, length, thick))
        pygame.draw.rect(surface, WHITE, (m, h - m - length, thick, length))
        # inf-dir
        pygame.draw.rect(surface, WHITE, (w - m - length, h - m - thick, length, thick))
        pygame.draw.rect(surface, WHITE, (w - m - thick, h - m - length, thick, length))

    def _draw_status_dot(self, surface: pygame.Surface) -> None:
        # bolinha piscando no canto sup-dir tipo "LED de power"
        on = (self._t % 1.6) < 1.2
        color = WHITE if on else DIM
        pygame.draw.rect(surface, color, (surface.get_width() - 26, 14, 3, 3))

    # ---------- conteúdo ----------

    def _draw_weather(self, surface: pygame.Surface) -> None:
        snap = self.weather.get()
        temp = f"{snap.temp_c:.0f}C" if snap.ok and snap.temp_c is not None else "--C"
        hum = f"{snap.humidity}%" if snap.ok and snap.humidity is not None else "--%"
        raw_desc = snap.description if snap.ok and snap.description else "sem dados"
        desc = _ascii_upper(raw_desc)[:12]

        x = 16
        rows = [
            ("TEMP", temp),
            ("UMID", hum),
            ("CEU", desc),
        ]
        for i, (label, value) in enumerate(rows):
            y = 22 + i * 16
            surface.blit(render_text(label, 8, DIM), (x, y + 1))
            surface.blit(render_text(value, 10, WHITE), (x + 48, y))

    def _draw_time(self, surface: pygame.Surface) -> None:
        now = dt.datetime.now()
        blink = (self._t % 1.0) < 0.5
        sep = ":" if blink else " "
        hh_mm = f"{now.hour:02d}{sep}{now.minute:02d}"
        big = render_text(hh_mm, 44, WHITE)
        cx = surface.get_width() // 2
        cy = surface.get_height() // 2 + 4
        rect = big.get_rect(center=(cx, cy))
        surface.blit(big, rect)

        ss = f"{now.second:02d}"
        small = render_text(ss, 10, DIM)
        sr = small.get_rect(midtop=(cx, rect.bottom + 4))
        surface.blit(small, sr)

    def _draw_date(self, surface: pygame.Surface) -> None:
        now = dt.datetime.now()
        weekday = PT_WEEKDAYS[now.weekday()]
        month = PT_MONTHS[now.month - 1]
        line1 = f"{weekday} {now.day:02d}"
        line2 = month
        x = surface.get_width() - 16
        y = surface.get_height() - 26
        img1 = render_text(line1, 8, WHITE)
        img2 = render_text(line2, 8, DIM)
        surface.blit(img1, img1.get_rect(topright=(x, y)))
        surface.blit(img2, img2.get_rect(topright=(x, y + 10)))
