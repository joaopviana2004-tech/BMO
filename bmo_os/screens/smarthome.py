"""Tela SMART HOUSE — controle das tomadas inteligentes (estilo CRT).

Mostra um card por tomada com o estado (LIGADA/desligada/offline) e um símbolo
de power colorido. Toque (ou A) liga/desliga a tomada selecionada; setas movem a
seleção; B/MENU volta. Um botão "TUDO" liga/desliga todas de uma vez.

Lê tudo do SmartHomeService (snapshot lock-guarded, sem bloquear o loop). No PC,
ou sem tomadas no .env, mostra uma mensagem de indisponível.
"""
from __future__ import annotations

import math

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import Colors, LOGICAL_SIZE, render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)
from ..services import audio

W = LOGICAL_SIZE[0]
H = LOGICAL_SIZE[1]


class SmartHomeScreen:
    voice_announce = "Casa inteligente."   # BMO anuncia ao abrir (cacheado)

    def __init__(self, *, on_back, smarthome) -> None:
        self.on_back = on_back
        self.smarthome = smarthome
        self._t = 0.0
        self._sel = 0

    def enter(self) -> None:
        self._sel = 0
        try:
            self.smarthome.refresh()   # força uma leitura ao abrir
        except Exception:
            pass

    def exit(self) -> None: ...

    def update(self, dt: float) -> None:
        self._t += dt

    # ---------- seleção: 0..n-1 = tomadas, n = botão TUDO ----------

    def _n_devices(self) -> int:
        return self.smarthome.count() if self.smarthome else 0

    def _n_sel(self) -> int:
        n = self._n_devices()
        return n + (1 if n >= 2 else 0)     # +1 = botão TUDO (só com 2+)

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        A = bmo_input.Action
        a = event.action
        total = self._n_sel()
        if a in (A.B, A.MENU):
            audio.play("back"); self.on_back()
        elif total == 0:
            return
        elif a in (A.LEFT, A.UP):
            self._sel = (self._sel - 1) % total
            audio.play("tick")
        elif a in (A.RIGHT, A.DOWN):
            self._sel = (self._sel + 1) % total
            audio.play("tick")
        elif a == A.A:
            self._activate(self._sel)
        elif a == A.TAP and getattr(event, "pos", None):
            self._handle_tap(event.pos)

    def _handle_tap(self, pos) -> None:
        if self._back_btn().collidepoint(pos):
            audio.play("back"); self.on_back(); return
        n = self._n_devices()
        for i in range(n):
            if self._card_rect(i, n).collidepoint(pos):
                self._sel = i
                self._activate(i)
                return
        if self._n_sel() > n and self._all_btn().collidepoint(pos):
            self._sel = n
            self._activate(n)

    def _activate(self, idx: int) -> None:
        n = self._n_devices()
        if n == 0:
            return
        audio.play("select")
        if idx >= n:                       # botão TUDO
            cur = self.smarthome.all_on()
            self.smarthome.set_all(not bool(cur))
            return
        devs = self.smarthome.get_devices()
        if idx < len(devs):
            self.smarthome.toggle(devs[idx]["key"])

    # ---------- layout ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def _has_all(self, n: int) -> bool:
        return n >= 2

    def _grid(self, n: int):
        inset = SAFE_INSET
        top = inset + 28
        bottom = H - inset - (26 if self._has_all(n) else 8)
        area_w = W - 2 * inset
        area_h = bottom - top
        cols = 1 if n <= 1 else 2
        rows = max(1, (n + cols - 1) // cols)
        gap = 8
        cw = (area_w - (cols - 1) * gap) // cols
        ch = min((area_h - (rows - 1) * gap) // rows, 130)
        return cols, rows, cw, ch, gap, inset, top

    def _card_rect(self, i: int, n: int) -> pygame.Rect:
        cols, rows, cw, ch, gap, inset, top = self._grid(n)
        row, col = i // cols, i % cols
        in_row = min(cols, n - row * cols)
        row_w = in_row * cw + (in_row - 1) * gap
        rx = inset + (W - 2 * inset - row_w) // 2
        return pygame.Rect(rx + col * (cw + gap), top + row * (ch + gap), cw, ch)

    def _all_btn(self) -> pygame.Rect:
        bw = 170
        return pygame.Rect(W // 2 - bw // 2, H - SAFE_INSET - 22, bw, 18)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_back_btn(surface)
        title = render_text("SMART HOUSE", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(W // 2, SAFE_INSET + 1)))

        if not getattr(self.smarthome, "available", False):
            self._draw_offline(surface)
            return

        devs = self.smarthome.get_devices()
        n = len(devs)
        if n == 0:
            self._draw_offline(surface)
            return
        for i, d in enumerate(devs):
            self._draw_card(surface, self._card_rect(i, n), d, selected=(i == self._sel))
        if self._has_all(n):
            self._draw_all_btn(surface, selected=(self._sel == n))

    def _draw_offline(self, surface) -> None:
        msg = getattr(self.smarthome, "status", "indisponivel")
        img = render_text("SMART HOUSE OFF", 11, CRT_DIM)
        surface.blit(img, img.get_rect(center=(W // 2, H // 2 - 8)))
        sub = render_text(str(msg), 8, CRT_DIM, pixel=False)
        surface.blit(sub, sub.get_rect(center=(W // 2, H // 2 + 10)))

    def _draw_card(self, surface, r: pygame.Rect, d: dict, *, selected: bool) -> None:
        online = bool(d.get("online"))
        on = bool(d.get("on")) if d.get("on") is not None else False
        if not online:
            color = Colors.RED
        elif on:
            color = Colors.GREEN_BTN
        else:
            color = CRT_DIM

        pygame.draw.rect(surface, CRT_BLACK, r)
        pygame.draw.rect(surface, CRT_WHITE if selected else CRT_DIM, r,
                         2 if selected else 1, border_radius=5)

        # nome no topo
        name = render_text(str(d.get("name", "?")), 9, CRT_WHITE if selected else CRT_DIM)
        surface.blit(name, name.get_rect(midtop=(r.centerx, r.top + 8)))

        # símbolo de power grande, colorido pelo estado (pisca de leve quando ligado)
        cy = r.centery - 2
        ring = 18
        glow = on and online and (math.sin(self._t * 4) > -0.3)
        pygame.draw.circle(surface, color, (r.centerx, cy + 1), ring, 0 if glow else 2)
        pygame.draw.rect(surface, CRT_BLACK, (r.centerx - 5, cy - ring - 4, 10, 12))
        line_col = CRT_BLACK if glow else color
        pygame.draw.line(surface, line_col, (r.centerx, cy - ring + 2), (r.centerx, cy + 1), 3)

        # estado em texto
        if not online:
            txt = "OFFLINE"
        elif on:
            txt = "LIGADA"
        else:
            txt = "DESLIGADA"
        st = render_text(txt, 9, color)
        surface.blit(st, st.get_rect(midtop=(r.centerx, cy + ring + 8)))

        # ip + dica de toque no rodapé do card
        foot = render_text(str(d.get("ip", "")), 7, CRT_DIM, pixel=False)
        surface.blit(foot, foot.get_rect(midbottom=(r.centerx, r.bottom - 4)))

    def _draw_all_btn(self, surface, *, selected: bool) -> None:
        rect = self._all_btn()
        cur = self.smarthome.all_on()
        label = "DESLIGAR TUDO" if cur else "LIGAR TUDO"
        if selected:
            pygame.draw.rect(surface, CRT_WHITE, rect, border_radius=3)
            fg = CRT_BLACK
        else:
            pygame.draw.rect(surface, CRT_DIM, rect, 1, border_radius=3)
            fg = CRT_DIM
        img = render_text(label, 8, fg, pixel=False)
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
