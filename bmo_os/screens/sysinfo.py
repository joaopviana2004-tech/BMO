"""Tela SISTEMA — monitor de hardware da Raspberry Pi (estilo CRT).

Barras de CPU / GPU / RAM coloridas (verde/amarelo/vermelho conforme a carga),
temperatura grande colorida + gráfico do histórico com linhas-guia (amarela em
WARN, vermelha em HOT), e rodapé com tensão do core + status de throttling.
Quando a temperatura passa do limite vermelho, pisca um alerta.

Lê tudo do SysInfoService (snapshot + histórico). No PC mostra "--".
"""
from __future__ import annotations

import math

import pygame

from ..core import config
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

    def __init__(self, *, on_back, sysinfo: SysInfoService, cooler=None) -> None:
        self.on_back = on_back
        self.sysinfo = sysinfo
        self.cooler = cooler            # CoolerService (GPIO 17/23); None = sem suporte
        self._t = 0.0
        self._fan_angle = 0.0           # giro do ícone do cooler quando ligado
        self._cooler_sel = False        # cursor (teclado/GPIO) sobre o botão do cooler
        self._status = ""
        self._strip_y = 176

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def update(self, dt: float) -> None:
        self._t += dt
        # gira o ícone só com o cooler efetivamente ligado (manual OU auto >60°C)
        if self.cooler is not None and self.cooler.on:
            self._fan_angle = (self._fan_angle + dt * 6.0) % (2 * math.pi)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        A = bmo_input.Action
        a = event.action
        if a == A.B:
            audio.play("back"); self.on_back()
        elif a in (A.LEFT, A.RIGHT, A.UP, A.DOWN):
            self._cooler_sel = not self._cooler_sel; audio.play("tick")
        elif a == A.A:
            self._toggle_cooler()
        elif a == A.TAP and getattr(event, "pos", None):
            if self._back_btn().collidepoint(event.pos):
                audio.play("back"); self.on_back(); return
            if self._cooler_btn().collidepoint(event.pos):
                self._cooler_sel = True
                self._toggle_cooler()

    # ---------- atalho do cooler ----------

    def _toggle_cooler(self) -> None:
        audio.play("select")
        if self.cooler is None:
            self._status = "Cooler indisponivel"
            return
        new = self.cooler.toggle()
        config.set_value("cooler_enabled", new)
        self._status = "Cooler ligado" if new else "Cooler desligado"

    def _cooler_state(self) -> str:
        if self.cooler is None:
            return "OFF"
        if self.cooler.enabled:
            return "ON"
        if self.cooler.auto_on:
            return "AUTO"
        return "OFF"

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def _cooler_btn(self) -> pygame.Rect:
        bw = 150
        return pygame.Rect(LOGICAL_SIZE[0] // 2 - bw // 2, self._strip_y, bw, 18)

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

        # ----- cooler (ícone que gira + estado) na linha da temperatura -----
        self._draw_cooler(surface, ty + 8)

        # ----- gráfico de temperatura -----
        self._draw_graph(surface, 20, 116, LOGICAL_SIZE[0] - 40, 52)

        # ----- atalho do cooler -----
        self._draw_cooler_btn(surface)
        if self._status:
            bright = "ligado" in self._status
            img = render_text(self._status, 8, CRT_WHITE if bright else CRT_DIM, pixel=False)
            surface.blit(img, img.get_rect(center=(LOGICAL_SIZE[0] // 2, 204)))

        # ----- rodapé: tensão + throttle -----
        self._draw_footer(surface, snap)

    # ---------- cooler ----------

    def _draw_cooler(self, surface, cy) -> None:
        cx, r = LOGICAL_SIZE[0] - 96, 12
        state = self._cooler_state()
        color = (Colors.GREEN_BTN if state == "ON"
                 else Colors.YELLOW if state == "AUTO" else CRT_DIM)
        on = bool(self.cooler and self.cooler.on)
        self._draw_fan(surface, cx, cy, r, self._fan_angle if on else 0.4, color)
        lbl = render_text("FAN " + state, 8, color, pixel=False)
        surface.blit(lbl, lbl.get_rect(midleft=(cx + r + 6, cy)))

    @staticmethod
    def _draw_fan(surface, cx, cy, r, angle, color) -> None:
        pygame.draw.circle(surface, color, (cx, cy), r, 1)
        for i in range(3):
            a = angle + i * (2 * math.pi / 3)
            tip = (cx + math.cos(a) * (r - 2), cy + math.sin(a) * (r - 2))
            base = (cx + math.cos(a + 0.7) * (r * 0.5), cy + math.sin(a + 0.7) * (r * 0.5))
            pygame.draw.polygon(surface, color, [(cx, cy), tip, base], 1)
        pygame.draw.circle(surface, color, (cx, cy), 2)

    def _draw_cooler_btn(self, surface) -> None:
        rect = self._cooler_btn()
        if self._cooler_sel:
            pygame.draw.rect(surface, CRT_WHITE, rect)
            fg = CRT_BLACK
        else:
            pygame.draw.rect(surface, CRT_DIM, rect, 1)
            fg = CRT_DIM
        img = render_text("COOLER " + self._cooler_state(), 8, fg, pixel=False)
        surface.blit(img, img.get_rect(center=rect.center))

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
