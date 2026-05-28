"""Tela do relógio — replica img_0471.

Fundo verde BMO, barrinha de status no topo (temp/umidade),
horário gigante no centro, data embaixo.
Toque em qualquer lugar -> abre menu home.
"""
from __future__ import annotations

import datetime as dt

import pygame

from ..core import input as bmo_input
from ..core.theme import Colors, render_text
from ..services.weather import WeatherService

PT_WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
PT_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


class ClockScreen:
    def __init__(self, on_open_home) -> None:
        self.on_open_home = on_open_home
        self.weather = WeatherService()

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == bmo_input.ACTION_EVENT:
            action = event.action
            if action in (bmo_input.Action.TAP, bmo_input.Action.A, bmo_input.Action.MENU):
                self.on_open_home()

    def update(self, dt_: float) -> None: ...

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(Colors.BG_GREEN)
        self._draw_dither(surface)
        self._draw_status_bar(surface)
        self._draw_time(surface)
        self._draw_date(surface)

    def _draw_dither(self, surface: pygame.Surface) -> None:
        # textura sutil estilo dithering
        for y in range(0, surface.get_height(), 4):
            for x in range((y // 4) % 2 * 2, surface.get_width(), 4):
                surface.set_at((x, y), (140, 196, 96))

    def _draw_status_bar(self, surface: pygame.Surface) -> None:
        snap = self.weather.get()
        temp = f"{snap.temp_c:.0f}C" if snap.ok and snap.temp_c is not None else "--C"
        hum = f"{snap.humidity}%" if snap.ok and snap.humidity is not None else "--%"
        line = f"i {temp}    H {hum}"
        img = render_text(line, 10, Colors.CYAN)
        surface.blit(img, (12, 8))

    def _draw_time(self, surface: pygame.Surface) -> None:
        now = dt.datetime.now()
        hh_mm = now.strftime("%H:%M")
        # sombra
        shadow = render_text(hh_mm, 56, (60, 120, 70))
        main = render_text(hh_mm, 56, Colors.CYAN)
        sr = shadow.get_rect(center=(surface.get_width() // 2 + 2, 120 + 2))
        mr = main.get_rect(center=(surface.get_width() // 2, 120))
        surface.blit(shadow, sr)
        surface.blit(main, mr)

    def _draw_date(self, surface: pygame.Surface) -> None:
        now = dt.datetime.now()
        weekday = PT_WEEKDAYS[now.weekday()]
        month = PT_MONTHS[now.month - 1]
        text = f"{weekday}, {now.day:02d} {month}".upper()
        img = render_text(text, 12, Colors.WHITE)
        rect = img.get_rect(midbottom=(surface.get_width() // 2, surface.get_height() - 14))
        surface.blit(img, rect)
