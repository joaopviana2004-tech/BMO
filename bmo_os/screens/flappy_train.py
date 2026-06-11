"""Treino do Flappy por neuroevolução — em tempo real, com viz da rede neural.

Uma população de pássaros (cada um com uma rede 2->5->1) joga ao mesmo tempo
sobre os mesmos canos. Quando todos morrem, o algoritmo genético cria a próxima
geração (elitismo + crossover + mutação). A tela mostra:
  - até 10 pássaros vivos por vez, cada um numa cor (enxame; o melhor destacado),
  - a rede neural do MELHOR pássaro em tempo real (entradas, hidden, saída),
  - HUD com geração / vivos / pontos / recorde,
  - botões REINICIAR (zera o treino) e SALVAR (grava o melhor cérebro pra
    "jogar contra" no Flappy normal).

Roda a 30 FPS (preferred_fps) e renderiza no máx. 10 pássaros pra não esquentar
a Pi — a simulação da população é barata (redes minúsculas em Python puro).
"""
from __future__ import annotations

import colorsys
import random
import time

import pygame

from ..core import input as bmo_input
from ..core.theme import Colors, LOGICAL_SIZE, render_text
from ..services import audio
from ..services import flappy_ai as fai
from ..services.flappy_ai import (
    W, H, GROUND_Y, PIPE_W, PIPE_GAP, BIRD_X, BIRD_R, N_INPUTS, N_HIDDEN,
)
# paleta do jogo (mesma identidade visual)
from .flappy import BG, WHITE, DIM, BIRD, BIRD_EYE, PIPE, PIPE_DARK, GROUND

# ---------- parâmetros do GA (leves pro Pi e estáveis entre gerações) ----------
POP = 24            # tamanho da população (simulada; barata)
RENDER = 10         # quantos pássaros aparecem por vez (enxame colorido; o resto roda invisível)
ELITE = 2           # melhores preservados intactos (não regridem)
MUTATE = 0.06       # taxa de mutação LEVE (filhos perto do campeão)
CROSS = 0.25        # crossover LEVE (raro; padrão é clonar + mutar)
MAX_GEN_SCORE = 30  # corta a geração quando o grupo passa N canos (mantém o ritmo)

PANEL = pygame.Rect(246, 26, 150, 170)


class FlappyTrainScreen:
    voice_announce = "Treinando o Flappy."
    preferred_fps = 30          # segura o FPS pra não aquecer a Pi

    def __init__(self, on_back) -> None:
        self.on_back = on_back
        self._buttons = ["reiniciar", "salvar"]
        self._sel = 0
        self._status = ""
        self._status_until = 0.0
        self._viz = None        # {"inputs","hid","out","brain"} do melhor pássaro
        self._init_population()

    def _init_population(self) -> None:
        self.brains = [fai.Brain() for _ in range(POP)]
        self.world = fai.World(POP)
        self.gen = 1
        self.record = 0
        self.best_brain = None
        # cor viva aleatória + leve deslocamento em X por pássaro (só visual —
        # a física é toda em BIRD_X). Dá a cara de enxame e some no REINICIAR.
        self._colors = [self._vivid_color() for _ in range(POP)]
        self._xoff = [random.randint(-6, 6) for _ in range(POP)]

    @staticmethod
    def _vivid_color() -> tuple[int, int, int]:
        h, s, v = random.random(), random.uniform(0.65, 1.0), random.uniform(0.85, 1.0)
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return (int(r * 255), int(g * 255), int(b * 255))

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- input ----------

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
                    self._sel = i
                    self._activate(key)
                    return

    def _activate(self, key: str) -> None:
        if key == "reiniciar":
            audio.play("select")
            self._init_population()
            self._toast("Treino reiniciado")
        elif key == "salvar":
            audio.play("select")
            # valida os candidatos em vários mundos novos e grava o MAIS ROBUSTO
            # (não o "líder sortudo" de um layout) — é ele que vai pro versus.
            cands = list(self.brains)
            if self.best_brain is not None:
                cands.append(self.best_brain)
            brain, (mn, _tot) = fai.most_robust(cands)
            if brain is not None and fai.save_brain(brain, self.gen, self.record):
                self.best_brain = brain.copy()
                self._toast(f"Salvo! robustez {mn}/20")
            else:
                self._toast("Falha ao salvar")

    def _toast(self, msg: str) -> None:
        self._status = msg
        self._status_until = time.time() + 3.0

    # ---------- update / GA ----------

    def update(self, dt: float) -> None:
        dt = min(dt, 0.05)      # clamp anti-explosão da física em lag
        if self.world.alive > 0 and self.world.score < MAX_GEN_SCORE:
            self.world.step(dt, self.brains)
            # campeão de TODOS os tempos, rastreado AO VIVO: quando o grupo bate
            # o recorde, congela o cérebro do líder. É ele que o SALVAR grava
            # (não o melhor da última geração, que pode ter regredido).
            if self.world.score > self.record:
                self.record = self.world.score
                i = self.world.best_index()
                if i is not None:
                    self.best_brain = self.brains[i].copy()
        else:
            self._next_generation()
        self._update_viz()

    def _next_generation(self) -> None:
        fitnesses = [b["fitness"] for b in self.world.birds]
        self.brains, _gen_best = fai.evolve(self.brains, fitnesses, ELITE, MUTATE, CROSS)
        # injeta o campeão histórico de volta na população: garante que a
        # próxima geração NUNCA colapse (o melhor pássaro de todos segue vivo
        # competindo, mesmo se a última geração tiver regredido).
        if self.best_brain is not None and POP > ELITE:
            self.brains[ELITE] = self.best_brain.copy()
        self.world.reset(POP)
        self.gen += 1

    def _update_viz(self) -> None:
        i = self.world.best_index()
        if i is None:
            return
        b = self.world.birds[i]
        p = self.world.next_pipe()
        gap_y = p["gap_y"] if p else H / 2
        pipe_x = p["x"] if p else float(W)
        inputs = fai.sense(b["y"], pipe_x, gap_y)
        out, hid = self.brains[i].forward(inputs)
        self._viz = {"inputs": inputs, "hid": hid, "out": out, "brain": self.brains[i]}

    # ---------- layout ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(4, 4, 52, 16)

    def _btn_rect(self, key: str) -> pygame.Rect:
        if key == "reiniciar":
            return pygame.Rect(W - 134, 4, 70, 16)
        return pygame.Rect(W - 60, 4, 56, 16)   # salvar

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BG)
        self._draw_pipes(surface)
        pygame.draw.rect(surface, GROUND, (0, GROUND_Y, W, H - GROUND_Y))
        self._draw_birds(surface)
        self._draw_net(surface)
        self._draw_hud(surface)
        self._draw_buttons(surface)
        if self._status and time.time() < self._status_until:
            img = render_text(self._status, 9, BIRD, pixel=False)
            surface.blit(img, img.get_rect(midbottom=(W // 2, H - 4)))

    def _draw_pipes(self, surface) -> None:
        for p in self.world.pipes:
            x = int(p["x"])
            gap_top = p["gap_y"] - PIPE_GAP // 2
            gap_bot = p["gap_y"] + PIPE_GAP // 2
            pygame.draw.rect(surface, PIPE, (x, 0, PIPE_W, gap_top))
            pygame.draw.rect(surface, PIPE, (x, gap_bot, PIPE_W, GROUND_Y - gap_bot))
            pygame.draw.rect(surface, PIPE_DARK, (x - 2, gap_top - 6, PIPE_W + 4, 6))
            pygame.draw.rect(surface, PIPE_DARK, (x - 2, gap_bot, PIPE_W + 4, 6))

    def _draw_birds(self, surface) -> None:
        shown = self.world.top_alive(RENDER)
        best = shown[0] if shown else None
        for idx in reversed(shown):   # desenha o melhor por último (por cima)
            b = self.world.birds[idx]
            x = BIRD_X + self._xoff[idx]
            y = int(b["y"])
            color = self._colors[idx]
            pygame.draw.rect(surface, color, (x - BIRD_R, y - BIRD_R, BIRD_R * 2, BIRD_R * 2))
            pygame.draw.rect(surface, BIRD_EYE, (x + 1, y - 3, 2, 2))
            if idx == best:
                # o líder (cuja rede aparece no painel): anel branco + biquinho
                pygame.draw.rect(surface, WHITE, (x - BIRD_R - 1, y - BIRD_R - 1, BIRD_R * 2 + 2, BIRD_R * 2 + 2), 1)
                pygame.draw.rect(surface, (230, 120, 40), (x + BIRD_R, y, 3, 2))

    def _draw_hud(self, surface) -> None:
        surface.blit(render_text(f"GER {self.gen}", 10, WHITE), (6, 24))
        surface.blit(render_text(f"VIVOS {self.world.alive}/{POP}", 8, DIM, pixel=False), (6, 38))
        surface.blit(render_text(f"PTS {self.world.score}", 8, WHITE, pixel=False), (6, 48))
        surface.blit(render_text(f"REC {self.record}", 8, BIRD, pixel=False), (6, 58))

    def _draw_buttons(self, surface) -> None:
        self._draw_back_btn(surface)
        for i, key in enumerate(self._buttons):
            rect = self._btn_rect(key)
            selected = (i == self._sel)
            if selected:
                pygame.draw.rect(surface, WHITE, rect); fg = BG
            else:
                pygame.draw.rect(surface, BG, rect); pygame.draw.rect(surface, DIM, rect, 1); fg = DIM
            img = render_text(key.upper(), 8, fg, pixel=False)
            surface.blit(img, img.get_rect(center=rect.center))

    def _draw_back_btn(self, surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, BG, rect)
        pygame.draw.rect(surface, WHITE, rect, 1)
        pygame.draw.polygon(surface, WHITE, [
            (rect.left + 6, rect.centery - 3), (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery)])
        img = render_text("HOME", 7, WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    # ---------- viz da rede neural ----------

    def _draw_net(self, surface) -> None:
        # fundo do painel (quase opaco) por cima do cenário
        box = pygame.Surface((PANEL.w, PANEL.h))
        box.set_alpha(216)
        box.fill((4, 6, 16))
        surface.blit(box, PANEL.topleft)
        pygame.draw.rect(surface, DIM, PANEL, 1)
        surface.blit(render_text("REDE DO MELHOR", 7, DIM, pixel=False), (PANEL.left + 6, PANEL.top + 4))

        viz = self._viz
        if viz is None:
            return
        in_acts, hid_acts, out_act = viz["inputs"], viz["hid"], viz["out"]
        brain = viz["brain"]

        x_in = PANEL.left + 26
        x_hid = PANEL.centerx + 4
        x_out = PANEL.right - 24
        in_ys = self._col_ys(N_INPUTS, PANEL.top + 30, PANEL.bottom - 16)
        hid_ys = self._col_ys(N_HIDDEN, PANEL.top + 22, PANEL.bottom - 14)
        out_y = (PANEL.top + PANEL.bottom) // 2

        # arestas entrada->hidden
        for i in range(N_INPUTS):
            for j in range(N_HIDDEN):
                w = brain.w_ih[i * N_HIDDEN + j]
                self._edge(surface, (x_in, in_ys[i]), (x_hid, hid_ys[j]), w)
        # arestas hidden->saida
        for j in range(N_HIDDEN):
            self._edge(surface, (x_hid, hid_ys[j]), (x_out, out_y), brain.w_ho[j])

        # nós
        labels = ["DIST", "ALT"]
        for i in range(N_INPUTS):
            self._node(surface, x_in, in_ys[i], in_acts[i])
            surface.blit(render_text(labels[i], 6, DIM, pixel=False),
                         (PANEL.left + 3, in_ys[i] - 12))
        for j in range(N_HIDDEN):
            self._node(surface, x_hid, hid_ys[j], hid_acts[j])
        self._node(surface, x_out, out_y, out_act, r=6)
        flap = out_act > 0.0
        surface.blit(render_text("FLAP" if flap else "----", 7,
                                 Colors.GREEN_BTN if flap else DIM, pixel=False),
                     (x_out - 12, out_y + 8))

    @staticmethod
    def _col_ys(n, top, bottom):
        if n == 1:
            return [(top + bottom) // 2]
        step = (bottom - top) / (n - 1)
        return [int(top + i * step) for i in range(n)]

    @staticmethod
    def _edge(surface, a, b, w) -> None:
        color = Colors.GREEN_BTN if w >= 0 else Colors.RED
        width = 2 if abs(w) >= 1.2 else 1
        pygame.draw.line(surface, color, a, b, width)

    @staticmethod
    def _node(surface, x, y, act, r=5) -> None:
        a = max(-1.0, min(1.0, act))
        m = int(40 + abs(a) * 215)
        fill = (0, m, int(m * 0.45)) if a >= 0 else (m, 0, 0)
        pygame.draw.circle(surface, fill, (x, y), r)
        pygame.draw.circle(surface, WHITE, (x, y), r, 1)
