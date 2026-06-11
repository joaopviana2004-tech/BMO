"""Neuroevolução do Flappy: rede neural minúscula + algoritmo genético.

Compartilhado entre a tela de TREINO (screens/flappy_train.py) e o jogo
(screens/flappy.py) — aqui ficam a física do mundo, a rede do pássaro, o GA e o
salvar/carregar do melhor cérebro (pra "jogar contra" no jogo).

Tudo é Python puro (sem numpy nos hot-loops) e a rede é 2->H->1, então roda
leve no Pi. Entradas do pássaro (normalizadas, é o que a viz mostra):
    in0 = distância horizontal até o próximo cano
    in1 = diferença de altura entre o pássaro e o centro do vão do cano
Saída > 0  =>  bate asa.
"""
from __future__ import annotations

import json
import math
import random

from ..core import config
from ..core.theme import LOGICAL_SIZE

# ---------- arena / física (FONTE ÚNICA — flappy.py importa daqui) ----------
W, H = LOGICAL_SIZE
GROUND_Y = H - 14
CEIL_Y = 0
GRAVITY = 520.0
FLAP_V = -175.0
MAX_FALL = 260.0
BIRD_X = 84
BIRD_R = 6
PIPE_W = 26
PIPE_GAP = 76
PIPE_SPEED = 96.0
PIPE_SPACING = 150
GAP_MARGIN = 30

# ---------- rede neural ----------
N_INPUTS = 2
N_HIDDEN = 5
N_OUTPUTS = 1
W_CLAMP = 4.0


def _rand() -> float:
    return random.uniform(-1.0, 1.0)


class Brain:
    """MLP 2->H->1 com tanh no hidden e no output. Pesos achatados em listas."""

    def __init__(self, w_ih=None, b_h=None, w_ho=None, b_o=None) -> None:
        self.w_ih = w_ih if w_ih is not None else [_rand() for _ in range(N_INPUTS * N_HIDDEN)]
        self.b_h = b_h if b_h is not None else [_rand() for _ in range(N_HIDDEN)]
        self.w_ho = w_ho if w_ho is not None else [_rand() for _ in range(N_HIDDEN * N_OUTPUTS)]
        self.b_o = b_o if b_o is not None else [_rand() for _ in range(N_OUTPUTS)]

    def forward(self, inputs):
        """Devolve (saida, ativacoes_hidden) — o hidden é usado pela viz."""
        hid = []
        for j in range(N_HIDDEN):
            s = self.b_h[j]
            for i in range(N_INPUTS):
                s += inputs[i] * self.w_ih[i * N_HIDDEN + j]
            hid.append(math.tanh(s))
        s = self.b_o[0]
        for j in range(N_HIDDEN):
            s += hid[j] * self.w_ho[j]
        return math.tanh(s), hid

    def flaps(self, inputs) -> bool:
        out, _ = self.forward(inputs)
        return out > 0.0

    def copy(self) -> "Brain":
        return Brain(list(self.w_ih), list(self.b_h), list(self.w_ho), list(self.b_o))

    def mutate(self, rate=0.12, scale=0.45) -> None:
        for lst in (self.w_ih, self.b_h, self.w_ho, self.b_o):
            for k in range(len(lst)):
                if random.random() < rate:
                    lst[k] = max(-W_CLAMP, min(W_CLAMP, lst[k] + random.gauss(0, scale)))

    def to_dict(self) -> dict:
        return {"w_ih": self.w_ih, "b_h": self.b_h, "w_ho": self.w_ho,
                "b_o": self.b_o, "n_inputs": N_INPUTS, "n_hidden": N_HIDDEN}

    @classmethod
    def from_dict(cls, d: dict) -> "Brain":
        return cls(d["w_ih"], d["b_h"], d["w_ho"], d["b_o"])


def crossover(a: Brain, b: Brain) -> Brain:
    """Filho com cada gene vindo (50/50) de um dos pais."""
    def mix(la, lb):
        return [la[k] if random.random() < 0.5 else lb[k] for k in range(len(la))]
    return Brain(mix(a.w_ih, b.w_ih), mix(a.b_h, b.b_h),
                 mix(a.w_ho, b.w_ho), mix(a.b_o, b.b_o))


def sense(bird_y, pipe_x, gap_y):
    """Entradas normalizadas do pássaro. MESMA função usada no treino e no jogo
    (garante que o cérebro salvo se comporte igual nos dois)."""
    dx = (pipe_x - BIRD_X) / W            # distância até o cano (~0..1+)
    dy = (gap_y - bird_y) / H             # vão acima (>0) ou abaixo (<0) do pássaro
    return [dx, dy]


# ---------- mundo headless (treino) ----------

class World:
    """Canos compartilhados + N pássaros. Avança a física de todos os vivos.

    Os canos são os mesmos pra todos os pássaros (comparação justa) — é o que
    permite renderizar vários pássaros sobre o mesmo cenário.
    """

    def __init__(self, n: int, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.reset(n)

    def reset(self, n: int) -> None:
        self.birds = [{"y": H / 2, "vel": 0.0, "alive": True, "fitness": 0.0}
                      for _ in range(n)]
        self.pipes = []
        x = W + 40
        for _ in range(3):
            self.pipes.append(self._make_pipe(x))
            x += PIPE_SPACING
        self.alive = n
        self.score = 0          # canos passados nesta geração (pelo grupo)
        self.t = 0.0

    def _make_pipe(self, x: float) -> dict:
        gap_y = self.rng.randint(CEIL_Y + GAP_MARGIN + PIPE_GAP // 2,
                                 GROUND_Y - GAP_MARGIN - PIPE_GAP // 2)
        return {"x": float(x), "gap_y": gap_y, "scored": False}

    def next_pipe(self) -> dict | None:
        """Primeiro cano cuja borda direita ainda não passou do pássaro."""
        for p in self.pipes:
            if p["x"] + PIPE_W >= BIRD_X:
                return p
        return self.pipes[0] if self.pipes else None

    def step(self, dt: float, brains: list) -> None:
        p = self.next_pipe()
        gap_y = p["gap_y"] if p else H / 2
        pipe_x = p["x"] if p else float(W)
        for i, b in enumerate(self.birds):
            if not b["alive"]:
                continue
            if brains[i].flaps(sense(b["y"], pipe_x, gap_y)):
                b["vel"] = FLAP_V
            b["vel"] = min(MAX_FALL, b["vel"] + GRAVITY * dt)
            b["y"] += b["vel"] * dt
            b["fitness"] += dt
            if b["y"] >= GROUND_Y - BIRD_R or b["y"] < CEIL_Y + BIRD_R or self._hit(b, p):
                b["alive"] = False
                self.alive -= 1
        # move canos + pontua (bônus de aptidão pra quem ainda está vivo)
        for q in self.pipes:
            q["x"] -= PIPE_SPEED * dt
            if not q["scored"] and q["x"] + PIPE_W < BIRD_X:
                q["scored"] = True
                self.score += 1
                for b in self.birds:
                    if b["alive"]:
                        b["fitness"] += 8.0
        self.pipes = [q for q in self.pipes if q["x"] + PIPE_W > -4]
        while len(self.pipes) < 3:
            last_x = max((q["x"] for q in self.pipes), default=float(W))
            self.pipes.append(self._make_pipe(last_x + PIPE_SPACING))
        self.t += dt

    @staticmethod
    def _hit(b: dict, p: dict | None) -> bool:
        if p is None:
            return False
        if p["x"] > BIRD_X + BIRD_R or p["x"] + PIPE_W < BIRD_X - BIRD_R:
            return False
        gap_top = p["gap_y"] - PIPE_GAP // 2
        gap_bot = p["gap_y"] + PIPE_GAP // 2
        return (b["y"] - BIRD_R) < gap_top or (b["y"] + BIRD_R) > gap_bot

    def top_alive(self, k: int) -> list[int]:
        """Índices de até k pássaros vivos, do mais apto pro menos apto."""
        alive = [i for i, b in enumerate(self.birds) if b["alive"]]
        alive.sort(key=lambda i: self.birds[i]["fitness"], reverse=True)
        return alive[:k]

    def best_index(self) -> int | None:
        """Pássaro vivo mais apto (ou o mais apto geral se todos morreram)."""
        idxs = range(len(self.birds))
        alive = [i for i in idxs if self.birds[i]["alive"]]
        pool = alive or list(idxs)
        if not pool:
            return None
        return max(pool, key=lambda i: self.birds[i]["fitness"])


def evolve(brains: list, fitnesses: list, elite: int = 1, mutate_rate: float = 0.12):
    """Próxima geração: elitismo + crossover de pais bons (torneio) + mutação.

    Devolve (proxima_geracao, melhor_cerebro_da_geracao_atual)."""
    n = len(brains)
    order = sorted(range(n), key=lambda i: fitnesses[i], reverse=True)
    ranked = [brains[i] for i in order]
    best = ranked[0].copy()
    nxt = [ranked[i].copy() for i in range(min(elite, n))]   # elitismo
    pool = ranked[:max(2, n // 2)]                            # metade superior reproduz
    while len(nxt) < n:
        pa, pb = random.choice(pool), random.choice(pool)
        child = crossover(pa, pb)
        child.mutate(mutate_rate)
        nxt.append(child)
    return nxt, best


# ---------- persistência do melhor cérebro ("jogar contra") ----------

def save_path():
    return config.REPO_ROOT / "flappy_ai.json"


def save_brain(brain: Brain, generation: int = 0, record: int = 0) -> bool:
    try:
        data = {"brain": brain.to_dict(), "generation": generation, "record": record}
        save_path().write_text(json.dumps(data), encoding="utf-8")
        return True
    except Exception:
        return False


def load_brain():
    """Devolve (Brain, meta) do arquivo salvo, ou (None, None) se não existe."""
    try:
        d = json.loads(save_path().read_text(encoding="utf-8"))
        return Brain.from_dict(d["brain"]), d
    except Exception:
        return None, None
