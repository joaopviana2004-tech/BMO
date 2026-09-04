"""Constantes do jogo.

Sistema de coordenadas da partida (metros):
  x = ao longo do comprimento da quadra; rede em x = 0, fundos em x = -10 / +10
  z = largura da quadra; -5 (topo da tela) .. +5 (base da tela)
  y = altura
Lado -1 = esquerda da tela, lado +1 = direita. Tela: 20 px = 1 m.
"""
import os

import pygame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
CONFIG_PATH = os.path.join(ROOT, "config.json")

# ------------------------------------------------------------------ tela
SCREEN_W, SCREEN_H = 640, 360     # resolucao base; pygame escala em inteiros (1280x720, 1920x1080)
FPS = 60
SUBSTEPS = 4                      # sub-passos de fisica por frame (colisao precisa com paredes)

# ------------------------------------------------------------------ quadra (padel oficial 10 x 20 m)
PX_PER_M = 20
COURT_HALF_W = 5.0
COURT_HALF_L = 10.0
SERVICE_LINE = 6.95     # distancia da rede ate a linha de saque
NET_H = 0.92
BACK_WALL_H = 4.0       # fundo: vidro 3 m + grade 1 m
SIDE_WALL_H = 3.0       # laterais (simplificado)
SIDE_GLASS_LEN = 4.0    # metros de vidro nas laterais, contados a partir do fundo
DOOR_GAP = 1.0          # abertura (porta) de cada lado da rede
DOOR_H = 2.0

# ------------------------------------------------------------------ fisica da bola
GRAVITY = 9.81
BALL_R = 0.035
REST_GROUND = 0.72      # restituicao no piso (um pouco alta de proposito: da tempo de jogar da parede)
FRICTION_GROUND = 0.80  # perda de velocidade horizontal a cada quique
REST_GLASS = 0.70
REST_MESH = 0.45        # a grade "mata" a bola (perde ~55%)
BALL_DEAD_SPEED = 0.35  # rolando abaixo disso a bola e considerada morta

# ------------------------------------------------------------------ jogador
PLAYER_SPEED = 5.8
PLAYER_ACCEL = 34.0
REACH = 1.15            # alcance horizontal da raquete (m)
SPRINT_MULT = 1.5       # corrida (shift): multiplicador de velocidade
SPRINT_ERR = 1.4        # metros extras de erro no golpe enquanto corre
SPRINT_SETTLE = 0.35    # segundos apos parar de correr em que o erro ainda decai
SPRINT_DUST = 0.16      # intervalo (s) da poeira nos pes durante a corrida
AIM_BASE_ERR = 0.3      # raio (m) do marcador de mira parado
INPUT_BUFFER = 0.30     # segundos que um comando de golpe fica "guardado"
HIT_COOLDOWN = 0.35

# golpes: profundidade alvo (m alem da rede), velocidade vertical inicial (m/s), abertura lateral (m),
# mult = quanto sobe o multiplicador de velocidade, power = "peso" do golpe (som, tremor, rastro),
# boost = velocidade extra real do golpe, hitstop = congelamento (s) no impacto
SHOTS = {
    "normal": dict(depth=6.8, vy=5.2, spread=3.2, mult=0.1, power=0.0, boost=1.0, hitstop=0.0),
    "fast":   dict(depth=8.2, vy=2.4, spread=3.0, mult=0.15, power=0.5, boost=1.15, hitstop=0.05),
    "lob":    dict(depth=8.6, vy=9.0, spread=2.4, mult=0.05, power=-0.5, boost=1.0, hitstop=0.0),
    "drop":   dict(depth=2.2, vy=3.6, spread=2.6, mult=0.05, power=-0.5, boost=1.0, hitstop=0.0),
    "volley": dict(depth=6.5, vy=2.0, spread=3.4, mult=0.1, power=0.2, boost=1.05, hitstop=0.0),
    "smash":  dict(depth=7.5, vy=-2.0, spread=3.6, mult=0.3, power=1.0, boost=1.3, hitstop=0.08),
    "serve":  dict(depth=7.6, vy=5.5, spread=1.4, mult=0.0, power=0.0, boost=1.0, hitstop=0.0),
}
MULT_MAX = 2.4          # multiplicador maximo de velocidade da bola (mostrado no HUD)
MULT_EFFECT = 0.6       # quanto do multiplicador vira velocidade real (2.4 -> 1.84x)
FIRE_LEVEL = 6          # nivel (0-8) em que a bola pega fogo

# ------------------------------------------------------------------ teclado do jogador
HUMAN_KEYS = dict(
    up=(pygame.K_UP, pygame.K_w), down=(pygame.K_DOWN, pygame.K_s),
    left=(pygame.K_LEFT, pygame.K_a), right=(pygame.K_RIGHT, pygame.K_d),
    normal=(pygame.K_z, pygame.K_j, pygame.K_SPACE),
    strong=(pygame.K_x, pygame.K_k),
    sprint=(pygame.K_LSHIFT, pygame.K_RSHIFT),
    lob=(pygame.K_c, pygame.K_l),
    drop=(pygame.K_v, pygame.K_i),
    serve=(pygame.K_SPACE, pygame.K_z, pygame.K_j),
    confirm=(pygame.K_e, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_z),
)

# bots (GAMEPLAY.md): velocidade em % do jogador, reacao em s, erro de mira em m,
# chance de smash em bola alta, chance de errar golpe forte
DIFFICULTY = [
    dict(name="FÁCIL",   stars=1, speed=0.80, reaction=0.45, aim=1.5, smash=0.20, miss=0.30),
    dict(name="MÉDIO",   stars=2, speed=0.95, reaction=0.25, aim=0.8, smash=0.50, miss=0.15),
    dict(name="DIFÍCIL", stars=3, speed=1.05, reaction=0.12, aim=0.3, smash=0.85, miss=0.05),
]

ARENAS = ["azul", "verde", "terra", "indoor"]
TIME_LIMITS = [5, 10, 15, None]
POINT_LIMITS = [7, 11, 15, 21]
GAMES_PER_SET = [3, 6]

# nomes e retratos dos personagens
NAMES = {
    "timeA_p1": "VOCÊ", "timeA_p2": "CARLOS", "timeB_p1": "ANA", "timeB_p2": "LEO",
    "extra_verde": "BRUNO", "extra_branco": "JÚLIA", "npc_socio": "SÓCIO", "npc_bar": "MARCOS",
    "npc_recepcao": "RITA",
}
PARTNERS = ["timeA_p2", "extra_verde", "extra_branco", "npc_socio"]
RIVALS = ["timeB_p1", "timeB_p2"]
