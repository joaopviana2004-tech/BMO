"""Fisica da bola: gravidade, quique no piso, rede, vidros, grade e portas.

A bola nao decide nada sobre regras: ela apenas devolve uma lista de eventos
(ground / wall / net / net_cord / cross / exit / dead) que o juiz (match.py) interpreta.
"""
import copy
import math
import random

from . import settings as S
from .court import hyp, sgn

GLASS, MESH, DOOR = "vidro", "grade", "porta"


def side_wall_kind(x, y):
    """Material da parede lateral na posicao x (ao longo da quadra) e altura y."""
    ax = abs(x)
    if ax < S.DOOR_GAP and y < S.DOOR_H:
        return DOOR
    if ax > S.COURT_HALF_L - S.SIDE_GLASS_LEN:
        return GLASS
    return MESH


class Ball:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z
        self.vx = self.vy = self.vz = 0.0
        self.hitter = None          # Player que bateu por ultimo
        self.side = 0               # lado (-1/+1) de quem bateu por ultimo
        self.serve = False          # a bola em jogo e um saque
        self.phase = "toss"         # "toss" (bola quicando na mao do sacador) | "rally"
        self.crossed = False        # ja cruzou a rede desde o ultimo golpe
        self.touched_net = False
        self.bounces = {-1: 0, 1: 0}  # quiques no piso de cada lado desde o ultimo golpe
        self.walls = 0
        self.age = 0.0
        self.out = False            # saiu do recinto (por cima das paredes ou pela porta)
        self.dead = False           # ponto ja decidido; continua so para animar
        self.rolling_dead = False
        self.trail = []

    # ------------------------------------------------------------------ controle
    def hit(self, player, vx, vy, vz, serve=False):
        self.vx, self.vy, self.vz = vx, vy, vz
        self.hitter = player
        self.side = player.side
        self.serve = serve
        self.phase = "rally"
        self.crossed = False
        self.touched_net = False
        self.bounces = {-1: 0, 1: 0}
        self.walls = 0
        self.age = 0.0
        self.rolling_dead = False

    def speed(self):
        return hyp(self.vx, self.vz)

    def clone(self):
        b = copy.copy(self)
        b.bounces = dict(self.bounces)
        b.trail = []
        return b

    # ------------------------------------------------------------------ simulacao
    def update(self, dt, wind=0.0):
        """`wind` (m/s no eixo z) entra dentro dos sub-passos: aplicado por fora, o empurrao
        acontecia depois da deteccao de colisao e a bola conseguia atravessar a parede."""
        events = []
        h = dt / S.SUBSTEPS
        for _ in range(S.SUBSTEPS):
            self._step(h, events, wind)
        self.age += dt
        self.trail.append((self.x, self.y, self.z))
        del self.trail[:-5]
        return events

    def _step(self, dt, ev, wind=0.0):
        g, R = S.GRAVITY, S.BALL_R
        px, py = self.x, self.y
        self.vy -= g * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += (self.vz + wind) * dt
        if self.out:
            return

        # ---- rede (plano x = 0), so vale depois de a bola ser golpeada
        if self.phase == "rally" and px != self.x and (px > 0) != (self.x > 0):
            t = px / (px - self.x)
            hy = py + (self.y - py) * t
            if hy < S.NET_H:
                if hy > S.NET_H - 0.07:
                    # pegou na fita: passa "mancando"
                    self.vx *= 0.4
                    self.vy = abs(self.vy) * 0.2 + 0.6
                    self.touched_net = True
                    self.crossed = True
                    ev.append(dict(type="net_cord"))
                else:
                    self.x = px if px != 0 else 0.01 * (1 if self.vx < 0 else -1)
                    self.vx = -self.vx * 0.12
                    self.vz *= 0.5
                    self.vy = min(self.vy, 0.0) * 0.5
                    self.touched_net = True
                    ev.append(dict(type="net"))
            elif not self.crossed:
                self.crossed = True
                ev.append(dict(type="cross"))

        # ---- piso
        if self.y < R:
            self.y = R
            if self.vy < -0.7:
                impact = -self.vy
                self.vy = -self.vy * S.REST_GROUND
                self.vx *= S.FRICTION_GROUND
                self.vz *= S.FRICTION_GROUND
                s = sgn(self.x) or 1
                self.bounces[s] += 1
                ev.append(dict(type="ground", x=self.x, z=self.z, side=s, speed=impact))
            else:
                self.vy = 0.0
                f = max(0.0, 1.0 - 2.5 * dt)
                self.vx *= f
                self.vz *= f
                if self.speed() < S.BALL_DEAD_SPEED and not self.rolling_dead:
                    self.rolling_dead = True
                    ev.append(dict(type="dead", side=sgn(self.x) or 1))

        # ---- paredes laterais (z = +-5)
        lim = S.COURT_HALF_W - R
        if abs(self.z) > lim:
            kind = side_wall_kind(self.x, self.y)
            if kind == DOOR or self.y > S.SIDE_WALL_H:
                self.out = True
                ev.append(dict(type="exit", side=sgn(self.x) or 1, kind=kind))
                return
            self.z = math.copysign(lim, self.z)
            rest = S.REST_GLASS if kind == GLASS else S.REST_MESH
            self.vz = -self.vz * rest
            if kind == MESH:
                # a grade devolve a bola de forma imprevisivel
                k = abs(self.vz)
                self.vx += random.uniform(-0.35, 0.35) * k
                self.vy += random.uniform(-0.2, 0.2) * k
            self.walls += 1
            ev.append(dict(type="wall", kind=kind, side=sgn(self.x) or 1, x=self.x, z=self.z))

        # ---- paredes de fundo (x = +-10)
        liml = S.COURT_HALF_L - R
        if abs(self.x) > liml:
            if self.y > S.BACK_WALL_H:
                self.out = True
                ev.append(dict(type="exit", side=sgn(self.x) or 1, kind=GLASS))
                return
            self.x = math.copysign(liml, self.x)
            self.vx = -self.vx * S.REST_GLASS
            self.walls += 1
            ev.append(dict(type="wall", kind=GLASS, side=sgn(self.x) or 1, x=self.x, z=self.z))


def predict_path(ball, side, allow_volley=True, max_t=3.0, dt=1.0 / 60.0, wind=0.0):
    """Simula a bola para frente (com quiques e paredes) e devolve a lista de instantes
    (x, z, y, t, apos_quique) em que um jogador do lado `side` poderia golpea-la."""
    b = ball.clone()
    t = 0.0
    out = []
    while t < max_t:
        b.update(dt, wind)
        t += dt
        if b.out or b.bounces[side] >= 2:
            break
        if sgn(b.x) != side or abs(b.x) < 0.5:
            continue
        nb = b.bounces[side]
        if nb >= 1:
            if 0.12 <= b.y <= 2.3:
                out.append((b.x, b.z, b.y, t, True))
        elif allow_volley and abs(b.x) < 6.5 and 0.4 <= b.y <= 2.2:
            out.append((b.x, b.z, b.y, t, False))
    return out
