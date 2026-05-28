"""Modo ambient 'BMO FACE' — pet virtual procedural.

Os olhos seguem o dedo, BMO reage quando você solta (sorri, surpresa, pisca)
e de vez em quando faz uma animação sozinho (olhar pros lados, sorrir, blink).
Tudo desenhado em runtime — nada de sprite.
"""
from __future__ import annotations

import math
import random

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text

# Paleta BMO (corpo verde claro, traços bem escuros pra contraste)
BMO_GREEN = (172, 230, 167)
BMO_GREEN_DARK = (118, 178, 120)
BMO_EYE = (12, 22, 14)
BMO_WHITE = (240, 250, 235)
BMO_BLUSH = (240, 150, 160)
BMO_HINT = (90, 140, 95)

# Posições base no canvas 400x240
LEFT_EYE_BASE = (140, 100)
RIGHT_EYE_BASE = (260, 100)
EYE_R = 16
MOUTH_CENTER = (200, 160)

EYE_MAX_OFFSET = 12   # raio máximo do olhar (pra olho não sair da face)
TRACK_FACTOR = 0.07   # fator que converte distância do dedo em offset

REACTION_DURATION = 1.6
IDLE_ANIM_DURATION = 1.4
IDLE_NEXT_MIN = 4.0
IDLE_NEXT_MAX = 9.0

REACTIONS = ["HAPPY", "SURPRISED", "WINK", "HEART"]
IDLE_ANIMS = ["BLINK", "LOOK_LEFT", "LOOK_RIGHT", "LOOK_UP", "SMILE", "DOUBLE_BLINK"]


def _to_logical(pos: tuple[int, int]) -> tuple[int, int]:
    """Converte coords da janela física pro canvas lógico 400x240."""
    win_w, win_h = pygame.display.get_window_size()
    if win_w <= 0 or win_h <= 0:
        return pos
    lx = pos[0] * LOGICAL_SIZE[0] // win_w
    ly = pos[1] * LOGICAL_SIZE[1] // win_h
    return (lx, ly)


class BMOFaceScreen:
    def __init__(self, on_open_home) -> None:
        self.on_open_home = on_open_home
        self.state = "IDLE"
        self.reaction: str | None = None
        self.reaction_until = 0.0
        self.idle_anim: str | None = None
        self.idle_anim_until = 0.0
        self.next_idle_at = 0.0
        self._target_ox = 0.0
        self._target_oy = 0.0
        self._eye_ox = 0.0
        self._eye_oy = 0.0
        self._touch_pos: tuple[int, int] | None = None
        self._t = 0.0

    def enter(self) -> None:
        self._schedule_next_idle()

    def exit(self) -> None: ...

    def _schedule_next_idle(self) -> None:
        self.next_idle_at = self._t + random.uniform(IDLE_NEXT_MIN, IDLE_NEXT_MAX)

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == bmo_input.ACTION_EVENT:
            self._handle_action(event)
            return
        # Eventos raw pra detectar drag e release do dedo
        if event.type == pygame.MOUSEMOTION:
            if pygame.mouse.get_pressed()[0] and self.state == "TRACKING":
                self._touch_pos = _to_logical(event.pos)
                self._update_target_from_touch()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.state == "TRACKING":
                self._start_reaction()

    def _handle_action(self, event) -> None:
        action = event.action
        if action == bmo_input.Action.MENU or action == bmo_input.Action.B:
            self.on_open_home()
            return
        if action == bmo_input.Action.A:
            # interpreta A como "fazer carinho rápido"
            self._start_reaction(forced="HAPPY")
            return
        if action == bmo_input.Action.TAP and event.pos is not None:
            # Toque no canto sup direito = abrir home
            if self._menu_hint_rect().collidepoint(event.pos):
                self.on_open_home()
                return
            # Começa a seguir o dedo
            self._touch_pos = event.pos
            self.state = "TRACKING"
            self.reaction = None
            self.idle_anim = None
            self._update_target_from_touch()

    def _update_target_from_touch(self) -> None:
        if self._touch_pos is None:
            return
        tx, ty = self._touch_pos
        cx, cy = LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2
        ox = (tx - cx) * TRACK_FACTOR
        oy = (ty - cy) * TRACK_FACTOR
        # clamp pra olho não sair do rosto
        ox = max(-EYE_MAX_OFFSET, min(EYE_MAX_OFFSET, ox))
        oy = max(-EYE_MAX_OFFSET, min(EYE_MAX_OFFSET, oy))
        self._target_ox = ox
        self._target_oy = oy

    def _start_reaction(self, *, forced: str | None = None) -> None:
        self.reaction = forced or random.choice(REACTIONS)
        self.reaction_until = self._t + REACTION_DURATION
        self.state = "REACTING"
        self._target_ox = 0.0
        self._target_oy = 0.0

    def _start_idle_anim(self) -> None:
        self.idle_anim = random.choice(IDLE_ANIMS)
        self.idle_anim_until = self._t + IDLE_ANIM_DURATION
        self.state = "IDLE_ANIM"

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        if self.state == "REACTING" and self._t >= self.reaction_until:
            self.state = "IDLE"
            self.reaction = None
            self._schedule_next_idle()
        elif self.state == "IDLE_ANIM" and self._t >= self.idle_anim_until:
            self.state = "IDLE"
            self.idle_anim = None
            self._schedule_next_idle()
        elif self.state == "IDLE" and self._t >= self.next_idle_at:
            self._start_idle_anim()

        # alvos do olhar conforme estado
        if self.state == "IDLE_ANIM":
            if self.idle_anim == "LOOK_LEFT":
                self._target_ox, self._target_oy = -10.0, 0.0
            elif self.idle_anim == "LOOK_RIGHT":
                self._target_ox, self._target_oy = 10.0, 0.0
            elif self.idle_anim == "LOOK_UP":
                self._target_ox, self._target_oy = 0.0, -8.0
            else:
                self._target_ox, self._target_oy = 0.0, 0.0
        elif self.state == "IDLE":
            # respirar suavemente e relaxar
            self._target_ox *= 0.92
            self._target_oy *= 0.92

        # easing pros olhos
        self._eye_ox += (self._target_ox - self._eye_ox) * 0.18
        self._eye_oy += (self._target_oy - self._eye_oy) * 0.18

    # ---------- draw ----------

    def _menu_hint_rect(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] - 50, 4, 46, 16)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BMO_GREEN)
        self._draw_face_panel(surface)
        self._draw_eyes(surface)
        self._draw_mouth(surface)
        self._draw_blush(surface)
        self._draw_menu_hint(surface)

    def _draw_face_panel(self, surface: pygame.Surface) -> None:
        # leve respirar do corpo
        bob = int(math.sin(self._t * 1.3) * 1.2)
        panel = pygame.Rect(28, 30 + bob, LOGICAL_SIZE[0] - 56, LOGICAL_SIZE[1] - 60)
        pygame.draw.rect(surface, BMO_GREEN_DARK, panel, 0, border_radius=10)
        pygame.draw.rect(surface, BMO_EYE, panel, 2, border_radius=10)

    def _draw_eyes(self, surface: pygame.Surface) -> None:
        ox = int(round(self._eye_ox))
        oy = int(round(self._eye_oy))
        bob = int(math.sin(self._t * 1.3) * 1.2)
        lx, ly = LEFT_EYE_BASE[0], LEFT_EYE_BASE[1] + bob
        rx, ry = RIGHT_EYE_BASE[0], RIGHT_EYE_BASE[1] + bob

        blink_full = self.state == "IDLE_ANIM" and self.idle_anim in ("BLINK", "DOUBLE_BLINK")
        wink_right = self.state == "REACTING" and self.reaction == "WINK"
        surprised = self.state == "REACTING" and self.reaction == "SURPRISED"
        happy = self.state == "REACTING" and self.reaction in ("HAPPY", "HEART")

        r = EYE_R + (4 if surprised else 0)

        # piscada dupla = pisca, abre, pisca de novo
        if self.idle_anim == "DOUBLE_BLINK":
            phase = (self.idle_anim_until - self._t) / IDLE_ANIM_DURATION
            blink_full = (phase > 0.7) or (phase < 0.3 and phase > 0.1)

        self._draw_one_eye(surface, lx + ox, ly + oy, r, closed=blink_full, happy=happy, hearts=(self.reaction == "HEART"))
        self._draw_one_eye(surface, rx + ox, ry + oy, r, closed=blink_full or wink_right, happy=happy, hearts=(self.reaction == "HEART"))

    def _draw_one_eye(self, surface, cx: int, cy: int, r: int, *, closed: bool, happy: bool, hearts: bool) -> None:
        if closed:
            pygame.draw.line(surface, BMO_EYE, (cx - r, cy), (cx + r, cy), 4)
            return
        if happy:
            # arco "^" sorrindo
            rect = pygame.Rect(cx - r, cy - r // 2, r * 2, r)
            pygame.draw.arc(surface, BMO_EYE, rect, 0, math.pi, 4)
            return
        if hearts:
            self._draw_heart(surface, cx, cy, r)
            return
        # olho normal: círculo escuro + reflexo branco
        pygame.draw.circle(surface, BMO_EYE, (cx, cy), r)
        pygame.draw.circle(surface, BMO_WHITE, (cx + r // 3, cy - r // 3), max(2, r // 4))

    def _draw_heart(self, surface, cx: int, cy: int, r: int) -> None:
        # dois círculos + triângulo abaixo, em rosa
        rr = max(3, r // 2)
        pygame.draw.circle(surface, BMO_BLUSH, (cx - rr // 2, cy - rr // 2), rr)
        pygame.draw.circle(surface, BMO_BLUSH, (cx + rr // 2, cy - rr // 2), rr)
        pts = [(cx - rr, cy), (cx + rr, cy), (cx, cy + rr + 2)]
        pygame.draw.polygon(surface, BMO_BLUSH, pts)

    def _draw_mouth(self, surface: pygame.Surface) -> None:
        cx, cy = MOUTH_CENTER
        bob = int(math.sin(self._t * 1.3) * 1.2)
        cy += bob

        smile = (
            (self.state == "REACTING" and self.reaction in ("HAPPY", "WINK", "HEART"))
            or (self.state == "IDLE_ANIM" and self.idle_anim == "SMILE")
        )
        surprised = self.state == "REACTING" and self.reaction == "SURPRISED"

        if surprised:
            pygame.draw.circle(surface, BMO_GREEN, (cx, cy), 12)
            pygame.draw.circle(surface, BMO_EYE, (cx, cy), 12, 3)
        elif smile:
            rect = pygame.Rect(cx - 22, cy - 10, 44, 20)
            pygame.draw.arc(surface, BMO_EYE, rect, math.pi, 2 * math.pi, 4)
            # cantinho da boca pra cima
            pygame.draw.line(surface, BMO_EYE, (cx - 22, cy), (cx - 18, cy - 4), 3)
            pygame.draw.line(surface, BMO_EYE, (cx + 22, cy), (cx + 18, cy - 4), 3)
        elif self.state == "TRACKING":
            # boquinha curiosa
            pygame.draw.line(surface, BMO_EYE, (cx - 6, cy + 2), (cx + 6, cy + 2), 3)
            pygame.draw.line(surface, BMO_EYE, (cx - 6, cy + 2), (cx - 9, cy - 1), 3)
            pygame.draw.line(surface, BMO_EYE, (cx + 6, cy + 2), (cx + 9, cy - 1), 3)
        else:
            pygame.draw.line(surface, BMO_EYE, (cx - 14, cy), (cx + 14, cy), 4)

    def _draw_blush(self, surface: pygame.Surface) -> None:
        if not (self.state == "REACTING" and self.reaction in ("HAPPY", "HEART", "WINK")):
            return
        bob = int(math.sin(self._t * 1.3) * 1.2)
        for cx in (88, 312):
            cy = 140 + bob
            for i in range(3):
                pygame.draw.line(surface, BMO_BLUSH, (cx - 6 + i * 5, cy), (cx - 6 + i * 5 + 3, cy), 2)

    def _draw_menu_hint(self, surface: pygame.Surface) -> None:
        rect = self._menu_hint_rect()
        img = render_text("MENU", 7, BMO_HINT)
        surface.blit(img, img.get_rect(center=rect.center))
