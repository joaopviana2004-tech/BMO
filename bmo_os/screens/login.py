"""Tela LOGIN — QR Code + código (Google Device Flow), estilo CRT P&B.

Sem sessão ativa o Bimo cai aqui: mostra um QR (google.com/device com o
user_code embutido) e o código em fonte grande pra digitar manualmente.
O DeviceFlow roda em thread; esta tela só lê o estado por frame.

"USAR SEM CONTA" entra como convidado (perfil local, sem sync). Se as
credenciais GOOGLE_CLIENT_ID/SECRET não existem no .env, é o único caminho.

QR renderizado nativo em pygame: qrcode.get_matrix() -> retângulos (sem PIL).
"""
from __future__ import annotations

import pygame

from ..core import theme_state
from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)
from ..services import audio
from ..services import google_auth

try:
    import qrcode
except ImportError:
    qrcode = None


def _make_qr_surface(data: str, target_px: int) -> pygame.Surface | None:
    """QR como Surface P&B (quiet zone inclusa). None se qrcode não instalado."""
    if qrcode is None or not data:
        return None
    try:
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                           border=2)
        qr.add_data(data)
        qr.make(fit=True)
        matrix = qr.get_matrix()
    except Exception:
        return None
    n = len(matrix)
    scale = max(1, target_px // n)
    size = n * scale
    surf = pygame.Surface((size, size))
    surf.fill((255, 255, 255))
    for y, row in enumerate(matrix):
        for x, on in enumerate(row):
            if on:
                pygame.draw.rect(surf, (0, 0, 0),
                                 (x * scale, y * scale, scale, scale))
    return surf


class LoginScreen:
    preferred_fps = 15   # tela quase estática; poupa CPU/bateria

    def __init__(self, *, on_success, on_guest) -> None:
        """on_success(user, tokens) — conta autorizada; on_guest() — sem conta."""
        self.on_success = on_success
        self.on_guest = on_guest
        self.flow = google_auth.DeviceFlow()
        self._qr_surf: pygame.Surface | None = None
        self._qr_for = ""      # url que gerou o QR cacheado
        self._done = False     # evita disparar on_success 2x
        self._t = 0.0

    def enter(self) -> None:
        if google_auth.available():
            self.flow.start()

    def exit(self) -> None:
        self.flow.cancel()

    # ---------- layout ----------

    @property
    def _guest_rect(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] // 2 - 70, LOGICAL_SIZE[1] - 38, 140, 18)

    @property
    def _retry_rect(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] // 2 - 70, LOGICAL_SIZE[1] - 62, 140, 18)

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT or self._done:
            return
        a = event.action
        if a == bmo_input.Action.TAP and getattr(event, "pos", None):
            if self._guest_rect.collidepoint(event.pos):
                audio.play("select")
                self._done = True
                self.on_guest()
            elif self.flow.state == "error" and self._retry_rect.collidepoint(event.pos):
                audio.play("select")
                self.flow.start()
        elif a == bmo_input.Action.A and self.flow.state == "error":
            audio.play("select")
            self.flow.start()
        elif a == bmo_input.Action.B:
            # sem "voltar" aqui — B também entra como convidado (única saída)
            audio.play("select")
            self._done = True
            self.on_guest()

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        if self._done:
            return
        if self.flow.state == "success" and self.flow.user and self.flow.tokens:
            self._done = True
            audio.play("select")
            self.on_success(self.flow.user, self.flow.tokens)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4,
                                    right_pad=SAFE_INSET + 4)
        title = render_text("QUEM ESTA AI?", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 6)))

        state = self.flow.state

        if not google_auth.available():
            self._draw_center_lines(surface, [
                ("LOGIN GOOGLE INDISPONIVEL", 10, CRT_WHITE),
                ("configure GOOGLE_CLIENT_ID no .env", 8, CRT_DIM),
            ])
        elif state in ("idle", "requesting"):
            dots = "." * (1 + int(self._t * 2) % 3)
            self._draw_center_lines(surface, [
                (f"GERANDO CODIGO{dots}", 10, CRT_WHITE),
            ])
        elif state == "waiting":
            self._draw_waiting(surface)
        elif state == "success":
            name = (self.flow.user or {}).get("name") or "voce"
            self._draw_center_lines(surface, [
                (f"OLA, {name.upper()}!", 12, CRT_WHITE),
                ("preparando o seu Bimo...", 8, CRT_DIM),
            ])
        else:   # error
            self._draw_center_lines(surface, [
                ("FALHOU :(", 12, CRT_WHITE),
                (self.flow.error or "erro no login", 8, CRT_DIM),
            ])
            self._draw_button(surface, self._retry_rect, "TENTAR DE NOVO")

        if not self._done and state != "success":
            self._draw_button(surface, self._guest_rect, "USAR SEM CONTA")

    def _draw_waiting(self, surface: pygame.Surface) -> None:
        qr_url = self.flow.qr_url
        if qr_url and qr_url != self._qr_for:
            self._qr_surf = _make_qr_surface(qr_url, 132)
            self._qr_for = qr_url

        if self._qr_surf is not None:
            # QR à esquerda, instruções + código à direita
            qr_rect = self._qr_surf.get_rect()
            qr_rect.topleft = (38, 50)
            pygame.draw.rect(surface, (255, 255, 255), qr_rect.inflate(6, 6))
            surface.blit(self._qr_surf, qr_rect)
            x = qr_rect.right + 24
            lines = [
                ("ESCANEIE COM O CELULAR", 8, CRT_DIM, 58),
                ("ou entre em", 8, CRT_DIM, 80),
                ("google.com/device", 9, CRT_WHITE, 94),
                ("e digite o codigo:", 8, CRT_DIM, 110),
                (self.flow.user_code or "----", 16, CRT_WHITE, 132),
            ]
            for text, size, color, y in lines:
                img = render_text(text, size, color, pixel=(size >= 16))
                surface.blit(img, img.get_rect(topleft=(x, y)))
            dots = "." * (1 + int(self._t * 2) % 3)
            wait = render_text(f"esperando autorizacao{dots}", 8, CRT_DIM)
            surface.blit(wait, wait.get_rect(topleft=(x, 162)))
        else:
            # sem lib qrcode: só o código manual
            self._draw_center_lines(surface, [
                ("ENTRE EM google.com/device", 9, CRT_DIM),
                ("E DIGITE O CODIGO:", 9, CRT_DIM),
                (self.flow.user_code or "----", 18, CRT_WHITE),
            ])

    @staticmethod
    def _draw_center_lines(surface: pygame.Surface, lines) -> None:
        cx = LOGICAL_SIZE[0] // 2
        total_h = sum(size + 10 for _, size, _ in lines)
        y = (LOGICAL_SIZE[1] - total_h) // 2
        for text, size, color in lines:
            img = render_text(text, size, color, pixel=(size >= 12))
            surface.blit(img, img.get_rect(midtop=(cx, y)))
            y += size + 10

    @staticmethod
    def _draw_button(surface: pygame.Surface, rect: pygame.Rect, label: str) -> None:
        pygame.draw.rect(surface, CRT_DIM, rect, 1)
        img = render_text(label, 8, CRT_WHITE)
        surface.blit(img, img.get_rect(center=rect.center))
