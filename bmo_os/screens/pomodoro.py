"""Tela POMODORO — timer de foco estilo CRT P&B.

Ciclo clássico: FOCO 25min -> PAUSA 5min, e a cada 4 focos uma PAUSA LONGA
de 15min. Countdown MM:SS gigante (igual ao relógio), label da fase, e 4
"tomates" indicando o progresso até a pausa longa.

Integração leve (read-only) com o Todoist: se houver tarefa em DOING, mostra
"FOCANDO: <tarefa>" embaixo do timer. NÃO mexe no board — zero risco pra tela
de TASKS. Sem token/sem tarefa, a linha some.

Controles:
    A / toque no centro  -> play / pause
    MENU / botão RESET   -> zera a fase atual
    botão PULAR          -> vai pra próxima fase
    B                    -> volta pra home

Obs: o timer só corre enquanto a tela está visível (o ScreenManager só faz
update da tela do topo). Sair pra home pausa o relógio na prática.
"""
from __future__ import annotations

import math

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)
from ..services import audio

FOCUS_S = 25 * 60
SHORT_S = 5 * 60
LONG_S = 15 * 60
CYCLES_BEFORE_LONG = 4

PHASE_LABELS = {"focus": "FOCO", "short": "PAUSA", "long": "PAUSA LONGA"}
PHASE_DUR = {"focus": FOCUS_S, "short": SHORT_S, "long": LONG_S}


class PomodoroScreen:
    def __init__(self, *, on_back, todoist=None) -> None:
        self.on_back = on_back
        self.todoist = todoist
        self.phase = "focus"
        self.remaining = float(FOCUS_S)
        self.running = False
        self.completed = 0      # focos concluídos (pra "tomates" e pausa longa)
        self._t = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        if not self.running:
            return
        self.remaining -= dt
        if self.remaining <= 0:
            self._advance(auto=True)

    def _advance(self, *, auto: bool) -> None:
        if self.phase == "focus":
            self.completed += 1
            if self.completed % CYCLES_BEFORE_LONG == 0:
                self._set_phase("long")
            else:
                self._set_phase("short")
            if auto:
                audio.play("win")
                audio.play_bmo_voice()
        else:
            self._set_phase("focus")
            if auto:
                audio.play("select")
        # auto-continua rodando na transição automática; manual cai pausado
        self.running = auto

    def _set_phase(self, phase: str) -> None:
        self.phase = phase
        self.remaining = float(PHASE_DUR[phase])

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        pos = getattr(event, "pos", None)
        if action == bmo_input.Action.B:
            audio.play("back")
            self.on_back()
        elif action == bmo_input.Action.A:
            self._toggle()
        elif action == bmo_input.Action.MENU:
            self._reset()
        elif action == bmo_input.Action.TAP and pos is not None:
            self._handle_tap(pos)

    def _handle_tap(self, pos) -> None:
        if self._back_btn().collidepoint(pos):
            audio.play("back")
            self.on_back()
        elif self._reset_btn().collidepoint(pos):
            self._reset()
        elif self._skip_btn().collidepoint(pos):
            audio.play("tick")
            self._advance(auto=False)
        elif self._center_btn().collidepoint(pos):
            self._toggle()

    def _toggle(self) -> None:
        self.running = not self.running
        audio.play("select" if self.running else "back")

    def _reset(self) -> None:
        self.running = False
        self.remaining = float(PHASE_DUR[self.phase])
        audio.play("tick")

    # ---------- hitboxes ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def _center_btn(self) -> pygame.Rect:
        r = pygame.Rect(0, 0, 180, 80)
        r.center = (LOGICAL_SIZE[0] // 2, 120)
        return r

    def _reset_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET + 16, LOGICAL_SIZE[1] - SAFE_INSET - 22, 64, 18)

    def _skip_btn(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] - SAFE_INSET - 80, LOGICAL_SIZE[1] - SAFE_INSET - 22, 64, 18)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_back_btn(surface)

        cx = LOGICAL_SIZE[0] // 2
        # label da fase
        label = render_text(PHASE_LABELS[self.phase], 12, CRT_DIM)
        surface.blit(label, label.get_rect(midtop=(cx, SAFE_INSET + 6)))

        # countdown MM:SS gigante
        m, s = divmod(max(0, int(self.remaining)), 60)
        big = render_text(f"{m:02d}:{s:02d}", 56, CRT_WHITE)
        surface.blit(big, big.get_rect(center=(cx, 108)))

        # ícone play/pause discreto sob o timer
        self._draw_state_icon(surface, cx, 142)

        # tomates (progresso até a pausa longa)
        self._draw_tomatoes(surface, cx, 162)

        # linha de foco do Todoist (opcional)
        self._draw_focus_task(surface, cx, 180)

        self._draw_buttons(surface)

    def _draw_state_icon(self, surface, cx: int, cy: int) -> None:
        if self.running:
            # pulsa de leve quando rodando
            on = (self._t % 1.0) < 0.5
            color = CRT_WHITE if on else CRT_DIM
            pygame.draw.rect(surface, color, (cx - 5, cy - 5, 3, 10))
            pygame.draw.rect(surface, color, (cx + 2, cy - 5, 3, 10))
        else:
            pygame.draw.polygon(surface, CRT_DIM, [
                (cx - 4, cy - 5), (cx - 4, cy + 5), (cx + 6, cy),
            ])

    def _draw_tomatoes(self, surface, cx: int, cy: int) -> None:
        done = self.completed % CYCLES_BEFORE_LONG
        # se acabou de fechar um ciclo completo, mostra os 4 cheios
        if self.completed > 0 and done == 0 and self.phase == "long":
            done = CYCLES_BEFORE_LONG
        gap = 14
        total_w = (CYCLES_BEFORE_LONG - 1) * gap
        sx = cx - total_w // 2
        for i in range(CYCLES_BEFORE_LONG):
            x = sx + i * gap
            if i < done:
                pygame.draw.circle(surface, CRT_WHITE, (x, cy), 4)
            else:
                pygame.draw.circle(surface, CRT_DIM, (x, cy), 4, 1)

    def _draw_focus_task(self, surface, cx: int, cy: int) -> None:
        task = self._doing_task()
        if not task:
            return
        prefix = render_text("FOCANDO: ", 8, CRT_DIM, pixel=False)
        name = render_text(self._fit(task, 30), 8, CRT_WHITE, pixel=False)
        total = prefix.get_width() + name.get_width()
        x = cx - total // 2
        surface.blit(prefix, (x, cy))
        surface.blit(name, (x + prefix.get_width(), cy))

    def _doing_task(self) -> str:
        if self.todoist is None:
            return ""
        try:
            doing = self.todoist.by_section().get("doing", [])
        except Exception:
            return ""
        return doing[0].content if doing else ""

    def _draw_buttons(self, surface) -> None:
        self._draw_text_btn(surface, self._reset_btn(), "RESET")
        self._draw_text_btn(surface, self._skip_btn(), "PULAR")

    def _draw_text_btn(self, surface, rect: pygame.Rect, text: str) -> None:
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, CRT_DIM, rect, 1)
        img = render_text(text, 8, CRT_WHITE, pixel=False)
        surface.blit(img, img.get_rect(center=rect.center))

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

    @staticmethod
    def _fit(text: str, max_chars: int) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return text[: max(1, max_chars - 1)] + "."
