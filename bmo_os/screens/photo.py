"""Tela PHOTO — preview ao vivo + botão grande pra disparar.

Touch:
- Tap no SHOOT (círculo grande embaixo) → captura foto
- Tap em HOME (canto sup-esq) → sai

Fotos salvam em <repo>/photos/. Sem câmera → mostra mensagem amigável.
"""
from __future__ import annotations

from pathlib import Path

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)
from ..services.camera import CameraService

PHOTOS_DIR = Path(__file__).resolve().parent.parent.parent / "photos"


class PhotoScreen:
    def __init__(self, on_back, camera: CameraService) -> None:
        self.on_back = on_back
        self.camera = camera
        self._t = 0.0
        self._flash_until = 0.0
        self._toast = ""
        self._toast_until = 0.0
        self._photo_count = self._count_existing_photos()

    def _count_existing_photos(self) -> int:
        try:
            return len(list(PHOTOS_DIR.glob("photo_*.jpg")))
        except Exception:
            return 0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        pos = getattr(event, "pos", None)
        if action == bmo_input.Action.B:
            self.on_back()
            return
        if action == bmo_input.Action.A:
            self._capture()
            return
        if action == bmo_input.Action.TAP and pos is not None:
            if self._back_btn().collidepoint(pos):
                self.on_back()
                return
            if self._shoot_btn_rect().collidepoint(pos):
                self._capture()

    def _capture(self) -> None:
        path = self.camera.capture_photo(PHOTOS_DIR)
        if path is not None:
            self._flash_until = self._t + 0.18
            self._toast = f"salvo: {path.name}"
            self._toast_until = self._t + 2.5
            self._photo_count += 1
        else:
            self._toast = "falhou ao capturar"
            self._toast_until = self._t + 2.5

    def update(self, dt: float) -> None:
        self._t += dt

    # ---------- layout ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def _shoot_btn_rect(self) -> pygame.Rect:
        # botão circular grande embaixo do centro
        size = 36
        return pygame.Rect(
            (LOGICAL_SIZE[0] - size) // 2,
            LOGICAL_SIZE[1] - SAFE_INSET - size - 4,
            size, size,
        )

    def _preview_rect(self) -> pygame.Rect:
        # preview centralizado entre header e botão shoot
        avail_top = SAFE_INSET + 26
        avail_bottom = LOGICAL_SIZE[1] - SAFE_INSET - 48
        h = avail_bottom - avail_top
        w = int(h * (4 / 3))  # mantém aspect 4:3 do preview
        w = min(w, LOGICAL_SIZE[0] - 2 * SAFE_INSET)
        x = (LOGICAL_SIZE[0] - w) // 2
        return pygame.Rect(x, avail_top, w, h)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        self._draw_back_btn(surface)
        self._draw_title(surface)
        self._draw_preview(surface)
        self._draw_shoot_btn(surface)
        if self._t < self._flash_until:
            self._draw_flash(surface)
        if self._t < self._toast_until and self._toast:
            self._draw_toast(surface)

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

    def _draw_title(self, surface) -> None:
        title = render_text("PHOTO", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 6)))
        if self.camera.is_available:
            count = render_text(f"{self._photo_count}", 9, CRT_DIM, pixel=False)
            surface.blit(count, count.get_rect(topright=(LOGICAL_SIZE[0] - SAFE_INSET - 70, SAFE_INSET + 6)))

    def _draw_preview(self, surface) -> None:
        rect = self._preview_rect()
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, CRT_DIM, rect, 1)
        if not self.camera.is_available:
            err = self.camera.error or "camera nao detectada"
            msg = render_text("CAMERA OFFLINE", 11, CRT_WHITE, pixel=False)
            hint = render_text(err, 8, CRT_DIM, pixel=False)
            help_ = render_text("rodar no Pi com picamera2 instalado", 8, CRT_DIM, pixel=False)
            surface.blit(msg, msg.get_rect(center=(rect.centerx, rect.centery - 14)))
            surface.blit(hint, hint.get_rect(center=(rect.centerx, rect.centery + 4)))
            surface.blit(help_, help_.get_rect(center=(rect.centerx, rect.centery + 18)))
            return
        frame = self.camera.get_preview()
        if frame is None:
            msg = render_text("carregando...", 10, CRT_DIM, pixel=False)
            surface.blit(msg, msg.get_rect(center=rect.center))
            return
        # encaixa o frame dentro do preview rect (escala mantendo aspect)
        scaled = pygame.transform.scale(frame, (rect.width, rect.height))
        surface.blit(scaled, rect.topleft)
        # mostra mini retângulos sobre rostos detectados
        faces = self.camera.get_faces()
        if faces:
            cam_w, cam_h = self.camera.preview_size
            sx = rect.width / cam_w
            sy = rect.height / cam_h
            for (fx, fy, fw, fh) in faces:
                box = pygame.Rect(
                    rect.left + int(fx * sx),
                    rect.top + int(fy * sy),
                    int(fw * sx),
                    int(fh * sy),
                )
                pygame.draw.rect(surface, CRT_WHITE, box, 1)

    def _draw_shoot_btn(self, surface) -> None:
        rect = self._shoot_btn_rect()
        cx, cy = rect.center
        r_outer = rect.width // 2
        # anel externo branco
        pygame.draw.circle(surface, CRT_WHITE, (cx, cy), r_outer, 2)
        # ponto vermelho interno se câmera ok, dim se não
        inner_color = (230, 80, 80) if self.camera.is_available else CRT_DIM
        pygame.draw.circle(surface, inner_color, (cx, cy), r_outer - 5)

    def _draw_flash(self, surface) -> None:
        # flash branco rápido pra dar feedback de captura
        flash = pygame.Surface(LOGICAL_SIZE)
        flash.fill((255, 255, 255))
        alpha = int(220 * max(0.0, (self._flash_until - self._t) / 0.18))
        flash.set_alpha(alpha)
        surface.blit(flash, (0, 0))

    def _draw_toast(self, surface) -> None:
        msg = render_text(self._toast, 9, CRT_WHITE, pixel=False)
        bg = pygame.Rect(0, 0, msg.get_width() + 16, msg.get_height() + 8)
        bg.midbottom = (LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 48)
        pygame.draw.rect(surface, CRT_BLACK, bg)
        pygame.draw.rect(surface, CRT_WHITE, bg, 1)
        surface.blit(msg, msg.get_rect(center=bg.center))
