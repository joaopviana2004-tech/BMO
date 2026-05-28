"""Modo ambient 'BMO FACE' — pet virtual procedural.

Inspirado nas faces do projeto be-more-agent: traços limpos pretos sobre
fundo verde pastel, sem painel/borda. Expressões alternam entre idle,
tracking (segue o dedo), reações (happy/surprised/wink/speak) e animações
espontâneas (blink, look around, think, sleepy). Tudo desenhado em runtime.
"""
from __future__ import annotations

import math
import random

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import LOGICAL_SIZE, render_text

# Paleta inspirada nas referências
BMO_GREEN      = (186, 247, 200)   # fundo
BMO_GREEN_DEEP = (55, 130, 80)     # interior da boca aberta
BLACK          = (15, 22, 18)
WHITE          = (245, 252, 245)
HINT           = (110, 170, 130)

# Geometria base (canvas 400x240) — proporções batidas com a referência
LEFT_EYE  = (130, 100)
RIGHT_EYE = (270, 100)
MOUTH     = (200, 148)
EYE_R     = 9
STROKE    = 3

REACTIONS = ["HAPPY", "SURPRISED", "WINK_LEFT", "WINK_RIGHT", "SPEAK"]
IDLE_ANIMS = [
    "BLINK", "DOUBLE_BLINK",
    "LOOK_LEFT", "LOOK_RIGHT", "LOOK_UP",
    "SMILE", "THINK", "SPEAK",
]

REACTION_DURATION   = 1.6
IDLE_ANIM_DURATION  = 1.5
IDLE_NEXT_MIN       = 3.5
IDLE_NEXT_MAX       = 8.0

EYE_MAX_OFFSET = 10
TRACK_FACTOR   = 0.06


def _to_logical(pos: tuple[int, int]) -> tuple[int, int]:
    """Converte coords da janela física pro canvas lógico 400x240."""
    w, h = pygame.display.get_window_size()
    if w <= 0 or h <= 0:
        return pos
    return (pos[0] * LOGICAL_SIZE[0] // w, pos[1] * LOGICAL_SIZE[1] // h)


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
        # raw events pra detectar drag e release do dedo
        if event.type == pygame.MOUSEMOTION:
            if pygame.mouse.get_pressed()[0] and self.state == "TRACKING":
                self._touch_pos = _to_logical(event.pos)
                self._update_target_from_touch()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.state == "TRACKING":
                self._start_reaction()

    def _handle_action(self, event) -> None:
        action = event.action
        if action in (bmo_input.Action.MENU, bmo_input.Action.B):
            self.on_open_home()
            return
        if action == bmo_input.Action.A:
            self._start_reaction(forced="HAPPY")
            return
        if action == bmo_input.Action.TAP and event.pos is not None:
            if self._menu_hint_rect().collidepoint(event.pos):
                self.on_open_home()
                return
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
        self._target_ox = max(-EYE_MAX_OFFSET, min(EYE_MAX_OFFSET, ox))
        self._target_oy = max(-EYE_MAX_OFFSET, min(EYE_MAX_OFFSET, oy))

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

        # alvo do olhar conforme estado
        if self.state == "IDLE_ANIM":
            if self.idle_anim == "LOOK_LEFT":
                self._target_ox, self._target_oy = -8.0, 0.0
            elif self.idle_anim == "LOOK_RIGHT":
                self._target_ox, self._target_oy = 8.0, 0.0
            elif self.idle_anim == "LOOK_UP":
                self._target_ox, self._target_oy = 0.0, -6.0
            else:
                self._target_ox *= 0.85
                self._target_oy *= 0.85
        elif self.state == "IDLE":
            self._target_ox *= 0.9
            self._target_oy *= 0.9

        # easing pros olhos
        self._eye_ox += (self._target_ox - self._eye_ox) * 0.18
        self._eye_oy += (self._target_oy - self._eye_oy) * 0.18

    # ---------- expression ----------

    def _current_expression(self) -> tuple[str, str, str | None]:
        """Retorna (eye_style, mouth_style, eyebrow) p/ o estado atual."""
        if self.state == "REACTING":
            r = self.reaction
            if r == "HAPPY":      return ("V_HAPPY", "SMILE", None)
            if r == "SURPRISED":  return ("BIG", "O_OPEN", None)
            if r == "WINK_LEFT":  return ("WINK_LEFT", "SMILE", None)
            if r == "WINK_RIGHT": return ("WINK_RIGHT", "SMILE", None)
            if r == "SPEAK":      return ("DOT", self._speak_frame(), None)
        if self.state == "TRACKING":
            return ("DOT", "SMILE", None)
        if self.state == "IDLE_ANIM":
            a = self.idle_anim
            if a == "BLINK":        return ("LINE", "DASH", None)
            if a == "DOUBLE_BLINK": return (self._double_blink_eye(), "DASH", None)
            if a in ("LOOK_LEFT", "LOOK_RIGHT", "LOOK_UP"):
                return ("DOT", "DASH", None)
            if a == "SMILE":        return ("DOT", "SMILE", None)
            if a == "THINK":        return ("DOT", "SMILE", "FLAT")
            if a == "SPEAK":        return ("DOT", self._speak_frame(), None)
        # IDLE default — referência: olhos preto-bolinha + sorrisinho em U
        return ("DOT", "SMILE", None)

    def _speak_frame(self) -> str:
        # cicla 3 bocas de fala a ~6Hz
        frame = int(self._t * 6) % 3
        return ["SPEAK_SMALL", "SPEAK_BIG", "SPEAK_MED"][frame]

    def _double_blink_eye(self) -> str:
        # 3 fases: fecha / abre / fecha
        elapsed = IDLE_ANIM_DURATION - (self.idle_anim_until - self._t)
        phase = elapsed / IDLE_ANIM_DURATION
        if phase < 0.28 or (0.5 < phase < 0.78):
            return "LINE"
        return "DOT"

    # ---------- draw ----------

    def _menu_hint_rect(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] - 48, 4, 44, 14)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BMO_GREEN)
        eye_style, mouth_style, eyebrow = self._current_expression()
        bob = int(math.sin(self._t * 1.5) * 1.2)
        self._draw_eyes(surface, eye_style, bob, eyebrow)
        self._draw_mouth(surface, mouth_style, bob)
        # mini-clock no topo-centro (cor que combina com o verde)
        theme_state.draw_mini_clock(surface, LOGICAL_SIZE[0] // 2, 4, HINT)
        self._draw_menu_hint(surface)

    def _draw_eyes(self, surface: pygame.Surface, style: str, bob: int, eyebrow: str | None) -> None:
        ox = int(round(self._eye_ox))
        oy = int(round(self._eye_oy))
        # com sobrancelha baixinha, abaixa um pouquinho o olho pra parecer "olhando de canto"
        eye_drop = 3 if eyebrow == "FLAT" else 0

        lx, ly = LEFT_EYE[0], LEFT_EYE[1] + bob + eye_drop
        rx, ry = RIGHT_EYE[0], RIGHT_EYE[1] + bob + eye_drop

        if style == "U_CLOSED":
            # arcos em "u" — eyes resting / sleepy (referência idle)
            r = EYE_R
            for cx, cy in ((lx, ly), (rx, ry)):
                rect = pygame.Rect(cx - r, cy - r // 2, r * 2, r + 2)
                pygame.draw.arc(surface, BLACK, rect, math.pi, 2 * math.pi, STROKE)
        elif style == "LINE":
            # piscada — linha horizontal
            for cx, cy in ((lx, ly), (rx, ry)):
                pygame.draw.line(surface, BLACK, (cx - EYE_R, cy), (cx + EYE_R, cy), STROKE)
        elif style == "V_HAPPY":
            # ^^ — arcos pra baixo (referência listen 02)
            r = EYE_R + 1
            for cx, cy in ((lx, ly), (rx, ry)):
                rect = pygame.Rect(cx - r, cy - r // 2, r * 2, r)
                pygame.draw.arc(surface, BLACK, rect, 0, math.pi, STROKE)
        elif style == "BIG":
            # olhos enormes anime — referência capturing
            R = 24
            for cx, cy in ((lx + ox, ly + oy), (rx + ox, ry + oy)):
                pygame.draw.circle(surface, BLACK, (cx, cy), R)
                # reflexo grande no canto sup esq
                hl = pygame.Rect(cx - R + 4, cy - R + 4, 17, 13)
                pygame.draw.ellipse(surface, WHITE, hl)
                # reflexo pequeno no canto inf dir
                pygame.draw.circle(surface, WHITE, (cx + 5, cy + 7), 4)
        elif style == "WINK_LEFT":
            # esquerdo fechado, direito normal
            pygame.draw.line(surface, BLACK, (lx - EYE_R, ly), (lx + EYE_R, ly), STROKE)
            pygame.draw.circle(surface, BLACK, (rx + ox, ry + oy), EYE_R)
        elif style == "WINK_RIGHT":
            pygame.draw.circle(surface, BLACK, (lx + ox, ly + oy), EYE_R)
            pygame.draw.line(surface, BLACK, (rx - EYE_R, ry), (rx + EYE_R, ry), STROKE)
        else:  # DOT — normal (referência listen 01 / speaking)
            for cx, cy in ((lx + ox, ly + oy), (rx + ox, ry + oy)):
                pygame.draw.circle(surface, BLACK, (cx, cy), EYE_R)

        if eyebrow == "FLAT":
            # barra horizontal acima do olho — referência thinking
            for cx, cy in ((lx + ox, ly + oy), (rx + ox, ry + oy)):
                br = pygame.Rect(cx - EYE_R - 3, cy - EYE_R - 5, EYE_R * 2 + 6, 3)
                pygame.draw.rect(surface, BLACK, br, border_radius=2)

    def _draw_mouth(self, surface: pygame.Surface, style: str, bob: int) -> None:
        cx, cy = MOUTH[0], MOUTH[1] + bob

        if style == "DASH":
            # tracinho horizontal — referência idle / thinking 03
            pygame.draw.line(surface, BLACK, (cx - 16, cy), (cx + 16, cy), STROKE + 1)
        elif style == "SMILE":
            # sorrisinho fino em U — proporções da referência (90w x 32d em 400x240)
            rect = pygame.Rect(cx - 40, cy - 26, 80, 52)
            pygame.draw.arc(surface, BLACK, rect, math.pi, 2 * math.pi, STROKE)
        elif style == "O_OPEN":
            # boca surpresa redonda — referência capturing
            pygame.draw.circle(surface, BMO_GREEN_DEEP, (cx, cy), 12)
            pygame.draw.circle(surface, BLACK, (cx, cy), 12, STROKE)
        elif style == "SPEAK_SMALL":
            # boquinha quase fechada — referência speaking 01
            rect = pygame.Rect(cx - 18, cy - 6, 36, 12)
            pygame.draw.rect(surface, BMO_GREEN_DEEP, rect, border_radius=6)
            pygame.draw.rect(surface, BLACK, rect, STROKE, border_radius=6)
            pygame.draw.line(surface, WHITE, (cx - 12, cy - 1), (cx + 12, cy - 1), 2)
        elif style == "SPEAK_MED":
            # boca média aberta — referência speaking 03
            rect = pygame.Rect(cx - 22, cy - 9, 44, 18)
            pygame.draw.rect(surface, BMO_GREEN_DEEP, rect, border_radius=8)
            pygame.draw.rect(surface, BLACK, rect, STROKE, border_radius=8)
            pygame.draw.line(surface, WHITE, (cx - 14, cy - 3), (cx + 14, cy - 3), 2)
        elif style == "SPEAK_BIG":
            # boca bem aberta com dentes — referência speaking 02
            rect = pygame.Rect(cx - 26, cy - 12, 52, 26)
            pygame.draw.ellipse(surface, BMO_GREEN_DEEP, rect)
            pygame.draw.ellipse(surface, BLACK, rect, STROKE)
            pygame.draw.rect(surface, WHITE, (cx - 20, cy - 9, 40, 5), border_radius=2)
            pygame.draw.line(surface, BLACK, (cx - 20, cy - 4), (cx + 20, cy - 4), 1)

    def _draw_menu_hint(self, surface: pygame.Surface) -> None:
        rect = self._menu_hint_rect()
        img = render_text("MENU", 7, HINT)
        surface.blit(img, img.get_rect(center=rect.center))
