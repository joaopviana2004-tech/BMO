"""Tela de confirmação genérica (sim/não) — estilo CRT P&B.

Usada por ações irreversíveis/disruptivas acionadas com um toque só no grid de
AJUSTES (DESLIGAR, ATUALIZAR). Dois botões: CONFIRMAR / CANCELAR. Começa com o
foco em CANCELAR (escolha segura). B/VOLTAR cancela.
"""
from __future__ import annotations

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)
from ..services import audio


class ConfirmScreen:
    def __init__(self, *, title, message, on_confirm, on_cancel,
                 confirm_label="CONFIRMAR", cancel_label="CANCELAR") -> None:
        self.title = title
        self.message = message
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self.labels = [confirm_label, cancel_label]
        self._sel = 1            # foco inicial em CANCELAR (seguro)
        self._fired = False      # trava re-entrada (a ação pode não retornar)

    def enter(self) -> None: ...
    def exit(self) -> None: ...
    def update(self, dt: float) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT or self._fired:
            return
        A = bmo_input.Action
        a = event.action
        if a in (A.LEFT, A.RIGHT):
            self._sel ^= 1; audio.play("tick")
        elif a == A.A:
            self._fire(self._sel)
        elif a == A.B:
            audio.play("back"); self.on_cancel()
        elif a == A.TAP and getattr(event, "pos", None):
            for i in (0, 1):
                if self._btn_rect(i).collidepoint(event.pos):
                    self._sel = i
                    self._fire(i)
                    return

    def _fire(self, i: int) -> None:
        self._fired = True
        if i == 0:
            audio.play("select"); self.on_confirm()
        else:
            audio.play("back"); self.on_cancel()

    def _btn_rect(self, i: int) -> pygame.Rect:
        bw, bh, gap = 118, 26, 18
        total = 2 * bw + gap
        x0 = LOGICAL_SIZE[0] // 2 - total // 2
        return pygame.Rect(x0 + i * (bw + gap), 150, bw, bh)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        title = render_text(self.title, 13, CRT_WHITE)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 18)))
        msg = render_text(self.message, 9, CRT_DIM, pixel=False)
        surface.blit(msg, msg.get_rect(center=(LOGICAL_SIZE[0] // 2, 96)))
        for i, lab in enumerate(self.labels):
            rect = self._btn_rect(i)
            selected = (i == self._sel)
            if selected:
                pygame.draw.rect(surface, CRT_WHITE, rect)
                fg = CRT_BLACK
            else:
                pygame.draw.rect(surface, CRT_DIM, rect, 2)
                fg = CRT_DIM
            img = render_text(lab, 10, fg, pixel=False)
            surface.blit(img, img.get_rect(center=rect.center))
