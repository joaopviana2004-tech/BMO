"""Tela PHOTO — preview ao vivo em tela cheia + botão grande pra disparar.

O preview da câmera ocupa o canvas inteiro (estilo app de câmera de
celular). UI (HOME / shoot / contagem) fica em overlay por cima.

Fotos salvam em <repo>/photos/. Sem câmera → mostra mensagem amigável.
"""
from __future__ import annotations

from pathlib import Path

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import CRT_BLACK, CRT_DIM, CRT_WHITE, SAFE_INSET
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
        # bem no canto pra não atrapalhar a vista
        return pygame.Rect(6, 6, 52, 16)

    def _shoot_btn_rect(self) -> pygame.Rect:
        size = 36
        return pygame.Rect(
            (LOGICAL_SIZE[0] - size) // 2,
            LOGICAL_SIZE[1] - size - 8,
            size, size,
        )

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        self._draw_preview_fullscreen(surface)
        self._draw_back_btn(surface)
        self._draw_title(surface)
        # status bar pequeno no canto sup-direito (sem SAFE_INSET grande
        # — câmera é fullscreen)
        theme_state.draw_status_bar(surface, top_pad=6, right_pad=8)
        self._draw_shoot_btn(surface)
        if self._t < self._flash_until:
            self._draw_flash(surface)
        if self._t < self._toast_until and self._toast:
            self._draw_toast(surface)

    def _draw_preview_fullscreen(self, surface) -> None:
        if not self.camera.is_available:
            surface.fill(CRT_BLACK)
            self._draw_offline_message(surface)
            return
        frame = self.camera.get_preview()
        if frame is None:
            surface.fill(CRT_BLACK)
            msg = render_text("carregando camera...", 10, CRT_DIM, pixel=False)
            surface.blit(msg, msg.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2)))
            return
        # frame vem em 800x480 (1:1 com display). Canvas é 400x240.
        # Smoothscale dá downsampling com filtro linear pra ficar limpo.
        scaled = pygame.transform.smoothscale(frame, LOGICAL_SIZE)
        surface.blit(scaled, (0, 0))
        # boxes brancos sobre rostos detectados
        faces = self.camera.get_faces()
        if faces:
            cam_w, cam_h = self.camera.preview_size
            sx = LOGICAL_SIZE[0] / cam_w
            sy = LOGICAL_SIZE[1] / cam_h
            for (fx, fy, fw, fh) in faces:
                box = pygame.Rect(
                    int(fx * sx), int(fy * sy),
                    int(fw * sx), int(fh * sy),
                )
                pygame.draw.rect(surface, CRT_WHITE, box, 1)

    def _draw_offline_message(self, surface) -> None:
        cx, cy = LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2
        msg = render_text("CAMERA OFFLINE", 13, CRT_WHITE, pixel=False)
        hint = render_text(self.camera.error or "camera nao detectada", 9, CRT_DIM, pixel=False)
        help_ = render_text("rodar no Pi com picamera2 instalado", 8, CRT_DIM, pixel=False)
        surface.blit(msg, msg.get_rect(center=(cx, cy - 14)))
        surface.blit(hint, hint.get_rect(center=(cx, cy + 6)))
        surface.blit(help_, help_.get_rect(center=(cx, cy + 22)))

    def _draw_back_btn(self, surface) -> None:
        rect = self._back_btn()
        # pill semi-transparente pra contrastar com qualquer fundo
        bg = pygame.Surface((rect.width, rect.height))
        bg.fill((0, 0, 0))
        bg.set_alpha(130)
        surface.blit(bg, rect.topleft)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        pygame.draw.polygon(surface, CRT_WHITE, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        img = render_text("HOME", 8, CRT_WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _draw_title(self, surface) -> None:
        title = render_text("PHOTO", 9, CRT_WHITE, pixel=False)
        # caixinha translúcida
        bg = pygame.Surface((title.get_width() + 12, title.get_height() + 4))
        bg.fill((0, 0, 0))
        bg.set_alpha(130)
        bg_rect = bg.get_rect(midtop=(LOGICAL_SIZE[0] // 2, 6))
        surface.blit(bg, bg_rect)
        surface.blit(title, title.get_rect(center=bg_rect.center))
        # contador de fotos discreto
        if self.camera.is_available:
            count = render_text(f"{self._photo_count}", 8, CRT_WHITE, pixel=False)
            c_bg = pygame.Surface((count.get_width() + 8, count.get_height() + 4))
            c_bg.fill((0, 0, 0))
            c_bg.set_alpha(130)
            c_rect = c_bg.get_rect(midtop=(bg_rect.right + 20, 7))
            surface.blit(c_bg, c_rect)
            surface.blit(count, count.get_rect(center=c_rect.center))

    def _draw_shoot_btn(self, surface) -> None:
        rect = self._shoot_btn_rect()
        cx, cy = rect.center
        r_outer = rect.width // 2
        # halo escuro semi-transparente atrás pra destacar do preview
        halo = pygame.Surface((rect.width + 8, rect.height + 8), pygame.SRCALPHA)
        pygame.draw.circle(halo, (0, 0, 0, 130), (halo.get_width() // 2, halo.get_height() // 2), r_outer + 4)
        surface.blit(halo, (rect.left - 4, rect.top - 4))
        # anel branco
        pygame.draw.circle(surface, CRT_WHITE, (cx, cy), r_outer, 2)
        # ponto vermelho interno
        inner_color = (230, 80, 80) if self.camera.is_available else CRT_DIM
        pygame.draw.circle(surface, inner_color, (cx, cy), r_outer - 5)

    def _draw_flash(self, surface) -> None:
        flash = pygame.Surface(LOGICAL_SIZE)
        flash.fill((255, 255, 255))
        alpha = int(220 * max(0.0, (self._flash_until - self._t) / 0.18))
        flash.set_alpha(alpha)
        surface.blit(flash, (0, 0))

    def _draw_toast(self, surface) -> None:
        msg = render_text(self._toast, 9, CRT_WHITE, pixel=False)
        bg = pygame.Rect(0, 0, msg.get_width() + 16, msg.get_height() + 8)
        bg.midbottom = (LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - 52)
        bg_surf = pygame.Surface((bg.width, bg.height))
        bg_surf.fill((0, 0, 0))
        bg_surf.set_alpha(180)
        surface.blit(bg_surf, bg.topleft)
        pygame.draw.rect(surface, CRT_WHITE, bg, 1)
        surface.blit(msg, msg.get_rect(center=bg.center))


# expor SAFE_INSET pra quem importar não precisar trazer o widgets também
__all__ = ["PhotoScreen", "PHOTOS_DIR"]
