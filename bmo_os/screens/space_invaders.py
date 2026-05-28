"""Space Invaders simplificado, touch-only.

- Toca e arrasta pra mover a nave horizontalmente
- Atira automaticamente em intervalo fixo
- Inimigos coloridos marcham lateralmente e descem ao bater nas bordas
- Toque no botão HOME no canto sup-esquerdo pra sair
"""
from __future__ import annotations

import random

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text

# ---------- paleta colorida (arcade) ----------
BG            = (8, 12, 24)
WHITE         = (240, 240, 240)
DIM           = (130, 130, 140)
PLAYER_COLOR  = (90, 230, 110)
ENEMY_COLORS  = [
    (230, 80, 80),    # row 0 — vermelho
    (230, 200, 60),   # row 1 — amarelo
    (90, 200, 90),    # row 2 — verde
    (90, 200, 220),   # row 3 — ciano
]
BULLET_COLOR  = (240, 240, 240)
ENEMY_BULLET  = (230, 100, 100)

# ---------- player ----------
PLAYER_W = 22
PLAYER_H = 12
PLAYER_Y = 210
PLAYER_LERP = 0.28      # quão rápido a nave segue o dedo

# ---------- bullets ----------
BULLET_W = 2
BULLET_H = 8
PLAYER_BULLET_SPEED = 260   # px/s (sobe)
ENEMY_BULLET_SPEED  = 140   # px/s (desce)
FIRE_INTERVAL_S     = 0.32

# ---------- inimigos ----------
ENEMY_W = 20
ENEMY_H = 14
ENEMY_ROWS = 4
ENEMY_COLS = 8
ENEMY_GAP_X = 6
ENEMY_GAP_Y = 8
ENEMY_TOP_Y = 38
ENEMY_SPEED_BASE = 18           # px/s horizontal inicial
ENEMY_DROP_PX = 8
ENEMY_FIRE_CHANCE_PER_FRAME = 0.006

INITIAL_LIVES = 3


def _to_logical(pos: tuple[int, int]) -> tuple[int, int]:
    w, h = pygame.display.get_window_size()
    if w <= 0 or h <= 0:
        return pos
    return (pos[0] * LOGICAL_SIZE[0] // w, pos[1] * LOGICAL_SIZE[1] // h)


class _Bullet:
    __slots__ = ("x", "y", "vy")

    def __init__(self, x: float, y: float, vy: float) -> None:
        self.x = x
        self.y = y
        self.vy = vy


class _Enemy:
    __slots__ = ("x", "y", "row", "alive")

    def __init__(self, x: float, y: float, row: int) -> None:
        self.x = x
        self.y = y
        self.row = row
        self.alive = True


class SpaceInvadersScreen:
    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self._reset()

    # ---------- state ----------

    def _reset(self) -> None:
        self.player_x = LOGICAL_SIZE[0] / 2
        self.target_x = self.player_x
        self.bullets: list[_Bullet] = []
        self.enemy_bullets: list[_Bullet] = []
        self.enemies: list[_Enemy] = []
        grid_w = ENEMY_COLS * ENEMY_W + (ENEMY_COLS - 1) * ENEMY_GAP_X
        start_x = (LOGICAL_SIZE[0] - grid_w) / 2 + ENEMY_W / 2
        for row in range(ENEMY_ROWS):
            for col in range(ENEMY_COLS):
                x = start_x + col * (ENEMY_W + ENEMY_GAP_X)
                y = ENEMY_TOP_Y + row * (ENEMY_H + ENEMY_GAP_Y)
                self.enemies.append(_Enemy(x, y, row))
        self.enemy_dir = 1
        self.enemy_speed = ENEMY_SPEED_BASE
        self.fire_timer = 0.0
        self.score = 0
        self.lives = INITIAL_LIVES
        self.game_over = False
        self.victory = False
        self._touching = False

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == bmo_input.ACTION_EVENT:
            self._handle_action(event)
            return
        if event.type == pygame.MOUSEMOTION:
            if self._touching and pygame.mouse.get_pressed()[0]:
                self.target_x = _to_logical(event.pos)[0]
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
            if self.game_over or self.victory:
                self._reset()
                return
            self._touching = True
            self.target_x = pos[0]
            return
        if action == bmo_input.Action.A and (self.game_over or self.victory):
            self._reset()

    # ---------- update ----------

    def update(self, dt: float) -> None:
        if self.game_over or self.victory:
            return

        # nave segue o dedo (lerp suave) + clamp dentro da tela
        self.player_x += (self.target_x - self.player_x) * PLAYER_LERP
        half = PLAYER_W / 2
        self.player_x = max(half + 4, min(LOGICAL_SIZE[0] - half - 4, self.player_x))

        # auto fire
        self.fire_timer += dt
        if self.fire_timer >= FIRE_INTERVAL_S:
            self.fire_timer = 0.0
            self.bullets.append(_Bullet(self.player_x, PLAYER_Y - PLAYER_H / 2 - 4, -PLAYER_BULLET_SPEED))

        # bullets do player sobem
        for b in self.bullets:
            b.y += b.vy * dt
        self.bullets = [b for b in self.bullets if b.y > -BULLET_H]

        # marcha dos inimigos
        alive = [e for e in self.enemies if e.alive]
        if not alive:
            self.victory = True
            return
        dx = self.enemy_speed * dt * self.enemy_dir
        min_x = min(e.x for e in alive)
        max_x = max(e.x for e in alive)
        bumped = False
        if max_x + dx > LOGICAL_SIZE[0] - 10:
            bumped = True
            dx = (LOGICAL_SIZE[0] - 10) - max_x
        elif min_x + dx < 10:
            bumped = True
            dx = 10 - min_x
        for e in alive:
            e.x += dx
        if bumped:
            self.enemy_dir *= -1
            for e in alive:
                e.y += ENEMY_DROP_PX
            # acelera conforme mais inimigos morrem (clássico)
            dead = ENEMY_ROWS * ENEMY_COLS - len(alive)
            self.enemy_speed = ENEMY_SPEED_BASE * (1 + dead * 0.05)

        # inimigos atiram (cada um tem pequena chance por frame)
        for e in alive:
            if random.random() < ENEMY_FIRE_CHANCE_PER_FRAME:
                self.enemy_bullets.append(_Bullet(e.x, e.y + ENEMY_H / 2 + 2, ENEMY_BULLET_SPEED))
        for b in self.enemy_bullets:
            b.y += b.vy * dt
        self.enemy_bullets = [b for b in self.enemy_bullets if b.y < LOGICAL_SIZE[1] + BULLET_H]

        # colisões: bullet do player vs inimigo
        remaining_bullets: list[_Bullet] = []
        for b in self.bullets:
            hit = False
            for e in alive:
                if not e.alive:
                    continue
                if abs(b.x - e.x) < ENEMY_W / 2 and abs(b.y - e.y) < ENEMY_H / 2:
                    e.alive = False
                    self.score += 10
                    hit = True
                    break
            if not hit:
                remaining_bullets.append(b)
        self.bullets = remaining_bullets

        # colisões: bullet inimigo vs player
        remaining_eb: list[_Bullet] = []
        for b in self.enemy_bullets:
            if (abs(b.x - self.player_x) < PLAYER_W / 2
                    and abs(b.y - PLAYER_Y) < PLAYER_H / 2):
                self.lives -= 1
                if self.lives <= 0:
                    self.game_over = True
                    return
                continue
            remaining_eb.append(b)
        self.enemy_bullets = remaining_eb

        # inimigos atingem o chão → game over
        for e in self.enemies:
            if e.alive and e.y > PLAYER_Y - 14:
                self.game_over = True
                return

    # ---------- draw ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(4, 4, 52, 16)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        self._draw_hud(surface)
        self._draw_back_btn(surface)
        self._draw_enemies(surface)
        self._draw_bullets(surface)
        self._draw_player(surface)
        if self.game_over:
            self._draw_overlay(surface, "GAME OVER", "toque pra recomecar")
        elif self.victory:
            self._draw_overlay(surface, "VOCE GANHOU!", "toque pra jogar de novo")

    def _draw_hud(self, surface: pygame.Surface) -> None:
        score = render_text(f"SCORE {self.score:04d}", 8, WHITE, pixel=False)
        lives = render_text(f"VIDAS {self.lives}", 8, WHITE, pixel=False)
        surface.blit(score, score.get_rect(midtop=(LOGICAL_SIZE[0] // 2, 8)))
        surface.blit(lives, lives.get_rect(topright=(LOGICAL_SIZE[0] - 8, 8)))

    def _draw_back_btn(self, surface: pygame.Surface) -> None:
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

    def _draw_player(self, surface: pygame.Surface) -> None:
        px = int(self.player_x)
        py_top = PLAYER_Y - PLAYER_H // 2
        py_bot = PLAYER_Y + PLAYER_H // 2
        # corpo trapezoidal
        pts = [
            (px - PLAYER_W // 2, py_bot),
            (px - PLAYER_W // 2 + 4, py_top),
            (px + PLAYER_W // 2 - 4, py_top),
            (px + PLAYER_W // 2, py_bot),
        ]
        pygame.draw.polygon(surface, PLAYER_COLOR, pts)
        # canhão
        pygame.draw.rect(surface, PLAYER_COLOR, (px - 2, py_top - 3, 4, 3))

    def _draw_enemies(self, surface: pygame.Surface) -> None:
        for e in self.enemies:
            if not e.alive:
                continue
            color = ENEMY_COLORS[e.row % len(ENEMY_COLORS)]
            x = int(e.x - ENEMY_W // 2)
            y = int(e.y - ENEMY_H // 2)
            pygame.draw.rect(surface, color, (x, y, ENEMY_W, ENEMY_H))
            # olhos pretos
            pygame.draw.rect(surface, BG, (x + 4, y + 4, 3, 3))
            pygame.draw.rect(surface, BG, (x + ENEMY_W - 7, y + 4, 3, 3))
            # boca / faixa
            pygame.draw.rect(surface, BG, (x + 3, y + ENEMY_H - 4, ENEMY_W - 6, 2))

    def _draw_bullets(self, surface: pygame.Surface) -> None:
        for b in self.bullets:
            pygame.draw.rect(surface, BULLET_COLOR, (int(b.x) - BULLET_W // 2, int(b.y), BULLET_W, BULLET_H))
        for b in self.enemy_bullets:
            pygame.draw.rect(surface, ENEMY_BULLET, (int(b.x) - BULLET_W // 2, int(b.y), BULLET_W, BULLET_H))

    def _draw_overlay(self, surface: pygame.Surface, title: str, hint: str) -> None:
        dim = pygame.Surface(LOGICAL_SIZE)
        dim.fill((0, 0, 0))
        dim.set_alpha(160)
        surface.blit(dim, (0, 0))
        t = render_text(title, 14, WHITE)
        h = render_text(hint, 9, DIM, pixel=False)
        surface.blit(t, t.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2 - 8)))
        surface.blit(h, h.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2 + 14)))
