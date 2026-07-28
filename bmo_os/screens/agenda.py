"""Tela AGENDA — eventos de HOJE do Google Calendar (estilo CRT P&B).

Lista vertical: HH:MM + título, barrinha colorida à esquerda indicando a conta.
Eventos passados ficam DIM, o próximo evento fica destacado (barra branca),
o que está rolando agora ganha tag "AGORA". Setas de scroll quando passa de
MAX_VISIBLE. HOME (sup-esq) volta; SYNC (sup-dir) força refresh.

Read-only — só exibe. Os avisos de antecedência são tratados pelo EventAlerter
+ AlertScreen, fora desta tela.
"""
from __future__ import annotations

import datetime as dt

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)
from ..services import audio
from ..services.gcalendar import CalendarService

ROW_H = 24
LIST_TOP = SAFE_INSET + 32          # ~46
MAX_VISIBLE = 6                     # 6 * 24 = 144 -> y=46..190
COL_X = SAFE_INSET + 6
COL_W = LOGICAL_SIZE[0] - 2 * (SAFE_INSET + 6)

PT_WEEKDAYS = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]
PT_MONTHS = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def _local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


class AgendaScreen:
    show_mic_button = True
    voice_announce = "Agenda na tela."   # BMO anuncia ao abrir (cacheado)
    # topo, logo à direita do botão HOME (a lista ocupa o resto da tela)
    mic_btn_rect = (70, 12, 28, 26)

    def __init__(self, *, on_back, calendar: CalendarService) -> None:
        self.on_back = on_back
        self.calendar = calendar
        self.scroll = 0
        self._sync_flash_until = 0.0
        self._t = 0.0

    def enter(self) -> None:
        self.scroll = 0

    def exit(self) -> None: ...

    # ---------- update ----------

    def update(self, dt_: float) -> None:
        self._t += dt_
        events = self.calendar.get().events
        # auto-scroll pra deixar o próximo evento visível
        nxt = self._next_index(events)
        if nxt is not None:
            if nxt < self.scroll:
                self.scroll = nxt
            elif nxt >= self.scroll + MAX_VISIBLE:
                self.scroll = nxt - MAX_VISIBLE + 1
        max_scroll = max(0, len(events) - MAX_VISIBLE)
        self.scroll = max(0, min(self.scroll, max_scroll))

    def _next_index(self, events) -> int | None:
        now = _local_now()
        for i, ev in enumerate(events):
            if not ev.all_day and ev.end >= now:
                return i
        return None

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        pos = getattr(event, "pos", None)
        events = self.calendar.get().events
        max_scroll = max(0, len(events) - MAX_VISIBLE)

        if action == bmo_input.Action.B:
            audio.play("back")
            self.on_back()
        elif action in (bmo_input.Action.UP, bmo_input.Action.LEFT):
            if self.scroll > 0:
                self.scroll -= 1
                audio.play("tick")
        elif action in (bmo_input.Action.DOWN, bmo_input.Action.RIGHT):
            if self.scroll < max_scroll:
                self.scroll += 1
                audio.play("tick")
        elif action == bmo_input.Action.A:
            audio.play("tick")
            self.calendar.trigger_refresh()
            self._sync_flash_until = self._t + 0.4
        elif action == bmo_input.Action.TAP and pos is not None:
            self._handle_tap(pos, max_scroll)

    def _handle_tap(self, pos, max_scroll) -> None:
        if self._back_btn().collidepoint(pos):
            audio.play("back")
            self.on_back()
            return
        if self._sync_btn().collidepoint(pos):
            audio.play("tick")
            self.calendar.trigger_refresh()
            self._sync_flash_until = self._t + 0.4
            return
        if self.scroll > 0 and self._scroll_up_btn().collidepoint(pos):
            self.scroll -= 1
            return
        if self.scroll < max_scroll and self._scroll_down_btn().collidepoint(pos):
            self.scroll += 1
            return

    # ---------- hitboxes ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def _sync_btn(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] - SAFE_INSET - 52, SAFE_INSET, 52, 16)

    def _scroll_up_btn(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] - SAFE_INSET - 18, LIST_TOP - 16, 18, 14)

    def _scroll_down_btn(self) -> pygame.Rect:
        ybot = LIST_TOP + MAX_VISIBLE * ROW_H
        return pygame.Rect(LOGICAL_SIZE[0] - SAFE_INSET - 18, ybot, 18, 14)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_header(surface)

        snap = self.calendar.get()
        if not snap.ok:
            self._draw_message(surface, snap.error)
            return
        if not snap.events:
            self._draw_centered(surface, "SEM COMPROMISSOS", "proximos dias livres :)")
            return
        self._draw_events(surface, snap.events)
        self._draw_footer(surface)

    def _draw_header(self, surface) -> None:
        self._draw_back_btn(surface)
        self._draw_sync_btn(surface)
        title = render_text("AGENDA", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 1)))
        now = _local_now()
        datestr = f"{PT_WEEKDAYS[now.weekday()]} {now.day:02d} {PT_MONTHS[now.month - 1]}"
        dimg = render_text(datestr, 9, CRT_WHITE, pixel=False)
        surface.blit(dimg, dimg.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 14)))

    def _draw_events(self, surface, events) -> None:
        now = _local_now()
        today = now.date()
        nxt = self._next_index(events)
        visible = events[self.scroll: self.scroll + MAX_VISIBLE]
        for vi, ev in enumerate(visible):
            gi = self.scroll + vi
            y = LIST_TOP + vi * ROW_H
            rect = pygame.Rect(COL_X, y, COL_W, ROW_H - 3)

            is_next = (gi == nxt)
            ongoing = (not ev.all_day) and (ev.start <= now <= ev.end)
            past = (not ev.all_day) and (ev.end < now)

            if is_next:
                pygame.draw.rect(surface, CRT_WHITE, rect)
                fg = CRT_BLACK
            else:
                fg = CRT_DIM if past else CRT_WHITE

            # barrinha colorida da conta
            pygame.draw.rect(surface, ev.color, (rect.left, rect.top, 3, rect.height))

            # horário
            when = "DIA" if ev.all_day else ev.start.strftime("%H:%M")
            timg = render_text(when, 10, fg, pixel=False)
            surface.blit(timg, timg.get_rect(midleft=(rect.left + 9, rect.centery)))

            # tag AGORA
            tag_w = 0
            if ongoing:
                tag = render_text("AGORA", 8, fg if is_next else CRT_WHITE, pixel=False)
                tag_w = tag.get_width() + 6
                surface.blit(tag, tag.get_rect(midright=(rect.right - 6, rect.centery)))

            # título truncado — com prefixo de data quando NÃO é hoje (a agenda
            # mostra os próximos dias, não só hoje).
            label = ev.title
            if not ev.all_day and ev.start.date() != today:
                label = f"{PT_WEEKDAYS[ev.start.weekday()]} {ev.start.day:02d} · {label}"
            title_x = rect.left + 46
            avail = rect.right - title_x - 6 - tag_w
            max_chars = max(4, avail // 6)
            timg2 = render_text(self._fit(label, max_chars), 11, fg, pixel=False)
            surface.blit(timg2, timg2.get_rect(midleft=(title_x, rect.centery)))

        # setas de scroll
        if self.scroll > 0:
            self._draw_scroll_btn(surface, self._scroll_up_btn(), up=True)
        if self.scroll + MAX_VISIBLE < len(events):
            self._draw_scroll_btn(surface, self._scroll_down_btn(), up=False)

    def _draw_scroll_btn(self, surface, btn: pygame.Rect, *, up: bool) -> None:
        pygame.draw.rect(surface, CRT_BLACK, btn)
        pygame.draw.rect(surface, CRT_DIM, btn, 1)
        if up:
            pts = [(btn.centerx - 4, btn.bottom - 4), (btn.centerx + 4, btn.bottom - 4),
                   (btn.centerx, btn.top + 3)]
        else:
            pts = [(btn.centerx - 4, btn.top + 4), (btn.centerx + 4, btn.top + 4),
                   (btn.centerx, btn.bottom - 3)]
        pygame.draw.polygon(surface, CRT_DIM, pts)

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
        img = render_text("SYNC", 8, fg, pixel=False)
        surface.blit(img, img.get_rect(center=rect.center))

    def _draw_centered(self, surface, msg: str, hint: str) -> None:
        cx, cy = LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2
        m = render_text(msg, 12, CRT_WHITE)
        surface.blit(m, m.get_rect(center=(cx, cy - 6)))
        h = render_text(hint, 9, CRT_DIM, pixel=False)
        surface.blit(h, h.get_rect(center=(cx, cy + 16)))

    def _draw_message(self, surface, error: str) -> None:
        if error == "sem URLs":
            self._draw_centered(surface, "CONFIGURE GCAL_ICS_URLS",
                                 "URL secreta iCal no .env")
        elif error == "sem libs":
            self._draw_centered(surface, "FALTA A LIB ICALENDAR",
                                 "pip install -r requirements.txt")
        else:
            self._draw_centered(surface, "SEM CONEXAO", error or "tente SYNC")

    def _draw_footer(self, surface) -> None:
        hint = render_text("A / SYNC pra atualizar", 8, CRT_DIM, pixel=False)
        surface.blit(hint, hint.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 4)))

    @staticmethod
    def _fit(text: str, max_chars: int) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return text[: max(1, max_chars - 1)] + "."
