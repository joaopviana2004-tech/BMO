"""Flappy — minimalista. Toque (ou A) pra bater asa e passar pelos canos.

Um único screen (player). Bate asa contra a gravidade; passou o cano, +1 ponto;
bateu, fim de jogo (toque pra recomeçar). Mesmo molde do PongScreen.
"""
from __future__ import annotations

import random

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..services import audio
from ..services import flappy_ai as fai
# física/arena: FONTE ÚNICA no serviço (mesmo mundo que o treino usa, pra o
# cérebro salvo se comportar igual quando você "joga contra")
from ..services.flappy_ai import (
    W, H, GROUND_Y, CEIL_Y, GRAVITY, FLAP_V, MAX_FALL, BIRD_X, BIRD_R,
    PIPE_W, PIPE_GAP, PIPE_SPEED, PIPE_SPACING, GAP_MARGIN,
)

# ---------- paleta ----------
BG        = (8, 10, 24)
WHITE     = (240, 240, 240)
DIM       = (110, 120, 140)
BIRD      = (250, 210, 70)    # amarelo (jogador)
BIRD_EYE  = (20, 20, 30)
AI_BIRD   = (120, 200, 255)   # azul claro (adversário IA)
PIPE      = (90, 200, 120)    # verde
PIPE_DARK = (60, 150, 90)
GROUND    = (40, 46, 64)


def _to_logical(pos: tuple[int, int]) -> tuple[int, int]:
    w, h = pygame.display.get_window_size()
    if w <= 0 or h <= 0:
        return pos
    return (pos[0] * W // w, pos[1] * H // h)


class FlappyScreen:
    def __init__(self, on_back) -> None:
        self.on_back = on_back
        # "jogar contra": se há um cérebro salvo (tela de TREINO IA), entra no
        # modo versus com um pássaro adversário controlado pela rede neural.
        self.brain, _meta = fai.load_brain()
        self.versus = self.brain is not None
        self._reset()

    def _reset(self) -> None:
        self.bird_y = H / 2
        self.vel = 0.0
        self.pipes: list[dict] = []     # {x, gap_y, scored}
        self.score = 0
        self.state = "ready"            # ready -> playing -> over
        self._t = 0.0
        # adversário IA (só ativo no modo versus)
        self.ai_y = H / 2
        self.ai_vel = 0.0
        self.ai_alive = self.versus
        self.ai_score = 0
        self._spawn_first_pipes()

    def _spawn_first_pipes(self) -> None:
        x = W + 40
        for _ in range(3):
            self.pipes.append(self._make_pipe(x))
            x += PIPE_SPACING

    def _make_pipe(self, x: float) -> dict:
        gap = fai.gap_for(self.score)   # vão afunila conforme a pontuação cresce
        gap_y = random.randint(CEIL_Y + GAP_MARGIN + gap // 2,
                               GROUND_Y - GAP_MARGIN - gap // 2)
        return {"x": float(x), "gap_y": gap_y, "gap": gap, "scored": False}

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        pos = getattr(event, "pos", None)
        if action in (bmo_input.Action.B, bmo_input.Action.MENU):
            audio.play("back")
            self.on_back()
            return
        if action == bmo_input.Action.TAP and pos is not None and self._back_btn().collidepoint(pos):
            audio.play("back")
            self.on_back()
            return
        if action in (bmo_input.Action.TAP, bmo_input.Action.A, bmo_input.Action.UP):
            self._flap()

    def _flap(self) -> None:
        if self.state == "over":
            self._reset()
            return
        if self.state == "ready":
            self.state = "playing"
        self.vel = FLAP_V
        audio.play("tick")

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        if self.state != "playing":
            return

        # --- jogador ---
        self.vel = min(MAX_FALL, self.vel + GRAVITY * dt)
        self.bird_y += self.vel * dt
        player_dead = False
        if self.bird_y >= GROUND_Y - BIRD_R:
            self.bird_y = GROUND_Y - BIRD_R
            player_dead = True
        elif self.bird_y < CEIL_Y + BIRD_R:
            self.bird_y = CEIL_Y + BIRD_R
            self.vel = 0.0

        # move canos, pontua (jogador E adversário vivo) e recicla
        speed = fai.speed_for(self.score)   # acelera conforme a pontuação cresce
        for p in self.pipes:
            p["x"] -= speed * dt
            if not p["scored"] and p["x"] + PIPE_W < BIRD_X:
                p["scored"] = True
                self.score += 1
                if self.ai_alive:
                    self.ai_score += 1
                audio.play("point")
        self.pipes = [p for p in self.pipes if p["x"] + PIPE_W > -4]
        while len(self.pipes) < 3:
            last_x = max((p["x"] for p in self.pipes), default=W)
            self.pipes.append(self._make_pipe(last_x + PIPE_SPACING))

        if not player_dead and self._hits_pipe(self.bird_y):
            player_dead = True

        # --- adversário IA (modo versus) ---
        if self.versus and self.ai_alive:
            self._step_ai(dt)

        if player_dead:
            self._die()

    def _step_ai(self, dt: float) -> None:
        p = self._next_pipe()
        gap_y = p["gap_y"] if p else H / 2
        pipe_x = p["x"] if p else float(W)
        if self.brain.flaps(fai.sense(self.ai_y, pipe_x, gap_y)):
            self.ai_vel = FLAP_V
        self.ai_vel = min(MAX_FALL, self.ai_vel + GRAVITY * dt)
        self.ai_y += self.ai_vel * dt
        if (self.ai_y >= GROUND_Y - BIRD_R or self.ai_y < CEIL_Y + BIRD_R
                or self._hits_pipe(self.ai_y)):
            self.ai_alive = False

    def _next_pipe(self) -> dict | None:
        for p in self.pipes:
            if p["x"] + PIPE_W >= BIRD_X:
                return p
        return self.pipes[0] if self.pipes else None

    def _hits_pipe(self, y: float) -> bool:
        bx0, bx1 = BIRD_X - BIRD_R, BIRD_X + BIRD_R
        by0, by1 = y - BIRD_R, y + BIRD_R
        for p in self.pipes:
            if p["x"] > bx1 or p["x"] + PIPE_W < bx0:
                continue
            half = p.get("gap", PIPE_GAP) // 2
            gap_top = p["gap_y"] - half
            gap_bot = p["gap_y"] + half
            if by0 < gap_top or by1 > gap_bot:
                return True
        return False

    def _die(self) -> None:
        if self.state != "over":
            self.state = "over"
            audio.play("fail")

    # ---------- draw ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(4, 4, 52, 16)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        # canos
        for p in self.pipes:
            x = int(p["x"])
            half = p.get("gap", PIPE_GAP) // 2
            gap_top = p["gap_y"] - half
            gap_bot = p["gap_y"] + half
            pygame.draw.rect(surface, PIPE, (x, 0, PIPE_W, gap_top))
            pygame.draw.rect(surface, PIPE, (x, gap_bot, PIPE_W, GROUND_Y - gap_bot))
            # "boca" do cano (detalhe mais escuro)
            pygame.draw.rect(surface, PIPE_DARK, (x - 2, gap_top - 6, PIPE_W + 4, 6))
            pygame.draw.rect(surface, PIPE_DARK, (x - 2, gap_bot, PIPE_W + 4, 6))
        # piso
        pygame.draw.rect(surface, GROUND, (0, GROUND_Y, W, H - GROUND_Y))
        # adversário IA atrás, jogador na frente
        if self.versus:
            self._draw_ai_bird(surface)
        self._draw_bird(surface)
        # placar: versus mostra VOCE x BMO; solo mostra o número grande
        if self.versus:
            sc = render_text(f"VOCE {self.score}", 10, BIRD)
            surface.blit(sc, sc.get_rect(midtop=(W // 2 - 46, 6)))
            ai = render_text(f"BMO {self.ai_score}", 10, AI_BIRD)
            surface.blit(ai, ai.get_rect(midtop=(W // 2 + 46, 6)))
        else:
            s = render_text(str(self.score), 18, WHITE)
            surface.blit(s, s.get_rect(midtop=(W // 2, 6)))
        self._draw_back_btn(surface)
        if self.state == "ready":
            hint = "voce x BMO" if self.versus else ""
            self._center_text(surface, "TOQUE PRA VOAR", hint)
        elif self.state == "over":
            if self.versus:
                self._center_text(surface, self._winner_text(), "toque pra jogar de novo")
            else:
                self._center_text(surface, "FIM DE JOGO", "toque pra jogar de novo")

    def _winner_text(self) -> str:
        if self.score == self.ai_score:
            return "BMO VENCEU!" if self.ai_alive else "EMPATE"
        return "VOCE VENCEU!" if self.score > self.ai_score else "BMO VENCEU!"

    def _draw_bird(self, surface) -> None:
        x, y = BIRD_X, int(self.bird_y)
        pygame.draw.rect(surface, BIRD, (x - BIRD_R, y - BIRD_R, BIRD_R * 2, BIRD_R * 2))
        pygame.draw.rect(surface, BIRD_EYE, (x + 1, y - 3, 2, 2))      # olho
        pygame.draw.rect(surface, (230, 120, 40), (x + BIRD_R, y, 3, 2))  # bico

    def _draw_ai_bird(self, surface) -> None:
        x, y = BIRD_X, int(self.ai_y)
        if self.ai_alive:
            pygame.draw.rect(surface, AI_BIRD, (x - BIRD_R, y - BIRD_R, BIRD_R * 2, BIRD_R * 2))
            pygame.draw.rect(surface, BIRD_EYE, (x + 1, y - 3, 2, 2))
        else:   # caiu: só o contorno apagado
            pygame.draw.rect(surface, DIM, (x - BIRD_R, y - BIRD_R, BIRD_R * 2, BIRD_R * 2), 1)

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

    def _center_text(self, surface, title: str, hint: str) -> None:
        dim = pygame.Surface(LOGICAL_SIZE)
        dim.fill((0, 0, 0))
        dim.set_alpha(150)
        surface.blit(dim, (0, 0))
        t = render_text(title, 14, BIRD)
        surface.blit(t, t.get_rect(center=(W // 2, H // 2 - 8)))
        if hint:
            h = render_text(hint, 9, WHITE, pixel=False)
            surface.blit(h, h.get_rect(center=(W // 2, H // 2 + 14)))
