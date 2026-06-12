"""Treino de IA do Haxball — co-evolução em tempo real (você assiste).

Grid 3x3 de mini-quadras: em cada uma um agente ESQUERDA joga contra um DIREITA
(redes neurais). A quadra fica VERDE quando o lado DIREITO está ganhando e
VERMELHA quando o ESQUERDO ganha. Painel à direita: a rede neural do melhor
agente da direita + estatísticas (geração, gols, vitórias, melhor fitness).

Bootstrap: as populações nascem SEEDADAS — do último campeão SALVO (continua o
treino de onde parou) ou, se não houver, de um imitador pré-treinado de um
jogador heurístico (assim os agentes já engajam a bola desde o início, em vez de
ficar parados). A co-evolução refina por cima; o melhor da DIREITA é o que o
SALVAR grava pra você "jogar contra" no Haxball normal.

Recompensa: progresso da BOLA rumo ao gol adversário + gols (sem premiar toque
ou andar — isso é farmável ficando na quina, como o repo de referência sofria).
Roda a 30 FPS com 2 passos de física por frame pra não esquentar a Pi.
"""
from __future__ import annotations

import math
import random
import time

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..services import audio
from ..services import haxball_ai as hai
from ..services.haxball_ai import (
    FIELD_L, FIELD_T, FIELD_W, FIELD_H, FIELD_R, FIELD_B, CX, CY,
    GOAL_TOP, GOAL_BOT, PLR_ACCEL, PLR_MAXV,
)

W, H = LOGICAL_SIZE

# ---------- GA / layout ----------
COLS, ROWS = 3, 4
POP = COLS * ROWS          # 12 por lado (todas as quadras visíveis)
MATCH_TIME = 7.0           # segundos de simulação por geração
SUBSTEPS = 2               # passos de física por frame (treina ~2x mais rápido)
ELITE = 2
GAP = 3
COURT_X0, COURT_Y0 = 2, 17
CW = (300 - 2 * GAP) // COLS              # ~98
CH = int(CW * FIELD_H / FIELD_W)          # ~52 — MESMA proporção do campo/BMO (paisagem)
PANEL = pygame.Rect(302, 17, 96, 240 - 17 - 4)

# ---------- paleta ----------
BG = (10, 12, 16)
GREEN_T = (18, 52, 28)     # direita ganhando
RED_T = (54, 22, 22)       # esquerda ganhando
LINE = (70, 90, 76)
WHITE = (238, 238, 238)
DIM = (120, 128, 138)
REDC = (232, 84, 72)
BLUEC = (92, 152, 240)
BALLC = (245, 245, 245)

# imitador pré-treinado uma vez por sessão (semente padrão)
_IMITATOR = None


def _get_imitator():
    global _IMITATOR
    if _IMITATOR is None:
        _IMITATOR = hai.pretrain_imitator()
    return _IMITATOR


def _seed_pop(base):
    pop = [base.copy()]
    for _ in range(POP - 1):
        b = base.copy()
        b.mutate(0.25, 0.25)     # diversidade (mantém 1 cópia exata)
        pop.append(b)
    return pop


def _ball_goal_dist(world, side):
    gx = FIELD_L if side == "b" else FIELD_R
    return math.hypot(world.ball.x - gx, world.ball.y - CY)


class HaxballTrainScreen:
    voice_announce = "Treinando o time."
    preferred_fps = 30

    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self._buttons = ["reiniciar", "salvar"]
        self._sel = 0
        self._status = ""
        self._status_until = 0.0
        self._loaded_from = "imitador"
        self._init_population(from_saved=True)

    def _init_population(self, from_saved: bool) -> None:
        base_r = base_l = None
        if from_saved:
            saved, meta = hai.load_brain()
            if saved is not None:
                base_r = saved
                self._loaded_from = "salvo (gen %s)" % (meta.get("generation", "?") if meta else "?")
                if meta and meta.get("brain_l"):
                    try:
                        base_l = hai.Brain.from_dict(meta["brain_l"])
                    except Exception:
                        base_l = None
        if base_r is None:
            base_r = _get_imitator()
            self._loaded_from = "imitador"
        if base_l is None:
            base_l = base_r                # frame canônico: o da direita serve pros 2 lados
        self.pop_l = _seed_pop(base_l)
        self.pop_r = _seed_pop(base_r)
        # campeões SEPARADOS por lado — divergem (assimetria) pra sair gol
        self.champion_l = base_l.copy()
        self.champion_r = base_r.copy()    # é o que o SALVAR grava (adversário)
        self.gen = 1
        self.total_goals = 0               # gols acumulados (fase de mutação + currículo)
        self.best_fit = 0.0
        self.right_wins = 0                # quadras da última ger. com direita na frente
        self.history = []                  # % de vitórias da direita por geração
        self._new_generation()

    def _goal_h(self) -> int:
        # currículo: gol largo no começo (gols acontecem) -> estreita até 60 real
        return max(60, 140 - self.total_goals // 2)

    # ---------- geração ----------

    def _new_generation(self) -> None:
        perm = list(range(POP))
        random.shuffle(perm)
        self.courts = []
        gh = self._goal_h()
        for i in range(POP):
            w = hai.HaxWorld(goal_h=gh)
            self.courts.append({
                "w": w, "li": i, "ri": perm[i], "fa": 0.0, "fb": 0.0,
                "pda": _ball_goal_dist(w, "a"), "pdb": _ball_goal_dist(w, "b"),
            })
        self._t_gen = 0.0
        self._own_goals = 0    # gols contra nesta geração (deve ficar ~0 c/ a penalidade)

    def _end_generation(self) -> None:
        fit_l = [0.0] * POP
        fit_r = [0.0] * POP
        goals = 0
        wins = 0
        for c in self.courts:
            fit_l[c["li"]] += c["fa"]
            fit_r[c["ri"]] += c["fb"]
            goals += c["w"].score_a + c["w"].score_b
            if c["w"].score_b > c["w"].score_a:
                wins += 1
        self.total_goals += goals
        self.right_wins = wins
        self.best_fit = max(fit_r) if fit_r else 0.0
        self.history.append(wins / POP)
        self.history = self.history[-120:]
        # campeões SEPARADOS (o melhor de cada lado nesta geração)
        self.champion_l = self.pop_l[max(range(POP), key=lambda i: fit_l[i])].copy()
        self.champion_r = self.pop_r[max(range(POP), key=lambda i: fit_r[i])].copy()
        # evolui (mutação adaptativa por fase, igual ideia do repo)
        rate, scale = hai.phase_params(self.total_goals)
        self.pop_l, _ = hai.evolve(self.pop_l, fit_l, ELITE, rate, scale, 0.25)
        self.pop_r, _ = hai.evolve(self.pop_r, fit_r, ELITE, rate, scale, 0.25)
        # injeta cada campeão na SUA pop (deixa os lados divergirem -> assimetria)
        self.pop_l[ELITE] = self.champion_l.copy()
        self.pop_r[ELITE] = self.champion_r.copy()
        self.gen += 1
        self._new_generation()

    # ---------- input ----------

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        A = bmo_input.Action
        a = event.action
        if a in (A.B, A.MENU):
            audio.play("back"); self.on_back()
        elif a == A.LEFT:
            self._sel = (self._sel - 1) % len(self._buttons); audio.play("tick")
        elif a == A.RIGHT:
            self._sel = (self._sel + 1) % len(self._buttons); audio.play("tick")
        elif a == A.A:
            self._activate(self._buttons[self._sel])
        elif a == A.TAP and getattr(event, "pos", None):
            if self._back_btn().collidepoint(event.pos):
                audio.play("back"); self.on_back(); return
            for i, key in enumerate(self._buttons):
                if self._btn_rect(key).collidepoint(event.pos):
                    self._sel = i; self._activate(key); return

    def _activate(self, key: str) -> None:
        if key == "reiniciar":
            audio.play("select")
            self._init_population(from_saved=False)
            self._toast("Treino reiniciado (do zero)")
        elif key == "salvar":
            audio.play("select")
            wr = self.right_wins / POP
            if hai.save_brain(self.champion_r, self.gen, wr, brain_l=self.champion_l):
                self._toast("Campeao salvo! (jogar contra)")
            else:
                self._toast("Falha ao salvar")

    def _toast(self, msg: str) -> None:
        self._status = msg
        self._status_until = time.time() + 3.0

    # ---------- update ----------

    def update(self, dt: float) -> None:
        dt = min(dt, 0.05)
        for _ in range(SUBSTEPS):
            self._step_courts(dt)
            self._t_gen += dt
            if self._t_gen >= MATCH_TIME:
                self._end_generation()
                break

    def _step_courts(self, dt: float) -> None:
        for c in self.courts:
            w = c["w"]
            al = hai.brain_action(self.pop_l[c["li"]], w, "a")
            ar = hai.brain_action(self.pop_r[c["ri"]], w, "b")
            goal = w.step(dt, al[0], al[1], ar[0], ar[1],
                          b_accel=PLR_ACCEL, b_maxv=PLR_MAXV)
            da, db = _ball_goal_dist(w, "a"), _ball_goal_dist(w, "b")
            # recompensa = progresso da BOLA rumo ao gol adversário (potencial)
            c["fa"] += (c["pda"] - da) * 0.04
            c["fb"] += (c["pdb"] - db) * 0.04
            c["pda"], c["pdb"] = da, db
            if goal:
                # GOL CONTRA = quem fez gol não foi quem encostou por último na
                # direção certa: o defensor empurrou pra PRÓPRIA meta. Pune os
                # DOIS pesado (e ninguém ganha de graça) — assim quase não aparece.
                scorer = "a" if goal == "A" else "b"
                if w.last_touch == scorer:
                    c["fa" if scorer == "a" else "fb"] += 20.0   # gol legítimo
                    c["fb" if scorer == "a" else "fa"] -= 8.0    # o outro sofreu
                else:
                    c["fa"] -= 15.0; c["fb"] -= 15.0             # gol contra: pune os 2
                    self._own_goals += 1
                w.kickoff()
                c["pda"], c["pdb"] = _ball_goal_dist(w, "a"), _ball_goal_dist(w, "b")

    # ---------- layout ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(4, 2, 52, 14)

    def _btn_rect(self, key: str) -> pygame.Rect:
        return pygame.Rect(W - 134 if key == "reiniciar" else W - 60, 2,
                           70 if key == "reiniciar" else 56, 14)

    def _cell(self, i: int) -> pygame.Rect:
        r, c = i // COLS, i % COLS
        return pygame.Rect(COURT_X0 + c * (CW + GAP), COURT_Y0 + r * (CH + GAP), CW, CH)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        for i, c in enumerate(self.courts):
            self._draw_court(surface, self._cell(i), c["w"])
        self._draw_panel(surface)
        self._draw_top(surface)
        if self._status and time.time() < self._status_until:
            img = render_text(self._status, 8, WHITE, pixel=False)
            surface.blit(img, img.get_rect(midbottom=(140, H - 1)))

    def _draw_court(self, surface, cell, w) -> None:
        adv = w.score_b - w.score_a
        if adv == 0:
            adv = 1 if w.ball.x < CX else -1     # empate: quem está pressionando
        pygame.draw.rect(surface, GREEN_T if adv > 0 else RED_T, cell)
        pygame.draw.rect(surface, (40, 46, 50), cell, 1)
        midx = cell.x + cell.w // 2
        pygame.draw.line(surface, LINE, (midx, cell.y), (midx, cell.bottom), 1)
        # bocas do gol (segmentos claros nas laterais) — usa a boca da quadra (currículo)
        sy = cell.h / FIELD_H
        gy0 = int(cell.y + (w.goal_top - FIELD_T) * sy)
        gy1 = int(cell.y + (w.goal_bot - FIELD_T) * sy)
        pygame.draw.line(surface, WHITE, (cell.left, gy0), (cell.left, gy1), 1)
        pygame.draw.line(surface, WHITE, (cell.right - 1, gy0), (cell.right - 1, gy1), 1)
        self._dot(surface, cell, w.b, BLUEC, 2)
        self._dot(surface, cell, w.a, REDC, 2)
        self._dot(surface, cell, w.ball, BALLC, 1)
        # placar nas bordas: esquerda (vermelho) e direita (azul)
        surface.blit(render_text(str(w.score_a), 7, REDC, pixel=False), (cell.x + 2, cell.y))
        sb = render_text(str(w.score_b), 7, BLUEC, pixel=False)
        surface.blit(sb, sb.get_rect(topright=(cell.right - 2, cell.y)))

    @staticmethod
    def _dot(surface, cell, d, color, r) -> None:
        px = int(cell.x + (d.x - FIELD_L) * cell.w / FIELD_W)
        py = int(cell.y + (d.y - FIELD_T) * cell.h / FIELD_H)
        pygame.draw.circle(surface, color, (px, py), r)

    def _draw_top(self, surface) -> None:
        # HOME
        rect = self._back_btn()
        pygame.draw.rect(surface, BG, rect); pygame.draw.rect(surface, WHITE, rect, 1)
        surface.blit(render_text("HOME", 7, WHITE, pixel=False),
                     (rect.left + 4, rect.top + 3))
        # título
        t = render_text("HAXBALL IA  GER %d" % self.gen, 8, DIM, pixel=False)
        surface.blit(t, t.get_rect(midtop=(150, 3)))
        # botões
        for key in self._buttons:
            r = self._btn_rect(key); sel = self._buttons[self._sel] == key
            if sel:
                pygame.draw.rect(surface, WHITE, r); fg = BG
            else:
                pygame.draw.rect(surface, DIM, r, 1); fg = DIM
            surface.blit(render_text(key.upper(), 7, fg, pixel=False),
                         render_text(key.upper(), 7, fg, pixel=False).get_rect(center=r.center))

    def _draw_panel(self, surface) -> None:
        pygame.draw.rect(surface, (6, 8, 12), PANEL)
        pygame.draw.rect(surface, (40, 46, 50), PANEL, 1)
        # rede do campeão (metade de cima)
        net_h = 118
        self._draw_net(surface, pygame.Rect(PANEL.x, PANEL.y, PANEL.w, net_h))
        # estatísticas (metade de baixo)
        x = PANEL.x + 5
        y = PANEL.y + net_h + 2
        lines = [
            ("REDE DO MELHOR (dir)", DIM),
            ("seed: %s" % self._loaded_from, DIM),
            ("gols %d  contra %d" % (self.total_goals, self._own_goals), WHITE),
            ("vit.dir %d/%d  gol %dpx" % (self.right_wins, POP, self._goal_h()), BLUEC),
            ("melhor fit: %.0f" % self.best_fit, WHITE),
        ]
        # a 1a linha é título da rede (desenha acima do gráfico); resto aqui
        for i, (txt, col) in enumerate(lines[1:]):
            surface.blit(render_text(txt, 7, col, pixel=False), (x, y + i * 11))
        self._draw_winbar(surface, pygame.Rect(x, y + 48, PANEL.w - 10, 18))

    def _draw_winbar(self, surface, box) -> None:
        pygame.draw.rect(surface, (40, 46, 50), box, 1)
        surface.blit(render_text("vitorias direita/ger", 6, DIM, pixel=False),
                     (box.x, box.y - 8))
        if len(self.history) < 2:
            return
        n = len(self.history)
        pts = [(box.x + 1 + int(i * (box.w - 3) / (n - 1)),
                box.bottom - 1 - int(v * (box.h - 3))) for i, v in enumerate(self.history)]
        pygame.draw.lines(surface, BLUEC, False, pts, 1)

    def _draw_net(self, surface, box) -> None:
        surface.blit(render_text("REDE DO MELHOR", 7, DIM, pixel=False), (box.x + 4, box.y + 2))
        # melhor agente DIREITA jogando AGORA (ativações frescas deste frame)
        bc = max(self.courts, key=lambda c: c["fb"]) if self.courts else None
        brain = self.pop_r[bc["ri"]] if bc else self.champion_r
        acts = getattr(brain, "last", None)
        sizes = brain.sizes
        cols = len(sizes)
        xs = [box.x + 14 + int(i * (box.w - 28) / (cols - 1)) for i in range(cols)]
        top, bot = box.y + 14, box.bottom - 6
        ys = []
        for li, sz in enumerate(sizes):
            if sz == 1:
                ys.append([(top + bot) // 2])
            else:
                step = (bot - top) / (sz - 1)
                ys.append([int(top + k * step) for k in range(sz)])
        # arestas (cor pelo sinal do peso)
        for li in range(cols - 1):
            Wm = brain.weights[li]
            for a in range(sizes[li]):
                for b in range(sizes[li + 1]):
                    wv = Wm[a][b]
                    col = (40, 150, 70) if wv >= 0 else (160, 50, 50)
                    pygame.draw.line(surface, col, (xs[li], ys[li][a]), (xs[li + 1], ys[li + 1][b]), 1)
        # nós (brilho pela ativação, se houver)
        for li in range(cols):
            for k in range(sizes[li]):
                act = 0.0
                if acts is not None and li < len(acts) and k < len(acts[li]):
                    act = float(acts[li][k])
                m = int(60 + min(1.0, abs(act)) * 195)
                fill = (0, m, int(m * 0.4)) if act >= 0 else (m, 0, 0)
                pygame.draw.circle(surface, fill, (xs[li], ys[li][k]), 2)
