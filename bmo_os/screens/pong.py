"""Pong — clássico de 2 paddles + bola.

Exporta dois screens:
- PongScreen: jogo player (touch) vs bot. Primeiro a 7 pontos vence.
- PongAmbientScreen: bot vs bot pra usar como tela de descanso.
"""
from __future__ import annotations

import math
import random

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import LOGICAL_SIZE, render_text

# ---------- paleta ----------
BG           = (8, 10, 24)
WHITE        = (240, 240, 240)
DIM          = (110, 120, 140)
PLAYER_COLOR = (90, 200, 220)
BOT_COLOR    = (230, 90, 90)
BALL_COLOR   = (255, 255, 255)
LINE_COLOR   = (60, 70, 90)

# ---------- arena ----------
COURT_TOP    = 24
COURT_BOTTOM = 216
CENTER_X     = LOGICAL_SIZE[0] // 2

PADDLE_W       = 4
PADDLE_H       = 40
PADDLE_HALF_H  = PADDLE_H // 2
PADDLE_LEFT_X  = 14
PADDLE_RIGHT_X = LOGICAL_SIZE[0] - 14

PADDLE_TOP    = COURT_TOP + PADDLE_HALF_H
PADDLE_BOTTOM = COURT_BOTTOM - PADDLE_HALF_H

BALL_SIZE = 6
BALL_HALF = BALL_SIZE // 2

BALL_SPEED_INIT      = 140   # px/s horizontal inicial
BALL_SPEED_MAX       = 280
BALL_SPEEDUP_PER_HIT = 1.06
MAX_BOUNCE_ANGLE     = math.radians(55)

WIN_SCORE = 7


def _to_logical(pos: tuple[int, int]) -> tuple[int, int]:
    w, h = pygame.display.get_window_size()
    if w <= 0 or h <= 0:
        return pos
    return (pos[0] * LOGICAL_SIZE[0] // w, pos[1] * LOGICAL_SIZE[1] // h)


# ---------- core física (sem UI) ----------

class _PongCore:
    def __init__(self) -> None:
        self.left_y = LOGICAL_SIZE[1] / 2
        self.right_y = LOGICAL_SIZE[1] / 2
        self.score_left = 0
        self.score_right = 0
        self._reset_ball(direction=random.choice([-1, 1]))

    def _reset_ball(self, direction: int) -> None:
        self.ball_x = float(CENTER_X)
        self.ball_y = LOGICAL_SIZE[1] / 2
        self.ball_vx = direction * BALL_SPEED_INIT
        self.ball_vy = random.uniform(-100, 100)

    def update_ball(self, dt: float) -> str | None:
        self.ball_x += self.ball_vx * dt
        self.ball_y += self.ball_vy * dt

        # paredes top/bottom
        if self.ball_y < COURT_TOP + BALL_HALF:
            self.ball_y = COURT_TOP + BALL_HALF
            self.ball_vy = abs(self.ball_vy)
        elif self.ball_y > COURT_BOTTOM - BALL_HALF:
            self.ball_y = COURT_BOTTOM - BALL_HALF
            self.ball_vy = -abs(self.ball_vy)

        # paddle esquerdo
        if (self.ball_vx < 0
                and self.ball_x - BALL_HALF <= PADDLE_LEFT_X + PADDLE_W
                and self.ball_x + BALL_HALF >= PADDLE_LEFT_X
                and abs(self.ball_y - self.left_y) < PADDLE_HALF_H + BALL_HALF):
            self._bounce('left')

        # paddle direito
        elif (self.ball_vx > 0
              and self.ball_x + BALL_HALF >= PADDLE_RIGHT_X - PADDLE_W
              and self.ball_x - BALL_HALF <= PADDLE_RIGHT_X
              and abs(self.ball_y - self.right_y) < PADDLE_HALF_H + BALL_HALF):
            self._bounce('right')

        # bola escapou pelos lados → ponto
        if self.ball_x < 0:
            self.score_right += 1
            self._reset_ball(direction=1)
            return 'point_right'
        if self.ball_x > LOGICAL_SIZE[0]:
            self.score_left += 1
            self._reset_ball(direction=-1)
            return 'point_left'
        return None

    def _bounce(self, side: str) -> None:
        paddle_y = self.left_y if side == 'left' else self.right_y
        offset = (self.ball_y - paddle_y) / PADDLE_HALF_H   # -1 a 1
        offset = max(-1.0, min(1.0, offset))
        speed = math.hypot(self.ball_vx, self.ball_vy) * BALL_SPEEDUP_PER_HIT
        speed = min(speed, BALL_SPEED_MAX)
        angle = offset * MAX_BOUNCE_ANGLE
        vx_mag = abs(speed * math.cos(angle))
        vy = speed * math.sin(angle)
        self.ball_vx = vx_mag if side == 'left' else -vx_mag
        self.ball_vy = vy
        # tira a bola de dentro do paddle pra evitar loop
        if side == 'left':
            self.ball_x = PADDLE_LEFT_X + PADDLE_W + BALL_HALF + 1
        else:
            self.ball_x = PADDLE_RIGHT_X - PADDLE_W - BALL_HALF - 1

    def move_paddle(self, side: str, target_y: float, max_speed: float, dt: float) -> None:
        attr = 'left_y' if side == 'left' else 'right_y'
        cur = getattr(self, attr)
        delta = target_y - cur
        max_d = max_speed * dt
        if abs(delta) > max_d:
            delta = max_d * (1 if delta > 0 else -1)
        new = cur + delta
        new = max(PADDLE_TOP, min(PADDLE_BOTTOM, new))
        setattr(self, attr, new)


# ---------- helpers de desenho ----------

def _draw_court(surface) -> None:
    # linha tracejada vertical
    for y in range(COURT_TOP, COURT_BOTTOM, 8):
        pygame.draw.rect(surface, LINE_COLOR, (CENTER_X - 1, y, 2, 4))
    # paredes top/bottom sutis
    pygame.draw.rect(surface, LINE_COLOR, (0, COURT_TOP - 1, LOGICAL_SIZE[0], 1))
    pygame.draw.rect(surface, LINE_COLOR, (0, COURT_BOTTOM, LOGICAL_SIZE[0], 1))


def _draw_paddle(surface, x_center: int, y_center: int, color) -> None:
    rect = pygame.Rect(x_center - PADDLE_W // 2, y_center - PADDLE_HALF_H, PADDLE_W, PADDLE_H)
    pygame.draw.rect(surface, color, rect)


def _draw_ball(surface, x: float, y: float, color=BALL_COLOR) -> None:
    pygame.draw.rect(surface, color, (int(x) - BALL_HALF, int(y) - BALL_HALF, BALL_SIZE, BALL_SIZE))


# ---------- jogo (player vs bot) ----------

class PongScreen:
    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self._reset()

    def _reset(self) -> None:
        self.core = _PongCore()
        self.target_y = LOGICAL_SIZE[1] / 2
        self._touching = False
        self.winner: str | None = None
        self._t = 0.0
        self._bot_offset = 0.0
        self._next_offset_change = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---- input ----
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == bmo_input.ACTION_EVENT:
            self._handle_action(event)
            return
        if event.type == pygame.MOUSEMOTION:
            if self._touching and pygame.mouse.get_pressed()[0]:
                self.target_y = _to_logical(event.pos)[1]
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._touching = False

    def _handle_action(self, event) -> None:
        action = event.action
        pos = getattr(event, "pos", None)
        if action in (bmo_input.Action.B, bmo_input.Action.MENU):
            self.on_back()
            return
        if action == bmo_input.Action.TAP and pos is not None:
            if self._back_btn().collidepoint(pos):
                self.on_back()
                return
            if self.winner is not None:
                self._reset()
                return
            self._touching = True
            self.target_y = pos[1]
            return
        if action == bmo_input.Action.A and self.winner is not None:
            self._reset()

    # ---- update ----
    def update(self, dt: float) -> None:
        self._t += dt
        if self.winner is not None:
            return

        # player paddle: rápido, segue dedo
        self.core.move_paddle('left', self.target_y, max_speed=420, dt=dt)

        # bot paddle: tracking imperfeito da bola
        if self._t >= self._next_offset_change:
            self._bot_offset = random.uniform(-16, 16)
            self._next_offset_change = self._t + random.uniform(0.4, 1.4)
        if self.core.ball_vx > 0:
            bot_target = self.core.ball_y + self._bot_offset
        else:
            bot_target = LOGICAL_SIZE[1] / 2     # drift pro centro
        self.core.move_paddle('right', bot_target, max_speed=180, dt=dt)

        # bola
        self.core.update_ball(dt)

        # vitória
        if self.core.score_left >= WIN_SCORE:
            self.winner = 'left'
        elif self.core.score_right >= WIN_SCORE:
            self.winner = 'right'

    # ---- draw ----
    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(4, 4, 52, 16)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        _draw_court(surface)
        # scores grandes
        s_l = render_text(str(self.core.score_left), 18, PLAYER_COLOR)
        s_r = render_text(str(self.core.score_right), 18, BOT_COLOR)
        surface.blit(s_l, s_l.get_rect(midtop=(LOGICAL_SIZE[0] // 3, 4)))
        surface.blit(s_r, s_r.get_rect(midtop=(2 * LOGICAL_SIZE[0] // 3, 4)))
        # paddles + bola
        _draw_paddle(surface, PADDLE_LEFT_X + PADDLE_W // 2, int(self.core.left_y), PLAYER_COLOR)
        _draw_paddle(surface, PADDLE_RIGHT_X - PADDLE_W // 2, int(self.core.right_y), BOT_COLOR)
        _draw_ball(surface, self.core.ball_x, self.core.ball_y)
        # back button
        self._draw_back_btn(surface)
        if self.winner:
            self._draw_winner(surface)

    def _draw_back_btn(self, surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, BG, rect)
        pygame.draw.rect(surface, WHITE, rect, 1)
        pygame.draw.polygon(surface, WHITE, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        img = render_text("HOME", 7, WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _draw_winner(self, surface) -> None:
        dim = pygame.Surface(LOGICAL_SIZE)
        dim.fill((0, 0, 0))
        dim.set_alpha(160)
        surface.blit(dim, (0, 0))
        txt = "VOCE VENCEU!" if self.winner == 'left' else "BOT VENCEU!"
        color = PLAYER_COLOR if self.winner == 'left' else BOT_COLOR
        t = render_text(txt, 14, color)
        h = render_text("toque pra jogar de novo", 9, WHITE, pixel=False)
        surface.blit(t, t.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2 - 8)))
        surface.blit(h, h.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2 + 14)))


# ---------- ambient (bot vs bot) ----------

class PongAmbientScreen:
    def __init__(self, on_open_home) -> None:
        self.on_open_home = on_open_home
        self.core = _PongCore()
        self._t = 0.0
        self._offset_l = 0.0
        self._offset_r = 0.0
        self._next_l = 0.0
        self._next_r = 0.0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        if event.action in (bmo_input.Action.TAP, bmo_input.Action.A, bmo_input.Action.MENU):
            self.on_open_home()

    def update(self, dt: float) -> None:
        self._t += dt
        # cada bot tem seu próprio erro independente
        if self._t >= self._next_l:
            self._offset_l = random.uniform(-22, 22)
            self._next_l = self._t + random.uniform(0.6, 1.6)
        if self._t >= self._next_r:
            self._offset_r = random.uniform(-22, 22)
            self._next_r = self._t + random.uniform(0.6, 1.6)

        if self.core.ball_vx < 0:
            tgt_l = self.core.ball_y + self._offset_l
        else:
            tgt_l = LOGICAL_SIZE[1] / 2
        if self.core.ball_vx > 0:
            tgt_r = self.core.ball_y + self._offset_r
        else:
            tgt_r = LOGICAL_SIZE[1] / 2

        self.core.move_paddle('left',  tgt_l, max_speed=160, dt=dt)
        self.core.move_paddle('right', tgt_r, max_speed=170, dt=dt)
        self.core.update_ball(dt)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        _draw_court(surface)
        # scores nos cantos pra liberar o centro do topo pro relógio
        s_l = render_text(str(self.core.score_left), 10, DIM, pixel=False)
        s_r = render_text(str(self.core.score_right), 10, DIM, pixel=False)
        surface.blit(s_l, s_l.get_rect(topleft=(8, 6)))
        surface.blit(s_r, s_r.get_rect(topright=(LOGICAL_SIZE[0] - 8, 6)))
        # mini-clock no topo-centro
        theme_state.draw_mini_clock(surface, LOGICAL_SIZE[0] // 2, 4, WHITE)
        # paddles iguais (não tem player aqui)
        _draw_paddle(surface, PADDLE_LEFT_X + PADDLE_W // 2, int(self.core.left_y), WHITE)
        _draw_paddle(surface, PADDLE_RIGHT_X - PADDLE_W // 2, int(self.core.right_y), WHITE)
        _draw_ball(surface, self.core.ball_x, self.core.ball_y)
