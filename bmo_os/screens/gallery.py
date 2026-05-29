"""Tela GALERIA — grid de thumbnails das fotos tiradas.

Tap num thumbnail abre o visualizador fullscreen. No visualizador:
- Tap esquerdo / direito → foto anterior / próxima
- Tap central → volta pra grade
- HOME → volta pra grade (e do grid pro PhotoScreen)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)
from ..services import audio

GRID_COLS = 3
GRID_ROWS = 2
PER_PAGE = GRID_COLS * GRID_ROWS

# fotos vêm em 800x480 (5:3) — thumbs preservam aspect
THUMB_W = 100
THUMB_H = 60
THUMB_GAP_X = 10
THUMB_GAP_Y = 16

MAX_THUMB_CACHE = 30


class GalleryScreen:
    def __init__(self, on_back, photos_dir: Path) -> None:
        self.on_back = on_back
        self.photos_dir = photos_dir
        self.page = 0
        self.viewer_index: Optional[int] = None
        self._thumb_cache: dict[Path, pygame.Surface] = {}
        self._full_cache: dict[Path, pygame.Surface] = {}
        self._files: list[Path] = []
        self._reload_files()

    def enter(self) -> None:
        self._reload_files()

    def exit(self) -> None: ...

    def update(self, dt: float) -> None: ...

    def _reload_files(self) -> None:
        try:
            files = list(self.photos_dir.glob("photo_*.jpg"))
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            self._files = files
            # corrige a página caso fotos tenham sido removidas
            self.page = min(self.page, max(0, self._total_pages() - 1))
        except Exception:
            self._files = []

    def _total_pages(self) -> int:
        if not self._files:
            return 1
        return (len(self._files) + PER_PAGE - 1) // PER_PAGE

    def _visible_files(self) -> list[Path]:
        start = self.page * PER_PAGE
        return self._files[start:start + PER_PAGE]

    # ---------- cache ----------

    def _get_thumb(self, path: Path) -> Optional[pygame.Surface]:
        if path in self._thumb_cache:
            return self._thumb_cache[path]
        try:
            img = pygame.image.load(str(path))
            thumb = pygame.transform.smoothscale(img, (THUMB_W, THUMB_H))
            self._thumb_cache[path] = thumb
            # cap o cache pra não explodir RAM
            if len(self._thumb_cache) > MAX_THUMB_CACHE:
                oldest = next(iter(self._thumb_cache))
                if oldest != path:
                    del self._thumb_cache[oldest]
            return thumb
        except Exception:
            return None

    def _get_full(self, path: Path) -> Optional[pygame.Surface]:
        if path in self._full_cache:
            return self._full_cache[path]
        try:
            img = pygame.image.load(str(path))
            scaled = pygame.transform.smoothscale(img, LOGICAL_SIZE)
            # só guarda o último viewer pra não estourar RAM
            self._full_cache = {path: scaled}
            return scaled
        except Exception:
            return None

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        if self.viewer_index is not None:
            self._handle_viewer(event)
        else:
            self._handle_grid(event)

    def _handle_grid(self, event) -> None:
        action = event.action
        pos = getattr(event, "pos", None)
        if action == bmo_input.Action.B:
            audio.play("back")
            self.on_back()
        elif action == bmo_input.Action.LEFT:
            if self.page > 0:
                self.page -= 1
                audio.play("tick")
        elif action == bmo_input.Action.RIGHT:
            if self.page < self._total_pages() - 1:
                self.page += 1
                audio.play("tick")
        elif action == bmo_input.Action.A:
            if self._files:
                audio.play("select")
                self.viewer_index = self.page * PER_PAGE
        elif action == bmo_input.Action.TAP and pos is not None:
            if self._back_btn().collidepoint(pos):
                audio.play("back")
                self.on_back()
                return
            if self.page > 0 and self._prev_btn().collidepoint(pos):
                self.page -= 1
                audio.play("tick")
                return
            if self.page < self._total_pages() - 1 and self._next_btn().collidepoint(pos):
                self.page += 1
                audio.play("tick")
                return
            for i, rect in enumerate(self._thumb_rects()):
                if rect.collidepoint(pos):
                    visible = self._visible_files()
                    if i < len(visible):
                        audio.play("select")
                        self.viewer_index = self.page * PER_PAGE + i
                    return

    def _handle_viewer(self, event) -> None:
        action = event.action
        pos = getattr(event, "pos", None)
        if action == bmo_input.Action.B:
            audio.play("back")
            self.viewer_index = None
            return
        if action == bmo_input.Action.LEFT:
            if self.viewer_index > 0:
                self.viewer_index -= 1
                audio.play("tick")
            return
        if action == bmo_input.Action.RIGHT:
            if self.viewer_index < len(self._files) - 1:
                self.viewer_index += 1
                audio.play("tick")
            return
        if action == bmo_input.Action.TAP and pos is not None:
            if self._back_btn().collidepoint(pos):
                audio.play("back")
                self.viewer_index = None
                return
            if pos[0] < LOGICAL_SIZE[0] // 4 and self.viewer_index > 0:
                self.viewer_index -= 1
                audio.play("tick")
            elif pos[0] > 3 * LOGICAL_SIZE[0] // 4 and self.viewer_index < len(self._files) - 1:
                self.viewer_index += 1
                audio.play("tick")
            else:
                audio.play("back")
                self.viewer_index = None

    # ---------- layout ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def _prev_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, LOGICAL_SIZE[1] - SAFE_INSET - 16, 26, 16)

    def _next_btn(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] - SAFE_INSET - 26, LOGICAL_SIZE[1] - SAFE_INSET - 16, 26, 16)

    def _thumb_rects(self) -> list[pygame.Rect]:
        grid_w = GRID_COLS * THUMB_W + (GRID_COLS - 1) * THUMB_GAP_X
        start_x = (LOGICAL_SIZE[0] - grid_w) // 2
        start_y = SAFE_INSET + 30
        rects: list[pygame.Rect] = []
        for r in range(GRID_ROWS):
            for c in range(GRID_COLS):
                x = start_x + c * (THUMB_W + THUMB_GAP_X)
                y = start_y + r * (THUMB_H + THUMB_GAP_Y)
                rects.append(pygame.Rect(x, y, THUMB_W, THUMB_H))
        return rects

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        if self.viewer_index is not None:
            self._draw_viewer(surface)
        else:
            self._draw_grid(surface)

    def _draw_grid(self, surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_back_btn(surface, label="HOME")
        self._draw_title(surface)
        if not self._files:
            msg = render_text("nenhuma foto ainda", 11, CRT_DIM, pixel=False)
            surface.blit(msg, msg.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2)))
            return
        visible = self._visible_files()
        rects = self._thumb_rects()
        for i, rect in enumerate(rects):
            if i >= len(visible):
                pygame.draw.rect(surface, CRT_DIM, rect, 1)
                continue
            path = visible[i]
            pygame.draw.rect(surface, CRT_BLACK, rect)
            thumb = self._get_thumb(path)
            if thumb is not None:
                surface.blit(thumb, rect.topleft)
            else:
                err = render_text("?", 10, CRT_DIM, pixel=False)
                surface.blit(err, err.get_rect(center=rect.center))
            pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        self._draw_page_nav(surface)

    def _draw_page_nav(self, surface) -> None:
        total = self._total_pages()
        info = render_text(f"{self.page + 1} / {total}", 9, CRT_DIM, pixel=False)
        surface.blit(info, info.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 4)))
        if self.page > 0:
            self._draw_arrow_btn(surface, self._prev_btn(), pointing_left=True)
        if self.page < total - 1:
            self._draw_arrow_btn(surface, self._next_btn(), pointing_left=False)

    def _draw_arrow_btn(self, surface, rect, *, pointing_left) -> None:
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        if pointing_left:
            pts = [
                (rect.left + 8, rect.centery),
                (rect.right - 8, rect.centery - 4),
                (rect.right - 8, rect.centery + 4),
            ]
        else:
            pts = [
                (rect.right - 8, rect.centery),
                (rect.left + 8, rect.centery - 4),
                (rect.left + 8, rect.centery + 4),
            ]
        pygame.draw.polygon(surface, CRT_WHITE, pts)

    def _draw_viewer(self, surface) -> None:
        path = self._files[self.viewer_index]
        full = self._get_full(path)
        if full is not None:
            surface.blit(full, (0, 0))
        else:
            surface.fill(CRT_BLACK)
            msg = render_text("erro ao carregar", 10, CRT_DIM, pixel=False)
            surface.blit(msg, msg.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2)))
        # info embaixo: índice e nome do arquivo
        info_txt = f"{self.viewer_index + 1} / {len(self._files)}  {path.name}"
        img = render_text(info_txt, 8, CRT_WHITE, pixel=False)
        bg = pygame.Surface((img.get_width() + 12, img.get_height() + 6))
        bg.fill((0, 0, 0))
        bg.set_alpha(170)
        bg_rect = bg.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - 8))
        surface.blit(bg, bg_rect)
        surface.blit(img, img.get_rect(center=bg_rect.center))
        # botão "voltar" pra grade
        self._draw_back_btn(surface, label="GRID")

    def _draw_back_btn(self, surface, label: str = "HOME") -> None:
        rect = self._back_btn()
        bg = pygame.Surface((rect.width, rect.height))
        bg.fill((0, 0, 0))
        bg.set_alpha(140)
        surface.blit(bg, rect.topleft)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        pygame.draw.polygon(surface, CRT_WHITE, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        img = render_text(label, 8, CRT_WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _draw_title(self, surface) -> None:
        title = render_text("GALERIA", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 6)))
        count = render_text(f"{len(self._files)} fotos", 9, CRT_DIM, pixel=False)
        surface.blit(count, count.get_rect(topright=(LOGICAL_SIZE[0] - SAFE_INSET - 70, SAFE_INSET + 6)))
