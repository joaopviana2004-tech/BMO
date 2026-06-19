"""Tela INTERNET (SETTINGS -> INTERNET): status de conexao + WiFi.

- Mostra ONLINE / SEM INTERNET e a rede atual.
- Lista as redes WiFi (so no Pi, via nmcli) com sinal e cadeado.
- Conectar: teclado virtual pra senha (screens/keyboard.py) OU escanear um QR
  de WiFi com a camera (WifiQrScreen), quando a camera esta disponivel.

No PC de dev (sem nmcli) a tela ainda mostra o status de internet e explica que
o controle de WiFi so existe no Pi.
"""
from __future__ import annotations

import pygame

from ..core import theme_state
from ..core import input as bmo_input
from ..core.theme import render_text, LOGICAL_SIZE
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
)
from ..services import audio
from ..services.network import parse_wifi_qr
from .keyboard import KeyboardScreen


def _draw_signal(surface, x: int, cy: int, signal: int, color) -> None:
    """4 barrinhas crescentes preenchidas conforme o sinal (0-100)."""
    filled = 1 + min(3, max(0, signal) * 4 // 100)   # 1..4
    for i in range(4):
        h = 3 + i * 2
        bx = x + i * 4
        by = cy + 5 - h
        if i < filled:
            pygame.draw.rect(surface, color, (bx, by, 3, h))
        else:
            pygame.draw.rect(surface, color, (bx, by, 3, h), 1)


def _draw_lock(surface, x: int, cy: int, color) -> None:
    pygame.draw.rect(surface, color, (x, cy - 1, 7, 6))       # corpo
    pygame.draw.rect(surface, color, (x + 1, cy - 5, 5, 5), 1)  # arco


class WifiScreen:
    preferred_fps = 20

    def __init__(self, *, net, camera=None, on_back, push, pop) -> None:
        self.net = net
        self.camera = camera
        self.on_back = on_back
        self.push = push    # manager.push (abrir teclado / QR)
        self.pop = pop      # manager.pop (fechar sub-telas)
        self._index = 0
        self._scroll = 0
        self._t = 0.0
        self._rows: list[dict] = []

    def enter(self) -> None:
        self.net.check_now()
        self.net.connect_status = ""
        if self.net.wifi_available:
            self.net.scan_async()

    def exit(self) -> None: ...

    # ---------- montagem das linhas ----------

    def _camera_ok(self) -> bool:
        return self.camera is not None and getattr(self.camera, "is_available", False)

    def _build_rows(self) -> None:
        rows: list[dict] = []
        if self.net.wifi_available:
            if self._camera_ok():
                rows.append({"kind": "qr", "label": "ESCANEAR QR DO WIFI"})
            rows.append({"kind": "rescan", "label": "ATUALIZAR LISTA"})
            for n in self.net.networks():
                rows.append({"kind": "net", "net": n})
        self._rows = rows
        if self._index >= len(rows):
            self._index = max(0, len(rows) - 1)

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        a = event.action
        if a == bmo_input.Action.UP:
            self._move(-1)
        elif a == bmo_input.Action.DOWN:
            self._move(+1)
        elif a in (bmo_input.Action.A, bmo_input.Action.RIGHT):
            self._activate()
        elif a == bmo_input.Action.B:
            audio.play("back"); self.on_back()
        elif a == bmo_input.Action.TAP and getattr(event, "pos", None):
            self._tap(event.pos)

    def _move(self, delta: int) -> None:
        if not self._rows:
            return
        self._index = (self._index + delta) % len(self._rows)
        audio.play("tick")

    def _tap(self, pos) -> None:
        if getattr(self, "_back_rect", None) and self._back_rect.collidepoint(pos):
            audio.play("back"); self.on_back(); return
        for i, rect in self._row_rects():
            if rect.collidepoint(pos):
                if i == self._index:
                    self._activate()
                else:
                    self._index = i; audio.play("tick")
                return

    def _activate(self) -> None:
        if not self._rows or self._index >= len(self._rows):
            return
        row = self._rows[self._index]
        if row["kind"] == "rescan":
            audio.play("select"); self.net.scan_async()
        elif row["kind"] == "qr":
            audio.play("select")
            self.push(WifiQrScreen(net=self.net, camera=self.camera,
                                   on_back=self.pop))
        elif row["kind"] == "net":
            audio.play("select"); self._connect(row["net"])

    def _connect(self, net: dict) -> None:
        ssid = net["ssid"]
        if not net.get("secure"):
            self.net.connect_async(ssid, "")
            return

        def done(pw: str) -> None:
            self.pop()
            self.net.connect_async(ssid, pw)

        def cancel() -> None:
            self.pop()

        self.push(KeyboardScreen(title=f"SENHA DE {ssid}", on_done=done,
                                 on_cancel=cancel))

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        self._build_rows()

    # ---------- layout ----------

    _VISIBLE = 7
    _ROW_TOP = 64
    _ROW_H = 18

    def _row_rects(self):
        """(i, rect) das linhas VISIVEIS conforme o scroll."""
        out = []
        start = self._scroll
        for vi in range(self._VISIBLE):
            i = start + vi
            if i >= len(self._rows):
                break
            rect = pygame.Rect(16, self._ROW_TOP + vi * self._ROW_H,
                               LOGICAL_SIZE[0] - 32, self._ROW_H - 2)
            out.append((i, rect))
        return out

    def _sync_scroll(self) -> None:
        if self._index < self._scroll:
            self._scroll = self._index
        elif self._index >= self._scroll + self._VISIBLE:
            self._scroll = self._index - self._VISIBLE + 1

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4,
                                    right_pad=SAFE_INSET + 4)
        title = render_text("INTERNET", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 6)))

        # ----- status de conexao -----
        online = self.net.online
        st = "ONLINE" if online else "SEM INTERNET"
        cur = self.net.current_ssid
        line = st + (f"  -  {cur}" if cur else "")
        img = render_text(line, 9, CRT_WHITE, pixel=False)
        surface.blit(img, img.get_rect(midtop=(LOGICAL_SIZE[0] // 2, 40)))

        if not self.net.wifi_available:
            self._draw_center(surface, [
                ("CONTROLE DE WIFI SO NO PI", 9, CRT_WHITE),
                ("(no PC, conecte pelo sistema)", 8, CRT_DIM),
            ])
            self._draw_back(surface)
            return

        # ----- lista de redes -----
        self._sync_scroll()
        if self.net.scanning and not self._rows:
            self._draw_center(surface, [("PROCURANDO REDES" + "." * (1 + int(self._t * 2) % 3), 9, CRT_WHITE)])
        elif self.net.scan_error and not self.net.networks():
            self._draw_center(surface, [("FALHA NO SCAN", 9, CRT_WHITE),
                                        (self.net.scan_error, 8, CRT_DIM)])
        else:
            for i, rect in self._row_rects():
                self._draw_row(surface, i, rect)
            # indicador de mais itens
            if self._scroll + self._VISIBLE < len(self._rows):
                more = render_text("v", 10, CRT_DIM)
                surface.blit(more, more.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, 210)))

        # ----- status de conexao (rodape) -----
        cs = (self.net.connect_status or "").strip()
        if cs:
            if cs == "ok":
                msg, color = "CONECTADO!", CRT_WHITE
            elif cs == "conectando":
                msg, color = "CONECTANDO" + "." * (1 + int(self._t * 2) % 3), CRT_WHITE
            else:
                msg, color = cs, CRT_DIM
            m = render_text(msg, 9, color, pixel=False)
            surface.blit(m, m.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 2)))

        self._draw_back(surface)

    def _draw_row(self, surface, i: int, rect: pygame.Rect) -> None:
        row = self._rows[i]
        selected = (i == self._index)
        if selected:
            pygame.draw.rect(surface, CRT_WHITE, rect)
            fg = CRT_BLACK
        else:
            fg = CRT_DIM
        if row["kind"] in ("qr", "rescan"):
            label = render_text(row["label"], 9, fg, pixel=False)
            surface.blit(label, label.get_rect(midleft=(rect.left + 8, rect.centery)))
        else:
            n = row["net"]
            name = n["ssid"]
            mark = "* " if n.get("in_use") else ""
            label = render_text(mark + name, 9, fg, pixel=False)
            surface.blit(label, label.get_rect(midleft=(rect.left + 8, rect.centery)))
            # cadeado + sinal a direita
            sx = rect.right - 26
            if n.get("secure"):
                _draw_lock(surface, rect.right - 40, rect.centery - 2, fg)
            _draw_signal(surface, sx, rect.centery - 2, n.get("signal", 0), fg)

    def _draw_center(self, surface, lines) -> None:
        cx = LOGICAL_SIZE[0] // 2
        total = sum(s + 8 for _, s, _ in lines)
        y = (LOGICAL_SIZE[1] - total) // 2 + 8
        for text, size, color in lines:
            img = render_text(text, size, color, pixel=(size >= 12))
            surface.blit(img, img.get_rect(midtop=(cx, y)))
            y += size + 8

    def _draw_back(self, surface) -> None:
        self._back_rect = pygame.Rect(LOGICAL_SIZE[0] // 2 - 30,
                                      LOGICAL_SIZE[1] - SAFE_INSET - 16, 60, 14)
        # so desenha o botao quando nao ha status de conexao ocupando o rodape
        if not (self.net.connect_status or "").strip():
            pygame.draw.rect(surface, CRT_DIM, self._back_rect, 1)
            img = render_text("VOLTAR", 8, CRT_WHITE)
            surface.blit(img, img.get_rect(center=self._back_rect.center))


class WifiQrScreen:
    """Escaneia um QR de WiFi com a camera e conecta. Aponte a camera pro QR
    (do roteador ou o que o celular gera em 'compartilhar WiFi')."""
    preferred_fps = 15

    def __init__(self, *, net, camera, on_back) -> None:
        self.net = net
        self.camera = camera
        self.on_back = on_back
        self._t = 0.0
        self._last_read = 0.0
        self._msg = ""
        self._done_at = 0.0

    def enter(self) -> None:
        try:
            self.camera.acquire()
        except Exception:
            pass

    def exit(self) -> None:
        try:
            self.camera.release()
        except Exception:
            pass

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        if event.action in (bmo_input.Action.B, bmo_input.Action.TAP):
            audio.play("back"); self.on_back()

    def update(self, dt: float) -> None:
        self._t += dt
        if self._done_at:
            if self._t >= self._done_at:
                self.on_back()
            return
        # le o QR ~3x/s pra nao pesar
        if self._t - self._last_read < 0.33:
            return
        self._last_read = self._t
        try:
            data = self.camera.read_qr()
        except Exception:
            data = ""
        if not data:
            return
        wifi = parse_wifi_qr(data)
        if wifi is None:
            self._msg = "QR nao e de WiFi"
            return
        audio.play("select")
        self.net.connect_async(wifi["ssid"], wifi.get("password", ""))
        self._msg = f"Conectando a {wifi['ssid']}..."
        self._done_at = self._t + 1.2   # mostra a msg e volta pra tela de redes

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        preview = None
        try:
            preview = self.camera.get_preview()
        except Exception:
            preview = None
        if preview is not None:
            try:
                scaled = pygame.transform.smoothscale(preview, LOGICAL_SIZE)
                surface.blit(scaled, (0, 0))
            except Exception:
                pass
        else:
            msg = render_text("CAMERA OFFLINE", 12, CRT_WHITE, pixel=False)
            surface.blit(msg, msg.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2)))

        draw_crt_corners(surface, margin=SAFE_INSET)
        # moldura-alvo no centro
        box = pygame.Rect(0, 0, 120, 120)
        box.center = (LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2)
        pygame.draw.rect(surface, CRT_WHITE, box, 1)

        hint = self._msg or "APONTE PRO QR DO WIFI"
        h = render_text(hint, 9, CRT_WHITE, pixel=False)
        bg = pygame.Rect(0, 0, h.get_width() + 10, h.get_height() + 6)
        bg.midbottom = (LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 4)
        pygame.draw.rect(surface, CRT_BLACK, bg)
        surface.blit(h, h.get_rect(center=bg.center))
