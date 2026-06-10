"""Tela SISTEMA — monitor de hardware da Raspberry Pi (estilo CRT).

Barras de CPU / GPU / RAM coloridas (verde/amarelo/vermelho conforme a carga),
temperatura grande colorida + gráfico do histórico com linhas-guia (amarela em
WARN, vermelha em HOT), e rodapé com tensão do core + status de throttling.
Quando a temperatura passa do limite vermelho, pisca um alerta.

Lê tudo do SysInfoService (snapshot + histórico). No PC mostra "--".
"""
from __future__ import annotations

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import Colors, LOGICAL_SIZE, render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)
from ..services import audio
from ..services.sysinfo import SysInfoService, THROTTLE_NOW_MASK

# limites de carga (%) pras barras CPU/GPU/RAM
LOAD_WARN = 70
LOAD_HOT = 88
# limites de temperatura (°C)
TEMP_WARN = 60
TEMP_HOT = 75
# faixa do gráfico de temperatura
GRAPH_MIN = 30
GRAPH_MAX = 90


def _load_color(pct):
    if pct is None:
        return CRT_DIM
    if pct >= LOAD_HOT:
        return Colors.RED
    if pct >= LOAD_WARN:
        return Colors.YELLOW
    return Colors.GREEN_BTN


def _temp_color(t):
    if t is None:
        return CRT_DIM
    if t >= TEMP_HOT:
        return Colors.RED
    if t >= TEMP_WARN:
        return Colors.YELLOW
    return Colors.GREEN_BTN


class SysInfoScreen:
    voice_announce = "Diagnóstico do sistema."   # BMO anuncia ao abrir (cacheado)

    def __init__(self, *, on_back, sysinfo: SysInfoService) -> None:
        self.on_back = on_back
        self.sysinfo = sysinfo
        self._t = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def update(self, dt: float) -> None:
        self._t += dt

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        if event.action == bmo_input.Action.B:
            audio.play("back")
            self.on_back()
        elif event.action == bmo_input.Action.TAP and getattr(event, "pos", None):
            if self._back_btn().collidepoint(event.pos):
                audio.play("back")
                self.on_back()

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_back_btn(surface)
        title = render_text("SISTEMA", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 1)))

        snap = self.sysinfo.get()

        # ----- barras CPU / GPU / RAM -----
        x_label, x_bar, bar_w = 20, 56, 150
        bar_h = 9
        y = 38
        self._bar(surface, "CPU", snap.cpu_pct, self._pct_txt(snap.cpu_pct),
                  x_label, x_bar, bar_w, y, bar_h)
        y += 16
        gpu_txt = f"{snap.gpu_mhz:.0f}MHz" if snap.gpu_mhz is not None else "--"
        self._bar(surface, "GPU", snap.gpu_pct, gpu_txt, x_label, x_bar, bar_w, y, bar_h)
        y += 16
        ram_txt = self._pct_txt(snap.ram_pct)
        if snap.ram_used_mb and snap.ram_total_mb:
            ram_txt = f"{snap.ram_used_mb/1024:.1f}/{snap.ram_total_mb/1024:.1f}G"
        self._bar(surface, "RAM", snap.ram_pct, ram_txt, x_label, x_bar, bar_w, y, bar_h)

        # ----- temperatura (número grande + alerta) -----
        ty = 92
        tcolor = _temp_color(snap.temp_c)
        surface.blit(render_text("TEMP", 8, CRT_DIM), (x_label, ty + 6))
        temp_str = f"{snap.temp_c:.0f}C" if snap.temp_c is not None else "--C"
        timg = render_text(temp_str, 20, tcolor)
        surface.blit(timg, timg.get_rect(midleft=(x_bar - 2, ty + 8)))
        if snap.temp_c is not None and snap.temp_c >= TEMP_HOT and (self._t % 1.0) < 0.5:
            warn = render_text("! TEMP ALTA", 9, Colors.RED)
            surface.blit(warn, warn.get_rect(midleft=(x_bar + 70, ty + 8)))

        # ----- gráfico de temperatura -----
        self._draw_graph(surface, 20, 118, LOGICAL_SIZE[0] - 40, 74)

        # ----- rodapé: tensão + throttle -----
        self._draw_footer(surface, snap)

    def _pct_txt(self, pct) -> str:
        return f"{pct:.0f}%" if pct is not None else "--"

    def _bar(self, surface, label, pct, value_txt, x_label, x_bar, w, y, h) -> None:
        surface.blit(render_text(label, 8, CRT_WHITE), (x_label, y + 1))
        pygame.draw.rect(surface, CRT_DIM, (x_bar, y, w, h), 1)
        if pct is not None:
            fw = int((w - 2) * max(0.0, min(100.0, pct)) / 100.0)
            if fw > 0:
                pygame.draw.rect(surface, _load_color(pct), (x_bar + 1, y + 1, fw, h - 2))
        val = render_text(value_txt, 8, CRT_WHITE, pixel=False)
        surface.blit(val, val.get_rect(midleft=(x_bar + w + 6, y + h // 2)))

    def _draw_graph(self, surface, gx, gy, gw, gh) -> None:
        pygame.draw.rect(surface, CRT_DIM, (gx, gy, gw, gh), 1)

        def ty(temp):
            frac = (temp - GRAPH_MIN) / (GRAPH_MAX - GRAPH_MIN)
            frac = max(0.0, min(1.0, frac))
            return gy + gh - int(frac * (gh - 2)) - 1

        # linhas-guia WARN (amarelo) e HOT (vermelho)
        for level, color in ((TEMP_WARN, Colors.YELLOW), (TEMP_HOT, Colors.RED)):
            ly = ty(level)
            for dx in range(0, gw, 6):   # tracejado leve
                pygame.draw.line(surface, color, (gx + dx, ly), (gx + min(dx + 3, gw), ly), 1)

        hist = self.sysinfo.temp_history()
        if len(hist) < 2:
            msg = render_text("coletando dados...", 8, CRT_DIM, pixel=False)
            surface.blit(msg, msg.get_rect(center=(gx + gw // 2, gy + gh // 2)))
            return

        # estica as amostras (até 5 min) pela largura toda do gráfico
        n = len(hist)
        line = [(gx + int(i * (gw - 1) / (n - 1)), ty(t)) for i, t in enumerate(hist)]
        color = _temp_color(hist[-1])
        pygame.draw.lines(surface, color, False, line, 2)

    def _draw_footer(self, surface, snap) -> None:
        y = LOGICAL_SIZE[1] - SAFE_INSET - 8
        # tensão
        v = f"VCORE {snap.volts:.2f}V" if snap.volts is not None else "VCORE --"
        surface.blit(render_text(v, 8, CRT_WHITE, pixel=False), (20, y))
        # throttle
        thr = snap.throttled
        if thr is None:
            txt, color = "THROTTLE --", CRT_DIM
        elif thr & THROTTLE_NOW_MASK:
            txt, color = "! THROTTLING", Colors.RED
        elif thr:
            txt, color = "throttle (hist)", Colors.YELLOW
        else:
            txt, color = "OK", Colors.GREEN_BTN
        img = render_text(txt, 8, color, pixel=False)
        surface.blit(img, img.get_rect(topright=(LOGICAL_SIZE[0] - 20, y)))

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
