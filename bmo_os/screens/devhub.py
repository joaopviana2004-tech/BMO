"""Tela DEV HUB — dashboard de programação (commits, CI, logs do Cursor/PC).

Estilo terminal ciano (diferente do Cérebro verde). Dados chegam via webhook
POST /dev — rode scripts/bimo_dev_bridge.py no PC apontando pro IP do Bimo.
"""
from __future__ import annotations

import math
import time

import pygame

from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import SAFE_INSET, draw_scanlines, LOGICAL_SIZE
from ..services import audio
from ..services.dev_hub import DevHubService

W, H = LOGICAL_SIZE

# paleta dev (ciano sobre azul-escuro)
DV_BG = (2, 8, 14)
DV_CYAN = (90, 220, 255)
DV_MID = (45, 120, 150)
DV_DIM = (25, 55, 70)
DV_OK = (80, 255, 140)
DV_FAIL = (255, 85, 85)
DV_WARN = (255, 190, 70)
DV_IDLE = (60, 70, 80)


def _ago(ts: float) -> str:
    if ts <= 0:
        return ""
    sec = int(time.time() - ts)
    if sec < 5:
        return "agora"
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    return f"{sec // 3600}h"


def _ci_color(status: str) -> tuple:
    s = (status or "").lower()
    if s == "success":
        return DV_OK
    if s == "failure":
        return DV_FAIL
    if s == "pending":
        return DV_WARN
    return DV_IDLE


class DevHubScreen:
    voice_announce = "Dev Hub na tela."

    def __init__(self, *, on_back, dev_hub: DevHubService) -> None:
        self.on_back = on_back
        self.dev_hub = dev_hub
        self._t = 0.0
        self._tab = 0   # 0=tudo 1=commits 2=ci 3=logs

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def update(self, dt: float) -> None:
        self._t += dt

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        a = event.action
        if a in (bmo_input.Action.B, bmo_input.Action.MENU):
            audio.play("back")
            self.on_back()
        elif a == bmo_input.Action.LEFT:
            self._tab = (self._tab - 1) % 4
            audio.play("tick")
        elif a == bmo_input.Action.RIGHT:
            self._tab = (self._tab + 1) % 4
            audio.play("tick")
        elif a == bmo_input.Action.TAP and getattr(event, "pos", None):
            if self._back_btn().collidepoint(event.pos):
                audio.play("back")
                self.on_back()
        elif a == bmo_input.Action.A:
            self._tab = (self._tab + 1) % 4
            audio.play("tick")

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(DV_BG)
        draw_scanlines(surface)
        self._draw_back_btn(surface)

        snap = self.dev_hub.snapshot()
        tabs = ["TUDO", "GIT", "CI", "LOG"]
        title = render_text("DEV HUB", 10, DV_CYAN)
        surface.blit(title, title.get_rect(midtop=(W // 2, SAFE_INSET)))
        tab_txt = render_text(tabs[self._tab], 8, DV_MID, pixel=False)
        surface.blit(tab_txt, tab_txt.get_rect(topright=(W - SAFE_INSET, SAFE_INSET + 2)))

        y = SAFE_INSET + 18
        pygame.draw.line(surface, DV_DIM, (SAFE_INSET, y), (W - SAFE_INSET, y), 1)
        y += 4

        if self._tab == 0:
            y = self._draw_ci_strip(surface, y)
            y = self._draw_commits(surface, snap["commits"], y, 3)
            y = self._draw_logs(surface, snap["logs"], y, 2)
        elif self._tab == 1:
            y = self._draw_commits(surface, snap["commits"], y, 10)
        elif self._tab == 2:
            y = self._draw_ci_list(surface, snap["ci"], y)
        elif self._tab == 3:
            y = self._draw_logs(surface, snap["logs"], y, 12)

        if not snap["commits"] and not snap["ci"] and not snap["logs"]:
            self._draw_empty(surface)

        # rodapé: link status
        ip_hint = "bridge no PC: bimo_dev_bridge.py"
        foot = render_text(ip_hint, 7, DV_DIM, pixel=False)
        surface.blit(foot, foot.get_rect(midbottom=(W // 2, H - SAFE_INSET)))

    def _draw_back_btn(self, surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, DV_BG, rect)
        pygame.draw.rect(surface, DV_MID, rect, 1)
        pygame.draw.polygon(surface, DV_CYAN, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        img = render_text("MENU", 8, DV_CYAN, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _draw_ci_strip(self, surface, y: int) -> int:
        items = self.dev_hub.ci_summary()
        if not items:
            lbl = render_text("CI  (aguardando dados do PC...)", 8, DV_DIM, pixel=False)
            surface.blit(lbl, (SAFE_INSET + 2, y))
            return y + 13
        x = SAFE_INSET + 2
        ci_lbl = render_text("CI", 8, DV_MID, pixel=False)
        surface.blit(ci_lbl, (x, y))
        x += 18
        for ci in items[:3]:
            col = _ci_color(ci.status)
            pygame.draw.rect(surface, col, (x, y + 2, 6, 6))
            st = {"success": "OK", "failure": "FAIL", "pending": "..."}.get(
                ci.status, "?")
            txt = f"{ci.repo[:8]}:{st}"
            img = render_text(txt, 8, col, pixel=False)
            surface.blit(img, (x + 9, y))
            x += img.get_width() + 10
        return y + 13

    def _draw_ci_list(self, surface, ci_list, y: int) -> int:
        hdr = render_text("PIPELINES", 8, DV_MID, pixel=False)
        surface.blit(hdr, (SAFE_INSET + 2, y))
        y += 12
        if not ci_list:
            empty = render_text("  (sem CI — instale gh e faca login)", 8, DV_DIM, pixel=False)
            surface.blit(empty, (SAFE_INSET + 2, y))
            return y + 14
        for ci in ci_list[:8]:
            col = _ci_color(ci.status)
            pygame.draw.rect(surface, col, (SAFE_INSET + 2, y + 1, 6, 6))
            st = {"success": "PASS", "failure": "FAIL", "pending": "RUN"}.get(
                ci.status, "?")
            line = f"{ci.repo[:10]} {ci.branch[:12]} {ci.name[:16]} [{st}]"
            img = render_text(line, 8, col, pixel=False)
            surface.blit(img, (SAFE_INSET + 12, y))
            ago = render_text(_ago(ci.ts), 7, DV_DIM, pixel=False)
            surface.blit(ago, (W - SAFE_INSET - ago.get_width(), y + 1))
            y += 12
        return y

    def _draw_commits(self, surface, commits, y: int, max_rows: int) -> int:
        hdr = render_text("COMMITS", 8, DV_MID, pixel=False)
        surface.blit(hdr, (SAFE_INSET + 2, y))
        y += 11
        if not commits:
            empty = render_text("  (nenhum commit ainda)", 8, DV_DIM, pixel=False)
            surface.blit(empty, (SAFE_INSET + 2, y))
            return y + 12
        for c in commits[:max_rows]:
            pulse = int((math.sin(self._t * 4) + 1) * 0.5) if commits and c == commits[0] else 0
            col = DV_CYAN if pulse else DV_MID
            sha = (c.sha or "???????")[:7]
            msg = (c.msg or "")[:34]
            line = f">{sha} {msg}"
            img = render_text(line, 8, col, pixel=False)
            surface.blit(img, (SAFE_INSET + 2, y))
            ago = render_text(_ago(c.ts), 7, DV_DIM, pixel=False)
            surface.blit(ago, (W - SAFE_INSET - ago.get_width(), y + 1))
            y += 11
        return y + 2

    def _draw_logs(self, surface, logs, y: int, max_rows: int) -> int:
        if y > H - 50 and self._tab == 0:
            pygame.draw.line(surface, DV_DIM, (SAFE_INSET, y), (W - SAFE_INSET, y), 1)
            y += 3
        hdr = render_text("LOGS", 8, DV_MID, pixel=False)
        surface.blit(hdr, (SAFE_INSET + 2, y))
        y += 11
        if not logs:
            empty = render_text("  (sem logs)", 8, DV_DIM, pixel=False)
            surface.blit(empty, (SAFE_INSET + 2, y))
            return y + 12
        for log in logs[:max_rows]:
            tag = {"error": "ERR", "warn": "WRN", "info": "INF"}.get(log.level, "LOG")
            col = {"error": DV_FAIL, "warn": DV_WARN, "info": DV_MID}.get(log.level, DV_DIM)
            src = (log.source or "pc")[:8]
            txt = (log.text or "")[:38]
            line = f"[{tag}] {src}: {txt}"
            img = render_text(line, 8, col, pixel=False)
            surface.blit(img, (SAFE_INSET + 2, y))
            y += 11
        return y

    def _draw_empty(self, surface) -> None:
        cx, cy = W // 2, H // 2 + 8
        pulse = 2 + int((math.sin(self._t * 2) + 1) * 2)
        pygame.draw.rect(surface, DV_DIM, (cx - 20, cy - pulse, 40, 8), 1)
        lines = [
            ("sem eventos ainda", 9, DV_MID),
            ("rode no PC:", 8, DV_DIM),
            ("python scripts/bimo_dev_bridge.py <ip>", 7, DV_DIM),
        ]
        y = cy + 6
        for text, size, color in lines:
            img = render_text(text, size, color, pixel=(size >= 9))
            surface.blit(img, img.get_rect(midtop=(cx, y)))
            y += size + 5
