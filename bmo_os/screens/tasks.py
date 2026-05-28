"""Tela Kanban — tarefas do Todoist em 3 colunas (TO-DO / DOING / DONE).

Estilo P&B mais funcional (não pixel) pra caber mais texto. Navegação via
arrows + A pra pegar a tarefa. No modo MOVING, LEFT/RIGHT troca de coluna
direto (chama Sync API otimisticamente). B sai do modo / volta pra home.
"""
from __future__ import annotations

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import CRT_BLACK, CRT_DIM, CRT_WHITE
from ..services.todoist import SECTION_LABELS, SECTION_NAMES, TodoistService

# Layout (400x240)
COL_PAD = 4
COL_GAP = 4
COL_W = (LOGICAL_SIZE[0] - COL_PAD * 2 - COL_GAP * 2) // 3   # ~128

CARD_H = 24
CARDS_TOP_Y = 46
CARDS_BOTTOM_Y = LOGICAL_SIZE[1] - 30
MAX_VISIBLE = (CARDS_BOTTOM_Y - CARDS_TOP_Y) // CARD_H

HEADER_Y = 4
COL_HEADER_Y = 26
FOOTER_Y = LOGICAL_SIZE[1] - 22


def _col_x(idx: int) -> int:
    return COL_PAD + idx * (COL_W + COL_GAP)


def _fit(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)] + "."


class TasksScreen:
    def __init__(self, *, on_back, todoist: TodoistService) -> None:
        self.on_back = on_back
        self.todoist = todoist
        self.cursor_col = 0
        self.cursor_idx = 0
        self.scroll = [0, 0, 0]
        self.mode = "cursor"   # "cursor" | "moving"
        self._t = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        by = self.todoist.by_section()
        col_key = SECTION_NAMES[self.cursor_col]
        n = len(by.get(col_key, []))
        self.cursor_idx = 0 if n == 0 else min(self.cursor_idx, n - 1)
        self._ensure_visible(n)

    def _ensure_visible(self, n: int) -> None:
        col = self.cursor_col
        if n == 0:
            self.scroll[col] = 0
            return
        if self.cursor_idx < self.scroll[col]:
            self.scroll[col] = self.cursor_idx
        elif self.cursor_idx >= self.scroll[col] + MAX_VISIBLE:
            self.scroll[col] = self.cursor_idx - MAX_VISIBLE + 1

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        if self.mode == "cursor":
            self._handle_cursor(action, getattr(event, "pos", None))
        else:
            self._handle_moving(action, getattr(event, "pos", None))

    def _handle_cursor(self, action, pos) -> None:
        if action == bmo_input.Action.UP:
            self.cursor_idx = max(0, self.cursor_idx - 1)
        elif action == bmo_input.Action.DOWN:
            n = len(self.todoist.by_section().get(SECTION_NAMES[self.cursor_col], []))
            self.cursor_idx = min(max(0, n - 1), self.cursor_idx + 1)
        elif action == bmo_input.Action.LEFT:
            self.cursor_col = max(0, self.cursor_col - 1)
            self.cursor_idx = 0
        elif action == bmo_input.Action.RIGHT:
            self.cursor_col = min(2, self.cursor_col + 1)
            self.cursor_idx = 0
        elif action == bmo_input.Action.A:
            self._enter_move()
        elif action == bmo_input.Action.B:
            self.on_back()
        elif action == bmo_input.Action.TAP and pos is not None:
            hit = self._card_at(pos)
            if hit is not None:
                self.cursor_col, self.cursor_idx = hit
                self._enter_move()

    def _handle_moving(self, action, pos) -> None:
        if action == bmo_input.Action.LEFT:
            self._move_card(-1)
        elif action == bmo_input.Action.RIGHT:
            self._move_card(+1)
        elif action in (bmo_input.Action.A, bmo_input.Action.B):
            self.mode = "cursor"
        elif action == bmo_input.Action.TAP and pos is not None:
            if self._left_btn().collidepoint(pos):
                self._move_card(-1)
                return
            if self._right_btn().collidepoint(pos):
                self._move_card(+1)
                return
            self.mode = "cursor"

    def _enter_move(self) -> None:
        col_key = SECTION_NAMES[self.cursor_col]
        if not self.todoist.by_section().get(col_key):
            return
        self.mode = "moving"

    def _move_card(self, direction: int) -> None:
        col_key = SECTION_NAMES[self.cursor_col]
        cards = self.todoist.by_section().get(col_key, [])
        if not cards:
            self.mode = "cursor"
            return
        new_col = self.cursor_col + direction
        if not (0 <= new_col <= 2):
            return
        target_key = SECTION_NAMES[new_col]
        task = cards[self.cursor_idx]
        if not self.todoist.move(task.id, target_key):
            return
        # acompanha o card pra nova coluna
        new_cards = self.todoist.by_section().get(target_key, [])
        self.cursor_col = new_col
        try:
            self.cursor_idx = next(i for i, t in enumerate(new_cards) if t.id == task.id)
        except StopIteration:
            self.cursor_idx = max(0, len(new_cards) - 1)

    def _card_at(self, pos):
        by = self.todoist.by_section()
        for col_i in range(3):
            cards = by.get(SECTION_NAMES[col_i], [])
            scroll = self.scroll[col_i]
            visible = cards[scroll: scroll + MAX_VISIBLE]
            x = _col_x(col_i)
            for vi, _ in enumerate(visible):
                y = CARDS_TOP_Y + vi * CARD_H
                rect = pygame.Rect(x, y, COL_W, CARD_H - 2)
                if rect.collidepoint(pos):
                    return (col_i, scroll + vi)
        return None

    # ---------- draw ----------

    def _left_btn(self):
        return pygame.Rect(8, FOOTER_Y - 2, 50, 18)

    def _right_btn(self):
        return pygame.Rect(LOGICAL_SIZE[0] - 58, FOOTER_Y - 2, 50, 18)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        self._draw_header(surface)
        self._draw_columns(surface)
        self._draw_footer(surface)

    def _draw_header(self, surface) -> None:
        title = render_text("BMO BOARD", 11, CRT_WHITE)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, HEADER_Y)))
        snap = self.todoist.get()
        if not snap.ok and snap.error:
            err = render_text(snap.error[:34], 8, CRT_DIM, pixel=False)
            surface.blit(err, err.get_rect(topright=(LOGICAL_SIZE[0] - 6, HEADER_Y + 4)))

    def _draw_columns(self, surface) -> None:
        by = self.todoist.by_section()
        snap = self.todoist.get()

        empty = not any(by.get(k) for k in SECTION_NAMES)
        if empty and not snap.ok:
            self._draw_empty_message(surface, snap.error)
            return

        for col_i in range(3):
            key = SECTION_NAMES[col_i]
            cards = by.get(key, [])
            x = _col_x(col_i)
            is_cursor_col = (col_i == self.cursor_col)
            col_color = CRT_WHITE if is_cursor_col else CRT_DIM

            # cabeçalho coluna + contagem
            hd = render_text(f"{SECTION_LABELS[key]}  {len(cards)}", 9, col_color, pixel=False)
            surface.blit(hd, hd.get_rect(midleft=(x + 4, COL_HEADER_Y + 4)))
            pygame.draw.rect(surface, col_color, (x, COL_HEADER_Y + 14, COL_W, 1))

            scroll = self.scroll[col_i]
            visible = cards[scroll: scroll + MAX_VISIBLE]
            for vi, task in enumerate(visible):
                gi = scroll + vi
                y = CARDS_TOP_Y + vi * CARD_H
                rect = pygame.Rect(x, y, COL_W, CARD_H - 2)
                self._draw_card(
                    surface, rect, task.content,
                    is_cursor=(is_cursor_col and gi == self.cursor_idx),
                )

            # indicadores de scroll (▲ no topo, ▼ embaixo)
            if scroll > 0:
                pts = [(x + COL_W - 10, CARDS_TOP_Y - 2),
                       (x + COL_W - 2, CARDS_TOP_Y - 2),
                       (x + COL_W - 6, CARDS_TOP_Y - 8)]
                pygame.draw.polygon(surface, CRT_DIM, pts)
            if scroll + MAX_VISIBLE < len(cards):
                ybot = CARDS_TOP_Y + MAX_VISIBLE * CARD_H
                pts = [(x + COL_W - 10, ybot),
                       (x + COL_W - 2, ybot),
                       (x + COL_W - 6, ybot + 6)]
                pygame.draw.polygon(surface, CRT_DIM, pts)

    def _draw_empty_message(self, surface, error: str) -> None:
        cx = LOGICAL_SIZE[0] // 2
        cy = LOGICAL_SIZE[1] // 2
        if "TOKEN" in error.upper():
            msg = render_text("Configure TODOIST_TOKEN", 11, CRT_WHITE, pixel=False)
            hint = render_text("env var ou bmo_config.json", 9, CRT_DIM, pixel=False)
        elif "secao" in error or "projeto" in error:
            msg = render_text(error, 10, CRT_WHITE, pixel=False)
            hint = render_text("Crie projeto BMO com 3 secoes", 9, CRT_DIM, pixel=False)
        else:
            msg = render_text("Sem conexao", 11, CRT_WHITE, pixel=False)
            hint = render_text(error or "tente de novo em instantes", 9, CRT_DIM, pixel=False)
        surface.blit(msg, msg.get_rect(center=(cx, cy - 6)))
        surface.blit(hint, hint.get_rect(center=(cx, cy + 12)))

    def _draw_card(self, surface, rect: pygame.Rect, content: str, *, is_cursor: bool) -> None:
        moving = is_cursor and self.mode == "moving"
        if moving:
            pygame.draw.rect(surface, CRT_WHITE, rect)
            fg = CRT_BLACK
            border = None
        elif is_cursor:
            pygame.draw.rect(surface, CRT_BLACK, rect)
            border = CRT_WHITE
            fg = CRT_WHITE
        else:
            pygame.draw.rect(surface, CRT_BLACK, rect)
            border = CRT_DIM
            fg = CRT_WHITE
        if border is not None:
            pygame.draw.rect(surface, border, rect, 1)

        # texto truncado (consolas ~5px/char @ 9pt)
        max_chars = max(4, (rect.width - 10) // 5)
        img = render_text(_fit(content, max_chars), 9, fg, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 6, rect.centery)))

        # setinhas embutidas no card quando movendo
        if moving:
            if self.cursor_col > 0:
                pygame.draw.polygon(surface, CRT_BLACK, [
                    (rect.left + 4, rect.centery - 4),
                    (rect.left + 4, rect.centery + 4),
                    (rect.left, rect.centery),
                ])
            if self.cursor_col < 2:
                pygame.draw.polygon(surface, CRT_BLACK, [
                    (rect.right - 4, rect.centery - 4),
                    (rect.right - 4, rect.centery + 4),
                    (rect.right, rect.centery),
                ])

    def _draw_footer(self, surface) -> None:
        if self.mode == "moving":
            for r_, txt, ok in (
                (self._left_btn(),  "<", self.cursor_col > 0),
                (self._right_btn(), ">", self.cursor_col < 2),
            ):
                color = CRT_WHITE if ok else CRT_DIM
                pygame.draw.rect(surface, CRT_BLACK, r_)
                pygame.draw.rect(surface, color, r_, 2)
                img = render_text(txt, 14, color)
                surface.blit(img, img.get_rect(center=r_.center))
            hint = render_text("MOVENDO   A: soltar", 8, CRT_DIM, pixel=False)
            surface.blit(hint, hint.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - 4)))
        else:
            hint = render_text("A pegar   <-> trocar coluna   B voltar", 8, CRT_DIM, pixel=False)
            surface.blit(hint, hint.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - 4)))
