"""Tela Kanban — tarefas do Todoist em 3 colunas (TO-DO / DOING / DONE).

Touch: toque e arraste um card pra movê-lo de coluna. HOME no canto sup
esquerdo sai pra menu; SYNC no canto sup direito força refresh.
Teclado: arrows navegam, A pega (modo MOVENDO), LEFT/RIGHT move, B sai.
"""
from __future__ import annotations

import math

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import CRT_BLACK, CRT_DIM, CRT_WHITE, SAFE_INSET
from ..services import audio
from ..services.todoist import SECTION_LABELS, SECTION_NAMES, TodoistService

# Layout (400x240) — fontes maiores, menos cards visíveis
COL_PAD = SAFE_INSET   # respeita zona morta do frame físico
COL_GAP = 4
COL_W = (LOGICAL_SIZE[0] - COL_PAD * 2 - COL_GAP * 2) // 3   # ~117

CARD_H = 28
HEADER_Y = SAFE_INSET             # buttons + title aqui
COL_HEADER_Y = HEADER_Y + 22      # ~36
CARDS_TOP_Y = COL_HEADER_Y + 22   # ~58
FOOTER_Y = LOGICAL_SIZE[1] - SAFE_INSET - 2   # ~224

FONT_CARD = 11
FONT_COL_HEADER = 11
FONT_HINT = 8
FONT_TITLE = 11

MAX_VISIBLE = 5    # 5 * 28 = 140 → cards de y=58 a y=198


def _col_x(idx: int) -> int:
    return COL_PAD + idx * (COL_W + COL_GAP)


def _fit(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)] + "."


def _to_logical(pos: tuple[int, int]) -> tuple[int, int]:
    w, h = pygame.display.get_window_size()
    if w <= 0 or h <= 0:
        return pos
    return (pos[0] * LOGICAL_SIZE[0] // w, pos[1] * LOGICAL_SIZE[1] // h)


class TasksScreen:
    show_mic_button = True   # mic virtual (overlay global do App), canto inf-dir
    voice_announce = "Seu quadro de tarefas."   # BMO anuncia ao abrir (cacheado)

    def __init__(self, *, on_back, todoist: TodoistService) -> None:
        self.on_back = on_back
        self.todoist = todoist
        self.cursor_col = 0
        self.cursor_idx = 0
        self.scroll = [0, 0, 0]
        self.mode = "cursor"   # "cursor" | "moving" (modo teclado)
        # Drag state (touch)
        self.dragging_task = None      # type: ignore[assignment]
        self.drag_origin_col: int | None = None
        self.drag_pos: tuple[int, int] | None = None
        # Flash do botão SYNC
        self._sync_flash_until = 0.0
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
        # Eventos raw pygame pra drag (precisa converter coords)
        if event.type == pygame.MOUSEMOTION:
            if self.dragging_task is not None and pygame.mouse.get_pressed()[0]:
                self.drag_pos = _to_logical(event.pos)
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging_task is not None:
                self._end_drag()
            return

        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        pos = getattr(event, "pos", None)

        # Botões globais (HOME, SYNC, scroll) — funcionam em qualquer modo
        if action == bmo_input.Action.TAP and pos is not None:
            if self._back_btn().collidepoint(pos):
                audio.play("back")
                self.on_back()
                return
            if self._sync_btn().collidepoint(pos):
                audio.play("tick")
                self.todoist.trigger_refresh()
                self._sync_flash_until = self._t + 0.4
                return
            if self._handle_scroll_tap(pos):
                return

        if self.mode == "cursor":
            self._handle_cursor(action, pos)
        else:
            self._handle_moving(action, pos)

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
                self._start_drag(hit, pos)

    def _handle_moving(self, action, pos) -> None:
        # Modo só usado pelo teclado (touch usa drag direto)
        if action == bmo_input.Action.LEFT:
            self._kb_move_card(-1)
        elif action == bmo_input.Action.RIGHT:
            self._kb_move_card(+1)
        elif action in (bmo_input.Action.A, bmo_input.Action.B):
            self.mode = "cursor"

    def _handle_scroll_tap(self, pos) -> bool:
        by = self.todoist.by_section()
        for col_i in range(3):
            n = len(by.get(SECTION_NAMES[col_i], []))
            if n == 0:
                continue
            if self.scroll[col_i] > 0 and self._scroll_up_btn(col_i).collidepoint(pos):
                self.scroll[col_i] -= 1
                return True
            if self.scroll[col_i] + MAX_VISIBLE < n and self._scroll_down_btn(col_i).collidepoint(pos):
                self.scroll[col_i] += 1
                return True
        return False

    def _enter_move(self) -> None:
        col_key = SECTION_NAMES[self.cursor_col]
        if not self.todoist.by_section().get(col_key):
            return
        self.mode = "moving"

    def _kb_move_card(self, direction: int) -> None:
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
        audio.play("click")
        new_cards = self.todoist.by_section().get(target_key, [])
        self.cursor_col = new_col
        try:
            self.cursor_idx = next(i for i, t in enumerate(new_cards) if t.id == task.id)
        except StopIteration:
            self.cursor_idx = max(0, len(new_cards) - 1)

    # ---------- drag (touch) ----------

    def _start_drag(self, hit, pos) -> None:
        col_i, idx = hit
        cards = self.todoist.by_section().get(SECTION_NAMES[col_i], [])
        if not cards or idx >= len(cards):
            return
        self.dragging_task = cards[idx]
        self.drag_origin_col = col_i
        self.drag_pos = pos
        self.cursor_col, self.cursor_idx = col_i, idx
        self.mode = "cursor"

    def _end_drag(self) -> None:
        task = self.dragging_task
        origin = self.drag_origin_col
        pos = self.drag_pos
        self.dragging_task = None
        self.drag_origin_col = None
        self.drag_pos = None
        if task is None or origin is None or pos is None:
            return

        target_col = self._col_at_x(pos[0])
        # Solta fora de qualquer coluna OU na mesma coluna = só foca
        if target_col is None or target_col == origin:
            return

        target_key = SECTION_NAMES[target_col]
        if not self.todoist.move(task.id, target_key):
            return
        audio.play("click")
        new_cards = self.todoist.by_section().get(target_key, [])
        self.cursor_col = target_col
        try:
            self.cursor_idx = next(i for i, t in enumerate(new_cards) if t.id == task.id)
        except StopIteration:
            self.cursor_idx = max(0, len(new_cards) - 1)

    def _col_at_x(self, x: int) -> int | None:
        for i in range(3):
            start = _col_x(i)
            if start <= x <= start + COL_W:
                return i
        return None

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

    # ---------- botões / hitboxes ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def _sync_btn(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] - SAFE_INSET - 52, SAFE_INSET, 52, 16)

    def _scroll_up_btn(self, col_i: int) -> pygame.Rect:
        x = _col_x(col_i)
        return pygame.Rect(x + COL_W - 20, CARDS_TOP_Y - 14, 20, 14)

    def _scroll_down_btn(self, col_i: int) -> pygame.Rect:
        x = _col_x(col_i)
        ybot = CARDS_TOP_Y + MAX_VISIBLE * CARD_H
        return pygame.Rect(x + COL_W - 20, ybot, 20, 14)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        self._draw_header(surface)
        self._draw_columns(surface)
        self._draw_footer(surface)
        # overlay do drag por cima de tudo
        if self.dragging_task is not None and self.drag_pos is not None:
            self._draw_drag_overlay(surface)

    def _draw_header(self, surface) -> None:
        self._draw_back_btn(surface)
        self._draw_sync_btn(surface)
        title = render_text("BMO BOARD", FONT_TITLE, CRT_WHITE)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, HEADER_Y + 1)))

    def _draw_back_btn(self, surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        pygame.draw.polygon(surface, CRT_WHITE, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        img = render_text("HOME", 8, CRT_WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _draw_sync_btn(self, surface) -> None:
        rect = self._sync_btn()
        flashing = self._t < self._sync_flash_until
        bg = CRT_WHITE if flashing else CRT_BLACK
        fg = CRT_BLACK if flashing else CRT_WHITE
        pygame.draw.rect(surface, bg, rect)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        # ícone de refresh (arco com setinha)
        ix, iy = rect.left + 9, rect.centery
        pygame.draw.arc(surface, fg, pygame.Rect(ix - 5, iy - 5, 10, 10),
                        -math.pi / 2, math.pi, 2)
        pygame.draw.polygon(surface, fg, [
            (ix, iy - 7), (ix + 4, iy - 4), (ix - 1, iy - 4),
        ])
        img = render_text("SYNC", 8, fg, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 18, rect.centery)))

    def _draw_columns(self, surface) -> None:
        by = self.todoist.by_section()
        snap = self.todoist.get()
        empty = not any(by.get(k) for k in SECTION_NAMES)
        if empty and not snap.ok:
            self._draw_empty_message(surface, snap.error)
            return

        # Coluna alvo do drag (highlight)
        drag_target = None
        if self.drag_pos is not None:
            drag_target = self._col_at_x(self.drag_pos[0])

        for col_i in range(3):
            key = SECTION_NAMES[col_i]
            cards = by.get(key, [])
            x = _col_x(col_i)
            is_cursor_col = (col_i == self.cursor_col)
            col_color = CRT_WHITE if is_cursor_col else CRT_DIM

            # destaque da coluna alvo do drag
            if drag_target == col_i and col_i != self.drag_origin_col:
                hi = pygame.Rect(x, COL_HEADER_Y - 2, COL_W, LOGICAL_SIZE[1] - COL_HEADER_Y - 24)
                pygame.draw.rect(surface, CRT_WHITE, hi, 1)

            # cabeçalho coluna + contagem
            hd = render_text(f"{SECTION_LABELS[key]}  {len(cards)}", FONT_COL_HEADER, col_color, pixel=False)
            surface.blit(hd, hd.get_rect(midleft=(x + 6, COL_HEADER_Y + 6)))
            pygame.draw.rect(surface, col_color, (x, COL_HEADER_Y + 16, COL_W, 1))

            scroll = self.scroll[col_i]
            visible = cards[scroll: scroll + MAX_VISIBLE]
            for vi, task in enumerate(visible):
                gi = scroll + vi
                y = CARDS_TOP_Y + vi * CARD_H
                rect = pygame.Rect(x, y, COL_W, CARD_H - 4)
                if self.dragging_task is not None and task.id == self.dragging_task.id:
                    # slot vazio enquanto arrasta
                    pygame.draw.rect(surface, CRT_BLACK, rect)
                    pygame.draw.rect(surface, CRT_DIM, rect, 1)
                else:
                    self._draw_card(
                        surface, rect, task.content,
                        is_cursor=(is_cursor_col and gi == self.cursor_idx),
                    )

            # botões de scroll (só se tiver pra scrollar)
            if scroll > 0:
                self._draw_scroll_btn(surface, self._scroll_up_btn(col_i), up=True)
            if scroll + MAX_VISIBLE < len(cards):
                self._draw_scroll_btn(surface, self._scroll_down_btn(col_i), up=False)

    def _draw_scroll_btn(self, surface, btn: pygame.Rect, *, up: bool) -> None:
        pygame.draw.rect(surface, CRT_BLACK, btn)
        pygame.draw.rect(surface, CRT_DIM, btn, 1)
        if up:
            pts = [(btn.centerx - 4, btn.bottom - 4),
                   (btn.centerx + 4, btn.bottom - 4),
                   (btn.centerx, btn.top + 3)]
        else:
            pts = [(btn.centerx - 4, btn.top + 4),
                   (btn.centerx + 4, btn.top + 4),
                   (btn.centerx, btn.bottom - 3)]
        pygame.draw.polygon(surface, CRT_DIM, pts)

    def _draw_empty_message(self, surface, error: str) -> None:
        cx = LOGICAL_SIZE[0] // 2
        cy = LOGICAL_SIZE[1] // 2
        if "TOKEN" in error.upper():
            msg = render_text("Configure TODOIST_TOKEN", 12, CRT_WHITE, pixel=False)
            hint = render_text("env var ou bmo_config.json", 10, CRT_DIM, pixel=False)
        elif "secao" in error or "projeto" in error:
            msg = render_text(error, 11, CRT_WHITE, pixel=False)
            hint = render_text("Crie projeto BMO com 3 secoes", 10, CRT_DIM, pixel=False)
        else:
            msg = render_text("Sem conexao", 12, CRT_WHITE, pixel=False)
            hint = render_text(error or "tente SYNC", 10, CRT_DIM, pixel=False)
        surface.blit(msg, msg.get_rect(center=(cx, cy - 8)))
        surface.blit(hint, hint.get_rect(center=(cx, cy + 14)))

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

        # texto truncado (consolas ~6px/char @ 11pt)
        max_chars = max(4, (rect.width - 12) // 6)
        img = render_text(_fit(content, max_chars), FONT_CARD, fg, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 7, rect.centery)))

    def _draw_drag_overlay(self, surface) -> None:
        if self.drag_pos is None or self.dragging_task is None:
            return
        cx, cy = self.drag_pos
        rect = pygame.Rect(0, 0, COL_W, CARD_H - 4)
        rect.center = (cx, cy)
        # sombra
        shadow = rect.move(2, 3)
        pygame.draw.rect(surface, CRT_DIM, shadow)
        # card com borda forte (segurado)
        pygame.draw.rect(surface, CRT_WHITE, rect)
        pygame.draw.rect(surface, CRT_BLACK, rect, 2)
        max_chars = max(4, (rect.width - 12) // 6)
        img = render_text(_fit(self.dragging_task.content, max_chars), FONT_CARD, CRT_BLACK, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 7, rect.centery)))

    def _draw_footer(self, surface) -> None:
        if self.dragging_task is not None:
            txt = "ARRASTANDO   solte na coluna alvo"
        elif self.mode == "moving":
            txt = "MOVENDO   < > p/ mover    A solta"
        else:
            txt = "toque e arraste um card    HOME / SYNC nos cantos"
        hint = render_text(txt, FONT_HINT, CRT_DIM, pixel=False)
        surface.blit(hint, hint.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 4)))
