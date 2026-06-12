"""Neuroevolução do Haxball: física do campo + rede neural + algoritmo genético.

Compartilhado entre o jogo (screens/haxball.py) e a tela de TREINO
(screens/haxball_train.py) — fonte única da física, então o cérebro treinado
joga igualzinho quando você "joga contra" no jogo normal.

Inspirado no repo do usuário (joaopviana2004-tech/Haxball_Genetic_Agent), com
melhorias pra convergir mais rápido:
  - 9 inputs (posição própria, bola RELATIVA + VELOCIDADE da bola, adversário
    relativo, sinal do lado) — a velocidade da bola é o que faltava lá;
  - âncora contra o bot scriptado (gradiente estável e rápido no começo);
  - co-evolução com injeção do CAMPEÃO (hall-of-fame, anti-regressão);
  - mutação adaptativa em fases (caos -> intermediário -> refino).

A física é Python puro (sem pygame aqui); a NN usa numpy (já é dependência core).
"""
from __future__ import annotations

import json
import math
import random

import numpy as np

from ..core import config

# ========================= física / campo =========================
# coords lógicas; o jogo monta um pygame.Rect a partir daqui pra desenhar
FIELD_L, FIELD_T, FIELD_W, FIELD_H = 12, 26, 376, 200
FIELD_R = FIELD_L + FIELD_W          # 388
FIELD_B = FIELD_T + FIELD_H          # 226
CX, CY = FIELD_L + FIELD_W // 2, FIELD_T + FIELD_H // 2   # 200, 126
GOAL_H = 60
GOAL_TOP = CY - GOAL_H // 2          # 96
GOAL_BOT = CY + GOAL_H // 2          # 156
_MAXD = math.hypot(FIELD_W, FIELD_H)  # diagonal do campo (normaliza distâncias)

BALL_R, BALL_MASS, BALL_FRIC, BALL_MAXV = 4.0, 1.0, 0.4, 420.0
PLR_R, PLR_MASS, PLR_FRIC, PLR_MAXV = 9.0, 4.0, 5.0, 122.0
PLR_ACCEL = 920.0
BOT_ACCEL, BOT_MAXV = 600.0, 92.0    # bot scriptado fraco (jogo casual)
WALL_REST = 0.7
DISC_REST = 0.55
WIN_SCORE = 5                        # gols pra vencer no jogo
# ---------- chute ----------
KICK_RANGE = PLR_R + BALL_R + 5      # 18: alcance pra chutar a bola
KICK_POWER = 340.0                   # impulso do chute (a bola voa, fura o goleiro)
KICK_COOLDOWN = 0.35                 # segundos entre chutes


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Disc:
    __slots__ = ("x", "y", "vx", "vy", "r", "inv_mass", "fric")

    def __init__(self, x, y, r, mass, fric):
        self.x = float(x); self.y = float(y)
        self.vx = 0.0; self.vy = 0.0
        self.r = r
        self.inv_mass = 0.0 if mass <= 0 else 1.0 / mass
        self.fric = fric


class HaxWorld:
    """Bola + 2 discos (a=esquerda/time 0, b=direita/time 1). `step()` recebe a
    aceleração desejada de cada lado (ax,ay em [-1,1]) e devolve 'A'/'B'/None se
    saiu gol. `observe(side)` dá os 9 inputs da rede daquele lado."""

    def __init__(self, goal_h=GOAL_H) -> None:
        self.score_a = 0
        self.score_b = 0
        self.last_touch = None
        # boca do gol por instância — o treino usa um gol que encolhe (currículo)
        self.goal_top = CY - goal_h // 2
        self.goal_bot = CY + goal_h // 2
        self.kickoff()

    def kickoff(self) -> None:
        self.ball = Disc(CX, CY, BALL_R, BALL_MASS, BALL_FRIC)
        self.a = Disc(FIELD_L + 48, CY, PLR_R, PLR_MASS, PLR_FRIC)
        self.b = Disc(FIELD_R - 48, CY, PLR_R, PLR_MASS, PLR_FRIC)
        self.touch_a = False
        self.touch_b = False
        self.t = 0.0                      # tempo da partida
        self.t_touch_a = self.t_touch_b = -999.0   # quando cada lado tocou a bola
        self.kick_cd_a = self.kick_cd_b = 0.0      # cooldown do chute por lado

    def random_reset(self, rng) -> None:
        """Saque ALEATÓRIO (só pro TREINO): bola e jogadores em posições/velocidades
        variadas (cada um mais no seu lado). Cria chances de gol e faz o agente
        generalizar — em vez de sempre o mesmo saque do centro (que empata)."""
        u = rng.uniform
        self.ball.x, self.ball.y = u(FIELD_L + 20, FIELD_R - 20), u(FIELD_T + 14, FIELD_B - 14)
        self.ball.vx, self.ball.vy = u(-150, 150), u(-150, 150)
        self.a.x, self.a.y = u(FIELD_L + 14, CX), u(FIELD_T + 14, FIELD_B - 14)
        self.b.x, self.b.y = u(CX, FIELD_R - 14), u(FIELD_T + 14, FIELD_B - 14)
        self.a.vx = self.a.vy = self.b.vx = self.b.vy = 0.0
        self.touch_a = self.touch_b = False

    def step(self, dt, ax_a, ay_a, ax_b, ay_b, kick_a=False, kick_b=False,
             a_accel=PLR_ACCEL, a_maxv=PLR_MAXV,
             b_accel=BOT_ACCEL, b_maxv=BOT_MAXV):
        self.touch_a = False
        self.touch_b = False
        self.kick_cd_a = max(0.0, self.kick_cd_a - dt)
        self.kick_cd_b = max(0.0, self.kick_cd_b - dt)
        self._control(self.a, ax_a, ay_a, a_accel, a_maxv, dt)
        self._control(self.b, ax_b, ay_b, b_accel, b_maxv, dt)
        for d in (self.a, self.b, self.ball):
            f = max(0.0, 1.0 - d.fric * dt)
            d.vx *= f; d.vy *= f
            d.x += d.vx * dt; d.y += d.vy * dt
        self._clamp_speed(self.ball, BALL_MAXV)
        if self._collide(self.a, self.ball):
            self.touch_a = True; self.last_touch = "a"; self.t_touch_a = self.t
        if self._collide(self.b, self.ball):
            self.touch_b = True; self.last_touch = "b"; self.t_touch_b = self.t
        self._collide(self.a, self.b)
        self._try_kick(self.a, "a", kick_a)   # chuta SE a rede/jogador pediu
        self._try_kick(self.b, "b", kick_b)
        self._clamp_speed(self.ball, BALL_MAXV)
        self._walls(self.a, ball=False)
        self._walls(self.b, ball=False)
        self.t += dt
        return self._walls(self.ball, ball=True)

    def _try_kick(self, player, side, want):
        """Chuta a bola (impulso forte) se `want` (3ª saída da rede / jogador) E o
        disco está perto E do lado de ATAQUE dela — assim o chute vai pro gol
        adversário, nunca pro próprio."""
        if not want:
            return
        cd = self.kick_cd_a if side == "a" else self.kick_cd_b
        if cd > 0:
            return
        dx, dy = self.ball.x - player.x, self.ball.y - player.y
        d = math.hypot(dx, dy)
        if d > KICK_RANGE or d < 1e-6:
            return
        if (side == "a" and dx <= 0) or (side == "b" and dx >= 0):
            return            # bola não está do lado de ataque -> não chuta (evita gol contra)
        self.ball.vx += dx / d * KICK_POWER
        self.ball.vy += dy / d * KICK_POWER
        self.last_touch = side
        if side == "a":
            self.kick_cd_a = KICK_COOLDOWN; self.touch_a = True; self.t_touch_a = self.t
        else:
            self.kick_cd_b = KICK_COOLDOWN; self.touch_b = True; self.t_touch_b = self.t

    # ---------- observação (entradas da rede) ----------

    def observe(self, side):
        """Entradas POLARES no FRAME CANÔNICO (o lado 'b' é espelhado no X pra todo
        agente "atacar pra +x"; a saída é des-espelhada por brain_action). Pra cada
        coisa relevante: distância + DIREÇÃO (cos, sin) — casa com a ação (mover
        numa direção) e dá consciência explícita do GOL. 18 features:
          bola: polar(3) + velocidade(2); oponente: polar(3) + velocidade(2);
          gol adversário: polar(3); próprio gol: polar(3); minha velocidade(2)."""
        me = self.b if side == "b" else self.a
        opp = self.a if side == "b" else self.b
        ball = self.ball
        mir = side == "b"
        mx = (lambda x: FIELD_L + FIELD_R - x) if mir else (lambda x: x)
        mv = (lambda v: -v) if mir else (lambda v: v)
        mex, mey = mx(me.x), me.y
        c = _clamp

        def pol(tx, ty):
            dx, dy = tx - mex, ty - mey
            d = math.hypot(dx, dy)
            if d < 1e-6:
                return (0.0, 1.0, 0.0)
            return (c(d / _MAXD, 0.0, 1.0), dx / d, dy / d)   # dist, cos, sin

        bp = pol(mx(ball.x), ball.y)
        op = pol(mx(opp.x), opp.y)
        eg = pol(FIELD_R, CY)        # gol adversário (canônico = lado +x)
        og = pol(FIELD_L, CY)        # próprio gol (canônico = lado -x)
        return [
            bp[0], bp[1], bp[2],
            c(mv(ball.vx) / BALL_MAXV, -1.0, 1.0), c(ball.vy / BALL_MAXV, -1.0, 1.0),
            op[0], op[1], op[2],
            c(mv(opp.vx) / PLR_MAXV, -1.0, 1.0), c(opp.vy / PLR_MAXV, -1.0, 1.0),
            eg[0], eg[1], eg[2],
            og[0], og[1], og[2],
            c(mv(me.vx) / PLR_MAXV, -1.0, 1.0), c(me.vy / PLR_MAXV, -1.0, 1.0),
        ]

    # ---------- helpers de física ----------

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
            return False
        inv = a.inv_mass + b.inv_mass
        if inv == 0:
            return False
        if dist < 1e-6:
            dx, dy, dist = 1.0, 0.0, 1.0
        nx, ny = dx / dist, dy / dist
        overlap = rsum - dist
        a.x -= nx * overlap * (a.inv_mass / inv)
        a.y -= ny * overlap * (a.inv_mass / inv)
        b.x += nx * overlap * (b.inv_mass / inv)
        b.y += ny * overlap * (b.inv_mass / inv)
        vn = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny
        if vn < 0:
            j = -(1.0 + DISC_REST) * vn / inv
            a.vx -= j * nx * a.inv_mass; a.vy -= j * ny * a.inv_mass
            b.vx += j * nx * b.inv_mass; b.vy += j * ny * b.inv_mass
            return True
        return False

    def _walls(self, d, ball):
        if d.y - d.r < FIELD_T:
            d.y = FIELD_T + d.r; d.vy = abs(d.vy) * WALL_REST
        elif d.y + d.r > FIELD_B:
            d.y = FIELD_B - d.r; d.vy = -abs(d.vy) * WALL_REST
        in_goal = ball and self.goal_top < d.y < self.goal_bot
        if d.x - d.r < FIELD_L:
            if in_goal:
                if d.x < FIELD_L - 2:
                    return "B"
            else:
                d.x = FIELD_L + d.r; d.vx = abs(d.vx) * WALL_REST
        if d.x + d.r > FIELD_R:
            if in_goal:
                if d.x > FIELD_R + 2:
                    return "A"
            else:
                d.x = FIELD_R - d.r; d.vx = -abs(d.vx) * WALL_REST
        return None


# ========================= bot scriptado (referência) =========================

def bot_action(world: HaxWorld, side: str):
    """Política simples (a mesma do jogo): defende o próprio gol e empurra a bola
    pro gol adversário. Serve de adversário-âncora no treino (gradiente estável)
    e de bot casual no jogo. Devolve (ax, ay) em [-1,1]."""
    me = world.b if side == "b" else world.a
    ball = world.ball
    if side == "b":
        own_x, enemy = FIELD_R, (FIELD_L, CY)
        retreat = ball.x < CX - 24
        back = -42
    else:
        own_x, enemy = FIELD_L, (FIELD_R, CY)
        retreat = ball.x > CX + 24
        back = 42
    if retreat:
        tx = own_x + back
        ty = _clamp(ball.y, GOAL_TOP + 4, GOAL_BOT - 4)
    else:
        dgx, dgy = ball.x - enemy[0], ball.y - enemy[1]
        dg = math.hypot(dgx, dgy) or 1.0
        tx = ball.x + dgx / dg * (PLR_R + BALL_R - 2)
        ty = ball.y + dgy / dg * (PLR_R + BALL_R - 2)
    tx = _clamp(tx, FIELD_L + PLR_R, FIELD_R - PLR_R)
    ty = _clamp(ty, FIELD_T + PLR_R, FIELD_B - PLR_R)
    dx, dy = tx - me.x, ty - me.y
    d = math.hypot(dx, dy)
    kick = math.hypot(ball.x - me.x, ball.y - me.y) < (KICK_RANGE + 2)
    if d > 2:
        return dx / d, dy / d, kick
    return 0.0, 0.0, kick


# ========================= rede neural =========================

N_OBS = 18             # observações (polar + gols + velocidades, frame canônico)
MEM = 4                # MEMÓRIA de curto prazo: neurônios recorrentes (realimentados)
N_IN = N_OBS + MEM     # entrada = observação + memória do passo anterior
N_OUT = 3 + MEM        # saída = ax, ay, chute + nova memória
HIDDEN = [32, 24, 16]  # 3 camadas ocultas (rede maior = mais "inteligência")


def goal_potential(x, y, goal_top, goal_bot):
    """Potencial (0..1) da bola pro ataque ao gol ESQUERDO. Funil ESTREITO: cai
    ao CUBO com a distância à BOCA do gol — quase plano no meio-campo e íngreme
    só PERTO do gol. Assim a recompensa é por ir na DIREÇÃO DO GOL inimigo
    (a boca), não por simplesmente estar na metade adversária.
    É a 'matriz de pontuação' do campo (recompensa + heatmap de fundo)."""
    cy = _clamp(y, goal_top, goal_bot)
    t = _clamp(math.hypot(x - FIELD_L, y - cy) / _MAXD, 0.0, 1.0)
    return (1.0 - t) ** 3


class Brain:
    """MLP densa (numpy) com tanh em todas as camadas. Saída = (ax, ay).

    Inicialização escalada por 1/sqrt(fan_in) (Xavier) — CRUCIAL: pesos grandes
    saturam a tanh e o agente vira uma direção constante (voa pro canto e ignora
    a bola). Com a escala certa, o output responde aos inputs desde o início."""

    def __init__(self, sizes=None):
        self.sizes = list(sizes) if sizes else [N_IN] + HIDDEN + [N_OUT]
        self.weights = [np.random.randn(self.sizes[i], self.sizes[i + 1])
                        * np.sqrt(1.0 / self.sizes[i])
                        for i in range(len(self.sizes) - 1)]
        self.biases = [np.zeros((1, self.sizes[i + 1]))
                       for i in range(len(self.sizes) - 1)]
        self.last = []   # ativações da última passagem (pra viz)

    def forward(self, inputs):
        a = np.asarray(inputs, dtype=np.float64).reshape(1, -1)
        self.last = [a[0]]
        for W, b in zip(self.weights, self.biases):
            a = np.tanh(a @ W + b)
            self.last.append(a[0])
        return a[0]                  # vetor de N_OUT saídas (ax, ay, chute)

    def mutate(self, rate, scale):
        for i in range(len(self.weights)):
            w = self.weights[i]
            mw = np.random.rand(*w.shape) < rate
            w[mw] += np.random.randn(*w.shape)[mw] * scale
            b = self.biases[i]
            mb = np.random.rand(*b.shape) < rate
            b[mb] += np.random.randn(*b.shape)[mb] * scale

    def copy(self):
        nb = Brain(self.sizes)
        nb.weights = [w.copy() for w in self.weights]
        nb.biases = [b.copy() for b in self.biases]
        return nb

    def to_dict(self):
        return {"sizes": list(self.sizes),
                "weights": [w.tolist() for w in self.weights],
                "biases": [b.tolist() for b in self.biases]}

    @classmethod
    def from_dict(cls, d):
        nb = cls(d["sizes"])
        nb.weights = [np.array(w, dtype=np.float64) for w in d["weights"]]
        nb.biases = [np.array(b, dtype=np.float64) for b in d["biases"]]
        return nb


def brain_action(brain: Brain, world: HaxWorld, side: str, mem=None):
    """Ação (ax, ay, kick, nova_memoria). A entrada é observação + memória do passo
    anterior (recorrência = memória de curto prazo). Frame canônico (des-espelha o
    ax pro lado 'b'); 3ª saída > 0 = chuta; o resto da saída é a memória nova."""
    if mem is None:
        mem = [0.0] * MEM
    out = brain.forward(list(world.observe(side)) + list(mem))
    ax, ay, kick = float(out[0]), float(out[1]), float(out[2])
    if side == "b":
        ax = -ax
    new_mem = [float(v) for v in out[3:3 + MEM]]
    return ax, ay, kick > 0.0, new_mem


def crossover(a: Brain, b: Brain) -> Brain:
    """Recombina dois pais por gene, ENVIESADO pro pai 'a' (o mais apto): ~65% dos
    pesos vêm de 'a'. Mantém a maior parte de uma política coerente (passo MENOR)
    em vez de picotar 50/50 e quebrar o que já funciona."""
    nb = a.copy()
    for i in range(len(nb.weights)):
        mw = np.random.rand(*nb.weights[i].shape) < 0.65
        nb.weights[i] = np.where(mw, a.weights[i], b.weights[i])
        mb = np.random.rand(*nb.biases[i].shape) < 0.65
        nb.biases[i] = np.where(mb, a.biases[i], b.biases[i])
    return nb


def phase_params(goals: int):
    """Mutação adaptativa (ideia do repo): caótica até marcar, refina depois. O
    passo de REFINO é pequeno (0.05/0.08) de propósito — passo grande perturba
    demais a rede já treinada e a estratégia boa 'some' de uma geração pra outra."""
    if goals <= 0:
        return 0.25, 0.40
    if goals < 8:
        return 0.12, 0.20
    return 0.05, 0.08


def evolve(brains, fits, elite=2, rate=0.15, scale=0.25, cross_rate=0.25):
    """Próxima geração: elitismo + reprodução leve (clone/crossover + mutação).
    Devolve (proxima_pop, melhor_cerebro)."""
    n = len(brains)
    order = sorted(range(n), key=lambda i: fits[i], reverse=True)
    ranked = [brains[i] for i in order]
    best = ranked[0].copy()
    nxt = [ranked[i].copy() for i in range(min(elite, n))]
    k = max(2, n // 2)
    pool = ranked[:k]                  # já ordenado: índice MENOR = mais apto
    while len(nxt) < n:
        if random.random() < cross_rate:
            i1, i2 = random.randrange(k), random.randrange(k)
            pa, pb = pool[min(i1, i2)], pool[max(i1, i2)]   # pa = o mais apto dos dois
            child = crossover(pa, pb)     # herda mais do pai mais apto (passo menor)
        else:
            child = random.choice(pool).copy()
        child.mutate(rate, scale)
        nxt.append(child)
    return nxt, best


# ========================= heurístico + bootstrap supervisionado =========================
# Redes aleatórias saturam e os agentes não engajam a bola (ficam parados/derivam
# pro canto). A solução: pré-treinar por IMITAÇÃO de um jogador heurístico que
# ataca E defende, e usar isso como semente da co-evolução. Aí os agentes já
# nascem competentes (vão na bola) e o GA refina rápido.

# Personas do sparring (dummy do treino): (distância p/ entrar em DEFESA, peso de
# BLOQUEIO = quão fundo senta no próprio gol). 'balanced' == comportamento padrão
# (usado também no jogo e na imitação). 'offensive' compromete pra frente (deixa o
# gol mais aberto, pressiona a bola); 'defensive' recua cedo e senta na linha.
_POSTURES = {
    "balanced":  (120.0, 0.50),
    "offensive": (75.0, 0.35),
    "defensive": (185.0, 0.70),
}


def heuristic_action(world, side, posture="balanced"):
    """Jogador completo (referência pra imitar), CONTÍNUO (fácil de imitar):
    ataca misturando suavemente "ir pra trás da bola" -> "conduzir a bola pro gol
    adversário"; defende quando a bola ameaça o próprio gol e o adversário chega
    antes. `posture` varia a postura do sparring (ver _POSTURES). Devolve
    (ax, ay) unitário (frame real)."""
    me = world.b if side == "b" else world.a
    opp = world.a if side == "b" else world.b
    ball = world.ball
    def_dist, block_w = _POSTURES.get(posture, _POSTURES["balanced"])
    egx = FIELD_L if side == "b" else FIELD_R
    own_goal = (FIELD_R if side == "b" else FIELD_L, CY)
    # mira no CANTO LIVRE do gol (longe do goleiro adversário) — não no centro,
    # onde o goleiro está; é assim que se fura a defesa.
    gtop, gbot = getattr(world, "goal_top", GOAL_TOP), getattr(world, "goal_bot", GOAL_BOT)
    aim_y = (gbot - PLR_R) if opp.y < CY else (gtop + PLR_R)
    enemy_goal = (egx, aim_y)
    # --- ataque (contínuo) ---
    pgx, pgy = enemy_goal[0] - ball.x, enemy_goal[1] - ball.y
    pg = math.hypot(pgx, pgy) or 1.0
    ux, uy = pgx / pg, pgy / pg                       # direção de empurrar a bola
    behind = (ball.x - ux * (PLR_R + BALL_R), ball.y - uy * (PLR_R + BALL_R))
    tbx, tby = behind[0] - me.x, behind[1] - me.y
    db = math.hypot(tbx, tby) or 1.0
    align = _clamp(1.0 - db / 45.0, 0.0, 1.0)         # 1 quando já está atrás da bola
    ax = (1.0 - align) * (tbx / db) + align * ux
    ay = (1.0 - align) * (tby / db) + align * uy
    # --- defesa (sobrepõe quando a bola ameaça o próprio gol) ---
    d_me = math.hypot(ball.x - me.x, ball.y - me.y)
    d_opp = math.hypot(ball.x - opp.x, ball.y - opp.y)
    d_ball_own = math.hypot(ball.x - own_goal[0], ball.y - own_goal[1])
    if d_ball_own < def_dist and d_opp < d_me:
        gx = own_goal[0] * block_w + ball.x * (1.0 - block_w)
        gy = own_goal[1] * (block_w * 0.7) + ball.y * (1.0 - block_w * 0.7)
        ax, ay = gx - me.x, gy - me.y
    # CHUTE: perto da bola E do lado de ataque (o impulso vai pro gol adversário)
    dball = math.hypot(ball.x - me.x, ball.y - me.y)
    attack_x = 1.0 if side == "a" else -1.0
    kick = dball < (KICK_RANGE + 2) and (ball.x - me.x) * attack_x > 0
    n = math.hypot(ax, ay) or 1.0
    return ax / n, ay / n, kick


def _random_state(rng):
    """Estado aleatório (posições/velocidades) pra amostrar o espaço no pré-treino."""
    w = HaxWorld()
    fr = lambda lo, hi: rng.uniform(lo, hi)
    w.ball.x, w.ball.y = fr(FIELD_L + 8, FIELD_R - 8), fr(FIELD_T + 8, FIELD_B - 8)
    w.ball.vx, w.ball.vy = fr(-220, 220), fr(-220, 220)
    w.a.x, w.a.y = fr(FIELD_L + 10, FIELD_R - 10), fr(FIELD_T + 10, FIELD_B - 10)
    w.b.x, w.b.y = fr(FIELD_L + 10, FIELD_R - 10), fr(FIELD_T + 10, FIELD_B - 10)
    # velocidades aleatórias também (pra exercitar os inputs de velocidade)
    w.a.vx, w.a.vy = fr(-PLR_MAXV, PLR_MAXV), fr(-PLR_MAXV, PLR_MAXV)
    w.b.vx, w.b.vy = fr(-PLR_MAXV, PLR_MAXV), fr(-PLR_MAXV, PLR_MAXV)
    return w


def _gen_dataset(rng, n):
    X = np.zeros((n, N_IN)); Y = np.zeros((n, N_OUT))
    for k in range(n):
        w = _random_state(rng)
        side = "b" if rng.rand() < 0.5 else "a"
        X[k, :N_OBS] = w.observe(side)        # memória (resto da entrada) fica 0
        tx, ty, kick = heuristic_action(w, side)
        if side == "b":   # canoniza o alvo (a rede pensa no frame +x)
            tx = -tx
        Y[k, 0], Y[k, 1], Y[k, 2] = tx, ty, (1.0 if kick else -1.0)  # ação; memória=0
    return X, Y


def pretrain_imitator(epochs=900, batch=256, lr=0.08, momentum=0.9, seed=0):
    """Treina (backprop + momentum) um Brain pra imitar heuristic_action. Um
    dataset fixo grande + minibatches; devolve o Brain imitador."""
    rng = np.random.RandomState(seed)
    Xall, Yall = _gen_dataset(rng, 8000)
    brain = Brain()
    vW = [np.zeros_like(w) for w in brain.weights]
    vB = [np.zeros_like(b) for b in brain.biases]
    n = Xall.shape[0]
    for ep in range(epochs):
        idx = rng.randint(0, n, batch)
        X, Y = Xall[idx], Yall[idx]
        acts = [X]
        a = X
        for W, b in zip(brain.weights, brain.biases):
            a = np.tanh(a @ W + b)
            acts.append(a)
        delta = (acts[-1] - Y) * (1.0 - acts[-1] ** 2) / batch
        for i in range(len(brain.weights) - 1, -1, -1):
            gW = acts[i].T @ delta
            gb = delta.sum(axis=0, keepdims=True)
            if i > 0:
                delta = (delta @ brain.weights[i].T) * (1.0 - acts[i] ** 2)
            vW[i] = momentum * vW[i] - lr * gW
            vB[i] = momentum * vB[i] - lr * gb
            brain.weights[i] += vW[i]
            brain.biases[i] += vB[i]
    return brain


# ========================= persistência (jogar contra) =========================

def save_path():
    return config.REPO_ROOT / "haxball_ai.json"


def save_brain(brain: Brain, generation=0, winrate=0.0, brain_l=None) -> bool:
    """Grava o campeão DIREITA ('brain' — o adversário do jogo). Opcionalmente
    grava o campeão ESQUERDA ('brain_l') pra o treino continuar os DOIS lados."""
    try:
        data = {"brain": brain.to_dict(), "generation": generation,
                "winrate": round(float(winrate), 3)}
        if brain_l is not None:
            data["brain_l"] = brain_l.to_dict()
        save_path().write_text(json.dumps(data), encoding="utf-8")
        return True
    except Exception:
        return False


def load_brain():
    try:
        d = json.loads(save_path().read_text(encoding="utf-8"))
        brain = Brain.from_dict(d["brain"])
        if brain.sizes[0] != N_IN or brain.sizes[-1] != N_OUT:
            return None, None      # arquitetura mudou -> ignora (recomeça limpo)
        return brain, d
    except Exception:
        return None, None
