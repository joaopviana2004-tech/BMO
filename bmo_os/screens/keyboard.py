"""Teclado virtual on-screen (estilo CRT P&B) — entrada de texto sem teclado.

Reutilizavel: recebe `title`, `on_done(text)` e `on_cancel()`. Pensado pro
touchscreen do BMO (5", 800x480), mas tambem aceita o teclado FISICO no PC de
dev (KEYDOWN cru) pra agilizar os testes.

Entrada:
  - TAP (toque): bate nas teclas desenhadas — interface real no Pi.
  - KEYDOWN cru (dev): letras/numeros/simbolos digitam; Enter=OK, Esc=cancela,
    Backspace apaga, Espaco insere espaco.
Os Actions UP/DOWN/A/B sao IGNORADOS de proposito: Backspace/Esc do teclado
fisico tambem viram Action.B no app, entao tratamos a fala fisica so pelo
KEYDOWN cru e o toque so pelo TAP — sem conflito de evento duplo.

Camadas: minusculas / MAIUSCULAS (Shift) / simbolos (?#=). Senhas de WiFi
costumam ter simbolo, por isso a camada de simbolos.
"""
from __future__ import annotations

import pygame

from ..core import input as bmo_input
from ..core.theme import render_text, LOGICAL_SIZE
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)
from ..services import audio

# Cada linha e uma lista de "specs": uma string de 1 char (tecla normal) ou uma
# tupla (rotulo, id_controle, unidades_de_largura). Ids de controle:
# shift / bksp / space / done / sym / abc / cancel.
_LAYERS = {
    "lower": [
        list("1234567890"),
        list("qwertyuiop"),
        list("asdfghjkl"),
        [("Shift", "shift", 1.6)] + list("zxcvbnm") + [("Del", "bksp", 1.6)],
        [("?#=", "sym", 1.8), ("Espaco", "space", 4.4), ("OK", "done", 1.8)],
    ],
    "upper": [
        list("1234567890"),
        list("QWERTYUIOP"),
        list("ASDFGHJKL"),
        [("Shift", "shift", 1.6)] + list("ZXCVBNM") + [("Del", "bksp", 1.6)],
        [("?#=", "sym", 1.8), ("Espaco", "space", 4.4), ("OK", "done", 1.8)],
    ],
    "sym": [
        list("1234567890"),
        list("@#$_&-+()/"),
        list("=*\"':;!?,."),
        [("\\", "\\", 1)] + list("~`|{}[]<>") + [("Del", "bksp", 1.4)],
        [("ABC", "abc", 1.8), ("Espaco", "space", 4.4), ("OK", "done", 1.8)],
    ],
}

MAX_LEN = 63   # senha WiFi WPA: 8..63 chars


class KeyboardScreen:
    preferred_fps = 20

    def __init__(self, *, title: str, on_done, on_cancel=None,
                 initial: str = "", max_len: int = MAX_LEN) -> None:
        self.title = title
        self.on_done = on_done
        self.on_cancel = on_cancel or (lambda: None)
        self.text = initial or ""
        self.max_len = max_len
        self._layer = "lower"
        self._keys: list[tuple[pygame.Rect, str, str]] = []  # (rect, rotulo, id)
        self._kb_top = 86
        self._key_h = 26
        self._t = 0.0
        self._build_keys()

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- layout das teclas ----------

    @staticmethod
    def _norm(spec):
        if isinstance(spec, tuple):
            return spec[0], spec[1], float(spec[2])
        return spec, spec, 1.0   # tecla normal: rotulo = caractere = id

    def _build_keys(self) -> None:
        self._keys = []
        rows = _LAYERS[self._layer]
        x0 = 16
        x1 = LOGICAL_SIZE[0] - 16
        area_w = x1 - x0
        hgap = 3
        vgap = 4
        for r, row in enumerate(rows):
            specs = [self._norm(s) for s in row]
            total_units = sum(u for _, _, u in specs)
            unit_w = (area_w - hgap * (len(specs) - 1)) / total_units
            y = self._kb_top + r * (self._key_h + vgap)
            x = float(x0)
            for label, key, units in specs:
                w = unit_w * units
                rect = pygame.Rect(int(round(x)), y, int(round(w)), self._key_h)
                self._keys.append((rect, label, key))
                x += w + hgap

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        # 1) toque nas teclas desenhadas (interface do Pi)
        if event.type == bmo_input.ACTION_EVENT:
            if event.action == bmo_input.Action.TAP and getattr(event, "pos", None):
                self._tap(event.pos)
            return
        # 2) teclado FISICO (conveniencia no PC) — KEYDOWN cru
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._press("done")
            elif event.key == pygame.K_ESCAPE:
                self._press("cancel")
            elif event.key == pygame.K_BACKSPACE:
                self._press("bksp")
            elif event.key == pygame.K_SPACE:
                self._insert(" ")
            else:
                ch = event.unicode
                if ch and ch.isprintable() and event.key not in bmo_input.KEY_MAP:
                    self._insert(ch)

    def _tap(self, pos) -> None:
        if self._handle_cancel_tap(pos):
            return
        for rect, _label, key in self._keys:
            if rect.collidepoint(pos):
                self._press(key)
                return

    def _insert(self, ch: str) -> None:
        if len(self.text) < self.max_len:
            self.text += ch
            audio.play("tick")

    def _press(self, key: str) -> None:
        if key == "shift":
            self._layer = "upper" if self._layer != "upper" else "lower"
            self._build_keys(); audio.play("tick")
        elif key == "sym":
            self._layer = "sym"; self._build_keys(); audio.play("tick")
        elif key == "abc":
            self._layer = "lower"; self._build_keys(); audio.play("tick")
        elif key == "bksp":
            self.text = self.text[:-1]; audio.play("tick")
        elif key == "space":
            self._insert(" ")
        elif key == "done":
            audio.play("select"); self.on_done(self.text)
        elif key == "cancel":
            audio.play("back"); self.on_cancel()
        else:
            self._insert(key)

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        # titulo
        title = render_text(self.title, 9, CRT_DIM, pixel=False)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 2)))

        # campo de texto (com cursor piscando)
        box = pygame.Rect(16, 30, LOGICAL_SIZE[0] - 60, 22)
        pygame.draw.rect(surface, CRT_WHITE, box, 1)
        shown = self.text
        # corta a esquerda se nao couber
        while shown and render_text(shown, 11, CRT_WHITE, pixel=False).get_width() > box.width - 12:
            shown = shown[1:]
        cursor = "_" if int(self._t * 2) % 2 == 0 else " "
        txt = render_text(shown + cursor, 11, CRT_WHITE, pixel=False)
        surface.blit(txt, txt.get_rect(midleft=(box.left + 6, box.centery)))

        # botao X (cancelar) ao lado do campo
        self._cancel_rect = pygame.Rect(box.right + 6, box.top, 22, 22)
        pygame.draw.rect(surface, CRT_DIM, self._cancel_rect, 1)
        x_img = render_text("X", 11, CRT_WHITE, pixel=False)
        surface.blit(x_img, x_img.get_rect(center=self._cancel_rect.center))

        # teclas
        for rect, label, key in self._keys:
            special = key in ("shift", "bksp", "space", "done", "sym", "abc")
            pygame.draw.rect(surface, CRT_DIM if special else CRT_WHITE, rect, 1)
            if key == "done":
                pygame.draw.rect(surface, CRT_WHITE, rect.inflate(-4, -4))
                fg = CRT_BLACK
            else:
                fg = CRT_WHITE
            size = 9 if len(label) > 1 else 12
            img = render_text(label, size, fg, pixel=False)
            surface.blit(img, img.get_rect(center=rect.center))

    # o X de cancelar so existe depois do 1o draw; trata o toque nele aqui
    def _handle_cancel_tap(self, pos) -> bool:
        rect = getattr(self, "_cancel_rect", None)
        if rect is not None and rect.collidepoint(pos):
            self._press("cancel")
            return True
        return False
