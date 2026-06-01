"""Tela POMODORO — timer de foco estilo CRT P&B (minimalista).

Ciclo clássico: FOCO 25min -> PAUSA 5min, e a cada 4 focos uma PAUSA LONGA
de 15min. Countdown MM:SS gigante, label da fase e 4 "tomates" de progresso.
Na troca automática de fase toca um "alarm" discreto (bip-bip-bip).

Integração com o Todoist (tarefas em DOING):
- mostra a tarefa atual e deixa escolher entre as de DOING com ‹ › (ou
  LEFT/RIGHT) — direto daqui, sem abrir o board;
- o botão FINALIZAR move a tarefa pra DONE (todoist.move) e já seleciona a
  próxima de DOING. Não mexe no tasks.py.

Sem token/sem tarefas em DOING, o seletor e o FINALIZAR somem (só o timer).

Controles:
    A / toque no centro  -> play / pause
    ‹ › / LEFT / RIGHT   -> troca a tarefa em foco
    FINALIZAR            -> conclui a tarefa atual e vai pra próxima
    RESET / MENU         -> zera a fase atual
    B                    -> volta pra home

Obs: o timer só corre enquanto a tela está visível (o ScreenManager só faz
update da tela do topo).
"""
from __future__ import annotations

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

CX = LOGICAL_SIZE[0] // 2


class PomodoroScreen:
    def __init__(self, *, on_back, todoist=None) -> None:
        self.on_back = on_back
        self.todoist = todoist
        self.phase = "focus"
        self.remaining = float(FOCUS_S)
        self.running = False
        self.completed = 0          # focos concluídos (pra "tomates" e pausa longa)
        self._focus_id = None       # id da tarefa DOING em foco
        self._work_time: dict = {}  # tempo de FOCO acumulado por task_id (segundos)
        self._t = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        self._sync_focus()
        if not self.running:
            return
        # acumula tempo de trabalho da tarefa atual (só em FOCO)
        if self.phase == "focus" and self._focus_id is not None:
            self._work_time[self._focus_id] = self._work_time.get(self._focus_id, 0.0) + dt
        self.remaining -= dt
        if self.remaining <= 0:
            self._advance()

    def _advance(self) -> None:
        """Troca de fase automática quando o tempo acaba (toca alarme)."""
        if self.phase == "focus":
            self.completed += 1
            self.phase = "long" if self.completed % CYCLES_BEFORE_LONG == 0 else "short"
        else:
            self.phase = "focus"
        self.remaining = float(PHASE_DUR[self.phase])
        self.running = True
        audio.play("alarm")

    # ---------- tarefas (Todoist, DOING) ----------

    def _doing_tasks(self) -> list:
        if self.todoist is None:
            return []
        try:
            return self.todoist.by_section().get("doing", [])
        except Exception:
            return []

    def _sync_focus(self) -> None:
        ids = [t.id for t in self._doing_tasks()]
        if self._focus_id not in ids:
            self._focus_id = ids[0] if ids else None

    def _current_task(self):
        for t in self._doing_tasks():
            if t.id == self._focus_id:
                return t
        return None

    def _cycle_task(self, direction: int) -> None:
        ids = [t.id for t in self._doing_tasks()]
        if len(ids) < 2:
            return
        i = ids.index(self._focus_id) if self._focus_id in ids else 0
        self._focus_id = ids[(i + direction) % len(ids)]
        audio.play("tick")

    def _finish_task(self) -> None:
        tasks = self._doing_tasks()
        ids = [t.id for t in tasks]
        if self._focus_id is None or self._focus_id not in ids:
            return
        i = ids.index(self._focus_id)
        if not self.todoist or not self.todoist.move(self._focus_id, "done"):
            return
        audio.play("click")
        # zera o tempo de trabalho da tarefa concluída (timer reinicia)
        self._work_time.pop(self._focus_id, None)
        # já aponta pra próxima de DOING (vizinha na ordem atual)
        if i + 1 < len(ids):
            self._focus_id = ids[i + 1]
        elif i - 1 >= 0:
            self._focus_id = ids[i - 1]
        else:
            self._focus_id = None

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
        elif action == bmo_input.Action.LEFT:
            self._cycle_task(-1)
        elif action == bmo_input.Action.RIGHT:
            self._cycle_task(+1)
        elif action == bmo_input.Action.MENU:
            self._reset()
        elif action == bmo_input.Action.TAP and pos is not None:
            self._handle_tap(pos)

    def _handle_tap(self, pos) -> None:
        if self._back_btn().collidepoint(pos):
            audio.play("back")
            self.on_back()
            return
        if self._reset_btn().collidepoint(pos):
            self._reset()
            return
        if self._current_task() is not None and self._finish_btn().collidepoint(pos):
            self._finish_task()
            return
        if len(self._doing_tasks()) > 1:
            if self._task_prev_btn().collidepoint(pos):
                self._cycle_task(-1)
                return
            if self._task_next_btn().collidepoint(pos):
                self._cycle_task(+1)
                return
        if self._center_btn().collidepoint(pos):
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
        r = pygame.Rect(0, 0, 200, 70)
        r.center = (CX, 100)
        return r

    def _task_prev_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET + 14, 168, 18, 16)

    def _task_next_btn(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] - SAFE_INSET - 32, 168, 18, 16)

    def _reset_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET + 8, LOGICAL_SIZE[1] - SAFE_INSET - 22, 56, 18)

    def _finish_btn(self) -> pygame.Rect:
        w = 104
        return pygame.Rect(LOGICAL_SIZE[0] - SAFE_INSET - 8 - w,
                           LOGICAL_SIZE[1] - SAFE_INSET - 22, w, 18)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_back_btn(surface)

        # label da fase
        label = render_text(PHASE_LABELS[self.phase], 12, CRT_DIM)
        surface.blit(label, label.get_rect(midtop=(CX, SAFE_INSET + 6)))

        # countdown MM:SS gigante
        m, s = divmod(max(0, int(self.remaining)), 60)
        big = render_text(f"{m:02d}:{s:02d}", 56, CRT_WHITE)
        surface.blit(big, big.get_rect(center=(CX, 96)))

        self._draw_state_icon(surface, CX, 130)
        self._draw_tomatoes(surface, CX, 148)
        self._draw_task_selector(surface)
        self._draw_work_time(surface)
        self._draw_buttons(surface)

    def _draw_state_icon(self, surface, cx: int, cy: int) -> None:
        if self.running:
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
        if self.completed > 0 and done == 0 and self.phase == "long":
            done = CYCLES_BEFORE_LONG
        gap = 14
        sx = cx - (CYCLES_BEFORE_LONG - 1) * gap // 2
        for i in range(CYCLES_BEFORE_LONG):
            x = sx + i * gap
            if i < done:
                pygame.draw.circle(surface, CRT_WHITE, (x, cy), 4)
            else:
                pygame.draw.circle(surface, CRT_DIM, (x, cy), 4, 1)

    def _draw_task_selector(self, surface) -> None:
        task = self._current_task()
        if task is None:
            return
        tasks = self._doing_tasks()
        y = 176
        # setas só quando há mais de uma tarefa pra escolher
        if len(tasks) > 1:
            la = self._task_prev_btn()
            pygame.draw.polygon(surface, CRT_DIM, [
                (la.right - 4, la.centery - 5), (la.right - 4, la.centery + 5),
                (la.left + 2, la.centery),
            ])
            ra = self._task_next_btn()
            pygame.draw.polygon(surface, CRT_DIM, [
                (ra.left + 4, ra.centery - 5), (ra.left + 4, ra.centery + 5),
                (ra.right - 2, ra.centery),
            ])
        name = render_text(self._fit(task.content, 30), 9, CRT_WHITE, pixel=False)
        surface.blit(name, name.get_rect(center=(CX, y)))

    def _draw_work_time(self, surface) -> None:
        """Tempo de FOCO acumulado na tarefa atual (relógiozinho + tempo)."""
        if self._current_task() is None:
            return
        secs = self._work_time.get(self._focus_id, 0.0)
        txt = self._fmt_dur(secs)
        img = render_text(txt, 8, CRT_DIM, pixel=False)
        y = 192
        total_w = 10 + img.get_width()
        x = CX - total_w // 2
        # relógiozinho
        cxi, cyi = x + 4, y + 4
        pygame.draw.circle(surface, CRT_DIM, (cxi, cyi), 4, 1)
        pygame.draw.line(surface, CRT_DIM, (cxi, cyi), (cxi, cyi - 2), 1)
        pygame.draw.line(surface, CRT_DIM, (cxi, cyi), (cxi + 2, cyi), 1)
        surface.blit(img, (x + 10, y))

    @staticmethod
    def _fmt_dur(secs: float) -> str:
        s = int(secs)
        h, rem = divmod(s, 3600)
        m, ss = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{ss:02d}"
        return f"{m:02d}:{ss:02d}"

    def _draw_buttons(self, surface) -> None:
        self._draw_text_btn(surface, self._reset_btn(), "RESET", strong=False)
        if self._current_task() is not None:
            self._draw_text_btn(surface, self._finish_btn(), "FINALIZAR", strong=True)

    def _draw_text_btn(self, surface, rect: pygame.Rect, text: str, *, strong: bool) -> None:
        if strong:
            pygame.draw.rect(surface, CRT_WHITE, rect)
            fg = CRT_BLACK
        else:
            pygame.draw.rect(surface, CRT_BLACK, rect)
            pygame.draw.rect(surface, CRT_DIM, rect, 1)
            fg = CRT_WHITE
        img = render_text(text, 8, fg, pixel=False)
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
