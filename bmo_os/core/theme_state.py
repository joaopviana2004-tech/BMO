"""Tema (dark/light/auto) + barra de status + mini-clock do BMO OS.

Aplica o tema mutando in-place os pygame.Color de widgets.CRT_*. Como Color
é mutável, todos os screens que importam essas constantes (mesmo via
`from widgets import CRT_BLACK as BLACK`) veem o novo valor automaticamente
sem precisar re-importar.

Status bar (canto sup-direito): sol/lua, sinal (mock 4/4), bateria (mock 100%).
Mini-clock: HH:MM pequeno pras telas idle que não são o clock-screen em si.
"""
from __future__ import annotations

import datetime as dt
import math

import pygame

from . import config, widgets
from .theme import render_text

DARK = {
    "bg":   (0, 0, 0),
    "fg":   (235, 235, 235),
    "dim":  (95, 95, 95),
    "scan": (10, 10, 10),
}
LIGHT = {
    "bg":   (225, 221, 205),   # creme tipo Game Boy DMG
    "fg":   (22, 24, 28),
    "dim":  (130, 128, 115),
    "scan": (208, 204, 190),
}

THEME_OPTIONS = ["auto", "dark", "light"]
THEME_LABELS  = {"auto": "AUTO", "dark": "ESCURO", "light": "CLARO"}

# Janela considerada "dia" pro modo auto.
DAY_START_H = 6
DAY_END_H = 18


def is_daytime() -> bool:
    h = dt.datetime.now().hour
    return DAY_START_H <= h < DAY_END_H


def resolve_theme_name() -> str:
    t = (config.get("theme") or "auto").strip().lower()
    if t in ("light", "dark"):
        return t
    return "light" if is_daytime() else "dark"


def apply_theme() -> None:
    """Atualiza widgets.CRT_* in-place pra refletir o tema corrente."""
    src = LIGHT if resolve_theme_name() == "light" else DARK
    widgets.CRT_BLACK.update(src["bg"])
    widgets.CRT_WHITE.update(src["fg"])
    widgets.CRT_DIM.update(src["dim"])
    widgets.CRT_SCAN.update(src["scan"])


# ---------- status bar ----------

# Getter opcional de conectividade (main registra lambda: network.online).
# None = desconhecido -> mantém o sinal "cheio" (comportamento antigo, mock).
_online_getter = None


def set_online_getter(fn) -> None:
    """Liga a status bar ao NetworkService (mostra 'sem internet')."""
    global _online_getter
    _online_getter = fn


def draw_status_bar(surface: pygame.Surface, *, top_pad: int = 7, right_pad: int = 10) -> None:
    """Top-right: sol/lua + sinal (internet) + bateria (mock 100%).

    O sinal reflete a conectividade real (via set_online_getter): cheio quando
    online, barras vazias + barra cortada quando offline. top_pad/right_pad
    afastam a barra dos brackets de canto (o clock pede mais).
    """
    fg = widgets.CRT_WHITE
    bg = widgets.CRT_BLACK
    dim = widgets.CRT_DIM
    right = surface.get_width() - right_pad
    top = top_pad

    online = None
    if _online_getter is not None:
        try:
            online = bool(_online_getter())
        except Exception:
            online = None

    # ---- Bateria (18x9 corpo + 2px terminal) ----
    bat = pygame.Rect(right - 20, top, 18, 9)
    pygame.draw.rect(surface, fg, bat, 1)
    pygame.draw.rect(surface, fg, (bat.right, bat.top + 2, 2, bat.height - 4))
    # fill 100%
    pygame.draw.rect(surface, fg, (bat.left + 2, bat.top + 2, bat.width - 4, bat.height - 4))

    # ---- Sinal (4 barras crescentes; offline = vazias + corte) ----
    sig_right = bat.left - 4
    bar_w = 2
    bar_gap = 1
    bars_total = 4 * bar_w + 3 * bar_gap   # 11
    sig_left = sig_right - bars_total
    for i in range(4):
        x = sig_left + i * (bar_w + bar_gap)
        h = 2 + i * 2   # 2,4,6,8
        y = top + 9 - h
        if online is False:
            pygame.draw.rect(surface, dim, (x, y, bar_w, h), 1)   # só contorno
        else:
            pygame.draw.rect(surface, fg, (x, y, bar_w, h))
    if online is False:
        # barra diagonal cortando o sinal (= sem internet)
        pygame.draw.line(surface, fg, (sig_left - 1, top + 9), (sig_right + 1, top), 1)

    # ---- Sol / Lua ----
    icon_right = sig_left - 4
    cx = icon_right - 5
    cy = top + 4
    if is_daytime():
        _draw_sun(surface, cx, cy, fg)
    else:
        _draw_moon(surface, cx, cy, fg, bg)


def _draw_sun(surface, cx: int, cy: int, fg) -> None:
    pygame.draw.circle(surface, fg, (cx, cy), 2)
    for ang_deg in (0, 45, 90, 135, 180, 225, 270, 315):
        a = math.radians(ang_deg)
        x1 = cx + int(round(math.cos(a) * 4))
        y1 = cy + int(round(math.sin(a) * 4))
        x2 = cx + int(round(math.cos(a) * 5))
        y2 = cy + int(round(math.sin(a) * 5))
        pygame.draw.line(surface, fg, (x1, y1), (x2, y2), 1)


def _draw_moon(surface, cx: int, cy: int, fg, bg) -> None:
    # crescente: círculo fg cheio - círculo bg com offset
    pygame.draw.circle(surface, fg, (cx, cy), 4)
    pygame.draw.circle(surface, bg, (cx + 2, cy - 1), 4)


def draw_mini_clock(surface: pygame.Surface, x: int, y: int, color) -> None:
    """HH:MM pequeno (10pt consolas), midtop em (x, y)."""
    now = dt.datetime.now()
    txt = render_text(now.strftime("%H:%M"), 10, color, pixel=False)
    surface.blit(txt, txt.get_rect(midtop=(x, y)))
