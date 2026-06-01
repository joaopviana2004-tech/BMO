"""Tela TESTE IA — diagnóstico de microfone, Whisper e câmera (estilo CRT).

- Medidor de nível do microfone em tempo real (verde/amarelo/vermelho).
- Push-to-talk: toca pra gravar a fala e transcrever com o Whisper; mostra o
  texto reconhecido (testa o Whisper sem depender do wake word).
- Câmera: tipo detectado (PI AI CAM / USB) + preview pequeno + se a
  inteligência está ativa.

Tudo degrada: sem mic/whisper/câmera mostra "indisponivel".
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
from .sysinfo import _temp_color   # mesmos limiares verde/amarelo/vermelho


def _level_color(lv: float):
    if lv >= 0.85:
        return Colors.RED
    if lv >= 0.6:
        return Colors.YELLOW
    return Colors.GREEN_BTN


class AITestScreen:
    def __init__(self, *, on_back, voice, camera, sysinfo=None, chat=None) -> None:
        self.on_back = on_back
        self.voice = voice
        self.camera = camera
        self.sysinfo = sysinfo
        self.chat = chat
        self._t = 0.0

    def enter(self) -> None:
        try:
            self._mics = self.voice.list_input_devices()
        except Exception:
            self._mics = []
        try:
            self.voice.start_monitor()
        except Exception:
            pass
        try:
            self.camera.acquire()
        except Exception:
            pass

    def exit(self) -> None:
        try:
            self.voice.stop_monitor()
        except Exception:
            pass
        try:
            self.camera.release()
        except Exception:
            pass

    def update(self, dt: float) -> None:
        self._t += dt

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        a = event.action
        pos = getattr(event, "pos", None)
        if a == bmo_input.Action.B:
            audio.play("back"); self.on_back()
        elif a == bmo_input.Action.A:
            self._ptt()
        elif a == bmo_input.Action.TAP and pos is not None:
            if self._back_btn().collidepoint(pos):
                audio.play("back"); self.on_back()
            elif self._ptt_btn().collidepoint(pos):
                self._ptt()

    def _ptt(self) -> None:
        if not getattr(self.voice, "available", False) or self.voice.busy:
            audio.play("back"); return
        audio.play("select")
        # pausa o monitor passivo (mesmo device) e grava
        self.voice.stop_monitor()
        self.voice.record_and_transcribe(on_done=self._on_transcribed)

    def _on_transcribed(self, text: str) -> None:
        # roda na thread de voz (após transcrição). Religa o monitor e manda o
        # texto pro BMO responder (chat.ask atualiza chat.last_msg, que a UI lê).
        self._restart_monitor()
        text = (text or "").strip()
        if text and self.chat is not None and self.chat.available:
            self.chat.ask(text)

    def _restart_monitor(self) -> None:
        try:
            self.voice.start_monitor()
        except Exception:
            pass

    # ---------- hitboxes ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def _ptt_btn(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] // 2 - 80, 142, 160, 22)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        self._draw_back_btn(surface)
        title = render_text("TESTE IA", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 1)))

        self._draw_temp(surface)
        self._draw_camera(surface)
        self._draw_mic(surface)
        self._draw_ptt(surface)

    def _draw_temp(self, surface) -> None:
        """Quadradinho de debug da temperatura da Pi (canto sup-direito)."""
        t = None
        if self.sysinfo is not None:
            try:
                t = self.sysinfo.get().temp_c
            except Exception:
                t = None
        color = _temp_color(t)
        sq = pygame.Rect(LOGICAL_SIZE[0] - SAFE_INSET - 12, SAFE_INSET + 1, 11, 11)
        pygame.draw.rect(surface, color, sq)
        pygame.draw.rect(surface, CRT_WHITE, sq, 1)
        txt = f"{t:.0f}C" if t is not None else "--C"
        img = render_text(txt, 9, color, pixel=False)
        surface.blit(img, img.get_rect(midright=(sq.left - 4, sq.centery)))

    def _draw_camera(self, surface) -> None:
        box = pygame.Rect(20, 38, 150, 86)
        pygame.draw.rect(surface, CRT_DIM, box, 1)
        prev = None
        try:
            prev = self.camera.get_preview()
        except Exception:
            prev = None
        if prev is not None:
            scaled = pygame.transform.scale(prev, (box.w - 2, box.h - 2))
            surface.blit(scaled, (box.x + 1, box.y + 1))
        else:
            err = getattr(self.camera, "error", "") or "sem video"
            for i, line in enumerate(self._wrap(err, 20)[:3]):
                m = render_text(line, 8, CRT_DIM, pixel=False)
                surface.blit(m, m.get_rect(center=(box.centerx, box.centery - 8 + i * 10)))
        # tipo + inteligência
        kind = getattr(self.camera, "kind_label", "--")
        intel = getattr(self.camera, "intelligence_active", False)
        surface.blit(render_text(f"CAM: {kind}", 8, CRT_WHITE, pixel=False), (box.x, box.bottom + 4))
        ic = Colors.GREEN_BTN if intel else CRT_DIM
        surface.blit(render_text(f"IA: {'ON' if intel else 'OFF'}", 8, ic, pixel=False), (box.x, box.bottom + 14))

    def _draw_mic(self, surface) -> None:
        x = 184
        surface.blit(render_text("MIC", 8, CRT_WHITE), (x, 40))
        # medidor de nível
        bar = pygame.Rect(x, 52, LOGICAL_SIZE[0] - SAFE_INSET - x, 12)
        pygame.draw.rect(surface, CRT_DIM, bar, 1)
        try:
            lv = float(self.voice.level())
        except Exception:
            lv = 0.0
        fw = int((bar.w - 2) * max(0.0, min(1.0, lv)))
        if fw > 0:
            pygame.draw.rect(surface, _level_color(lv), (bar.x + 1, bar.y + 1, fw, bar.h - 2))
        # dispositivo + status
        from ..core import config
        dev = (config.get("mic_device") or "padrao")
        dev = dev if len(dev) <= 16 else dev[:15] + "."
        n = len(getattr(self, "_mics", []))
        surface.blit(render_text(f"dev: {dev} ({n} mics)", 8, CRT_DIM, pixel=False), (x, 70))
        status = getattr(self.voice, "status", "?")
        avail = getattr(self.voice, "available", False)
        sc = CRT_WHITE if avail else Colors.RED
        surface.blit(render_text(f"whisper: {status}", 8, sc, pixel=False), (x, 82))
        ww = getattr(self.voice, "wakeword_available", False)
        listening = getattr(self.voice, "listening", False)
        det = getattr(self.voice, "wake_count", 0)
        if ww and listening:
            wc, state = Colors.GREEN_BTN, "ouvindo"
        elif ww:
            wc, state = Colors.YELLOW, "ok"
        else:
            wc, state = CRT_DIM, "off"
        from ..services.voice import WAKE_NAME
        surface.blit(render_text(f"wake {WAKE_NAME}: {state}  det:{det}", 8, wc, pixel=False), (x, 94))
        # info do ultimo audio gravado (mic mudo? capturou?)
        ai = getattr(self.voice, "last_audio", "") or "-"
        surface.blit(render_text(f"audio: {ai}", 8, CRT_DIM, pixel=False), (x, 106))

    def _draw_ptt(self, surface) -> None:
        rect = self._ptt_btn()
        busy = getattr(self.voice, "busy", False)
        avail = getattr(self.voice, "available", False)
        if busy:
            pygame.draw.rect(surface, Colors.YELLOW, rect)
            fg, txt = CRT_BLACK, getattr(self.voice, "status", "...").upper()
        elif avail:
            pygame.draw.rect(surface, CRT_WHITE, rect)
            fg, txt = CRT_BLACK, "TOCAR P/ FALAR"
        else:
            pygame.draw.rect(surface, CRT_BLACK, rect)
            pygame.draw.rect(surface, CRT_DIM, rect, 1)
            fg, txt = CRT_DIM, "MIC INDISPONIVEL"
        img = render_text(txt, 9, fg, pixel=False)
        surface.blit(img, img.get_rect(center=rect.center))

        # ---- conversa: voce -> BMO ----
        y0 = rect.bottom + 6
        heard = getattr(self.voice, "last_text", "") or "—"
        pre = render_text("voce: ", 8, CRT_DIM, pixel=False)
        surface.blit(pre, (20, y0))
        surface.blit(render_text(self._fit_line(heard, 52), 8, CRT_WHITE, pixel=False),
                     (20 + pre.get_width(), y0))

        # "BMO:" em ciano + a msg em branco (até 2 linhas)
        by = y0 + 12
        lbl = render_text("BMO: ", 9, Colors.CYAN, pixel=False)
        surface.blit(lbl, (20, by))
        bmo_msg = getattr(self.chat, "last_msg", "") if self.chat else ""
        lines = self._wrap(bmo_msg or "—", 50)[:2]
        if lines:
            surface.blit(render_text(lines[0], 9, CRT_WHITE, pixel=False),
                         (20 + lbl.get_width(), by))
        if len(lines) > 1:
            surface.blit(render_text(lines[1], 9, CRT_WHITE, pixel=False), (20, by + 11))

        # status compacto stt / llm
        stt_err = getattr(self.voice, "last_error", "")
        llm_err = getattr(self.chat, "last_error", "") if self.chat else ""
        if stt_err or llm_err:
            tag = ("stt " + stt_err) if stt_err else ("llm " + llm_err)
            color = Colors.RED
        else:
            tag = "stt ok | llm ok"
            color = Colors.GREEN_BTN
        surface.blit(render_text(self._fit_line(tag, 58), 8, color, pixel=False), (20, by + 24))

    @staticmethod
    def _fit_line(text: str, n: int) -> str:
        return text if len(text) <= n else text[: n - 1] + "."

    @staticmethod
    def _wrap(text: str, width: int) -> list:
        words, lines, cur = text.split(), [], ""
        for w in words:
            if len(cur) + len(w) + 1 <= width:
                cur = (cur + " " + w).strip()
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def _draw_back_btn(self, surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        pygame.draw.polygon(surface, CRT_WHITE, [
            (rect.left + 6, rect.centery - 3), (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery)])
        img = render_text("HOME", 8, CRT_WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))
