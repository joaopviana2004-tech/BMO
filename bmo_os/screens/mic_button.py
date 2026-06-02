"""Botão de microfone virtual — overlay global desenhado por cima de algumas
telas (descanso, foco, kanban, agenda).

Vive no App (não numa tela): o App desenha e trata o toque, gated pelo atributo
`show_mic_button = True` na tela atual. A posição padrão é o canto inferior-
direito; uma tela pode sobrescrever com `mic_btn_rect = (x, y, w, h)` quando
esse canto estiver ocupado (ex.: relógio tem a data ali).

Toque = grava a fala (até o silêncio) e manda pro LLM via `on_text` — o mesmo
caminho do push-to-talk físico. O rodapé de voz (overlay no main) mostra
GRAVANDO / PENSANDO / resposta.
"""
from __future__ import annotations

import pygame

from ..core.theme import Colors, LOGICAL_SIZE
from ..core.widgets import CRT_BLACK, CRT_DIM, CRT_WHITE, SAFE_INSET
from ..services import audio

MIC_W, MIC_H = 18, 16


def default_rect() -> pygame.Rect:
    w, h = LOGICAL_SIZE
    return pygame.Rect(w - SAFE_INSET - MIC_W, h - SAFE_INSET - MIC_H, MIC_W, MIC_H)


class MicButton:
    def __init__(self, *, voice, on_text) -> None:
        self.voice = voice          # VoiceService
        self.on_text = on_text      # callback(text) — manda pro LLM e navega

    @staticmethod
    def rect_for(screen) -> pygame.Rect:
        """Rect do botão pra tela: override em `mic_btn_rect` ou o padrão."""
        r = getattr(screen, "mic_btn_rect", None)
        return pygame.Rect(r) if r else default_rect()

    def trigger(self) -> None:
        v = self.voice
        if not getattr(v, "available", False) or getattr(v, "busy", False):
            audio.play("back")
            return
        audio.play("select")
        # o voice suspende monitor/wake sozinho (acesso exclusivo ao mic)
        v.record_and_transcribe(on_done=self.on_text)

    def draw(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        busy = getattr(self.voice, "busy", False)
        avail = getattr(self.voice, "available", False)
        col = Colors.RED if busy else (CRT_WHITE if avail else CRT_DIM)
        # fundo + borda
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, col, rect, 1)
        cx, cy = rect.centerx, rect.centery
        # corpo do mic (cápsula) + haste + base
        body = pygame.Rect(0, 0, 5, 8)
        body.center = (cx, cy - 1)
        pygame.draw.rect(surface, col, body, border_radius=2)
        pygame.draw.line(surface, col, (cx, body.bottom), (cx, body.bottom + 2), 1)
        pygame.draw.line(surface, col, (cx - 3, body.bottom + 2), (cx + 3, body.bottom + 2), 1)
        # pontinho vermelho piscando enquanto grava
        if busy:
            pygame.draw.circle(surface, Colors.RED, (rect.right - 3, rect.top + 3), 2)
