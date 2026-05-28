"""Paleta de cores, fontes e constantes visuais do BMO OS."""
from __future__ import annotations

import os
from pathlib import Path

import pygame

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"


class Colors:
    BG_GREEN = (157, 216, 111)
    BG_DARK = (10, 22, 30)
    CYAN = (95, 225, 217)
    CYAN_DIM = (60, 160, 155)
    YELLOW = (247, 213, 71)
    RED = (233, 75, 60)
    GREEN_BTN = (91, 168, 95)
    BMO_BLUE = (159, 229, 221)
    WHITE = (240, 250, 248)
    BLACK = (8, 14, 18)
    SHADOW = (0, 0, 0, 90)


LOGICAL_SIZE = (400, 240)
WINDOW_SIZE = (800, 480)
FPS = 30


_font_cache: dict[tuple[str, int], pygame.font.Font] = {}


def get_font(size: int, *, pixel: bool = True) -> pygame.font.Font:
    """Retorna fonte pixel se o .ttf estiver em assets/fonts/, senão fallback."""
    key = ("pixel" if pixel else "default", size)
    if key in _font_cache:
        return _font_cache[key]

    font: pygame.font.Font | None = None
    if pixel:
        for name in ("PressStart2P.ttf", "pixel.ttf", "DepartureMono.ttf"):
            path = FONTS_DIR / name
            if path.exists():
                font = pygame.font.Font(str(path), size)
                break

    if font is None:
        font = pygame.font.SysFont("consolas,courier,monospace", size, bold=True)

    _font_cache[key] = font
    return font


def render_text(text: str, size: int, color, *, pixel: bool = True) -> pygame.Surface:
    return get_font(size, pixel=pixel).render(text, False, color)
