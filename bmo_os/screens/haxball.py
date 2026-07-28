"""Haxball — futebol de botão top-down (você x bot / IA treinada).

Você é o disco VERMELHO (esquerda); o adversário é o AZUL (direita). Arraste seu
disco com o dedo: ele acelera na direção do toque e empurra a bola só de encostar
(colisão elástica, tipo air hockey). Faça gol no gol adversário (à direita).
Primeiro a 5 vence.

A física vive em `services/haxball_ai.py` (`HaxWorld`) — a mesma do treino de IA.
Se existir um cérebro salvo pela tela de TREINO, o adversário azul passa a ser
controlado por ELE (você joga contra a IA que treinou); senão, um bot scriptado.
"""
from __future__ import annotations

import math

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..services import audio
from ..services import haxball_ai as hai
from ..services.haxball_ai import (
    FIELD_L, FIELD_T, FIELD_W, FIELD_H, CX, CY, GOAL_H, GOAL_TOP, GOAL_BOT,
    PLR_R, PLR_ACCEL, PLR_MAXV, WIN_SCORE,
)

W, H = LOGICAL_SIZE
FIELD = pygame.Rect(FIELD_L, FIELD_T, FIELD_W, FIELD_H)

# ---------- paleta ----------
BG = (8, 14, 10)
FIELD_BG = (18, 62, 34)
LINE = (96, 156, 116)
WHITE = (240, 240, 240)
DIM = (110, 120, 130)
RED = (232, 84, 72)        # jogador (esquerda)
BLUE = (92, 152, 240)      # adversário (direita)
BALL_C = (245, 245, 245)
NET = (34, 84, 54)


class HaxballScreen:
    voice_announce = "Bola rolando!"   # BMO anuncia ao abrir (cacheado)

    def __init__(self, on_back) -> None:
        self.on_back = on_back
        # "jogar contra": se há um cérebro salvo (tela de TREINO), o azul é a IA
        # treinada, em força total. Senão, o bot scriptado (mais fraco).
        self.brain, _meta = hai.load_brain()
        self._vs_ai = self.brain is not None
        self._b_accel = PLR_ACCEL if self._vs_ai else hai.BOT_ACCEL
        self._b_maxv = PLR_MAXV if self._vs_ai else hai.BOT_MAXV
        self._opp_mem = [0.0] * hai.MEM   # memória de curto prazo da IA
        self._reset_match()

    def _reset_match(self) -> None:
        self.world = hai.HaxWorld()
        self._opp_mem = [0.0] * hai.MEM   # zera a memória da IA
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
            self._opp_mem = [0.0] * hai.MEM
            self.state = "playing"
        if self.state != "playing":
            return
        ax_a, ay_a, kick_a = self._player_input()
        ax_b, ay_b, kick_b = self._opp_input()
        goal = self.world.step(dt, ax_a, ay_a, ax_b, ay_b, kick_a, kick_b,
                               b_accel=self._b_accel, b_maxv=self._b_maxv)
        if goal == "A":
            self.world.score_a += 1; self._on_goal("VERMELHO")
        elif goal == "B":
            self.world.score_b += 1; self._on_goal("AZUL")
        else:
            self._anti_stall(dt)

    def _anti_stall(self, dt: float) -> None:
        """Se a bola fica quase parada por um tempo (encravada num canto ou
        prensada entre os discos), empurra ela de volta pro CENTRO do campo."""
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
        opp_name = "IA" if self._vs_ai else "BOT"
        if self.world.score_a >= WIN_SCORE or self.world.score_b >= WIN_SCORE:
            self.state = "over"
            self._msg = "VOCE VENCEU!" if self.world.score_a > self.world.score_b else f"{opp_name} VENCEU!"
        else:
            self.state = "goal"
            self._msg = f"GOL {who}!"
            self._resume_at = self._t + 1.3

    def _player_input(self):
        # devolve (ax, ay, chute). Enquanto você controla (arrasta/teclas), o
        # chute fica ligado: encostar na bola pelo lado de ataque já finaliza.
        keys = pygame.key.get_pressed()
        kx = keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
        ky = keys[pygame.K_DOWN] - keys[pygame.K_UP]
        if kx or ky:
            n = math.hypot(kx, ky) or 1.0
            return kx / n, ky / n, True
        if self._dragging and self._target is not None:
            a = self.world.a
            dx = self._target[0] - a.x; dy = self._target[1] - a.y
            d = math.hypot(dx, dy)
            if d > 3:
                return dx / d, dy / d, True
            return 0.0, 0.0, True
        return 0.0, 0.0, False

    def _opp_input(self):
        # adversário azul: a IA treinada (se houver) ou o jogador heurístico
        # (ataca+defende; bem mais esperto que o bot defensivo antigo)
        if self.brain is not None:
            ax, ay, kick, self._opp_mem = hai.brain_action(
                self.brain, self.world, "b", self._opp_mem)
            return ax, ay, kick
        return hai.heuristic_action(self.world, "b")

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
            hint = "voce x IA treinada" if self._vs_ai else "arraste seu disco (vermelho)"
            self._center(surface, "TOQUE PRA COMECAR", hint)
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
