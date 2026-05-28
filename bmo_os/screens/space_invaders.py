"""Space Invaders simplificado, touch-only.

- Toca e arrasta pra mover a nave horizontalmente
- Atira automaticamente em intervalo fixo
- 4 tipos de inimigos pixel-art coloridos marcham e atiram
- Campo de estrelas com parallax (3 camadas) no fundo
- Toque no botão HOME no canto sup-esquerdo pra sair
"""
from __future__ import annotations

import random

import pygame

from ..core import input as bmo_input
from ..core import theme_state
from ..core.theme import LOGICAL_SIZE, render_text

# ---------- paleta ----------
BG            = (8, 10, 24)
WHITE         = (240, 240, 240)
DIM           = (130, 130, 140)
BULLET_COLOR  = (255, 250, 200)
ENEMY_BULLET  = (255, 90, 90)

# ---------- player ----------
PIXEL = 2
PLAYER_SPRITE = [
    "....G....",
    "...GGG...",
    "..GCCCG..",
    ".GGGGGGG.",
    "GG.GGG.GG",
    "GGGGGGGGG",
    "G.GG.GG.G",
]
PLAYER_COLORS = {
    "G": (90, 230, 110),
    "C": (160, 220, 255),
}
PLAYER_W = len(PLAYER_SPRITE[0]) * PIXEL    # 18
PLAYER_H = len(PLAYER_SPRITE) * PIXEL       # 14
PLAYER_Y = 208
PLAYER_LERP = 0.28

# ---------- bullets ----------
BULLET_W = 2
BULLET_H = 8
PLAYER_BULLET_SPEED = 260
ENEMY_BULLET_SPEED  = 140
FIRE_INTERVAL_S     = 0.32

# ---------- inimigos ----------
ENEMY_SPRITES = {
    0: [   # CRAB — vermelho
        ".X....X.",
        "..X..X..",
        ".XXXXXX.",
        "XX.XX.XX",
        "XXXXXXXX",
        "X.X..X.X",
        ".X....X.",
    ],
    1: [   # OCTOPUS — amarelo
        "..XXXX..",
        ".XXXXXX.",
        "XXXXXXXX",
        "XX.XX.XX",
        "XXXXXXXX",
        "..X..X..",
        ".X.XX.X.",
    ],
    2: [   # UFO — verde
        "...XX...",
        "..XXXX..",
        "XXXXXXXX",
        "XX.XX.XX",
        ".XXXXXX.",
        "..X..X..",
        ".X....X.",
    ],
    3: [   # SQUID — ciano
        "..XXXX..",
        ".XXXXXX.",
        "XX.XX.XX",
        "XXXXXXXX",
        ".X....X.",
        ".X.XX.X.",
        "X.X..X.X",
    ],
}
ENEMY_BODY_COLORS = {
    0: (230, 80, 80),    # vermelho
    1: (230, 200, 60),   # amarelo
    2: (90, 200, 90),    # verde
    3: (90, 200, 220),   # ciano
}
ENEMY_W = len(ENEMY_SPRITES[0][0]) * PIXEL   # 16
ENEMY_H = len(ENEMY_SPRITES[0]) * PIXEL      # 14
ENEMY_ROWS = 4
ENEMY_COLS = 8
ENEMY_GAP_X = 8
ENEMY_GAP_Y = 8
ENEMY_TOP_Y = 40
ENEMY_SPEED_BASE = 18
ENEMY_DROP_PX = 8
ENEMY_FIRE_CHANCE_PER_FRAME = 0.006

INITIAL_LIVES = 3

# ---------- starfield ----------
STAR_LAYERS = [
    {"count": 22, "speed": 14, "size": 1, "color": (100, 110, 140)},   # longe
    {"count": 14, "speed": 30, "size": 1, "color": (170, 180, 210)},   # médio
    {"count": 7,  "speed": 55, "size": 2, "color": (235, 240, 250)},   # perto
]


def _to_logical(pos: tuple[int, int]) -> tuple[int, int]:
    w, h = pygame.display.get_window_size()
    if w <= 0 or h <= 0:
        return pos
    return (pos[0] * LOGICAL_SIZE[0] // w, pos[1] * LOGICAL_SIZE[1] // h)


def _draw_sprite(surface, lines, x_top, y_top, color_map):
    for r, row in enumerate(lines):
        for c, ch in enumerate(row):
            color = color_map.get(ch)
            if color is None:
                continue
            pygame.draw.rect(surface, color, (x_top + c * PIXEL, y_top + r * PIXEL, PIXEL, PIXEL))


class _Bullet:
    __slots__ = ("x", "y", "vy")
    def __init__(self, x, y, vy):
        self.x, self.y, self.vy = x, y, vy


class _Enemy:
    __slots__ = ("x", "y", "row", "alive")
    def __init__(self, x, y, row):
        self.x, self.y, self.row, self.alive = x, y, row, True


class _Star:
    __slots__ = ("x", "y", "speed", "size", "color")
    def __init__(self, x, y, speed, size, color):
        self.x, self.y, self.speed, self.size, self.color = x, y, speed, size, color


class SpaceInvadersScreen:
    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self._t = 0.0
        self._init_starfield()
        self._reset()

    # ---------- starfield ----------

    def _init_starfield(self) -> None:
        self.stars: list[_Star] = []
        for layer in STAR_LAYERS:
            for _ in range(layer["count"]):
                self.stars.append(_Star(
                    x=random.uniform(0, LOGICAL_SIZE[0]),
                    y=random.uniform(0, LOGICAL_SIZE[1]),
                    speed=layer["speed"],
                    size=layer["size"],
                    color=layer["color"],
                ))

    def _update_stars(self, dt: float) -> None:
        h = LOGICAL_SIZE[1]
        w = LOGICAL_SIZE[0]
        for s in self.stars:
            s.y += s.speed * dt
            if s.y > h:
                s.y = -s.size
                s.x = random.uniform(0, w)

    def _draw_stars(self, surface) -> None:
        for s in self.stars:
            pygame.draw.rect(surface, s.color, (int(s.x), int(s.y), s.size, s.size))

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
        self._t += dt
        self._update_stars(dt)
        if self.game_over or self.victory:
            return

        # nave segue o dedo
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
            dead = ENEMY_ROWS * ENEMY_COLS - len(alive)
            self.enemy_speed = ENEMY_SPEED_BASE * (1 + dead * 0.05)

        # inimigos atiram
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

        # inimigos chegam no chão
        for e in self.enemies:
            if e.alive and e.y > PLAYER_Y - 14:
                self.game_over = True
                return

    # ---------- draw ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(4, 4, 52, 16)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        self._draw_stars(surface)
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
        # sprite centralizado no player_x, PLAYER_Y é o centro vertical
        top_x = px - PLAYER_W // 2
        top_y = PLAYER_Y - PLAYER_H // 2
        # chamas pulsantes embaixo da nave
        self._draw_engine_flame(surface, px, top_y + PLAYER_H)
        # corpo da nave
        _draw_sprite(surface, PLAYER_SPRITE, top_x, top_y, PLAYER_COLORS)

    def _draw_engine_flame(self, surface, cx: int, base_y: int) -> None:
        phase = (self._t * 14) % 1.0
        extra = int(phase * 4)
        # vermelho externo
        pygame.draw.polygon(surface, (255, 90, 40), [
            (cx - 6, base_y - 1),
            (cx - 3, base_y + 5 + extra),
            (cx + 3, base_y + 5 + extra),
            (cx + 6, base_y - 1),
        ])
        # laranja médio
        pygame.draw.polygon(surface, (255, 180, 60), [
            (cx - 4, base_y - 1),
            (cx - 2, base_y + 4 + extra),
            (cx + 2, base_y + 4 + extra),
            (cx + 4, base_y - 1),
        ])
        # amarelo interno
        pygame.draw.polygon(surface, (255, 240, 150), [
            (cx - 2, base_y - 1),
            (cx, base_y + 3 + extra),
            (cx + 2, base_y - 1),
        ])

    def _draw_enemies(self, surface: pygame.Surface) -> None:
        # leve sway no tronco da marcha (vertical) pra dar vida
        sway = int((self._t * 4) % 2)
        for e in self.enemies:
            if not e.alive:
                continue
            sprite = ENEMY_SPRITES[e.row]
            body_color = ENEMY_BODY_COLORS[e.row]
            color_map = {"X": body_color}
            top_x = int(e.x - ENEMY_W // 2)
            top_y = int(e.y - ENEMY_H // 2) + (sway if e.row % 2 == 0 else (1 - sway))
            _draw_sprite(surface, sprite, top_x, top_y, color_map)

    def _draw_bullets(self, surface: pygame.Surface) -> None:
        for b in self.bullets:
            # bala do player com glow sutil (rect interno + outline)
            pygame.draw.rect(surface, (180, 180, 100),
                             (int(b.x) - BULLET_W // 2 - 1, int(b.y) - 1, BULLET_W + 2, BULLET_H + 2))
            pygame.draw.rect(surface, BULLET_COLOR,
                             (int(b.x) - BULLET_W // 2, int(b.y), BULLET_W, BULLET_H))
        for b in self.enemy_bullets:
            # bala do inimigo: zigzag pequenino pra parecer agressiva
            x0 = int(b.x) - BULLET_W // 2
            y0 = int(b.y)
            pygame.draw.rect(surface, ENEMY_BULLET, (x0, y0, BULLET_W, 3))
            pygame.draw.rect(surface, ENEMY_BULLET, (x0 + 1, y0 + 3, BULLET_W, 3))
            pygame.draw.rect(surface, ENEMY_BULLET, (x0, y0 + 6, BULLET_W, 2))

    def _draw_overlay(self, surface: pygame.Surface, title: str, hint: str) -> None:
        dim = pygame.Surface(LOGICAL_SIZE)
        dim.fill((0, 0, 0))
        dim.set_alpha(160)
        surface.blit(dim, (0, 0))
        t = render_text(title, 14, WHITE)
        h = render_text(hint, 9, DIM, pixel=False)
        surface.blit(t, t.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2 - 8)))
        surface.blit(h, h.get_rect(center=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2 + 14)))


# ---------- AMBIENT (BMO joga sozinho) ----------

class SpaceInvadersAmbientScreen:
    """Modo idle: a nave fica vagando e caça inimigos isolados que aparecem."""

    def __init__(self, on_open_home) -> None:
        self.on_open_home = on_open_home
        self._t = 0.0
        # Reusa o helper de estrelas de SpaceInvadersScreen (3 camadas parallax)
        self.stars: list[_Star] = []
        for layer in STAR_LAYERS:
            for _ in range(layer["count"]):
                self.stars.append(_Star(
                    x=random.uniform(0, LOGICAL_SIZE[0]),
                    y=random.uniform(0, LOGICAL_SIZE[1]),
                    speed=layer["speed"],
                    size=layer["size"],
                    color=layer["color"],
                ))
        self.player_x = LOGICAL_SIZE[0] / 2
        self.target_x = self.player_x
        self.target_change_at = 0.0
        self.bullets: list[_Bullet] = []
        self.fire_timer = 0.0
        self.enemy: _Enemy | None = None
        self.enemy_vx = 0.0
        self.next_enemy_at = 3.0
        self.score = 0

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        if event.action in (bmo_input.Action.TAP, bmo_input.Action.A, bmo_input.Action.MENU):
            self.on_open_home()

    def update(self, dt: float) -> None:
        self._t += dt
        self._update_stars(dt)

        # decide target da nave: se tem inimigo, persegue; senão wandering
        if self._t >= self.target_change_at:
            if self.enemy is not None:
                self.target_x = self.enemy.x
                self.target_change_at = self._t + 0.25
            else:
                self.target_x = random.uniform(40, LOGICAL_SIZE[0] - 40)
                self.target_change_at = self._t + random.uniform(2.0, 5.0)

        # move a nave
        self.player_x += (self.target_x - self.player_x) * 0.13
        half = PLAYER_W / 2
        self.player_x = max(half + 4, min(LOGICAL_SIZE[0] - half - 4, self.player_x))

        # spawn de inimigo isolado
        if self.enemy is None and self._t >= self.next_enemy_at:
            self.enemy = _Enemy(
                x=random.uniform(40, LOGICAL_SIZE[0] - 40),
                y=random.uniform(46, 80),
                row=random.randint(0, 3),
            )
            self.enemy_vx = random.choice([-1, 1]) * random.uniform(22, 45)

        # move o inimigo (vagueia lateral + desce devagar)
        if self.enemy is not None:
            self.enemy.x += self.enemy_vx * dt
            self.enemy.y += 7 * dt
            if self.enemy.x < 20:
                self.enemy.x = 20
                self.enemy_vx = abs(self.enemy_vx)
            elif self.enemy.x > LOGICAL_SIZE[0] - 20:
                self.enemy.x = LOGICAL_SIZE[0] - 20
                self.enemy_vx = -abs(self.enemy_vx)
            # se chegou no chão sem ser abatido, escapa
            if self.enemy.y > 170:
                self.enemy = None
                self.next_enemy_at = self._t + random.uniform(5.0, 14.0)

        # atira só quando tem alvo E está mais ou menos alinhado
        if self.enemy is not None and abs(self.player_x - self.enemy.x) < 10:
            self.fire_timer += dt
            if self.fire_timer >= FIRE_INTERVAL_S:
                self.fire_timer = 0.0
                self.bullets.append(_Bullet(
                    self.player_x, PLAYER_Y - PLAYER_H / 2 - 4, -PLAYER_BULLET_SPEED,
                ))
        else:
            self.fire_timer = max(0.0, self.fire_timer - dt)

        # bullets sobem
        for b in self.bullets:
            b.y += b.vy * dt
        self.bullets = [b for b in self.bullets if b.y > -BULLET_H]

        # colisão bullet vs inimigo
        if self.enemy is not None:
            for b in self.bullets:
                if (abs(b.x - self.enemy.x) < ENEMY_W / 2
                        and abs(b.y - self.enemy.y) < ENEMY_H / 2):
                    self.score += 10
                    self.enemy = None
                    self.next_enemy_at = self._t + random.uniform(5.0, 14.0)
                    self.bullets.remove(b)
                    break

    def _update_stars(self, dt: float) -> None:
        h = LOGICAL_SIZE[1]
        w = LOGICAL_SIZE[0]
        for s in self.stars:
            s.y += s.speed * dt
            if s.y > h:
                s.y = -s.size
                s.x = random.uniform(0, w)

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        # estrelas no fundo
        for s in self.stars:
            pygame.draw.rect(surface, s.color, (int(s.x), int(s.y), s.size, s.size))
        # mini relógio centro-top
        theme_state.draw_mini_clock(surface, LOGICAL_SIZE[0] // 2, 6, WHITE)
        # placar discreto à esquerda
        sc = render_text(f"SCORE {self.score:04d}", 7, DIM, pixel=False)
        surface.blit(sc, sc.get_rect(topleft=(8, 7)))

        # inimigo (se houver)
        if self.enemy is not None:
            sprite = ENEMY_SPRITES[self.enemy.row]
            color_map = {"X": ENEMY_BODY_COLORS[self.enemy.row]}
            top_x = int(self.enemy.x - ENEMY_W // 2)
            top_y = int(self.enemy.y - ENEMY_H // 2)
            _draw_sprite(surface, sprite, top_x, top_y, color_map)

        # bullets do player
        for b in self.bullets:
            pygame.draw.rect(surface, (180, 180, 100),
                             (int(b.x) - BULLET_W // 2 - 1, int(b.y) - 1, BULLET_W + 2, BULLET_H + 2))
            pygame.draw.rect(surface, BULLET_COLOR,
                             (int(b.x) - BULLET_W // 2, int(b.y), BULLET_W, BULLET_H))

        # nave (com chama)
        px = int(self.player_x)
        top_x = px - PLAYER_W // 2
        top_y = PLAYER_Y - PLAYER_H // 2
        self._draw_engine_flame(surface, px, top_y + PLAYER_H)
        _draw_sprite(surface, PLAYER_SPRITE, top_x, top_y, PLAYER_COLORS)

    def _draw_engine_flame(self, surface, cx: int, base_y: int) -> None:
        phase = (self._t * 14) % 1.0
        extra = int(phase * 4)
        pygame.draw.polygon(surface, (255, 90, 40), [
            (cx - 6, base_y - 1),
            (cx - 3, base_y + 5 + extra),
            (cx + 3, base_y + 5 + extra),
            (cx + 6, base_y - 1),
        ])
        pygame.draw.polygon(surface, (255, 180, 60), [
            (cx - 4, base_y - 1),
            (cx - 2, base_y + 4 + extra),
            (cx + 2, base_y + 4 + extra),
            (cx + 4, base_y - 1),
        ])
        pygame.draw.polygon(surface, (255, 240, 150), [
            (cx - 2, base_y - 1),
            (cx, base_y + 3 + extra),
            (cx + 2, base_y - 1),
        ])
