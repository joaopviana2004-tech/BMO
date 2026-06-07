"""Snake — minimalista. Setas/botões OU toque pra virar; coma e cresça.

Um único screen (player). Movimento em grade com passo de tempo fixo. Bater na
parede ou no próprio corpo = fim de jogo (toque pra recomeçar). No touch, o
toque vira a cobra na direção do toque em relação à cabeça.
"""
from __future__ import annotations

import random

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..services import audio

# ---------- paleta ----------
BG          = (8, 10, 24)
WHITE       = (240, 240, 240)
DIM         = (110, 120, 140)
SNAKE       = (120, 220, 130)
SNAKE_HEAD  = (180, 250, 180)
FOOD        = (240, 110, 110)
GRID_LINE   = (20, 24, 40)

# ---------- grade ----------
W, H      = LOGICAL_SIZE
CELL      = 10
TOP_BAR   = 18                          # faixa do score
FIELD_X   = 0
FIELD_Y   = TOP_BAR
COLS      = W // CELL
ROWS      = (H - TOP_BAR) // CELL

STEP_S        = 0.13                     # tempo entre passos (velocidade base)
STEP_MIN      = 0.07                      # passo mínimo (cobra grande = mais rápida)
SPEEDUP_EVERY = 4                         # acelera a cada N comidas


def _to_logical(pos: tuple[int, int]) -> tuple[int, int]:
    w, h = pygame.display.get_window_size()
    if w <= 0 or h <= 0:
        return pos
    return (pos[0] * W // w, pos[1] * H // h)


class SnakeScreen:
    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self._reset()

    def _reset(self) -> None:
        cx, cy = COLS // 2, ROWS // 2
        self.snake: list[tuple[int, int]] = [(cx - 1, cy), (cx, cy), (cx + 1, cy)]
        self.dir = (1, 0)               # indo pra direita
        self._next_dir = (1, 0)
        self.food = self._spawn_food()
        self.score = 0
        self.state = "ready"            # ready -> playing -> over
        self._acc = 0.0
        self._step = STEP_S

    def _spawn_food(self) -> tuple[int, int]:
        free = [(c, r) for c in range(COLS) for r in range(ROWS)
                if (c, r) not in self.snake]
        return random.choice(free) if free else (0, 0)

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
        if action == bmo_input.Action.UP:
            self._steer((0, -1))
        elif action == bmo_input.Action.DOWN:
            self._steer((0, 1))
        elif action == bmo_input.Action.LEFT:
            self._steer((-1, 0))
        elif action == bmo_input.Action.RIGHT:
            self._steer((1, 0))
        elif action == bmo_input.Action.A and self.state == "over":
            self._reset()
        elif action == bmo_input.Action.TAP and pos is not None:
            if self._back_btn().collidepoint(pos):
                audio.play("back")
                self.on_back()
                return
            if self.state == "over":
                self._reset()
                return
            self._steer_from_touch(pos)

    def _steer(self, d: tuple[int, int]) -> None:
        if self.state == "ready":
            self.state = "playing"
        # não deixa inverter 180° em cima de si mesma
        if (d[0] == -self.dir[0] and d[1] == -self.dir[1]):
            return
        self._next_dir = d

    def _steer_from_touch(self, pos: tuple[int, int]) -> None:
        """Vira na direção do toque em relação à cabeça (eixo dominante)."""
        hx = FIELD_X + self.snake[-1][0] * CELL + CELL // 2
        hy = FIELD_Y + self.snake[-1][1] * CELL + CELL // 2
        dx, dy = pos[0] - hx, pos[1] - hy
        if abs(dx) > abs(dy):
            self._steer((1, 0) if dx > 0 else (-1, 0))
        else:
            self._steer((0, 1) if dy > 0 else (0, -1))

    # ---------- update ----------

    def update(self, dt: float) -> None:
        if self.state != "playing":
            return
        self._acc += dt
        while self._acc >= self._step:
            self._acc -= self._step
            self._advance()
            if self.state != "playing":
                break

    def _advance(self) -> None:
        self.dir = self._next_dir
        hx, hy = self.snake[-1]
        nx, ny = hx + self.dir[0], hy + self.dir[1]
        # parede
        if nx < 0 or nx >= COLS or ny < 0 or ny >= ROWS:
            self._die()
            return
        # corpo (ignora a cauda, que vai sair — salvo se for crescer)
        body = self.snake if (nx, ny) == self.food else self.snake[1:]
        if (nx, ny) in body:
            self._die()
            return
        self.snake.append((nx, ny))
        if (nx, ny) == self.food:
            self.score += 1
            audio.play("point")
            self.food = self._spawn_food()
            if self.score % SPEEDUP_EVERY == 0:
                self._step = max(STEP_MIN, self._step - 0.012)
        else:
            self.snake.pop(0)           # anda: tira a cauda

    def _die(self) -> None:
        self.state = "over"
        audio.play("fail")

    # ---------- draw ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(4, 1, 52, 16)

    def _cell_rect(self, c: int, r: int) -> pygame.Rect:
        return pygame.Rect(FIELD_X + c * CELL, FIELD_Y + r * CELL, CELL, CELL)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        # campo (borda sutil)
        field = pygame.Rect(FIELD_X, FIELD_Y, COLS * CELL, ROWS * CELL)
        pygame.draw.rect(surface, GRID_LINE, field, 1)
        # comida
        fr = self._cell_rect(*self.food)
        pygame.draw.rect(surface, FOOD, fr.inflate(-2, -2))
        # cobra
        for i, (c, r) in enumerate(self.snake):
            col = SNAKE_HEAD if i == len(self.snake) - 1 else SNAKE
            pygame.draw.rect(surface, col, self._cell_rect(c, r).inflate(-1, -1))
        # score
        s = render_text(f"PONTOS {self.score}", 9, DIM, pixel=False)
        surface.blit(s, s.get_rect(midtop=(W // 2, 4)))
        self._draw_back_btn(surface)
        if self.state == "ready":
            self._center_text(surface, "SNAKE", "toque ou setas pra comecar")
        elif self.state == "over":
            self._center_text(surface, "FIM DE JOGO", "toque pra jogar de novo")

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
        t = render_text(title, 14, SNAKE_HEAD)
        surface.blit(t, t.get_rect(center=(W // 2, H // 2 - 8)))
        if hint:
            h = render_text(hint, 9, WHITE, pixel=False)
            surface.blit(h, h.get_rect(center=(W // 2, H // 2 + 14)))
