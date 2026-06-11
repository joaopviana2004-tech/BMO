"""Haxball — futebol de botão top-down (você x bot).

Você é o disco VERMELHO (esquerda); o bot é o AZUL (direita). Arraste seu disco
com o dedo: ele acelera na direção do toque e empurra a bola só de encostar
(física de colisão elástica, tipo air hockey / futebol de botão). Faça gol no
gol adversário (à direita). Primeiro a 5 vence.

A física vive numa classe `HaxWorld` SEM pygame — pensada pra ser reaproveitada
pela tela de treino de IA (dois jogadores controlados por redes neurais).
"""
from __future__ import annotations

import math
import random

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..services import audio

W, H = LOGICAL_SIZE

# ---------- campo ----------
FIELD = pygame.Rect(12, 26, 376, 200)        # área de jogo (right=388, bottom=226)
CX, CY = FIELD.centerx, FIELD.centery
GOAL_H = 60
GOAL_TOP = CY - GOAL_H // 2
GOAL_BOT = CY + GOAL_H // 2
LEFT_GOAL = (FIELD.left, CY)
RIGHT_GOAL = (FIELD.right, CY)

# ---------- física ----------
BALL_R, BALL_MASS, BALL_FRIC, BALL_MAXV = 4.0, 1.0, 0.4, 420.0
PLR_R, PLR_MASS, PLR_FRIC, PLR_MAXV = 9.0, 4.0, 5.0, 122.0
PLR_ACCEL = 920.0
BOT_ACCEL, BOT_MAXV = 600.0, 92.0            # bot nitidamente mais lento (dá pra ganhar);
                                             # é placeholder até o treino de IA o substituir
WALL_REST = 0.7                              # quique nas paredes
DISC_REST = 0.55                             # quique disco-disco
WIN_SCORE = 5

# ---------- paleta ----------
BG = (8, 14, 10)
FIELD_BG = (18, 62, 34)
LINE = (96, 156, 116)
WHITE = (240, 240, 240)
DIM = (110, 120, 130)
RED = (232, 84, 72)        # jogador (esquerda)
BLUE = (92, 152, 240)      # bot (direita)
BALL_C = (245, 245, 245)
NET = (34, 84, 54)


class Disc:
    __slots__ = ("x", "y", "vx", "vy", "r", "inv_mass", "fric")

    def __init__(self, x, y, r, mass, fric):
        self.x = float(x); self.y = float(y)
        self.vx = 0.0; self.vy = 0.0
        self.r = r
        self.inv_mass = 0.0 if mass <= 0 else 1.0 / mass
        self.fric = fric


class HaxWorld:
    """Física do haxball: bola + 2 discos (a=esquerda, b=direita). `step()` recebe
    a aceleração desejada de cada jogador (ax, ay em [-1,1]) e devolve 'A'/'B'/None
    se saiu gol. Sem pygame — reaproveitável no treino de IA."""

    def __init__(self) -> None:
        self.score_a = 0
        self.score_b = 0
        self.kickoff()

    def kickoff(self) -> None:
        self.ball = Disc(CX, CY, BALL_R, BALL_MASS, BALL_FRIC)
        self.a = Disc(FIELD.left + 48, CY, PLR_R, PLR_MASS, PLR_FRIC)
        self.b = Disc(FIELD.right - 48, CY, PLR_R, PLR_MASS, PLR_FRIC)

    def step(self, dt, ax_a, ay_a, ax_b, ay_b,
             a_accel=PLR_ACCEL, a_maxv=PLR_MAXV,
             b_accel=BOT_ACCEL, b_maxv=BOT_MAXV):
        self._control(self.a, ax_a, ay_a, a_accel, a_maxv, dt)
        self._control(self.b, ax_b, ay_b, b_accel, b_maxv, dt)
        for d in (self.a, self.b, self.ball):
            f = max(0.0, 1.0 - d.fric * dt)
            d.vx *= f; d.vy *= f
            d.x += d.vx * dt; d.y += d.vy * dt
        self._clamp_speed(self.ball, BALL_MAXV)   # evita a bola atravessar discos/paredes
        self._collide(self.a, self.ball)
        self._collide(self.b, self.ball)
        self._collide(self.a, self.b)
        self._walls(self.a, ball=False)
        self._walls(self.b, ball=False)
        return self._walls(self.ball, ball=True)

    @staticmethod
    def _control(d, ax, ay, accel, maxv, dt):
        d.vx += ax * accel * dt
        d.vy += ay * accel * dt
        HaxWorld._clamp_speed(d, maxv)

    @staticmethod
    def _clamp_speed(d, maxv):
        sp = math.hypot(d.vx, d.vy)
        if sp > maxv:
            k = maxv / sp
            d.vx *= k; d.vy *= k

    @staticmethod
    def _collide(a, b):
        dx = b.x - a.x; dy = b.y - a.y
        dist = math.hypot(dx, dy)
        rsum = a.r + b.r
        if dist >= rsum:
            return
        inv = a.inv_mass + b.inv_mass
        if inv == 0:
            return
        if dist < 1e-6:
            dx, dy, dist = 1.0, 0.0, 1.0
        nx, ny = dx / dist, dy / dist
        # separa (corrige a sobreposição, proporcional ao inverso da massa)
        overlap = rsum - dist
        a.x -= nx * overlap * (a.inv_mass / inv)
        a.y -= ny * overlap * (a.inv_mass / inv)
        b.x += nx * overlap * (b.inv_mass / inv)
        b.y += ny * overlap * (b.inv_mass / inv)
        # impulso elástico (só se estão se aproximando)
        vn = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny
        if vn < 0:
            j = -(1.0 + DISC_REST) * vn / inv
            a.vx -= j * nx * a.inv_mass; a.vy -= j * ny * a.inv_mass
            b.vx += j * nx * b.inv_mass; b.vy += j * ny * b.inv_mass

    @staticmethod
    def _walls(d, ball):
        # topo / base — sempre sólidos
        if d.y - d.r < FIELD.top:
            d.y = FIELD.top + d.r; d.vy = abs(d.vy) * WALL_REST
        elif d.y + d.r > FIELD.bottom:
            d.y = FIELD.bottom - d.r; d.vy = -abs(d.vy) * WALL_REST
        in_goal = ball and GOAL_TOP < d.y < GOAL_BOT
        # esquerda
        if d.x - d.r < FIELD.left:
            if in_goal:
                if d.x < FIELD.left - 2:
                    return "B"        # bola no gol da esquerda -> ponto do AZUL
            else:
                d.x = FIELD.left + d.r; d.vx = abs(d.vx) * WALL_REST
        # direita
        if d.x + d.r > FIELD.right:
            if in_goal:
                if d.x > FIELD.right + 2:
                    return "A"        # bola no gol da direita -> ponto do VERMELHO
            else:
                d.x = FIELD.right - d.r; d.vx = -abs(d.vx) * WALL_REST
        return None


class HaxballScreen:
    voice_announce = "Bola rolando!"   # BMO anuncia ao abrir (cacheado)

    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self._reset_match()

    def _reset_match(self) -> None:
        self.world = HaxWorld()
        self.state = "ready"           # ready -> playing -> goal -> over
        self._t = 0.0
        self._resume_at = 0.0
        self._msg = ""
        self._target = None            # ponto que o dedo está puxando (logical)
        self._dragging = False
        self._stall = 0.0              # tempo com a bola quase parada (anti-trava)

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- input ----------

    def _to_logical(self, pos):
        win = pygame.display.get_window_size()
        if win[0] <= 0 or win[1] <= 0:
            return pos
        return (pos[0] * W // win[0], pos[1] * H // win[1])

    def handle_event(self, event: pygame.event.Event) -> None:
        et = event.type
        if et == bmo_input.ACTION_EVENT:
            a = event.action
            if a in (bmo_input.Action.B, bmo_input.Action.MENU):
                audio.play("back"); self.on_back(); return
            if a == bmo_input.Action.TAP:
                pos = getattr(event, "pos", None)
                if pos is not None and self._back_btn().collidepoint(pos):
                    audio.play("back"); self.on_back(); return
                self._tap_to_play()
            return
        if et == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 1) == 1:
            self._dragging = True
            self._target = self._to_logical(event.pos)
        elif et == pygame.MOUSEMOTION and self._dragging:
            self._target = self._to_logical(event.pos)
        elif et == pygame.MOUSEBUTTONUP and getattr(event, "button", 1) == 1:
            self._dragging = False

    def _tap_to_play(self) -> None:
        if self.state == "over":
            self._reset_match()
            self.state = "playing"
            audio.play("select")
        elif self.state == "ready":
            self.state = "playing"
            audio.play("select")

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        if self.state == "goal" and self._t >= self._resume_at:
            self.world.kickoff()
            self.state = "playing"
        if self.state != "playing":
            return
        ax_a, ay_a = self._player_input()
        ax_b, ay_b = self._bot_input()
        goal = self.world.step(dt, ax_a, ay_a, ax_b, ay_b)
        if goal == "A":
            self.world.score_a += 1; self._on_goal("VERMELHO")
        elif goal == "B":
            self.world.score_b += 1; self._on_goal("AZUL")
        else:
            self._anti_stall(dt)

    def _anti_stall(self, dt: float) -> None:
        """Se a bola fica quase parada por um tempo (encravada num canto ou
        prensada entre os discos), empurra ela de volta pro CENTRO do campo —
        solta de qualquer canto, sem favorecer ninguém."""
        ball = self.world.ball
        if math.hypot(ball.vx, ball.vy) < 16:
            self._stall += dt
        else:
            self._stall = 0.0
        if self._stall > 2.0:
            dx, dy = CX - ball.x, CY - ball.y
            d = math.hypot(dx, dy) or 1.0
            ball.vx = dx / d * 170.0
            ball.vy = dy / d * 170.0
            self._stall = 0.0

    def _on_goal(self, who: str) -> None:
        audio.play("point")
        if self.world.score_a >= WIN_SCORE or self.world.score_b >= WIN_SCORE:
            self.state = "over"
            self._msg = "VOCE VENCEU!" if self.world.score_a > self.world.score_b else "BOT VENCEU!"
        else:
            self.state = "goal"
            self._msg = f"GOL {who}!"
            self._resume_at = self._t + 1.3

    def _player_input(self):
        # teclado (dev): setas movem o disco vermelho
        keys = pygame.key.get_pressed()
        kx = keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
        ky = keys[pygame.K_DOWN] - keys[pygame.K_UP]
        if kx or ky:
            n = math.hypot(kx, ky) or 1.0
            return kx / n, ky / n
        # toque: acelera na direção do dedo
        if self._dragging and self._target is not None:
            a = self.world.a
            dx = self._target[0] - a.x; dy = self._target[1] - a.y
            d = math.hypot(dx, dy)
            if d > 3:
                return dx / d, dy / d
        return 0.0, 0.0

    def _bot_input(self):
        b = self.world.b; ball = self.world.ball
        if ball.x < CX - 24:
            # bola no campo do jogador: recua e fica de guarda na boca do gol
            tx = FIELD.right - 42
            ty = max(GOAL_TOP + 4, min(GOAL_BOT - 4, ball.y))
        else:
            # bola no seu campo: pressiona o lado direito da bola pra empurrá-la
            # pro gol da ESQUERDA (um tico além do contato).
            dgx, dgy = ball.x - LEFT_GOAL[0], ball.y - LEFT_GOAL[1]
            dg = math.hypot(dgx, dgy) or 1.0
            tx = ball.x + dgx / dg * (PLR_R + BALL_R - 2)
            ty = ball.y + dgy / dg * (PLR_R + BALL_R - 2)
        tx = max(FIELD.left + PLR_R, min(FIELD.right - PLR_R, tx))
        ty = max(FIELD.top + PLR_R, min(FIELD.bottom - PLR_R, ty))
        dx, dy = tx - b.x, ty - b.y
        d = math.hypot(dx, dy)
        if d > 2:
            return dx / d, dy / d
        return 0.0, 0.0

    # ---------- draw ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(4, 4, 52, 16)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        pygame.draw.rect(surface, FIELD_BG, FIELD)
        # gols (rede + caixa) atrás da linha
        self._draw_goal(surface, pygame.Rect(FIELD.left - 7, GOAL_TOP, 7, GOAL_H))
        self._draw_goal(surface, pygame.Rect(FIELD.right, GOAL_TOP, 7, GOAL_H))
        # linhas do campo
        pygame.draw.rect(surface, LINE, FIELD, 1)
        pygame.draw.line(surface, LINE, (CX, FIELD.top), (CX, FIELD.bottom), 1)
        pygame.draw.circle(surface, LINE, (CX, CY), 26, 1)
        pygame.draw.circle(surface, LINE, (CX, CY), 2)
        # postes do gol (marcadores)
        for gx in (FIELD.left, FIELD.right):
            for gy in (GOAL_TOP, GOAL_BOT):
                pygame.draw.rect(surface, WHITE, (gx - 1, gy - 1, 2, 2))
        # discos + bola
        w = self.world
        self._disc(surface, w.b, BLUE)
        self._disc(surface, w.a, RED)
        pygame.draw.circle(surface, BALL_C, (int(w.ball.x), int(w.ball.y)), int(w.ball.r))
        pygame.draw.circle(surface, (0, 0, 0), (int(w.ball.x), int(w.ball.y)), int(w.ball.r), 1)
        # placar
        sc = render_text(f"{w.score_a}  {w.score_b}", 16, WHITE)
        surface.blit(sc, sc.get_rect(midtop=(CX, 4)))
        self._draw_back_btn(surface)
        # mensagens de estado
        if self.state == "ready":
            self._center(surface, "TOQUE PRA COMECAR", "arraste seu disco (vermelho)")
        elif self.state == "goal":
            self._center(surface, self._msg, "")
        elif self.state == "over":
            self._center(surface, self._msg, "toque pra jogar de novo")

    def _disc(self, surface, d, color):
        pygame.draw.circle(surface, color, (int(d.x), int(d.y)), int(d.r))
        pygame.draw.circle(surface, (0, 0, 0), (int(d.x), int(d.y)), int(d.r), 1)

    def _draw_goal(self, surface, rect):
        pygame.draw.rect(surface, NET, rect)
        for gx in range(rect.left, rect.right, 3):
            pygame.draw.line(surface, LINE, (gx, rect.top), (gx, rect.bottom), 1)

    def _draw_back_btn(self, surface):
        rect = self._back_btn()
        pygame.draw.rect(surface, BG, rect)
        pygame.draw.rect(surface, WHITE, rect, 1)
        pygame.draw.polygon(surface, WHITE, [
            (rect.left + 6, rect.centery - 3), (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery)])
        img = render_text("HOME", 7, WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _center(self, surface, title, hint):
        dim = pygame.Surface(LOGICAL_SIZE)
        dim.fill((0, 0, 0)); dim.set_alpha(150)
        surface.blit(dim, (0, 0))
        t = render_text(title, 14, BALL_C)
        surface.blit(t, t.get_rect(center=(W // 2, H // 2 - 8)))
        if hint:
            h = render_text(hint, 9, WHITE, pixel=False)
            surface.blit(h, h.get_rect(center=(W // 2, H // 2 + 14)))
