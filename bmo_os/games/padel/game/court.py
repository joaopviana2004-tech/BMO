"""Geometria da quadra e conversao metros -> pixels (tela de partida 640x360)."""
import math

from . import settings as S


def sgn(v):
    return 1 if v > 0 else (-1 if v < 0 else 0)


def hyp(a, b):
    """Distancia euclidiana. Usamos sqrt em vez de math.hypot de proposito: hypot nao e
    exatamente arredondado e varia entre implementacoes (e entre motores JavaScript),
    o que quebraria a simulacao compartilhada do multiplayer. Ver MULTIPLAYER.md."""
    return math.sqrt(a * a + b * b)


class Court:
    def __init__(self, meta):
        self.meta = meta
        self.rect = tuple(meta["court"])          # x, y, w, h em pixels
        self.net_x = meta["net_x"]
        self.center_y = meta["center_y"]
        self.service_x = tuple(meta["service_x"])
        self.scoreboard = tuple(meta["scoreboard"])

    def to_screen(self, x, z, y=0.0):
        """(x, z) em metros a partir do centro da quadra; y = altura em metros."""
        sx = self.net_x + x * S.PX_PER_M
        sy = self.center_y + z * S.PX_PER_M - y * S.PX_PER_M
        return sx, sy

    def ground(self, x, z):
        return self.to_screen(x, z, 0.0)


def right_z(side):
    """Sinal de z que corresponde ao lado DIREITO do jogador que joga no lado `side`.
    O jogador da esquerda (-1) olha para +x: sua direita e +z (parte de baixo da tela).
    O da direita (+1) olha para -x: sua direita e -z."""
    return -side


def in_service_box(x, z, x_sign, z_sign):
    """Caixa de saque no lado x_sign, metade z_sign, entre a linha de saque e o fundo."""
    if x * x_sign <= 0 or abs(x) > S.COURT_HALF_L:
        return False
    if z * z_sign < 0 or abs(z) > S.COURT_HALF_W:
        return False
    return abs(x) >= S.SERVICE_LINE
