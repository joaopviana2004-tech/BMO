"""Bots: preveem onde a bola vai (simulando quiques e paredes), correm ate la e escolhem o golpe.

Baseado na ideia do PlayerNormalAI do MinimumTennis (previsao do ponto de chegada + atraso de
reacao + ruido no alvo), adaptado para as paredes do padel e para duplas:
- a previsao e uma simulacao completa da bola; o bot escolhe o primeiro instante que consegue alcancar
- em duplas, o membro do time com mais folga para chegar e quem vai na bola; o outro cobre a base
- o parceiro do humano nunca disputa a bola: se o humano chega antes, o parceiro volta para a base
"""
import math
import random

from . import settings as S
from .court import hyp


class AIController:
    def __init__(self, player, scene, difficulty):
        self.p = player
        self.scene = scene
        self.d = S.DIFFICULTY[difficulty]
        self.p.speed = S.PLAYER_SPEED * self.d["speed"]
        self.reaction = self.d["reaction"]
        self.aim = self.d["aim"]
        self.serve_delay = 1.2
        self.target = None
        self.chasing = False
        self.think_t = random.uniform(0, 0.08)
        self.serve_t = 0.0

    # ------------------------------------------------------------------ util
    def base(self):
        p = self.p
        sc = self.scene
        ball = sc.ball
        x = p.side * (3.4 if p.role == "net" else 7.4)
        if sc.doubles:
            s = 1 if p.base_z > 0 else -1
            z = abs(p.base_z)
            if ball is not None and not ball.dead:
                z = max(0.8, min(4.2, abs(p.base_z) + 0.3 * ball.z * s))
            return x, z * s
        z = 0.0
        if ball is not None and not ball.dead:
            z = max(-2.5, min(2.5, ball.z * 0.35))
        return x, z

    def _go(self, dt, tx, tz):
        p = self.p
        dx, dz = tx - p.x, tz - p.z
        dist = hyp(dx, dz)
        if dist < 0.10:
            p.move(dt, 0.0, 0.0)
            return
        k = min(1.0, dist / 0.5)
        p.move(dt, dx / dist * k, dz / dist * k)

    @staticmethod
    def choose(path, player, wait):
        """Entre os instantes em que a bola e golpeavel, escolhe o primeiro que `player` alcanca.
        Devolve (x, z, folga): folga > 0 significa que da tempo de chegar."""
        if not path:
            return None
        best = None
        for x, z, y, t, after_bounce in path:
            sx, sz = x, z - 0.45 * player.right_z
            arrive = wait + hyp(sx - player.x, sz - player.z) / max(player.speed, 0.1)
            slack = t - arrive
            if slack >= 0.04:
                good = 0.35 <= y <= 1.3
                if best is None or (good and not best[3]):
                    best = (sx, sz, slack, good)
                if good:
                    break
        if best is None:
            x, z, y, t, _ = path[-1]
            sx, sz = x, z - 0.45 * player.right_z
            arrive = wait + hyp(sx - player.x, sz - player.z) / max(player.speed, 0.1)
            best = (sx, sz, t - arrive, False)
        return best[0], best[1], best[2]

    # ------------------------------------------------------------------ loop
    def update(self, dt):
        sc, p = self.scene, self.p
        ball = sc.ball
        if sc.phase != "play":
            p.stop(dt)
            return

        if p.locked:
            p.stop(dt)
            return
        if sc.state == "serve":
            if sc.server is p and (ball is None or ball.phase == "toss"):
                if ball is None:
                    self.serve_t += dt
                    if self.serve_t >= self.serve_delay:
                        self.serve_t = 0.0
                        p.aim = (0.0, random.uniform(-1.0, 1.0))
                        sc.start_toss(p)
                p.stop(dt)
            else:
                self._go(dt, *self.base())
            return

        if ball is None or ball.dead or ball.phase == "toss":
            self._go(dt, *self.base())
            return

        incoming = ball.side != p.side and not ball.out
        if not incoming:
            self.chasing = False
            self.target = None
            self._go(dt, *self.base())
            return

        # bola vindo para o meu lado: re-avalia a previsao periodicamente (as paredes mudam a trajetoria)
        self.think_t -= dt
        if self.think_t <= 0:
            self.think_t = 0.08
            path = sc.predict(p.side, allow_volley=not ball.serve)
            wait = max(0.0, self.reaction - ball.age)
            mine = self.choose(path, p, wait)
            mate = sc.teammate(p)
            chase = mine is not None
            if chase and mate is not None:
                if mate.human:
                    his = self.choose(path, mate, 0.0)
                    # o humano tem prioridade: o parceiro so vai se chegar bem antes
                    chase = his is None or mine[2] > his[2] + 0.25
                else:
                    his = self.choose(path, mate, max(0.0, self.reaction - ball.age))
                    chase = his is None or mine[2] > his[2] or (mine[2] == his[2] and p.idx < mate.idx)
            self.chasing = chase
            self.target = (mine[0], mine[1]) if chase else None

        if self.chasing and self.target is not None:
            if ball.age < self.reaction:
                p.stop(dt)
            else:
                self._go(dt, *self.target)
        else:
            self._go(dt, *self.base())

        if self.chasing and sc.can_hit(p) and (ball.vy <= 0.3 or ball.y < 1.2):
            self._decide_shot()

    def _decide_shot(self):
        sc, p = self.scene, self.p
        ball = sc.ball
        d = self.d
        opps = sc.opponents(p)
        n = self.aim

        # joga para o lado longe do adversario mais proximo da rede
        near = min(opps, key=lambda o: abs(o.x))
        if abs(near.z) > 0.8:
            tz = -math.copysign(3.0, near.z)
        else:
            tz = random.choice((-3.0, 3.0))
        tz += random.uniform(-n, n)
        depth = random.uniform(-0.8, 0.5) + random.uniform(-n, n) * 0.6

        near_net = abs(p.x) < 5.5
        deep = abs(p.x) > 8.0
        before_bounce = ball.bounces[p.side] == 0
        far_opp = max(abs(o.x) for o in opps) > 8.3
        p.ai_miss = None
        if ball.y > 1.5 and random.random() < d["smash"]:
            kind = "smash"
        elif before_bounce and near_net:
            kind = "volley"
        elif deep and ball.y < 0.7 and random.random() < 0.35:
            kind = "lob"
        elif far_opp and near_net and random.random() < 0.35:
            kind = "drop"
            depth = 0.0
        elif random.random() < 0.3:
            kind = "fast"
        else:
            kind = "normal"

        strong = kind in ("fast", "smash")
        miss = d["miss"] if strong else d["miss"] * 0.4
        miss += 0.012 * sc.score.rally          # "cansaco": rallies longos terminam em erro
        if random.random() < miss:
            p.ai_miss = random.choices(("long", "wide", "net"), weights=(50, 35, 15))[0]

        p.ai_target_z = tz
        p.ai_depth = depth
        p.request_shot(kind)
