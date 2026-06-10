"""Tela home — hub de categorias + carrossel em cada subtela.

Nível 1: IA · REPOUSO · ESTUDOS · AJUSTES
Nível 2: apps da categoria (carrossel horizontal, mesmo estilo CRT).
B no hub → volta pro ambient; B na subtela → volta pro hub.
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
    SAFE_INSET, draw_crt_corners, draw_scanlines,
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
) -> list[HubCategory]:
    """Monta as 4 categorias do hub a partir dos callbacks do main."""
    return [
        HubCategory("IA", _icon_cat_ia, [
            HubItem("CEREBRO", _icon_brain, on_brain),
            HubItem("TESTE IA", _icon_aitest, on_aitest),
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
        ]),
    ]


class HomeScreen:
    def __init__(self, *, on_back, categories: list[HubCategory]) -> None:
        self.on_back = on_back
        self.categories = categories
        self._view = "hub"          # hub | category
        self._cat_index = 0
        self._item_index = 0
        self._idle = 0.0
        self._timed_out = False
        self._t = 0.0

    def enter(self) -> None:
        self._idle = 0.0
        self._timed_out = False
        self._view = "hub"

    def exit(self) -> None: ...

    @property
    def _active_items(self) -> list[HubItem]:
        return self.categories[self._cat_index].items

    def _step(self, delta: int) -> None:
        if self._view == "hub":
            self._cat_index = (self._cat_index + delta) % len(self.categories)
        else:
            self._item_index = (self._item_index + delta) % len(self._active_items)

    def _select(self) -> None:
        if self._view == "hub":
            self._view = "category"
            self._item_index = 0
            return
        self._active_items[self._item_index].action()

    def _go_back(self) -> None:
        if self._view == "category":
            self._view = "hub"
            return
        self.on_back()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        self._idle = 0.0
        action = event.action
        if action == bmo_input.Action.LEFT:
            self._step(-1)
            audio.play("tick")
        elif action == bmo_input.Action.RIGHT:
            self._step(1)
            audio.play("tick")
        elif action == bmo_input.Action.A:
            audio.play("select")
            self._select()
        elif action == bmo_input.Action.B:
            audio.play("back")
            self._go_back()
        elif action == bmo_input.Action.TAP and event.pos is not None:
            self._handle_tap(event.pos)

    def _handle_tap(self, pos: tuple[int, int]) -> None:
        cx, cy = LOGICAL_SIZE[0] // 2, 110
        if pygame.Rect(0, cy - 36, 80, 72).collidepoint(pos):
            self._step(-1)
            audio.play("tick")
            return
        if pygame.Rect(LOGICAL_SIZE[0] - 80, cy - 36, 80, 72).collidepoint(pos):
            self._step(1)
            audio.play("tick")
            return
        if pygame.Rect(0, 0, 80, 80).move(cx - 40, cy - 40).collidepoint(pos):
            audio.play("select")
            self._select()

    def update(self, dt: float) -> None:
        self._t += dt
        self._idle += dt
        timeout = float(config.get("idle_timeout_s") or 10)
        if self._idle >= timeout and not self._timed_out:
            self._timed_out = True
            self.on_back()

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        if self._view == "hub":
            self._draw_hub(surface)
        else:
            self._draw_category(surface)
        self._draw_hint(surface)

    def _draw_hub(self, surface: pygame.Surface) -> None:
        title = render_text("MENU", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 2)))
        cat = self.categories[self._cat_index]
        self._draw_carousel(
            surface,
            draw_icon=cat.draw_icon,
            label=cat.label,
            subtitle="escolha uma area",
            index=self._cat_index,
            total=len(self.categories),
        )

    def _draw_category(self, surface: pygame.Surface) -> None:
        cat = self.categories[self._cat_index]
        item = self._active_items[self._item_index]
        crumb = render_text(cat.label, 9, CRT_DIM)
        surface.blit(crumb, crumb.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 2)))
        self._draw_carousel(
            surface,
            draw_icon=item.draw_icon,
            label=item.label,
            subtitle="",
            index=self._item_index,
            total=len(self._active_items),
        )

    def _draw_carousel(
        self,
        surface: pygame.Surface,
        *,
        draw_icon: Callable,
        label: str,
        subtitle: str,
        index: int,
        total: int,
    ) -> None:
        cx = LOGICAL_SIZE[0] // 2
        cy = 110
        bob = int(math.sin(self._t * 3) * 2)
        bob_arr = int(math.sin(self._t * 4) * 2)

        lx = 28 - bob_arr
        pts_l = [(lx + 10, cy - 10), (lx + 10, cy + 10), (lx, cy)]
        pygame.draw.polygon(surface, CRT_WHITE, pts_l)

        rx = LOGICAL_SIZE[0] - 28 + bob_arr
        pts_r = [(rx - 10, cy - 10), (rx - 10, cy + 10), (rx, cy)]
        pygame.draw.polygon(surface, CRT_WHITE, pts_r)

        draw_icon(surface, cx, cy + bob)

        lbl = render_text(label, 12, CRT_WHITE)
        surface.blit(lbl, lbl.get_rect(midtop=(cx, cy + 38)))

        if subtitle:
            sub = render_text(subtitle, 8, CRT_DIM, pixel=False)
            surface.blit(sub, sub.get_rect(midtop=(cx, cy + 52)))

        dot_w = 6
        dots_y = cy + 58 if subtitle else cy + 54
        total_w = total * dot_w + (total - 1) * 4
        sx = cx - total_w // 2
        for i in range(total):
            color = CRT_WHITE if i == index else CRT_DIM
            pygame.draw.rect(surface, color, (sx + i * (dot_w + 4), dots_y, dot_w, 2))

    def _draw_hint(self, surface: pygame.Surface) -> None:
        if self._view == "category":
            hint = "B = voltar"
        else:
            hint = "A = abrir"
        img = render_text(hint, 7, CRT_DIM, pixel=False)
        surface.blit(img, img.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 8)))

        timeout = float(config.get("idle_timeout_s") or 10)
        idle_frac = min(self._idle / timeout, 1.0) if timeout > 0 else 0.0
        x = SAFE_INSET + 8
        max_w = LOGICAL_SIZE[0] - 2 * x
        bar_w = int(max_w * (1.0 - idle_frac))
        if bar_w > 0:
            pygame.draw.rect(surface, CRT_DIM, (x, LOGICAL_SIZE[1] - SAFE_INSET - 4, bar_w, 2))
