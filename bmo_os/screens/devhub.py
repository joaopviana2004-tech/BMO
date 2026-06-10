"""DEV HUB — dashboard de programação (GitHub + bridge do PC).

Modo menu (carrossel): abas RESUMO / GIT / CI / LOG + botão MENU.
Modo ambient (descanso): stats grandes, gráfico 7d, feed de commits com scroll
lento, relógio discreto. Toque → home.

Dados: GitHub API (GITHUB_USER/TOKEN no .env) + POST /dev do PC.
"""
from __future__ import annotations

import datetime as dt
import math
import time

import pygame

from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import SAFE_INSET, draw_scanlines, LOGICAL_SIZE
from ..services import audio
from ..services.dev_hub import DevHubService
from ..services.github_dev import DevHubStats, GitHubPoller

W, H = LOGICAL_SIZE

# paleta — ciano profundo, vibe terminal / cyberpunk suave
DV_BG = (1, 6, 12)
DV_BG2 = (4, 14, 22)
DV_CYAN = (72, 210, 255)
DV_GLOW = (40, 140, 180)
DV_MID = (38, 100, 128)
DV_DIM = (22, 48, 62)
DV_OK = (70, 240, 130)
DV_FAIL = (255, 80, 80)
DV_WARN = (255, 185, 60)
DV_IDLE = (55, 65, 75)
DV_GRID = (8, 22, 32)


def _ago(ts: float) -> str:
    if ts <= 0:
        return ""
    sec = int(time.time() - ts)
    if sec < 8:
        return "agora"
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    if sec < 86400:
        return f"{sec // 3600}h"
    return f"{sec // 86400}d"


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
    show_mic_button = True
    mic_btn_rect = (14, 200, 28, 26)

    def __init__(
        self,
        *,
        on_back=None,
        on_open_home=None,
        dev_hub: DevHubService,
        github: GitHubPoller | None = None,
        ambient: bool = False,
    ) -> None:
        self.on_back = on_open_home or on_back
        self.dev_hub = dev_hub
        self.github = github
        self.ambient = ambient
        self._t = 0.0
        self._tab = 0
        self._scroll = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def update(self, dt: float) -> None:
        self._t += dt
        if self.ambient:
            self._scroll += dt * 14.0

    def _stats(self) -> DevHubStats:
        if self.github is not None:
            return self.github.get_stats()
        return DevHubStats()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        a = event.action
        if self.ambient:
            if a in (bmo_input.Action.TAP, bmo_input.Action.A, bmo_input.Action.MENU):
                audio.play("select")
                self.on_back()
            return
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
        self._draw_grid(surface)
        draw_scanlines(surface)

        stats = self._stats()
        snap = self.dev_hub.snapshot()

        if self.ambient:
            self._draw_ambient(surface, stats, snap)
        else:
            self._draw_menu(surface, stats, snap)

    # ── fundo animado ──────────────────────────────────────────────

    def _draw_grid(self, surface: pygame.Surface) -> None:
        step = 20
        pulse = (math.sin(self._t * 0.7) + 1) * 0.5
        col = tuple(int(DV_GRID[i] + pulse * 6) for i in range(3))
        for x in range(0, W, step):
            pygame.draw.line(surface, col, (x, 0), (x, H), 1)
        for y in range(0, H, step):
            pygame.draw.line(surface, col, (0, y), (W, y), 1)
        # halo central suave
        cx, cy = W // 2, H // 2 - 10
        r = 60 + int(8 * math.sin(self._t * 0.5))
        try:
            glow = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(glow, (*DV_GLOW, 18), (r, r), r)
            surface.blit(glow, (cx - r, cy - r))
        except (pygame.error, ValueError):
            pass

    # ── modo ambient (descanso) ────────────────────────────────────

    def _draw_ambient(self, surface, stats: DevHubStats, snap: dict) -> None:
        self._draw_header(surface, stats, show_clock=True)
        y = SAFE_INSET + 16
        pygame.draw.line(surface, DV_DIM, (SAFE_INSET, y), (W - SAFE_INSET, y), 1)
        y += 5

        y = self._draw_stat_row(surface, stats, y, big=True)
        y += 2
        self._draw_sparkline(surface, stats.week_bars, SAFE_INSET + 2, y, W - 2 * SAFE_INSET - 4, 22)
        y += 26
        pygame.draw.line(surface, DV_DIM, (SAFE_INSET, y), (W - SAFE_INSET, y), 1)
        y += 4

        feed_h = max(0, H - y - SAFE_INSET - 14)
        self._draw_scrolling_feed(surface, snap["commits"], y, feed_h)
        self._draw_footer_strip(surface, stats, snap, H - SAFE_INSET - 12)

        if stats.sync_error and not snap["commits"]:
            self._draw_sync_hint(surface, stats.sync_error)

    def _draw_header(self, surface, stats: DevHubStats, *, show_clock: bool) -> None:
        user = stats.github_user or stats.display_name or "dev"
        if stats.display_name and stats.github_user:
            label = f"@{stats.github_user}"
        else:
            label = f"@{user}" if not user.startswith("@") else user
        pulse = (math.sin(self._t * 2.2) + 1) * 0.5
        col = tuple(int(DV_MID[i] + pulse * (DV_CYAN[i] - DV_MID[i])) for i in range(3))
        img = render_text(label[:16], 9, col, pixel=False)
        surface.blit(img, (SAFE_INSET + 2, SAFE_INSET))

        if show_clock:
            now = dt.datetime.now()
            clk = render_text(now.strftime("%H:%M"), 10, DV_CYAN)
            surface.blit(clk, clk.get_rect(topright=(W - SAFE_INSET - 2, SAFE_INSET)))

        if stats.last_sync > 0:
            sync_age = int(time.time() - stats.last_sync)
            if sync_age < 300:
                dot_col = DV_OK
            elif sync_age < 600:
                dot_col = DV_WARN
            else:
                dot_col = DV_DIM
            pygame.draw.circle(surface, dot_col, (W - SAFE_INSET - 6, SAFE_INSET + 14), 2)

    def _draw_footer_strip(self, surface, stats: DevHubStats, snap: dict, y: int) -> None:
        parts = []
        if stats.ci_pass_pct > 0:
            parts.append(f"CI {stats.ci_pass_pct}%")
        if stats.top_language:
            parts.append(stats.top_language[:10])
        if stats.stars_total > 0:
            parts.append(f"*{stats.stars_total}")
        if not parts:
            ci_items = self.dev_hub.ci_summary()
            if ci_items:
                ok = sum(1 for c in ci_items if c.status == "success")
                parts.append(f"CI {ok}/{len(ci_items)}")
        line = " | ".join(parts) if parts else "github + bridge"
        col = DV_MID if parts else DV_DIM
        img = render_text(line, 7, col, pixel=False)
        surface.blit(img, img.get_rect(midbottom=(W // 2, y + 10)))

    def _draw_sync_hint(self, surface, err: str) -> None:
        cx, cy = W // 2, H // 2 + 20
        for i, (txt, sz, col) in enumerate([
            ("configure GITHUB_USER no .env", 8, DV_MID),
            (err[:42], 7, DV_DIM),
            ("ou rode bimo_dev_bridge.py", 7, DV_DIM),
        ]):
            img = render_text(txt, sz, col, pixel=False)
            surface.blit(img, img.get_rect(midtop=(cx, cy + i * 12)))

    # ── modo menu (carrossel) ────────────────────────────────────────

    def _draw_menu(self, surface, stats: DevHubStats, snap: dict) -> None:
        self._draw_back_btn(surface)
        title = render_text("DEV HUB", 10, DV_CYAN)
        surface.blit(title, title.get_rect(midtop=(W // 2, SAFE_INSET)))
        tabs = ["RESUMO", "GIT", "CI", "LOG"]
        tab_txt = render_text(tabs[self._tab], 8, DV_MID, pixel=False)
        surface.blit(tab_txt, tab_txt.get_rect(topright=(W - SAFE_INSET, SAFE_INSET + 2)))

        y = SAFE_INSET + 18
        pygame.draw.line(surface, DV_DIM, (SAFE_INSET, y), (W - SAFE_INSET, y), 1)
        y += 4

        if self._tab == 0:
            y = self._draw_stat_row(surface, stats, y, big=False)
            y += 2
            self._draw_sparkline(surface, stats.week_bars, SAFE_INSET + 2, y, W - 2 * SAFE_INSET - 4, 18)
            y += 22
            y = self._draw_ci_strip(surface, y)
            y = self._draw_commits(surface, snap["commits"], y, 4, compact=True)
            y = self._draw_logs(surface, snap["logs"], y, 2)
        elif self._tab == 1:
            y = self._draw_commits(surface, snap["commits"], y, 12, compact=False)
        elif self._tab == 2:
            y = self._draw_ci_list(surface, snap["ci"], y)
        else:
            y = self._draw_logs(surface, snap["logs"], y, 12)

        if not snap["commits"] and not snap["ci"] and not snap["logs"]:
            if not stats.github_user:
                self._draw_sync_hint(surface, stats.sync_error or "aguardando dados")

        foot = "github api + bridge PC"
        if stats.sync_error:
            foot = stats.sync_error[:38]
        fimg = render_text(foot, 7, DV_DIM, pixel=False)
        surface.blit(fimg, fimg.get_rect(midbottom=(W // 2, H - SAFE_INSET)))

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

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

    # ── widgets compartilhados ───────────────────────────────────────

    def _draw_stat_row(self, surface, stats: DevHubStats, y: int, *, big: bool) -> int:
        cards = [
            ("HOJE", stats.commits_today),
            ("7 DIAS", stats.commits_week),
            ("STREAK", stats.streak_days),
            ("REPOS", stats.repos_active or stats.repos_total),
        ]
        n = len(cards)
        gap = 4
        total_w = W - 2 * SAFE_INSET - 4
        cw = (total_w - gap * (n - 1)) // n
        ch = 30 if big else 24
        x0 = SAFE_INSET + 2
        pulse = (math.sin(self._t * 1.8) + 1) * 0.5

        for i, (label, val) in enumerate(cards):
            x = x0 + i * (cw + gap)
            border = DV_CYAN if (big and i == 0 and val > 0) else DV_DIM
            if big and val > 0 and cw > 0 and ch > 0:
                try:
                    glow_a = int(12 + pulse * 10)
                    glow = pygame.Surface((cw, ch), pygame.SRCALPHA)
                    glow.fill((*DV_CYAN, glow_a))
                    surface.blit(glow, (x, y))
                except (pygame.error, ValueError):
                    pass
            pygame.draw.rect(surface, DV_BG2, (x, y, cw, ch))
            pygame.draw.rect(surface, border, (x, y, cw, ch), 1)
            vsize = 14 if big else 11
            vimg = render_text(str(val), vsize, DV_CYAN, pixel=(vsize >= 12))
            surface.blit(vimg, vimg.get_rect(midtop=(x + cw // 2, y + 2)))
            limg = render_text(label, 7, DV_MID, pixel=False)
            surface.blit(limg, limg.get_rect(midbottom=(x + cw // 2, y + ch - 1)))
        return y + ch

    def _draw_sparkline(self, surface, bars: list, x: int, y: int, w: int, h: int) -> None:
        if not bars or len(bars) < 2:
            bars = [0] * 7
        try:
            mx = max(int(v) for v in bars) or 1
        except (TypeError, ValueError):
            bars = [0] * 7
            mx = 1
        n = len(bars)
        bar_w = max(4, (w - (n - 1) * 3) // n)
        lbl = render_text("atividade", 7, DV_DIM, pixel=False)
        surface.blit(lbl, (x, y - 1))
        by = y + 8
        for i, v in enumerate(bars):
            bx = x + i * (bar_w + 3)
            bh = max(2, int((v / mx) * (h - 4)))
            col = DV_CYAN if v == mx and v > 0 else DV_MID
            pygame.draw.rect(surface, col, (bx, by + h - 4 - bh, bar_w, bh))

    def _draw_scrolling_feed(self, surface, commits, y0: int, h: int) -> None:
        if h <= 0:
            return
        if not commits:
            txt = render_text("aguardando commits...", 8, DV_DIM, pixel=False)
            surface.blit(txt, txt.get_rect(midleft=(SAFE_INSET + 4, y0 + max(0, h // 2))))
            return
        row_h = 13
        clip = pygame.Rect(SAFE_INSET, y0, max(1, W - 2 * SAFE_INSET), max(1, h))
        prev = surface.get_clip()
        surface.set_clip(clip)
        doubled = list(commits) * 2
        total = len(commits) * row_h
        offset = int(self._scroll % total) if total > h else 0
        y = y0 - offset
        for i, c in enumerate(doubled):
            if y > y0 + h:
                break
            if y + row_h >= y0:
                self._draw_commit_row(surface, c, SAFE_INSET + 2, y, highlight=(i == 0))
            y += row_h
        surface.set_clip(prev)

    def _draw_commit_row(self, surface, c, x: int, y: int, *, highlight: bool) -> None:
        pulse = (math.sin(self._t * 4) + 1) * 0.5 if highlight else 0
        col = tuple(int(DV_MID[i] + pulse * (DV_CYAN[i] - DV_MID[i])) for i in range(3))
        repo = (c.repo or "?")[:6]
        sha = (c.sha or "????")[:7]
        msg = (c.msg or "")[:28]
        pygame.draw.circle(surface, col, (x + 3, y + 6), 2)
        line = f"{repo} {sha} {msg}"
        img = render_text(line, 8, col, pixel=False)
        surface.blit(img, (x + 8, y))
        ago = render_text(_ago(c.ts), 7, DV_DIM, pixel=False)
        surface.blit(ago, (W - SAFE_INSET - ago.get_width(), y + 1))

    def _draw_ci_strip(self, surface, y: int) -> int:
        items = self.dev_hub.ci_summary()
        if not items:
            lbl = render_text("CI  (github ou bridge...)", 8, DV_DIM, pixel=False)
            surface.blit(lbl, (SAFE_INSET + 2, y))
            return y + 13
        x = SAFE_INSET + 2
        ci_lbl = render_text("CI", 8, DV_MID, pixel=False)
        surface.blit(ci_lbl, (x, y))
        x += 18
        for ci in items[:4]:
            col = _ci_color(ci.status)
            pygame.draw.rect(surface, col, (x, y + 2, 6, 6))
            st = {"success": "OK", "failure": "FAIL", "pending": "..."}.get(ci.status, "?")
            txt = f"{ci.repo[:7]}:{st}"
            img = render_text(txt, 8, col, pixel=False)
            surface.blit(img, (x + 9, y))
            x += img.get_width() + 8
        return y + 13

    def _draw_ci_list(self, surface, ci_list, y: int) -> int:
        hdr = render_text("PIPELINES", 8, DV_MID, pixel=False)
        surface.blit(hdr, (SAFE_INSET + 2, y))
        y += 12
        if not ci_list:
            empty = render_text("  (sem CI no github)", 8, DV_DIM, pixel=False)
            surface.blit(empty, (SAFE_INSET + 2, y))
            return y + 14
        for ci in ci_list[:9]:
            col = _ci_color(ci.status)
            pygame.draw.rect(surface, col, (SAFE_INSET + 2, y + 1, 6, 6))
            st = {"success": "PASS", "failure": "FAIL", "pending": "RUN"}.get(ci.status, "?")
            line = f"{ci.repo[:9]} {ci.branch[:10]} [{st}]"
            img = render_text(line, 8, col, pixel=False)
            surface.blit(img, (SAFE_INSET + 12, y))
            ago = render_text(_ago(ci.ts), 7, DV_DIM, pixel=False)
            surface.blit(ago, (W - SAFE_INSET - ago.get_width(), y + 1))
            y += 12
        return y

    def _draw_commits(self, surface, commits, y: int, max_rows: int, *, compact: bool) -> int:
        hdr = render_text("COMMITS", 8, DV_MID, pixel=False)
        surface.blit(hdr, (SAFE_INSET + 2, y))
        y += 11
        if not commits:
            empty = render_text("  (nenhum commit)", 8, DV_DIM, pixel=False)
            surface.blit(empty, (SAFE_INSET + 2, y))
            return y + 12
        for c in commits[:max_rows]:
            self._draw_commit_row(surface, c, SAFE_INSET + 2, y, highlight=(c == commits[0]))
            y += 11 if compact else 12
        return y + 2

    def _draw_logs(self, surface, logs, y: int, max_rows: int) -> int:
        if y > H - 50 and self._tab == 0:
            pygame.draw.line(surface, DV_DIM, (SAFE_INSET, y), (W - SAFE_INSET, y), 1)
            y += 3
        hdr = render_text("LOGS", 8, DV_MID, pixel=False)
        surface.blit(hdr, (SAFE_INSET + 2, y))
        y += 11
        if not logs:
            empty = render_text("  (sem logs do cursor)", 8, DV_DIM, pixel=False)
            surface.blit(empty, (SAFE_INSET + 2, y))
            return y + 12
        for log in logs[:max_rows]:
            tag = {"error": "ERR", "warn": "WRN", "info": "INF"}.get(log.level, "LOG")
            col = {"error": DV_FAIL, "warn": DV_WARN, "info": DV_MID}.get(log.level, DV_DIM)
            src = (log.source or "pc")[:7]
            txt = (log.text or "")[:36]
            line = f"[{tag}] {src}: {txt}"
            img = render_text(line, 8, col, pixel=False)
            surface.blit(img, (SAFE_INSET + 2, y))
            y += 11
        return y
