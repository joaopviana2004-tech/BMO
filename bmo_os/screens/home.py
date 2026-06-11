"""Tela home — hub de categorias + carrossel em cada subtela.

Nível 1: IA · REPOUSO · ESTUDOS · AJUSTES
Nível 2: apps da categoria (carrossel horizontal, mesmo estilo CRT).
Botão no canto sup-esq: VOLTAR (hub → ambient) ou MENU (subtela → hub).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import pygame

from ..core import config, theme_state
from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_dashed_rect, draw_scanlines,
    LOGICAL_SIZE,
)
from ..services import audio


@dataclass
class HubItem:
    label: str
    draw_icon: Callable[[pygame.Surface, int, int], None]
    action: Callable[[], None]


@dataclass
class HubCategory:
    label: str
    draw_icon: Callable[[pygame.Surface, int, int], None]
    items: list[HubItem]


# ── ícones de apps ────────────────────────────────────────────────

def _icon_sleep(surf: pygame.Surface, cx: int, cy: int) -> None:
    body = pygame.Rect(0, 0, 36, 28)
    body.center = (cx, cy - 2)
    pygame.draw.rect(surf, CRT_WHITE, body, 2, border_radius=5)
    pygame.draw.line(surf, CRT_DIM, (body.left + 8, body.centery - 3), (body.left + 14, body.centery - 3), 2)
    pygame.draw.line(surf, CRT_DIM, (body.right - 14, body.centery - 3), (body.right - 8, body.centery - 3), 2)
    pygame.draw.line(surf, CRT_DIM, (cx - 5, body.centery + 6), (cx + 5, body.centery + 6), 2)
    for i, ch in enumerate(["z", "z"]):
        img = render_text(ch, 8, CRT_DIM)
        surf.blit(img, (body.right + 2 + i * 6, body.top + 2 + i * 5))


def _icon_suspend(surf: pygame.Surface, cx: int, cy: int) -> None:
    pygame.draw.circle(surf, CRT_WHITE, (cx - 2, cy), 14)
    pygame.draw.circle(surf, CRT_BLACK, (cx + 4, cy - 3), 14)
    for sx, sy in [(cx - 16, cy - 14), (cx + 14, cy + 10), (cx + 12, cy - 12)]:
        pygame.draw.rect(surf, CRT_WHITE, (sx, sy, 2, 2))


def _icon_games(surf: pygame.Surface, cx: int, cy: int) -> None:
    pad = pygame.Rect(0, 0, 42, 26)
    pad.center = (cx, cy - 2)
    pygame.draw.rect(surf, CRT_WHITE, pad, 2, border_radius=6)
    dx, dy = pad.left + 10, pad.centery
    pygame.draw.line(surf, CRT_WHITE, (dx - 5, dy), (dx + 5, dy), 2)
    pygame.draw.line(surf, CRT_WHITE, (dx, dy - 5), (dx, dy + 5), 2)
    pygame.draw.circle(surf, CRT_WHITE, (pad.right - 12, pad.centery - 3), 3, 2)
    pygame.draw.circle(surf, CRT_WHITE, (pad.right - 5, pad.centery + 3), 3, 2)


def _icon_settings(surf: pygame.Surface, cx: int, cy: int) -> None:
    pygame.draw.circle(surf, CRT_WHITE, (cx, cy - 2), 12, 2)
    pygame.draw.circle(surf, CRT_WHITE, (cx, cy - 2), 4, 2)
    for i in range(6):
        ang = i * math.pi / 3
        x1 = cx + int(math.cos(ang) * 13)
        y1 = (cy - 2) + int(math.sin(ang) * 13)
        x2 = cx + int(math.cos(ang) * 17)
        y2 = (cy - 2) + int(math.sin(ang) * 17)
        pygame.draw.line(surf, CRT_WHITE, (x1, y1), (x2, y2), 3)


def _icon_photo(surf: pygame.Surface, cx: int, cy: int) -> None:
    body = pygame.Rect(0, 0, 38, 26)
    body.center = (cx, cy + 1)
    pygame.draw.rect(surf, CRT_WHITE, body, 2, border_radius=3)
    pygame.draw.rect(surf, CRT_WHITE, (cx - 6, body.top - 4, 12, 4))
    pygame.draw.circle(surf, CRT_WHITE, (cx, body.centery + 1), 7, 2)
    pygame.draw.circle(surf, CRT_DIM, (cx, body.centery + 1), 3)
    pygame.draw.rect(surf, CRT_WHITE, (body.right - 6, body.top + 3, 3, 3))


def _icon_tasks(surf: pygame.Surface, cx: int, cy: int) -> None:
    col_w, col_h, gap = 12, 30, 3
    total_w = 3 * col_w + 2 * gap
    start_x = cx - total_w // 2
    top_y = cy - col_h // 2
    for i in range(3):
        x = start_x + i * (col_w + gap)
        pygame.draw.rect(surf, CRT_WHITE, (x, top_y, col_w, col_h), 1)
        pygame.draw.rect(surf, CRT_WHITE, (x + 2, top_y + 4, col_w - 4, 3))
        pygame.draw.rect(surf, CRT_WHITE, (x + 2, top_y + 11, col_w - 4, 3))
        if i < 2:
            pygame.draw.rect(surf, CRT_DIM, (x + 2, top_y + 18, col_w - 4, 3))


def _icon_agenda(surf: pygame.Surface, cx: int, cy: int) -> None:
    body = pygame.Rect(0, 0, 36, 32)
    body.center = (cx, cy + 2)
    pygame.draw.rect(surf, CRT_WHITE, body, 2, border_radius=3)
    pygame.draw.rect(surf, CRT_WHITE, (body.left, body.top, body.width, 7))
    pygame.draw.rect(surf, CRT_BLACK, (body.left + 8, body.top - 4, 2, 5))
    pygame.draw.rect(surf, CRT_BLACK, (body.right - 10, body.top - 4, 2, 5))
    pygame.draw.rect(surf, CRT_WHITE, (body.left + 8, body.top - 5, 2, 4))
    pygame.draw.rect(surf, CRT_WHITE, (body.right - 10, body.top - 5, 2, 4))
    for r in range(2):
        for c in range(3):
            x = body.left + 6 + c * 9
            y = body.top + 12 + r * 8
            on = (r == 1 and c == 1)
            pygame.draw.rect(surf, CRT_WHITE if on else CRT_DIM, (x, y, 5, 4))


def _icon_pomodoro(surf: pygame.Surface, cx: int, cy: int) -> None:
    pygame.draw.circle(surf, CRT_WHITE, (cx, cy + 4), 15, 2)
    pygame.draw.arc(surf, CRT_DIM, pygame.Rect(cx - 9, cy - 3, 10, 10),
                    math.pi * 0.6, math.pi * 1.1, 2)
    pygame.draw.rect(surf, CRT_WHITE, (cx - 1, cy - 14, 2, 5))
    pygame.draw.line(surf, CRT_WHITE, (cx, cy - 11), (cx - 6, cy - 13), 2)
    pygame.draw.line(surf, CRT_WHITE, (cx, cy - 11), (cx + 6, cy - 13), 2)


def _icon_recorder(surf: pygame.Surface, cx: int, cy: int) -> None:
    body = pygame.Rect(0, 0, 40, 26)
    body.center = (cx, cy)
    pygame.draw.rect(surf, CRT_WHITE, body, 2, border_radius=3)
    pygame.draw.circle(surf, CRT_WHITE, (body.left + 11, body.centery), 5, 2)
    pygame.draw.circle(surf, CRT_WHITE, (body.right - 11, body.centery), 5, 2)
    pygame.draw.line(surf, CRT_DIM, (body.left + 16, body.centery),
                     (body.right - 16, body.centery), 2)
    pygame.draw.circle(surf, CRT_WHITE, (body.right + 5, body.top - 2), 4)


def _icon_devhub(surf: pygame.Surface, cx: int, cy: int) -> None:
    body = pygame.Rect(0, 0, 38, 28)
    body.center = (cx, cy)
    pygame.draw.rect(surf, CRT_WHITE, body, 2, border_radius=2)
    pygame.draw.rect(surf, CRT_DIM, (body.left + 2, body.top + 2, body.width - 4, 5))
    pygame.draw.line(surf, CRT_DIM, (body.left + 2, body.top + 9), (body.right - 2, body.top + 9), 1)
    prompt = render_text(">", 8, CRT_WHITE)
    surf.blit(prompt, (body.left + 4, body.top + 12))
    pygame.draw.line(surf, CRT_DIM, (body.left + 12, body.top + 15),
                     (body.right - 4, body.top + 15), 1)
    pygame.draw.line(surf, CRT_DIM, (body.left + 12, body.top + 20),
                     (body.right - 10, body.top + 20), 1)


def _icon_brain(surf: pygame.Surface, cx: int, cy: int) -> None:
    nodes = [(cx, cy - 12), (cx - 14, cy + 2), (cx + 13, cy - 2),
             (cx - 6, cy + 13), (cx + 10, cy + 11)]
    edges = [(0, 1), (0, 2), (1, 3), (2, 4), (3, 4), (1, 2)]
    for a, b in edges:
        pygame.draw.line(surf, CRT_DIM, nodes[a], nodes[b], 1)
    for i, (x, y) in enumerate(nodes):
        pygame.draw.circle(surf, CRT_WHITE, (x, y), 4 if i == 0 else 3)


def _icon_sysinfo(surf: pygame.Surface, cx: int, cy: int) -> None:
    body = pygame.Rect(0, 0, 26, 26)
    body.center = (cx, cy)
    pygame.draw.rect(surf, CRT_WHITE, body, 2)
    pygame.draw.rect(surf, CRT_DIM, body.inflate(-12, -12))
    for off in (-7, 0, 7):
        pygame.draw.line(surf, CRT_WHITE, (body.left + 13 + off, body.top - 4), (body.left + 13 + off, body.top), 2)
        pygame.draw.line(surf, CRT_WHITE, (body.left + 13 + off, body.bottom), (body.left + 13 + off, body.bottom + 4), 2)
        pygame.draw.line(surf, CRT_WHITE, (body.left - 4, body.top + 13 + off), (body.left, body.top + 13 + off), 2)
        pygame.draw.line(surf, CRT_WHITE, (body.right, body.top + 13 + off), (body.right + 4, body.top + 13 + off), 2)


def _icon_aitest(surf: pygame.Surface, cx: int, cy: int) -> None:
    cap = pygame.Rect(0, 0, 14, 22)
    cap.center = (cx, cy - 4)
    pygame.draw.rect(surf, CRT_WHITE, cap, 2, border_radius=7)
    pygame.draw.arc(surf, CRT_WHITE, pygame.Rect(cx - 12, cy - 10, 24, 26), math.pi, 2 * math.pi, 2)
    pygame.draw.line(surf, CRT_WHITE, (cx, cy + 12), (cx, cy + 18), 2)
    pygame.draw.line(surf, CRT_WHITE, (cx - 7, cy + 18), (cx + 7, cy + 18), 2)
    pygame.draw.arc(surf, CRT_DIM, pygame.Rect(cx + 10, cy - 12, 10, 18), -1.0, 1.0, 2)


def _icon_flappy_ai(surf: pygame.Surface, cx: int, cy: int) -> None:
    # pássaro + nós de rede neural (treino por neuroevolução)
    nodes = [(cx - 15, cy - 8), (cx - 15, cy + 8), (cx - 2, cy)]
    for a in (0, 1):
        pygame.draw.line(surf, CRT_DIM, nodes[a], nodes[2], 1)
    for x, y in nodes:
        pygame.draw.circle(surf, CRT_WHITE, (x, y), 2)
    # passarinho à direita
    bx, by = cx + 10, cy
    pygame.draw.rect(surf, CRT_WHITE, (bx - 5, by - 5, 10, 10))
    pygame.draw.rect(surf, CRT_BLACK, (bx + 1, by - 2, 2, 2))      # olho
    pygame.draw.rect(surf, CRT_DIM, (bx + 5, by, 3, 2))           # bico
    pygame.draw.line(surf, CRT_DIM, nodes[2], (bx - 5, by), 1)


def _icon_power(surf: pygame.Surface, cx: int, cy: int) -> None:
    # símbolo de power: anel com abertura no topo + traço vertical
    pygame.draw.circle(surf, CRT_WHITE, (cx, cy + 1), 14, 2)
    pygame.draw.rect(surf, CRT_BLACK, (cx - 4, cy - 16, 8, 9))   # abre o anel no topo
    pygame.draw.line(surf, CRT_WHITE, (cx, cy - 13), (cx, cy + 1), 2)


def _icon_update(surf: pygame.Surface, cx: int, cy: int) -> None:
    # setas circulares (refresh): anel com dois cortes + pontas de seta
    pygame.draw.circle(surf, CRT_WHITE, (cx, cy), 13, 2)
    pygame.draw.rect(surf, CRT_BLACK, (cx + 8, cy - 4, 10, 8))   # corte direito
    pygame.draw.rect(surf, CRT_BLACK, (cx - 18, cy - 4, 10, 8))  # corte esquerdo
    pygame.draw.polygon(surf, CRT_WHITE, [
        (cx + 8, cy - 8), (cx + 8, cy + 2), (cx + 15, cy - 3)])
    pygame.draw.polygon(surf, CRT_WHITE, [
        (cx - 8, cy + 8), (cx - 8, cy - 2), (cx - 15, cy + 3)])


# ── ícones das categorias (hub) ───────────────────────────────────

def _icon_cat_ia(surf: pygame.Surface, cx: int, cy: int) -> None:
    # chip + faísca
    body = pygame.Rect(0, 0, 30, 30)
    body.center = (cx, cy + 2)
    pygame.draw.rect(surf, CRT_WHITE, body, 2, border_radius=4)
    pygame.draw.rect(surf, CRT_DIM, body.inflate(-14, -14))
    for i in range(4):
        ang = i * math.pi / 2 + 0.4
        x1 = cx + int(math.cos(ang) * 18)
        y1 = cy + 2 + int(math.sin(ang) * 18)
        x2 = cx + int(math.cos(ang) * 22)
        y2 = cy + 2 + int(math.sin(ang) * 22)
        pygame.draw.line(surf, CRT_WHITE, (x1, y1), (x2, y2), 2)


def _icon_cat_rest(surf: pygame.Surface, cx: int, cy: int) -> None:
    _icon_suspend(surf, cx, cy)


def _icon_cat_study(surf: pygame.Surface, cx: int, cy: int) -> None:
    # livro aberto
    pygame.draw.polygon(surf, CRT_WHITE, [
        (cx, cy - 14), (cx - 18, cy - 6), (cx - 18, cy + 14), (cx, cy + 8),
    ], 2)
    pygame.draw.polygon(surf, CRT_WHITE, [
        (cx, cy - 14), (cx + 18, cy - 6), (cx + 18, cy + 14), (cx, cy + 8),
    ], 2)
    pygame.draw.line(surf, CRT_DIM, (cx, cy - 14), (cx, cy + 8), 1)
    for dy in (-4, 2, 8):
        pygame.draw.line(surf, CRT_DIM, (cx - 14, cy + dy), (cx - 4, cy + dy - 2), 1)
        pygame.draw.line(surf, CRT_DIM, (cx + 4, cy + dy - 2), (cx + 14, cy + dy), 1)


def _icon_cat_settings(surf: pygame.Surface, cx: int, cy: int) -> None:
    _icon_settings(surf, cx, cy)


def build_categories(
    *,
    on_brain: Callable[[], None],
    on_aitest: Callable[[], None],
    on_flappy_ai: Callable[[], None],
    on_sleep: Callable[[], None],
    on_suspend: Callable[[], None],
    on_tasks: Callable[[], None],
    on_agenda: Callable[[], None],
    on_pomodoro: Callable[[], None],
    on_recorder: Callable[[], None],
    on_games: Callable[[], None],
    on_photo: Callable[[], None],
    on_dev: Callable[[], None],
    on_settings: Callable[[], None],
    on_sysinfo: Callable[[], None],
    on_shutdown: Callable[[], None],
    on_update: Callable[[], None],
) -> list[HubCategory]:
    """Monta as 4 categorias do hub a partir dos callbacks do main."""
    return [
        HubCategory("IA", _icon_cat_ia, [
            HubItem("CEREBRO", _icon_brain, on_brain),
            HubItem("TESTE IA", _icon_aitest, on_aitest),
            HubItem("FLAPPY IA", _icon_flappy_ai, on_flappy_ai),
        ]),
        HubCategory("REPOUSO", _icon_cat_rest, [
            HubItem("SLEEP", _icon_sleep, on_sleep),
            HubItem("SUSPEND", _icon_suspend, on_suspend),
        ]),
        HubCategory("ESTUDOS", _icon_cat_study, [
            HubItem("TASKS", _icon_tasks, on_tasks),
            HubItem("AGENDA", _icon_agenda, on_agenda),
            HubItem("FOCO", _icon_pomodoro, on_pomodoro),
            HubItem("GRAVAR", _icon_recorder, on_recorder),
            HubItem("JOGOS", _icon_games, on_games),
            HubItem("FOTO", _icon_photo, on_photo),
            HubItem("DEV", _icon_devhub, on_dev),
        ]),
        HubCategory("AJUSTES", _icon_cat_settings, [
            HubItem("SETTINGS", _icon_settings, on_settings),
            HubItem("SISTEMA", _icon_sysinfo, on_sysinfo),
            HubItem("DESLIGAR", _icon_power, on_shutdown),
            HubItem("ATUALIZAR", _icon_update, on_update),
        ]),
    ]


W = LOGICAL_SIZE[0]
H = LOGICAL_SIZE[1]


class HomeScreen:
    """Menu em pager de grades.

    Cada categoria é uma *página*: seus apps aparecem numa grade (vários ícones
    por vez). Arrasta pro lado (swipe, com inércia/flick) ou usa as setas/←→ pra
    trocar de categoria, com slide animado e a vizinha 'espiando'. O destaque de
    seleção desliza suave entre os tiles. Toque num tile abre o app.

    O toque é tratado a partir dos eventos brutos (down/move/up) pra distinguir
    tap de swipe — o `TAP` sintético do app (postado no press) é ignorado aqui.
    """

    def __init__(self, *, on_back, categories: list[HubCategory]) -> None:
        self.on_back = on_back
        self.categories = categories
        self._page = 0            # categoria atual
        self._sel = 0             # tile selecionado na página (cursor teclado/GPIO)
        self._t = 0.0
        self._idle = 0.0
        self._timed_out = False
        # animação de slide entre páginas (offset px da página atual; 0 = parado)
        self._slide = 0.0
        self._slide_at_press = 0.0
        # gesto de ponteiro
        self._ptr_down = False
        self._moved = False
        self._press = (0, 0)
        self._press_t = 0.0
        # destaque animado [x, y, w, h] e bob de entrada
        self._hl = [0.0, 0.0, 0.0, 0.0]
        self._enter_off = 0.0
        self._snap_hl()

    # ── ciclo de vida ─────────────────────────────────────────────
    def enter(self) -> None:
        self._idle = 0.0
        self._timed_out = False
        self._ptr_down = False
        self._moved = False
        self._enter_off = 12.0
        self._sel = min(self._sel, len(self._active.items) - 1)
        self._snap_hl()

    def exit(self) -> None: ...

    @property
    def _active(self) -> HubCategory:
        return self.categories[self._page]

    # ── layout da grade ───────────────────────────────────────────
    @staticmethod
    def _cols(n: int) -> int:
        if n <= 1:
            return 1
        if n <= 4:
            return 2
        if n <= 6:
            return 3
        return 4

    def _layout(self, n: int):
        ax, ay = SAFE_INSET + 8, SAFE_INSET + 30
        aw, ah = W - 2 * ax, H - ay - (SAFE_INSET + 18)
        gap = 10
        cols = self._cols(n)
        rows = max(1, (n + cols - 1) // cols)
        tile_w = min((aw - (cols - 1) * gap) // cols, 118)
        tile_h = min((ah - (rows - 1) * gap) // rows, 84)
        grid_h = rows * tile_h + (rows - 1) * gap
        y0 = ay + (ah - grid_h) // 2
        return cols, rows, tile_w, tile_h, gap, ax, ay, aw, ah, y0

    def _tile_rect(self, i: int, n: int) -> pygame.Rect:
        cols, rows, tw, th, gap, ax, ay, aw, ah, y0 = self._layout(n)
        row, col = i // cols, i % cols
        in_row = min(cols, n - row * cols)
        row_w = in_row * tw + (in_row - 1) * gap
        rx = ax + (aw - row_w) // 2
        return pygame.Rect(rx + col * (tw + gap), y0 + row * (th + gap), tw, th)

    def _snap_hl(self) -> None:
        r = self._tile_rect(self._sel, len(self._active.items))
        self._hl = [float(r.x), float(r.y), float(r.w), float(r.h)]

    # ── navegação ─────────────────────────────────────────────────
    def _page_step(self, direction: int, sel: str | None = None) -> None:
        n_pages = len(self.categories)
        self._page = (self._page + direction) % n_pages
        self._slide = max(-W, min(W, self._slide + direction * W))
        n = len(self._active.items)
        if sel == "first":
            self._sel = 0
        elif sel == "last":
            self._sel = n - 1
        else:
            self._sel = min(self._sel, n - 1)
        self._snap_hl()
        audio.play("tick")

    def _launch(self) -> None:
        audio.play("select")
        self._active.items[self._sel].action()

    def _on_action(self, a) -> None:
        A = bmo_input.Action
        n = len(self._active.items)
        cols = self._cols(n)
        if a == A.LEFT:
            if self._sel > 0:
                self._sel -= 1
                self._snap_hl()
                audio.play("tick")
            else:
                self._page_step(-1, sel="last")
        elif a == A.RIGHT:
            if self._sel < n - 1:
                self._sel += 1
                self._snap_hl()
                audio.play("tick")
            else:
                self._page_step(1, sel="first")
        elif a == A.UP:
            self._sel = max(0, self._sel - cols)
            self._snap_hl()
            audio.play("tick")
        elif a == A.DOWN:
            self._sel = min(n - 1, self._sel + cols)
            self._snap_hl()
            audio.play("tick")
        elif a == A.A:
            self._launch()
        elif a in (A.MENU, A.B):
            audio.play("back")
            self.on_back()

    # ── input ─────────────────────────────────────────────────────
    def _to_logical(self, pos: tuple[int, int]) -> tuple[int, int]:
        try:
            win = pygame.display.get_window_size()
            return (pos[0] * W // win[0], pos[1] * H // win[1])
        except Exception:
            return (pos[0] // 2, pos[1] // 2)

    def handle_event(self, event: pygame.event.Event) -> None:
        et = event.type
        if et == bmo_input.ACTION_EVENT:
            self._idle = 0.0
            if event.action == bmo_input.Action.TAP:
                return  # toque tratado via eventos brutos (tap vs swipe)
            self._on_action(event.action)
            return
        if et == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 1) == 1:
            self._idle = 0.0
            self._ptr_down = True
            self._moved = False
            self._press = self._to_logical(event.pos)
            self._press_t = self._t
            self._slide_at_press = self._slide
        elif et == pygame.MOUSEMOTION and self._ptr_down:
            self._idle = 0.0
            lx, _ = self._to_logical(event.pos)
            dx = lx - self._press[0]
            if abs(dx) > 3:
                self._moved = True
            if self._moved:
                self._slide = max(-W, min(W, self._slide_at_press + dx))
        elif et == pygame.MOUSEBUTTONUP and getattr(event, "button", 1) == 1 and self._ptr_down:
            self._ptr_down = False
            if self._moved:
                self._settle_drag()
            else:
                self._handle_tap(self._press)

    def _settle_drag(self) -> None:
        flick = (self._t - self._press_t) < 0.32 and abs(self._slide - self._slide_at_press) > 24
        moved_right = self._slide - self._slide_at_press > 0
        if self._slide > W * 0.25 or (flick and moved_right):
            self._page_step(-1)
        elif self._slide < -W * 0.25 or (flick and not moved_right):
            self._page_step(1)
        # senão: volta sozinho pra 0 no update()

    def _handle_tap(self, pos: tuple[int, int]) -> None:
        if self._back_btn().collidepoint(pos):
            audio.play("back")
            self.on_back()
            return
        # tile tem prioridade sobre as setas (em página cheia o swipe pagina)
        if abs(self._slide) < 4:
            n = len(self._active.items)
            for i in range(n):
                if self._tile_rect(i, n).collidepoint(pos):
                    self._sel = i
                    self._snap_hl()
                    self._launch()
                    return
        if self._arrow_rect("l").collidepoint(pos):
            self._page_step(-1)
            return
        if self._arrow_rect("r").collidepoint(pos):
            self._page_step(1)
            return

    # ── update ────────────────────────────────────────────────────
    def update(self, dt: float) -> None:
        self._t += dt
        self._idle += dt
        if not self._ptr_down:
            self._slide += (0.0 - self._slide) * min(1.0, dt * 12)
            if abs(self._slide) < 0.5:
                self._slide = 0.0
        self._enter_off += (0.0 - self._enter_off) * min(1.0, dt * 10)
        tgt = self._tile_rect(self._sel, len(self._active.items))
        k = min(1.0, dt * 16)
        self._hl[0] += (tgt.x - self._hl[0]) * k
        self._hl[1] += (tgt.y - self._hl[1]) * k
        self._hl[2] += (tgt.w - self._hl[2]) * k
        self._hl[3] += (tgt.h - self._hl[3]) * k
        timeout = float(config.get("idle_timeout_s") or 10)
        if self._idle >= timeout and not self._timed_out:
            self._timed_out = True
            self.on_back()

    # ── desenho ───────────────────────────────────────────────────
    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        self._draw_pages(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_back_btn(surface)
        self._draw_title(surface)
        self._draw_arrows(surface)
        self._draw_dots(surface)
        self._draw_idle(surface)

    def _draw_pages(self, surface: pygame.Surface) -> None:
        clip = pygame.Rect(SAFE_INSET, SAFE_INSET + 26, W - 2 * SAFE_INSET, H - 2 * SAFE_INSET - 38)
        surface.set_clip(clip)
        y_off = int(self._enter_off)
        slide = int(self._slide)
        self._draw_page(surface, self._page, slide, y_off, current=True)
        n_pages = len(self.categories)
        if self._slide > 0.5:
            self._draw_page(surface, (self._page - 1) % n_pages, slide - W, y_off, current=False)
        elif self._slide < -0.5:
            self._draw_page(surface, (self._page + 1) % n_pages, slide + W, y_off, current=False)
        # destaque animado (acompanha o slide da página atual)
        pulse = (1.0 + math.sin(self._t * 5)) * 1.5
        hlr = pygame.Rect(int(self._hl[0]) + slide, int(self._hl[1]) + y_off,
                          int(self._hl[2]), int(self._hl[3]))
        draw_dashed_rect(surface, CRT_WHITE, hlr.inflate(int(6 + pulse), int(6 + pulse)))
        surface.set_clip(None)

    def _draw_page(self, surface, page: int, x_off: int, y_off: int, *, current: bool) -> None:
        items = self.categories[page].items
        n = len(items)
        settled = abs(self._slide) < W * 0.5
        for i, item in enumerate(items):
            r = self._tile_rect(i, n).move(x_off, y_off)
            self._draw_tile(surface, r, item, selected=current and settled and i == self._sel)

    def _draw_tile(self, surface, r: pygame.Rect, item: HubItem, *, selected: bool) -> None:
        pygame.draw.rect(surface, CRT_BLACK, r)
        pygame.draw.rect(surface, CRT_WHITE if selected else CRT_DIM, r,
                         2 if selected else 1, border_radius=4)
        bob = int(math.sin(self._t * 3) * 2) if selected else 0
        item.draw_icon(surface, r.centerx, r.centery - 6 + bob)
        lbl = render_text(item.label, 8, CRT_WHITE if selected else CRT_DIM, pixel=False)
        surface.blit(lbl, lbl.get_rect(midbottom=(r.centerx, r.bottom - 3)))

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def _draw_back_btn(self, surface: pygame.Surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        pygame.draw.polygon(surface, CRT_WHITE, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        img = render_text("VOLTAR", 8, CRT_WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _draw_title(self, surface: pygame.Surface) -> None:
        title = render_text(self._active.label, 11, CRT_WHITE)
        surface.blit(title, title.get_rect(midtop=(W // 2, SAFE_INSET + 1)))

    def _arrow_rect(self, side: str) -> pygame.Rect:
        cy = 120
        if side == "l":
            return pygame.Rect(0, cy - 30, SAFE_INSET + 26, 60)
        return pygame.Rect(W - (SAFE_INSET + 26), cy - 30, SAFE_INSET + 26, 60)

    def _draw_arrows(self, surface: pygame.Surface) -> None:
        cy = 120
        bob = int(math.sin(self._t * 4) * 2)
        lx = SAFE_INSET + 2 - bob
        pygame.draw.polygon(surface, CRT_DIM, [(lx + 8, cy - 9), (lx + 8, cy + 9), (lx, cy)])
        rx = W - SAFE_INSET - 2 + bob
        pygame.draw.polygon(surface, CRT_DIM, [(rx - 8, cy - 9), (rx - 8, cy + 9), (rx, cy)])

    def _draw_dots(self, surface: pygame.Surface) -> None:
        total = len(self.categories)
        dot_w, gap = 7, 4
        total_w = total * dot_w + (total - 1) * gap
        sx = W // 2 - total_w // 2
        y = H - SAFE_INSET - 9
        for i in range(total):
            color = CRT_WHITE if i == self._page else CRT_DIM
            pygame.draw.rect(surface, color, (sx + i * (dot_w + gap), y, dot_w, 3))

    def _draw_idle(self, surface: pygame.Surface) -> None:
        timeout = float(config.get("idle_timeout_s") or 10)
        frac = min(self._idle / timeout, 1.0) if timeout > 0 else 0.0
        x = SAFE_INSET + 8
        max_w = W - 2 * x
        bar_w = int(max_w * (1.0 - frac))
        if bar_w > 0:
            pygame.draw.rect(surface, CRT_DIM, (x, H - SAFE_INSET - 3, bar_w, 2))
