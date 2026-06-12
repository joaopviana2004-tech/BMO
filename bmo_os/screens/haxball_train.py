"""Treino de IA do Haxball — em tempo real (você assiste).

Grid 3×4 de 12 mini-quadras NA PROPORÇÃO DO CAMPO (paisagem, igual ao jogo): em
cada uma um agente DIREITA (rede neural, azul) enfrenta o jogador HEURÍSTICO
(vermelho, sparring forte). A quadra fica VERDE quando o lado direito (a IA que
você treina) está ganhando e VERMELHA quando o heurístico ganha. O placar aparece
GIGANTE e translúcido atrás dos jogadores. Painel à direita: os NÓS da rede do
melhor agente (ao vivo) + estatísticas + gráfico de vitórias.

Treino vs-HEURÍSTICO (em vez de self-play): o oponente é FIXO e forte, então o
fitness é ABSOLUTO (quanto a IA bate o heurístico) — não regride como a
co-evolução. As redes nascem seedadas de um imitador do heurístico; um currículo
de gol que encolhe (largo → 60px) faz os gols aparecerem. O melhor da direita é
salvo pra você "jogar contra".

Recompensa = progresso da bola ao gol + gols; GOL CONTRA pune pesado (e ninguém
ganha de graça). Roda a 30 FPS com 2 passos de física por frame.
"""
from __future__ import annotations

import random
import time

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..services import audio
from ..services import haxball_ai as hai
from ..services.haxball_ai import (
    FIELD_L, FIELD_T, FIELD_W, FIELD_H, CX, PLR_ACCEL, PLR_MAXV,
)

W, H = LOGICAL_SIZE

# ---------- GA / layout ----------
COLS, ROWS = 3, 4
POP = COLS * ROWS          # 12 redes (direita), todas visíveis
MATCH_TIME = 12.0          # segundos de simulação por geração (partidas mais longas)
SUBSTEPS = 2               # passos de física por frame (treina ~2x mais rápido)
ELITE = 2
GAP = 3
COURT_X0, COURT_Y0 = 2, 17
CW = (300 - 2 * GAP) // COLS              # ~98
CH = int(CW * FIELD_H / FIELD_W)          # ~52 — MESMA proporção do campo (paisagem)
PANEL = pygame.Rect(302, 17, 96, 240 - 17 - 4)

# ---------- paleta ----------
BG = (10, 12, 16)
GREEN_T = (18, 52, 28)     # direita (IA) ganhando
RED_T = (54, 22, 22)       # heurístico ganhando
LINE = (70, 90, 76)
WHITE = (238, 238, 238)
DIM = (120, 128, 138)
REDC = (232, 84, 72)       # heurístico (esquerda)
BLUEC = (92, 152, 240)     # IA (direita)
BALLC = (245, 245, 245)

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
        b.mutate(0.25, 0.25)
        pop.append(b)
    return pop


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
        self._heatmaps = {}              # funil de potencial por largura de gol (cache)
        self._init_population(from_saved=True)

    def _init_population(self, from_saved: bool) -> None:
        base = None
        if from_saved:
            saved, meta = hai.load_brain()
            if saved is not None:
                base = saved
                self._loaded_from = "salvo (gen %s)" % (meta.get("generation", "?") if meta else "?")
        if base is None:
            base = _get_imitator()
            self._loaded_from = "imitador"
        self.pop = _seed_pop(base)           # população da DIREITA (a IA)
        self.champion = base.copy()          # melhor da direita (o SALVAR grava)
        self.gen = 1
        self.total_goals = 0                 # gols da IA (drives o currículo + fase)
        self.conceded = 0                    # gols do heurístico
        self.own_goals = 0
        self.best_fit = 0.0
        self.right_wins = 0                  # quadras com a IA na frente (última ger.)
        self.history = []                    # % de vitórias da IA por geração
        # CURRÍCULO: o oponente começa fraco (quase dummy) e fica mais forte
        # conforme a IA domina — um sparring que acompanha o nível dela.
        self._opp_strength = 0.30
        self._new_generation()

    def _goal_h(self) -> int:
        # gol levemente mais largo que o real (menos flukes de gol-contra que o 130)
        return max(60, 84 - self.total_goals // 3)

    # ---------- geração ----------

    def _new_generation(self) -> None:
        gh = self._goal_h()
        self.courts = []
        for i in range(POP):
            w = hai.HaxWorld(goal_h=gh)
            self.courts.append({
                "w": w, "ri": i, "fb": 0.0,
                "ppot": hai.goal_potential(w.ball.x, w.ball.y, w.goal_top, w.goal_bot),
                "mem": [0.0] * hai.MEM,          # memória de curto prazo da IA
            })
        self._t_gen = 0.0
        self._gen_own = 0

    def _end_generation(self) -> None:
        fits = [0.0] * POP
        goals = conc = wins = 0
        for c in self.courts:
            fits[c["ri"]] += c["fb"]
            goals += c["w"].score_b
            conc += c["w"].score_a
            if c["w"].score_b > c["w"].score_a:
                wins += 1
        self.total_goals += goals
        self.conceded += conc
        self.own_goals += self._gen_own
        self.right_wins = wins
        # currículo adaptativo: pelo SALDO de gols da geração. Se a IA domina (até
        # via flukes do oponente fraco), fortalece o oponente -> ele para de
        # presentear e a IA precisa marcar de verdade. Se apanha, alivia.
        if goals > conc + 12:
            self._opp_strength = min(1.0, self._opp_strength + 0.05)
        elif goals < conc + 2:
            self._opp_strength = max(0.30, self._opp_strength - 0.03)
        self.best_fit = max(fits) if fits else 0.0
        self.history.append(self.best_fit)     # curva de fitness (controle de bola) por geração
        self.history = self.history[-120:]
        self.champion = self.pop[max(range(POP), key=lambda i: fits[i])].copy()
        rate, scale = hai.phase_params(self.total_goals)
        self.pop, _ = hai.evolve(self.pop, fits, ELITE, rate, scale, 0.25)
        self.pop[ELITE] = self.champion.copy()    # campeão sempre compete (anti-regressão)
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
            if hai.save_brain(self.champion, self.gen, wr):
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
            al = hai.heuristic_action(w, "a")                  # esquerda = heurístico (ax,ay,chute)
            # IA (direita): ação + memória de curto prazo realimentada
            ax_b, ay_b, kick_b, c["mem"] = hai.brain_action(self.pop[c["ri"]], w, "b", c["mem"])
            s = self._opp_strength       # oponente na força do CURRÍCULO
            goal = w.step(dt, al[0], al[1], ax_b, ay_b, al[2], kick_b,
                          a_accel=PLR_ACCEL * s, a_maxv=PLR_MAXV * s,
                          b_accel=PLR_ACCEL, b_maxv=PLR_MAXV)
            # recompensa = SUBIDA do POTENCIAL (funil ao gol) — a matriz de pontuação
            pot = hai.goal_potential(w.ball.x, w.ball.y, w.goal_top, w.goal_bot)
            c["fb"] += (pot - c["ppot"]) * 25.0
            c["ppot"] = pot
            if goal == "B":                # gol no gol ESQUERDO (a IA ataca aqui)
                w.score_b += 1             # CONTA no placar da quadra (azul/IA)
                if (w.t - w.t_touch_b) < 0.6:   # IA tocou recente -> criou o gol (até desvio do goleiro conta)
                    c["fb"] += 20.0
                else:
                    c["fb"] -= 10.0; self._gen_own += 1   # fluke do heurístico sozinho (sem brinde)
                w.kickoff(); c["mem"] = [0.0] * hai.MEM
                c["ppot"] = hai.goal_potential(w.ball.x, w.ball.y, w.goal_top, w.goal_bot)
            elif goal == "A":              # gol no gol DIREITO (a IA sofreu)
                w.score_a += 1             # CONTA no placar da quadra (vermelho/heurístico)
                if w.t_touch_b > w.t_touch_a:   # IA tocou por ÚLTIMO -> empurrou pro PRÓPRIO gol
                    c["fb"] -= 20.0; self._gen_own += 1   # GOL CONTRA -> penalidade pesada
                else:
                    c["fb"] -= 8.0         # heurístico marcou de verdade
                w.kickoff(); c["mem"] = [0.0] * hai.MEM
                c["ppot"] = hai.goal_potential(w.ball.x, w.ball.y, w.goal_top, w.goal_bot)

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
            surface.blit(img, img.get_rect(midbottom=(150, H - 1)))

    def _draw_court(self, surface, cell, w) -> None:
        adv = w.score_b - w.score_a
        if adv == 0:
            adv = 1 if w.ball.x < CX else -1     # empate: quem está pressionando
        # FUNDO = matriz de pontuação (funil): mais claro perto do gol esquerdo,
        # mostrando pra IA o "caminho" da bola ao gol que ela ataca.
        surface.blit(self._ensure_heatmap(w.goal_top, w.goal_bot), cell)
        tint = pygame.Surface((cell.w, cell.h))   # tom de quem está ganhando por cima
        tint.set_alpha(70); tint.fill(GREEN_T if adv > 0 else RED_T)
        surface.blit(tint, cell)
        pygame.draw.rect(surface, (40, 46, 50), cell, 1)
        # placar GIGANTE translúcido (atrás dos jogadores)
        self._big_score(surface, cell, str(w.score_a), REDC, cell.x + cell.w * 0.28)
        self._big_score(surface, cell, str(w.score_b), BLUEC, cell.x + cell.w * 0.72)
        # linha do meio + bocas do gol
        midx = cell.x + cell.w // 2
        pygame.draw.line(surface, LINE, (midx, cell.y), (midx, cell.bottom), 1)
        sy = cell.h / FIELD_H
        gy0 = int(cell.y + (w.goal_top - FIELD_T) * sy)
        gy1 = int(cell.y + (w.goal_bot - FIELD_T) * sy)
        pygame.draw.line(surface, WHITE, (cell.left, gy0), (cell.left, gy1), 1)
        pygame.draw.line(surface, WHITE, (cell.right - 1, gy0), (cell.right - 1, gy1), 1)
        # jogadores POR CIMA do placar
        self._dot(surface, cell, w.a, REDC, 2)
        self._dot(surface, cell, w.b, BLUEC, 2)
        self._dot(surface, cell, w.ball, BALLC, 1)

    def _ensure_heatmap(self, goal_top, goal_bot):
        """Constrói (e cacheia) o funil de potencial pro gol ESQUERDO como uma
        imagem do tamanho da quadra. Verde escuro = longe; verde claro = boca do
        gol — é a 'matriz de pontuação' que guia a IA igual a um funil."""
        key = (int(goal_top), int(goal_bot))
        cached = self._heatmaps.get(key)
        if cached is not None:
            return cached
        GW, GH = 40, 21
        small = pygame.Surface((GW, GH))
        cells = []
        for gx in range(GW):
            for gy in range(GH):
                fx = FIELD_L + (gx + 0.5) / GW * FIELD_W
                fy = FIELD_T + (gy + 0.5) / GH * FIELD_H
                cells.append((gx, gy, hai.goal_potential(fx, fy, goal_top, goal_bot)))
        lo = min(v for _, _, v in cells); hi = max(v for _, _, v in cells)
        rng = (hi - lo) or 1.0
        for gx, gy, v in cells:
            t = (v - lo) / rng                  # 0 longe -> 1 na boca do gol esq
            small.set_at((gx, gy), (int(10 + 8 * t), int(26 + 78 * t), int(18 + 16 * t)))
        img = pygame.transform.scale(small, (CW, CH))
        self._heatmaps[key] = img
        return img

    @staticmethod
    def _big_score(surface, cell, text, color, cx) -> None:
        img = render_text(text, 30, color)      # número grande (fonte pixel)
        img.set_alpha(90)                        # translúcido
        surface.blit(img, img.get_rect(center=(int(cx), cell.centery)))

    @staticmethod
    def _dot(surface, cell, d, color, r) -> None:
        px = int(cell.x + (d.x - FIELD_L) * cell.w / FIELD_W)
        py = int(cell.y + (d.y - FIELD_T) * cell.h / FIELD_H)
        pygame.draw.circle(surface, color, (px, py), r)

    def _draw_top(self, surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, BG, rect); pygame.draw.rect(surface, WHITE, rect, 1)
        surface.blit(render_text("HOME", 7, WHITE, pixel=False), (rect.left + 4, rect.top + 3))
        t = render_text("HAXBALL IA  GER %d" % self.gen, 8, DIM, pixel=False)
        surface.blit(t, t.get_rect(midtop=(150, 3)))
        for key in self._buttons:
            r = self._btn_rect(key); sel = self._buttons[self._sel] == key
            if sel:
                pygame.draw.rect(surface, WHITE, r); fg = BG
            else:
                pygame.draw.rect(surface, DIM, r, 1); fg = DIM
            img = render_text(key.upper(), 7, fg, pixel=False)
            surface.blit(img, img.get_rect(center=r.center))

    def _draw_panel(self, surface) -> None:
        pygame.draw.rect(surface, (6, 8, 12), PANEL)
        pygame.draw.rect(surface, (40, 46, 50), PANEL, 1)
        net_h = 110
        self._draw_net(surface, pygame.Rect(PANEL.x, PANEL.y, PANEL.w, net_h))
        x = PANEL.x + 5
        y = PANEL.y + net_h + 2
        lines = [
            ("gols IA: %d" % self.total_goals, BLUEC),
            ("sofridos: %d" % self.conceded, REDC),
            ("gol contra: %d" % self.own_goals, DIM),
            ("vit %d/%d  gol %dpx" % (self.right_wins, POP, self._goal_h()), WHITE),
            ("fit %.0f  oponente %d%%" % (self.best_fit, int(self._opp_strength * 100)), WHITE),
        ]
        for i, (txt, col) in enumerate(lines):
            surface.blit(render_text(txt, 7, col, pixel=False), (x, y + i * 10))
        self._draw_graph(surface, pygame.Rect(x, y + 54, PANEL.w - 10, 22))

    def _draw_graph(self, surface, box) -> None:
        surface.blit(render_text("fitness/ger", 6, DIM, pixel=False), (box.x, box.y - 8))
        pygame.draw.rect(surface, (40, 46, 50), box, 1)
        if len(self.history) < 2:
            return
        peak = max(max(self.history), 1.0)
        n = len(self.history)
        pts = [(box.x + 1 + int(i * (box.w - 3) / (n - 1)),
                box.bottom - 1 - int(max(0.0, v) / peak * (box.h - 3))) for i, v in enumerate(self.history)]
        pygame.draw.lines(surface, BLUEC, False, pts, 1)

    def _draw_net(self, surface, box) -> None:
        surface.blit(render_text("REDE (nos)", 7, DIM, pixel=False), (box.x + 4, box.y + 2))
        bc = max(self.courts, key=lambda c: c["fb"]) if self.courts else None
        brain = self.pop[bc["ri"]] if bc else self.champion
        acts = getattr(brain, "last", None)
        sizes = brain.sizes
        cols = len(sizes)
        xs = [box.x + 12 + int(i * (box.w - 24) / (cols - 1)) for i in range(cols)]
        top, bot = box.y + 14, box.bottom - 6
        # SÓ OS NÓS (sem arestas), brilho pela ativação
        for li, sz in enumerate(sizes):
            ys = [(top + bot) // 2] if sz == 1 else [int(top + k * (bot - top) / (sz - 1)) for k in range(sz)]
            for k, y in enumerate(ys):
                act = float(acts[li][k]) if (acts is not None and li < len(acts) and k < len(acts[li])) else 0.0
                m = int(55 + min(1.0, abs(act)) * 200)
                fill = (0, m, int(m * 0.4)) if act >= 0 else (m, 0, 0)
                pygame.draw.circle(surface, fill, (xs[li], y), 2)
