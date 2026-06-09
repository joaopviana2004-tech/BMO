"""Tela GRAVADOR — captura offline-first (aulas/reuniões/insights).

Botão grande REC/STOP, timer, VU meter e a fila do "Sync & Destroy":
quantos áudios aguardam upload e o status do drive_sync. Funciona 100%
offline — os arquivos esperam no disco e sobem sozinhos quando a rede
voltar (aí o toast "Sincronização com o Drive concluída" aparece).

Estilo CRT P&B, igual às outras telas de utilidade.
"""
from __future__ import annotations

import math

import pygame

from ..core import theme_state
from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)
from ..services import audio


def _fmt_time(s: float) -> str:
    s = int(s)
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


class RecorderScreen:
    voice_announce = "Gravador pronto!"   # falado quando a IA abre a tela

    def __init__(self, *, on_back, recorder, get_sync=None) -> None:
        """get_sync() -> DriveSync ou None (guest/offline não sincroniza)."""
        self.on_back = on_back
        self.recorder = recorder
        self.get_sync = get_sync or (lambda: None)
        self._t = 0.0

    def enter(self) -> None: ...

    def exit(self) -> None:
        # sair da tela NÃO para a gravação — aula longa pode rolar com o
        # Bimo mostrando o relógio. O REC fica indicado no botão ao voltar.
        ...

    # ---------- layout ----------

    @property
    def _rec_rect(self) -> pygame.Rect:
        r = pygame.Rect(0, 0, 72, 72)
        r.center = (LOGICAL_SIZE[0] // 2, 112)
        return r

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        a = event.action
        if a == bmo_input.Action.A:
            self._toggle()
        elif a in (bmo_input.Action.B, bmo_input.Action.MENU):
            audio.play("back")
            self.on_back()
        elif a == bmo_input.Action.TAP and getattr(event, "pos", None):
            if self._back_btn().collidepoint(event.pos):
                audio.play("back")
                self.on_back()
            elif self._rec_rect.inflate(20, 20).collidepoint(event.pos):
                self._toggle()

    def _toggle(self) -> None:
        if not self.recorder.available:
            audio.play("back")
            return
        audio.play("select")
        self.recorder.toggle()

    def update(self, dt: float) -> None:
        self._t += dt

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4,
                                    right_pad=SAFE_INSET + 4)
        self._draw_back_btn(surface)
        title = render_text("GRAVADOR", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 6)))

        rec = self.recorder
        cx = LOGICAL_SIZE[0] // 2

        # ---- botão central REC/STOP ----
        r = self._rec_rect
        if rec.recording:
            # anel pulsante + quadrado STOP
            pulse = 2 + int((math.sin(self._t * 4) + 1) * 2)
            pygame.draw.circle(surface, CRT_WHITE, r.center, r.width // 2 + pulse, 2)
            stop = pygame.Rect(0, 0, 30, 30)
            stop.center = r.center
            pygame.draw.rect(surface, CRT_WHITE, stop)
        else:
            pygame.draw.circle(surface, CRT_WHITE, r.center, r.width // 2, 2)
            pygame.draw.circle(surface, CRT_WHITE, r.center, 16)

        # ---- timer + VU ----
        if rec.recording:
            timer = render_text(_fmt_time(rec.elapsed), 16, CRT_WHITE)
            surface.blit(timer, timer.get_rect(midtop=(cx, r.bottom + 10)))
            # VU meter: barrinha embaixo do timer
            vu_w = int(120 * min(1.0, rec.level))
            pygame.draw.rect(surface, CRT_DIM, (cx - 60, r.bottom + 32, 120, 4), 1)
            if vu_w > 2:
                pygame.draw.rect(surface, CRT_WHITE, (cx - 60, r.bottom + 32, vu_w, 4))
            lbl = render_text("GRAVANDO", 9, CRT_WHITE)
        elif not rec.available:
            lbl = render_text(rec.status.upper()[:30], 9, CRT_DIM)
        else:
            lbl = render_text("TOQUE PRA GRAVAR", 9, CRT_DIM)
        surface.blit(lbl, lbl.get_rect(midtop=(cx, 44)))

        # ---- fila do Sync & Destroy (rodapé) ----
        pending = len(rec.pending())
        sync = self.get_sync()
        if sync is None:
            sync_txt = "sem conta: audios ficam locais" if pending else ""
        elif pending:
            sync_txt = f"{pending} audio(s) esperando o Drive"
        elif getattr(sync, "audio_uploads", 0):
            sync_txt = "tudo sincronizado (e destruido) ;)"
        else:
            sync_txt = ""
        lines = []
        if rec.last_file and not rec.recording:
            lines.append((rec.status, CRT_WHITE))
        if sync_txt:
            lines.append((sync_txt, CRT_DIM))
        y = LOGICAL_SIZE[1] - SAFE_INSET - 6
        for text, color in reversed(lines):
            img = render_text(text, 8, color, pixel=False)
            surface.blit(img, img.get_rect(midbottom=(cx, y)))
            y -= 12

    def _draw_back_btn(self, surface: pygame.Surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        pygame.draw.polygon(surface, CRT_WHITE, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        img = render_text("MENU", 8, CRT_WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))
