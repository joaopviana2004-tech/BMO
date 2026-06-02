"""Botão de microfone virtual — overlay global desenhado por cima de algumas
telas (descanso, foco, kanban, agenda).

Vive no App (não numa tela): o App desenha e trata o toque, gated pelo atributo
`show_mic_button = True` na tela atual. A posição padrão é o canto inferior-
direito; uma tela pode sobrescrever com `mic_btn_rect = (x, y, w, h)` quando
esse canto estiver ocupado (ex.: relógio tem a data ali).

SEGURAR pra gravar: começa ao apertar (`press`) e transcreve ao soltar
(`release`) — igual ao push-to-talk físico (GPIO). O App trata o soltar do
toque. O resultado vai pro LLM via `on_text`; o rodapé de voz (overlay no main)
mostra GRAVANDO / PENSANDO / resposta.
"""
from __future__ import annotations

import pygame

from ..core.theme import Colors, LOGICAL_SIZE
from ..core.widgets import CRT_BLACK, CRT_DIM, CRT_WHITE, SAFE_INSET
from ..services import audio

# Botão grandinho de propósito — zona de toque generosa pro dedo.
MIC_W, MIC_H = 28, 26


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

    # ---- segurar pra gravar (o App chama press/release no toque) ----

    def press(self) -> None:
        """Apertou: começa a gravar (até soltar)."""
        v = self.voice
        if not getattr(v, "available", False) or getattr(v, "busy", False):
            audio.play("back")
            return
        audio.play("select")
        # ptt_begin suspende monitor/wake sozinho (acesso exclusivo ao mic)
        v.ptt_begin(on_done=self.on_text)

    def release(self) -> None:
        """Soltou: encerra a gravação — o worker transcreve e manda pro LLM."""
        try:
            self.voice.ptt_end()
        except Exception:
            pass

    def draw(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        busy = getattr(self.voice, "busy", False)
        avail = getattr(self.voice, "available", False)
        col = Colors.RED if busy else (CRT_WHITE if avail else CRT_DIM)
        # fundo + borda
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, col, rect, 1)
        cx, cy = rect.centerx, rect.centery
        # corpo do mic (cápsula) + haste + base
        body = pygame.Rect(0, 0, 7, 11)
        body.center = (cx, cy - 2)
        pygame.draw.rect(surface, col, body, border_radius=3)
        pygame.draw.line(surface, col, (cx, body.bottom), (cx, body.bottom + 3), 1)
        pygame.draw.line(surface, col, (cx - 4, body.bottom + 3), (cx + 4, body.bottom + 3), 1)
        # pontinho vermelho piscando enquanto grava
        if busy:
            pygame.draw.circle(surface, Colors.RED, (rect.right - 4, rect.top + 4), 2)
