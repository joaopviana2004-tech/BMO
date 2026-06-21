"""Tela ALARME — configura hora/minuto/ligado de um único alarme.

Estilo CRT, igual o Settings (cyclers). UP/DOWN navega; LEFT/RIGHT cicla
valor do item selecionado. TAP cicla pra frente. A activa actions
(TESTAR / VOLTAR). B volta.

O AlarmService roda em background lendo config; este screen só edita.
"""
from __future__ import annotations

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


def _fmt_onoff(v) -> str:
    return "ON" if v else "OFF"


def _fmt_2digit(v) -> str:
    return f"{int(v):02d}"


ITEMS = [
    {"type": "cycle", "key": "alarm_enabled", "label": "Ativo",
     "options": [False, True], "format": _fmt_onoff},
    {"type": "cycle", "key": "alarm_hour", "label": "Hora",
     "options": list(range(24)), "format": _fmt_2digit},
    {"type": "cycle", "key": "alarm_minute", "label": "Minuto",
     "options": list(range(0, 60, 5)), "format": _fmt_2digit},
    {"type": "action", "key": "test", "label": "Testar som"},
    {"type": "action", "key": "back", "label": "Voltar"},
]


class AlarmSetScreen:
    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self._index = 0
        self._t = 0.0
        self._test_until = 0.0   # quando parar o som de teste

    def enter(self) -> None: ...
    def exit(self) -> None:
        # garante que som de teste não fica tocando se sair antes do timeout
        audio.stop_alarm_loop()

    def update(self, dt: float) -> None:
        self._t += dt
        if self._test_until > 0 and self._t >= self._test_until:
            audio.stop_alarm_loop()
            self._test_until = 0.0

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        pos = getattr(event, "pos", None)
        if action == bmo_input.Action.UP:
            self._index = (self._index - 1) % len(ITEMS)
            audio.play("tick")
        elif action == bmo_input.Action.DOWN:
            self._index = (self._index + 1) % len(ITEMS)
            audio.play("tick")
        elif action == bmo_input.Action.LEFT:
            self._cycle(-1)
        elif action == bmo_input.Action.RIGHT:
            self._cycle(+1)
        elif action == bmo_input.Action.A:
            self._activate()
        elif action == bmo_input.Action.B:
            audio.play("back")
            self.on_back()
        elif action == bmo_input.Action.TAP and pos is not None:
            self._handle_tap(pos)

    def _handle_tap(self, pos) -> None:
        for i, rect in enumerate(self._row_rects()):
            if rect.collidepoint(pos):
                if i == self._index:
                    self._activate()
                else:
                    self._index = i
                    audio.play("tick")
                return

    def _cycle(self, direction: int) -> None:
        item = ITEMS[self._index]
        if item["type"] != "cycle":
            return
        current = config.get(item["key"])
        options = item["options"]
        try:
            idx = options.index(current)
        except ValueError:
            idx = 0
        new = options[(idx + direction) % len(options)]
        config.set_value(item["key"], new)
        audio.play("tick")

    def _activate(self) -> None:
        item = ITEMS[self._index]
        if item["type"] == "cycle":
            self._cycle(+1)
            return
        if item["key"] == "test":
            audio.play("select")
            audio.play_alarm_loop()
            self._test_until = self._t + 2.5
        elif item["key"] == "back":
            audio.play("back")
            self.on_back()

    # ---------- layout ----------

    def _row_rects(self):
        top = 44
        step = 24
        return [pygame.Rect(20, top + i * step, LOGICAL_SIZE[0] - 40, 22)
                for i in range(len(ITEMS))]

    # ---------- draw ----------

    def draw(self, surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        title = render_text("ALARME", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 6)))
        self._draw_menu(surface)
        # status do teste
        if self._test_until > 0:
            msg = render_text("TESTANDO...", 9, CRT_WHITE, pixel=False)
            surface.blit(msg, msg.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 4)))
        else:
            # exibe horário do alarme em destaque embaixo
            h = config.get("alarm_hour") or 0
            m = config.get("alarm_minute") or 0
            enabled = config.get("alarm_enabled")
            txt = f"{h:02d}:{m:02d}  " + ("LIGADO" if enabled else "desligado")
            color = CRT_WHITE if enabled else CRT_DIM
            msg = render_text(txt, 11, color, pixel=False)
            surface.blit(msg, msg.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 4)))

    def _draw_menu(self, surface) -> None:
        for i, (item, rect) in enumerate(zip(ITEMS, self._row_rects())):
            selected = (i == self._index)
            fg = CRT_BLACK if selected else CRT_DIM
            if selected:
                pygame.draw.rect(surface, CRT_WHITE, rect)
                arrow = [
                    (rect.left + 5, rect.centery - 4),
                    (rect.left + 5, rect.centery + 4),
                    (rect.left + 11, rect.centery),
                ]
                pygame.draw.polygon(surface, CRT_BLACK, arrow)
                label_x = rect.left + 16
            else:
                label_x = rect.left + 8
            label = render_text(item["label"].upper(), 9, fg)
            surface.blit(label, label.get_rect(midleft=(label_x, rect.centery)))
            if item["type"] == "cycle":
                val = item["format"](config.get(item["key"]))
                val_img = render_text(val, 9, fg)
                if selected:
                    val_x = rect.right - 46
                    surface.blit(val_img, val_img.get_rect(midright=(val_x, rect.centery)))
                    # setinhas < >
                    la = pygame.Rect(rect.right - 38, rect.top, 16, rect.height)
                    ra = pygame.Rect(rect.right - 16, rect.top, 16, rect.height)
                    pygame.draw.polygon(surface, CRT_BLACK, [
                        (la.right - 3, la.centery - 4),
                        (la.right - 3, la.centery + 4),
                        (la.left + 3, la.centery),
                    ])
                    pygame.draw.polygon(surface, CRT_BLACK, [
                        (ra.left + 3, ra.centery - 4),
                        (ra.left + 3, ra.centery + 4),
                        (ra.right - 3, ra.centery),
                    ])
                else:
                    surface.blit(val_img, val_img.get_rect(midright=(rect.right - 8, rect.centery)))
