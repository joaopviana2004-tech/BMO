"""Cena da partida (GAMEPLAY.md): entrada dos bots, contagem, jogo, ponto, fim.

Fases:  entry -> countdown -> play -> (point -> between -> play)* -> end
Dentro de `play`, `state` e "serve" (esperando o saque) ou "rally".
O juiz (judge) aplica as regras do padel; o placar (rules.py) conta games/sets ou pontos corridos.

`demo=True` roda a partida so com bots, sem HUD, som ou entrada (fundo da tela de titulo).
"""
import math
import random

import pygame

from . import settings as S
from .ai import AIController
from .ball import Ball, MESH, predict_path
from .court import Court, hyp, in_service_box, right_z, sgn
from .menus import MenuList, draw_button, draw_hints
from .player import Player
from .rules import ArcadeScore, Match
from .sounds import SILENT
from .ui import (BLACK, BLUE, DIM, GREEN, GREY, RED, WHITE, YELLOW, Effects, angle_of, draw_scaled,
                 ease_out, fmt_time, pop_scale)

TEAM_COLORS = [(255, 120, 110), (255, 225, 110)]
COUNTDOWN = [("PREPARAR", 1.0), ("3", 1.0), ("2", 1.0), ("1", 1.0), ("JOGO!", 0.7)]
KIND_NAMES = dict(normal="GOLPE", fast="GOLPE FORTE", lob="LOB", drop="DEIXADINHA", volley="VOLEIO",
                  smash="SMASH", serve="SAQUE")
K = S.HUMAN_KEYS
ENTRY_LEN = 3.0
BETWEEN_LEN = 0.9
DEMO_OPTS = dict(palette="azul", court_name="", mode=0, difficulty=2, time=3, scoring=1, games=1, points=0,
                 side=0, partner=0, wind=0)


def demo_options(palette):
    o = dict(DEMO_OPTS)
    o["palette"] = palette
    return o


class MatchScene:
    def __init__(self, app, opts, on_finish=None, demo=False):
        self.app = app
        self.a = app.assets
        self.demo = demo
        self.sounds = SILENT if demo else app.sounds
        self.on_finish = on_finish
        self.opts = opts
        self.arena_img, meta = self.a.arena(opts["palette"])
        self.court = Court(meta)
        self.doubles = opts["mode"] == 1

        human_side = -1 if opts["side"] == 0 else 1
        self.team_side = [human_side, -human_side]
        self.players = []
        control = "ai" if demo else "p1"

        def add(name, sheet, team, ctrl, base_z):
            p = Player(len(self.players), name, sheet, self.team_side[team], ctrl, team, base_z)
            self.players.append(p)
            return p

        self.human = add("VOCÊ", "timeA_p1", 0, control, -2.5 if self.doubles else 0.0)
        if self.doubles:
            ps = S.PARTNERS[opts["partner"]]
            add(S.NAMES[ps], ps, 0, "ai", 2.5)
        add(S.NAMES["timeB_p1"], "timeB_p1", 1, "ai", -2.5 if self.doubles else 0.0)
        if self.doubles:
            add(S.NAMES["timeB_p2"], "timeB_p2", 1, "ai", 2.5)
        self.teams = [[p for p in self.players if p.team == t] for t in (0, 1)]
        self.sheets = {p.idx: self.a.sheet(p.sheet_name) for p in self.players}
        self.ai = [AIController(p, self, opts["difficulty"]) for p in self.players if not p.human]

        self.new_score()
        tl = S.TIME_LIMITS[opts["time"]]
        self.time_left = tl * 60.0 if tl else None
        self.elapsed = 0.0
        self.sudden_death = False
        self.wind_on = bool(opts["wind"])
        self.wind = 0.0
        self.wind_t = 0.0

        self.effects = Effects(self.a.fx, self.court)
        self.frame = pygame.Surface((S.SCREEN_W, S.SCREEN_H))
        self.ball = None
        self.server = None
        self.serve_box = (1, 1)
        self.toss_bounced = False
        self.phase = "entry"
        self.state = "serve"
        self.phase_t = 0.0
        self.timer = 0.0
        self.cd_i = 0
        self.paused = False
        self.pause_menu = None
        self.mult = 1.0
        self.level = 0
        self.fire_shown = False
        self.max_mult = 1.0
        self.banner = None
        self.big_msg = None
        self.big_t = 0.0
        self.shake_t = 0.0
        self.shake_amt = 0
        self.hitstop = 0.0
        self.flash_t = 0.0
        self.hud_y = -60.0
        self.marker_t = 0.0
        self.fade = 1.0
        self.zoom = 0.62
        self.prev_hitter = None
        self.end_sel = 0
        self.coins = 0
        self.t = 0.0
        self.dust_t = 0.0
        self._predict_cache = {}
        self._overlay = pygame.Surface((S.SCREEN_W, S.SCREEN_H), pygame.SRCALPHA)
        if demo:
            self.skip_intro()
        else:
            self.setup_entry()

    def new_score(self):
        first = random.randint(0, 1)
        if self.opts["scoring"] == 0:
            self.score = Match(S.GAMES_PER_SET[self.opts["games"]], first_server=first)
        else:
            self.score = ArcadeScore(S.POINT_LIMITS[self.opts["points"]], first_server=first)
        self.turns_served = [0, 0]
        self.last_turn = None

    # ------------------------------------------------------------------ utilidades de time
    def teammate(self, p):
        for m in self.teams[p.team]:
            if m is not p:
                return m
        return None

    def opponents(self, p):
        return self.teams[1 - p.team]

    def predict(self, side, allow_volley=True):
        b = self.ball
        wind = self.wind if self.wind_on else 0.0
        key = (id(b), round(b.age, 3), side, allow_volley, wind)
        path = self._predict_cache.get(key)
        if path is None:
            if len(self._predict_cache) > 8:
                self._predict_cache.clear()
            path = predict_path(b, side, allow_volley, wind=wind)
            self._predict_cache[key] = path
        return path

    # ------------------------------------------------------------------ preparacao
    def setup_entry(self):
        self.prepare()
        h = self.human
        hx, hz = h.x, h.z
        h.x, h.z = h.side * 1.6, -S.COURT_HALF_W - 0.8   # entra pela abertura de cima
        h.walk_target = (hx, hz)
        self.appear = []
        t = 1.2
        for p in self.players:
            if p is not h:
                p.visible = False
                self.appear.append((t, p))
                t += 0.4
        self.phase = "entry"
        self.phase_t = 0.0

    def prepare(self):
        sc = self.score
        team = sc.server
        turn = sc.serve_turn()
        if turn != self.last_turn:
            self.last_turn = turn
            self.turns_served[team] += 1
        members = self.teams[team]
        srv = members[(self.turns_served[team] - 1) % len(members)]
        deuce = sc.serve_side() == "deuce"
        side = self.team_side[team]
        sz = right_z(side) * 2.5 * (1 if deuce else -1)
        srv.place(side * 8.6, sz)
        srv.role = "back"
        for m in members:
            if m is not srv:
                m.place(side * 3.4, -sz)
                m.role = "net"
        rteam = self.teams[1 - team]
        rside = -side
        rcv = min(rteam, key=lambda m: abs(m.base_z - (-sz)))
        rcv.place(rside * 8.6, -sz)
        rcv.role = "back"
        for m in rteam:
            if m is not rcv:
                m.place(rside * 3.4, sz)
                m.role = "net"
        self.server = srv
        self.serve_box = (rside, sgn(-sz))
        self.ball = None
        self.toss_bounced = False
        self.state = "serve"
        self.mult = 1.0
        self.level = 0
        self.fire_shown = False
        self.marker_t = 3.0
        self.prev_hitter = None
        self.effects.clear()
        self._predict_cache.clear()
        for a in self.ai:
            a.serve_t = 0.0
            a.target = None
            a.chasing = False

    def skip_intro(self):
        """Pula a entrada e a contagem (demo e testes)."""
        for p in self.players:
            p.visible = True
            p.walk_target = None
        self.prepare()
        self.phase = "play"
        self.hud_y = 4.0
        self.fade = 0.0
        self.zoom = 1.0

    def restart_demo(self):
        self.new_score()
        self.time_left = None
        self.sudden_death = False
        self.prepare()
        self.phase = "between"
        self.phase_t = 0.0

    def show_big(self, text, t=1.0):
        self.big_msg, self.big_t = text, t

    def shake(self, t, amt):
        self.shake_t = max(self.shake_t, t)
        self.shake_amt = max(self.shake_amt, amt)

    # ------------------------------------------------------------------ pausa
    def set_paused(self, on):
        self.paused = on
        if on:
            self.sounds.play("pause")
            self.sounds.set_duck(0.35)
            items = [
                dict(label="CONTINUAR", action=lambda: self.set_paused(False)),
                dict(label="CONTROLES", action=lambda: self.app.open_controls()),
                dict(label="OPÇÕES", action=lambda: self.app.open_options()),
                dict(label="SAIR DA PARTIDA", action=self.finish),
            ]
            self.pause_menu = MenuList(self.app, items, S.SCREEN_W // 2 - 70, 150, 140)
            self.pause_menu.on_escape = lambda: self.set_paused(False)
        else:
            self.sounds.set_duck(1.0)
            self.pause_menu = None

    # ------------------------------------------------------------------ entrada
    def handle_event(self, ev):
        if self.demo or ev.type != pygame.KEYDOWN:
            return
        k = ev.key
        if self.paused:
            if k == pygame.K_ESCAPE:
                self.set_paused(False)
            else:
                self.pause_menu.handle_event(ev)
            return
        if k == pygame.K_ESCAPE:
            if self.phase == "end":
                self.finish()
            else:
                self.set_paused(True)
            return
        if self.phase == "end":
            if k in (pygame.K_LEFT, pygame.K_a, pygame.K_RIGHT, pygame.K_d):
                self.end_sel = 1 - self.end_sel
                self.sounds.play("menu")
            elif k in K["confirm"]:
                self.sounds.play("select")
                if self.end_sel == 0:
                    self.sounds.set_duck(1.0)
                    self.app.start_match(self.opts, self.on_finish)
                else:
                    self.finish()
            return
        if self.phase != "play":
            return
        h = self.human
        if self.state == "serve" and self.server is h and self.ball is None and k in K["serve"]:
            self.start_toss(h)
        elif k in K["normal"]:
            h.request_shot("normal")
        elif k in K["strong"]:
            h.request_shot("fast")
        elif k in K["lob"]:
            h.request_shot("lob")
        elif k in K["drop"]:
            h.request_shot("drop")

    def finish(self):
        self.sounds.set_duck(1.0)
        if self.on_finish:
            self.on_finish(self)

    def in_menu(self):
        """Fora do jogo em si o botao A do controle tambem confirma (menus, pausa, tela de fim)."""
        return self.paused or self.phase == "end"

    # ------------------------------------------------------------------ loop
    def update(self, dt):
        if self.paused:
            return
        if self.hitstop > 0:            # congela tudo por um instante no impacto forte
            self.hitstop -= dt
            return
        self.t += dt
        self.phase_t += dt
        phase_at_start = self.phase
        if self.fade > 0:
            self.fade = max(0.0, self.fade - dt * 1.6)
        if self.phase == "entry":
            self.zoom = 0.62 + 0.38 * ease_out(self.phase_t / 1.0)
        else:
            self.zoom = 1.0
        if self.big_t > 0:
            self.big_t -= dt
        if self.flash_t > 0:
            self.flash_t -= dt
        if self.shake_t > 0:
            self.shake_t -= dt
            if self.shake_t <= 0:
                self.shake_amt = 0
        if self.marker_t > 0:
            self.marker_t -= dt
        hud_target = 4.0 if (self.phase in ("play", "point", "between", "end") and not self.demo) else -60.0
        self.hud_y += (hud_target - self.hud_y) * min(1.0, dt * 8.0)
        self.effects.update(dt)

        if self.phase == "entry":
            self.human.walk_step(dt)
            for t, p in self.appear:
                if not p.visible and self.phase_t >= t:
                    p.visible = True
                    self.effects.spawn("poeira", p.x, p.z, 0.2, scale=1)
                    self.sounds.play("grade")
            if self.phase_t >= ENTRY_LEN:
                self.phase = "countdown"
                self.phase_t = 0.0
                self.cd_i = 0
                self.sounds.play_music("partida")
                self.sounds.play("tick")
        elif self.phase == "countdown":
            if self.phase_t >= COUNTDOWN[self.cd_i][1]:
                self.cd_i += 1
                self.phase_t = 0.0
                if self.cd_i >= len(COUNTDOWN):
                    self.phase = "play"
                    self.state = "serve"
                    self.marker_t = 3.0
                else:
                    self.sounds.play("go" if COUNTDOWN[self.cd_i][0] == "JOGO!" else "tick")
        elif self.phase == "play":
            self.update_play(dt)
        elif self.phase == "point":
            self.timer -= dt
            if self.timer <= 0:
                self.after_point()
        elif self.phase == "between":
            if self.phase_t >= BETWEEN_LEN:
                self.phase = "play"
                self.phase_t = 0.0
        elif self.phase == "end" and self.demo:
            self.restart_demo()

        for p in self.players:
            p.update(dt)
        # so avanca a bola aqui se a fase JA era de pausa no inicio do quadro: se `update_play`
        # rodou e terminou o ponto, a bola ja foi avancada uma vez neste quadro.
        if self.ball is not None and phase_at_start in ("point", "between", "end"):
            self.ball.update(dt, self.wind if self.wind_on else 0.0)
            if self.ball.age > 6.0 or self.ball.y < -3:
                self.ball = None

    def update_play(self, dt):
        if self.time_left is not None and not self.sudden_death:
            self.time_left = max(0.0, self.time_left - dt)
        self.elapsed += dt
        if self.wind_on:
            self.wind_t += dt
            if self.wind_t >= 30.0 or (self.wind == 0.0 and self.wind_t > 5.0):
                self.wind_t = 0.0
                self.wind = random.choice((-0.3, 0.3))

        if not self.demo:
            h = self.human
            mx, mz = self.app.input.axis()
            h.aim = (mx, mz)
            if h.locked:
                h.stop(dt)
            else:
                h.move(dt, mx, mz, sprint=self.app.input.sprint())
            if h.sprinting:
                self.dust_t -= dt
                if self.dust_t <= 0:
                    self.dust_t = S.SPRINT_DUST
                    self.effects.spawn("poeira", h.x - h.vx * 0.06, h.z + 0.25, 0.0, scale=1)
                    self.sounds.play("step", 0.7)
        for a in self.ai:
            a.update(dt)

        b = self.ball
        if b is not None:
            wind = self.wind if (self.wind_on and b.phase == "rally") else 0.0
            events = b.update(dt, wind)
            if not b.dead:
                if b.phase == "toss":
                    self.update_toss(events)
                else:
                    self.judge(events)
            if self.state == "rally" and self.ball is not None and not self.ball.dead:
                for p in self.players:
                    if p.shot_req and self.can_hit(p):
                        self.hit_ball(p, p.shot_req)

    # ------------------------------------------------------------------ saque
    def start_toss(self, p):
        b = Ball(p.x, 1.15, p.z + 0.35 * p.right_z)
        b.hitter = p
        b.side = p.side
        b.phase = "toss"
        self.ball = b
        self.toss_bounced = False
        p.locked = True
        p.clear_shot()

    def update_toss(self, events):
        b = self.ball
        p = b.hitter
        for e in events:
            if e["type"] == "ground":
                self.toss_bounced = True
                self.sounds.play("bounce", 0.6)
        if self.toss_bounced and b.vy <= 0.05 and b.y > 0.2:
            self.serve_strike(p)      # bate no apice do quique (saque por baixo)
        elif b.age > 2.5:
            self.ball = None          # errou o toss: pega outra bola
            p.locked = False

    def serve_target(self, p, jitter=0.0):
        """Ponto de queda do saque de `p`: diagonal para a caixa de saque; o eixo vertical do controle
        desloca dentro da caixa (baixo = baixo na tela, nos dois lados)."""
        xs, zs = self.serve_box
        spec = S.SHOTS["serve"]
        tz = zs * 2.6 + p.aim[1] * spec["spread"]
        tz = max(-4.4, min(4.4, tz))
        if zs > 0:
            tz = max(0.6, tz)
        else:
            tz = min(-0.6, tz)
        return xs * (spec["depth"] + jitter), tz

    def serve_strike(self, p):
        b = self.ball
        spec = S.SHOTS["serve"]
        tx, tz = self.serve_target(p, random.uniform(-0.4, 0.4))
        vx, vy, vz = self.launch(b, tx, tz, spec["vy"])
        b.hit(p, vx, vy, vz, serve=True)
        b.power = 0.0
        p.play("serve", self.sheets[p.idx])
        p.locked = False
        p.hit_cd = S.HIT_COOLDOWN
        p.last_kind = "serve"
        self.state = "rally"
        self.score.rally = 0
        self.sounds.play("serve")
        self.effects.spawn("swoosh", p.x - p.side * 0.5, p.z, 0.8, flip=p.side > 0)

    # ------------------------------------------------------------------ golpes
    def launch(self, b, tx, tz, vy, mult=1.0, ensure_net=True):
        """Velocidades para a bola cair em (tx, tz). `mult` encurta o tempo de voo (bola mais rapida
        e mais rasa, mesmo alvo). Se nao passar a rede, o voo e alongado ate passar."""
        g = S.GRAVITY
        y0 = max(b.y - S.BALL_R, 0.0)
        t = (vy + math.sqrt(vy * vy + 2 * g * y0)) / g
        t /= max(mult, 1.0)
        vx = vz = 0.0
        for _ in range(16):
            vy = (0.5 * g * t * t - y0) / t
            vx = (tx - b.x) / t
            vz = (tz - b.z) / t
            if not ensure_net or vx == 0:
                break
            tn = -b.x / vx
            if tn <= 0:
                break
            h = y0 + vy * tn - 0.5 * g * tn * tn
            if h >= S.NET_H + 0.22:
                break
            t *= 1.07
        return vx, vy, vz

    def can_hit(self, p):
        b = self.ball
        if b is None or b.out or b.dead or b.phase == "toss":
            return False
        if b.side == p.side:                   # bola bateu por ultimo neste lado (golpe do meu time)
            return False
        if sgn(b.x) != p.side:                 # bola ainda no lado do adversario
            return False
        if p.hit_cd > 0 or not p.visible:
            return False
        nb = b.bounces[p.side]
        if nb >= 2:
            return False
        if b.serve and nb == 0:                # devolucao de saque so depois do quique
            return False
        if b.y > 3.0:
            return False
        return hyp(b.x - p.x, b.z - p.z) <= S.REACH

    def resolve_kind(self, p, kind):
        """Promove o golpe pedido conforme a situacao: bola alta vira smash, antes do quique perto da rede vira voleio."""
        b = self.ball
        if b is None:
            return kind
        if b.y > 1.45 and kind in ("normal", "fast"):
            return "smash"
        if b.bounces[p.side] == 0 and kind in ("normal", "fast") and abs(p.x) < S.SERVICE_LINE:
            return "volley"
        return kind

    def human_target(self, p, kind, err=0.0):
        """Alvo (tx, tz) do golpe humano. Mesma conta da seta de mira; `err` (m) e o ruido aplicado."""
        spec = S.SHOTS[kind]
        opp = -p.side
        ax, az = p.aim
        tz = az * spec["spread"]
        depth = spec["depth"] + ax * opp * 1.6
        if err > 0:
            tz += random.uniform(-err, err)
            depth += random.uniform(-err, err) * 0.8
        depth = max(1.5, min(9.3, depth))
        tz = max(-4.5, min(4.5, tz))
        return opp * depth, tz

    def aim_target(self, p):
        if self.state == "serve":
            return self.serve_target(p)
        return self.human_target(p, self.resolve_kind(p, "normal"))

    def hit_ball(self, p, kind):
        b = self.ball
        dist = hyp(b.x - p.x, b.z - p.z)
        kind = self.resolve_kind(p, kind)
        spec = S.SHOTS[kind]
        opp = -p.side
        vy = spec["vy"] + random.uniform(-0.3, 0.3)
        ensure_net = True
        if p.human:
            quality = 1.0 - dist / S.REACH
            err = (1.0 - quality) * 1.3 + p.control_error()
            tx, tz = self.human_target(p, kind, err)
        else:
            tz = p.ai_target_z
            depth = spec["depth"] + p.ai_depth
            if p.ai_miss == "long":
                depth = 10.6 + random.random() * 1.5
            elif p.ai_miss == "wide":
                tz = math.copysign(5.6 + random.random(), tz or 1.0)
            elif p.ai_miss == "net":
                ensure_net = False
                vy = min(vy, 0.8)
            depth = max(1.5, min(12.0, depth))
            tz = max(-6.0, min(6.0, tz))
            tx = opp * depth

        self.prev_hitter = b.hitter
        self.mult = min(S.MULT_MAX, self.mult + spec["mult"])
        self.level = max(0, min(8, round((self.mult - 1.0) / 1.4 * 8)))
        self.max_mult = max(self.max_mult, self.mult)
        eff = (1.0 + (self.mult - 1.0) * S.MULT_EFFECT) * spec["boost"]
        vx, vy, vz = self.launch(b, tx, tz, vy, mult=eff, ensure_net=ensure_net)
        b.hit(p, vx, vy, vz)
        b.power = spec["power"]
        anim = "smash" if kind == "smash" else ("forehand" if (b.z - p.z) * p.right_z >= 0 else "backhand")
        p.play(anim, self.sheets[p.idx])
        p.clear_shot()
        p.hit_cd = S.HIT_COOLDOWN
        p.last_kind = kind
        p.vmax = max(p.vmax, self.mult)
        if kind == "smash":
            p.smashes += 1
        self.score.rally += 1

        # ---- feeling: som, tremor, congelamento, efeitos e vibracao conforme o peso do golpe
        power = spec["power"]
        strong = power >= 0.5
        self.effects.spawn("swoosh", p.x - p.side * 0.5, p.z, 0.9, flip=p.side > 0, scale=2 if strong else 1)
        self.effects.spawn("impacto", b.x, b.z, b.y, scale=2 if strong else 1)
        if strong:
            self.effects.spawn("vento", b.x, b.z, b.y, follow=b, offset=(p.side * 0.6, 0.0), life=0.35, flip=p.side < 0)
            self.sounds.play("hit_strong")
            self.sounds.play("swing", 0.9)
            self.flash_t = 0.1
            self.hitstop = spec["hitstop"]
            if kind == "smash":
                self.shake(0.25, 4)
            else:
                self.shake(0.15, 2)
            if p.human:
                self.app.input.rumble(0.5, 0.8, 220)
        elif power < 0:
            self.sounds.play("hit", 0.55)
            if p.human:
                self.app.input.rumble(0.1, 0.2, 60)
        else:
            self.sounds.play("hit")
            if p.human:
                self.app.input.rumble(0.2, 0.3, 80)
        if self.level >= S.FIRE_LEVEL and not self.fire_shown:
            self.fire_shown = True
            self.show_big("EM CHAMAS!", 1.0)
            self.shake(0.3, 3)
            self.sounds.play("fire")

    # ------------------------------------------------------------------ juiz
    def judge(self, events):
        b = self.ball
        h = b.hitter
        ht, ot = h.team, 1 - h.team
        for e in events:
            t = e["type"]
            if t == "ground":
                self.sounds.play("bounce", min(1.0, 0.35 + e.get("speed", 4.0) / 9.0))
                if e["side"] == h.side:
                    if b.crossed:
                        self.end_point(ht, "PONTO!", f"{h.name} - A BOLA VOLTOU POR CIMA DA REDE")
                    elif b.touched_net:
                        self.end_point(ot, "REDE!", f"BOLA NA REDE - {h.name}", serve_fault=b.serve)
                    else:
                        self.end_point(ot, "FORA!", f"ERRO DE {h.name}", serve_fault=b.serve)
                else:
                    if b.serve and b.bounces[e["side"]] == 1:
                        if not in_service_box(e["x"], e["z"], *self.serve_box):
                            self.end_point(ot, "FORA!", f"SAQUE FORA - {h.name}", serve_fault=True)
                        elif b.touched_net:
                            self.let()
                    elif b.bounces[e["side"]] >= 2:
                        self.end_point(ht, "PONTO!", self._winner_desc(h))
            elif t == "wall":
                vol = min(1.0, 0.3 + b.speed() / 12.0)
                self.sounds.play(e["kind"], vol)
                if b.speed() > 9:
                    self.shake(0.08, 1)
                if e["side"] == h.side:
                    if not b.crossed and e["kind"] == MESH:
                        self.end_point(ot, "FORA!", f"BOLA NA PRÓPRIA GRADE - {h.name}", serve_fault=b.serve)
                else:
                    if b.bounces[e["side"]] == 0:
                        self.end_point(ot, "FORA!", f"ERRO DE {h.name} - DIRETO NA PAREDE", serve_fault=b.serve)
                    elif b.serve and e["kind"] == MESH and b.bounces[e["side"]] == 1:
                        self.end_point(ot, "FORA!", f"SAQUE NA GRADE - {h.name}", serve_fault=True)
            elif t in ("net", "net_cord"):
                self.sounds.play("net")
            elif t == "exit":
                if e["side"] != h.side and b.bounces[e["side"]] >= 1:
                    self.end_point(ht, "PONTO!", f"{h.name} - SAIU POR 4!")
                else:
                    self.end_point(ot, "FORA!", f"ERRO DE {h.name} - SAIU DA QUADRA", serve_fault=b.serve)
            elif t == "dead":
                if e["side"] != h.side and b.bounces[e["side"]] >= 1:
                    self.end_point(ht, "PONTO!", self._winner_desc(h))
                else:
                    self.end_point(ot, "FORA!", f"ERRO DE {h.name}", serve_fault=b.serve)
            if self.phase == "point":
                break

    def _winner_desc(self, h):
        kind = KIND_NAMES.get(getattr(h, "last_kind", "normal"), "GOLPE")
        return f"{kind} DE {h.name} - BOLA A X{self.mult:.1f}"

    def let(self):
        self.ball.dead = True
        self.phase = "point"
        self.timer = 1.1
        self.banner = dict(title="LET", desc="REPETE O SAQUE", portrait=None, plus=None, t=0.0)
        self.sounds.play("fault")

    def end_point(self, winner, title, desc, serve_fault=False):
        b = self.ball
        b.dead = True
        sc = self.score
        h = b.hitter
        if serve_fault:
            if not sc.fault():
                self.phase = "point"
                self.timer = 1.1
                self.banner = dict(title="FALTA", desc=desc + " - SEGUNDO SAQUE", portrait=None, plus=None, t=0.0)
                self.sounds.play("fault")
                return
            title, desc = "PONTO!", f"DUPLA FALTA - {h.name}"
        if winner == h.team:
            scorer = h
        elif self.prev_hitter is not None and self.prev_hitter.team == winner:
            scorer = self.prev_hitter
        else:
            scorer = self.teams[winner][0]
        scorer.points_won += 1
        if winner != h.team:
            h.errors += 1
        res = sc.point_won(winner)
        self.timer = 1.5
        if res in ("game", "set"):
            title = "SET!" if res == "set" else "JOGO!"
            desc = f"GAME {sc.games[0]}-{sc.games[1]}  -  " + desc
            self.timer = 2.2
            self.sounds.play("game")
            self.sounds.play("crowd_big")
        elif res == "match":
            self.timer = 2.0
            self.sounds.play("game")
            self.sounds.play("crowd_big")
        else:
            self.sounds.play("point")
            self.sounds.play("crowd", 0.8 if winner == 0 else 0.5)
        if winner != 0 and not self.demo:
            self.app.input.rumble(0.3, 0.3, 250)
        if self.time_left is not None and self.time_left <= 0 and not sc.finished:
            lead = sc.leader()
            if lead is None:
                self.sudden_death = True
                desc += "  -  PRÓXIMO PONTO DECIDE"
            else:
                sc.force_finish(lead)
                title = "TEMPO!"
                self.timer = 2.0
        self.banner = dict(title=title, desc=desc, portrait=scorer.sheet_name, plus=winner, t=0.0)
        self.phase = "point"
        self.phase_t = 0.0

    def after_point(self):
        sc = self.score
        self.banner = None
        if sc.finished:
            self.phase = "end"
            self.phase_t = 0.0
            self.ball = None
            won = sc.winner == 0
            pts = sum(p.points_won for p in self.teams[0])
            self.coins = (100 if won else 30) + 5 * pts + 10 * sum(p.smashes for p in self.teams[0])
            self.sounds.set_duck(0.3)
            self.sounds.jingle("vitoria" if won else "derrota")
            return
        if sc.change_ends:
            sc.change_ends = False
            for p in self.players:
                p.side = -p.side
            self.team_side = [-s for s in self.team_side]
            self.show_big("TROCA DE LADO", 1.4)
        self.prepare()
        self.phase = "between"
        self.phase_t = 0.0

    # ------------------------------------------------------------------ desenho
    def draw_big(self, surf, name, cx, cy, scale=1.0, color=YELLOW):
        if self.a.big.has(name):
            draw_scaled(surf, self.a.big.get(name), cx, cy, scale)
        else:
            img = self.a.font.render(name, color, 3, outline=BLACK, shadow=(0, 0, 0))
            draw_scaled(surf, img, cx, cy, scale)

    def draw(self, surf):
        fr = self.frame
        fr.blit(self.arena_img, (0, 0))
        court = self.court
        b = self.ball
        fx = self.a.fx

        # sombras
        for p in self.players:
            if p.visible:
                sx, sy = court.ground(p.x, p.z)
                fx.draw(fr, "sombra_jogador", sx, sy, "center")
        if b is not None:
            sx, sy = court.ground(b.x, b.z)
            sc = 1 + min(b.y, 4.0) * 0.35
            img = pygame.transform.scale_by(fx.get("sombra_bola"), sc) if sc > 1.2 else fx.get("sombra_bola")
            fr.blit(img, img.get_rect(center=(int(sx), int(sy))))

        ents = [(p.z, 0, p) for p in self.players if p.visible]
        if b is not None:
            ents.append((b.z + 0.01, 1, b))
        for _, kind, obj in sorted(ents, key=lambda e: (e[0], e[1])):
            if kind == 0:
                obj.draw(fr, court, self.sheets[obj.idx])
            else:
                self.draw_ball(fr, obj)
        self.draw_aim(fr)
        self.effects.draw(fr)
        if self.demo:
            surf.blit(fr, (0, 0))
            return
        self.draw_tags(fr)
        self.draw_hud(fr)
        if self.phase == "play" and self.state == "serve" and self.ball is None and self.server is self.human:
            sx, sy = court.ground(self.human.x, self.human.z)
            self.a.font.draw(fr, "ESPAÇO: SACAR", sx, sy - 58, YELLOW, 1, "midtop", outline=BLACK)
        if self.phase == "countdown":
            self.draw_countdown(fr)
        elif self.phase == "between":
            self.draw_big(fr, "SAQUE", court.net_x, court.center_y - 10, pop_scale(self.phase_t))
            self.a.font.draw(fr, f"SAQUE: {self.server.name}", court.net_x, court.center_y + 14, WHITE, 1, "midtop", outline=BLACK)
        if self.banner is not None and self.phase == "point":
            self.draw_banner(fr)
        if self.big_msg and self.big_t > 0:
            self.draw_big(fr, self.big_msg, court.net_x, court.center_y - 30, pop_scale(1.0 - self.big_t if self.big_t < 1 else 0))
        if self.phase == "end":
            self.draw_end(fr)
        if self.paused:
            self.draw_pause(fr)

        # composicao final: zoom (entrada), tremor e fade
        ox = oy = 0
        if self.shake_t > 0 and self.shake_amt:
            ox = random.randint(-self.shake_amt, self.shake_amt)
            oy = random.randint(-self.shake_amt, self.shake_amt)
        if self.zoom < 0.999:
            surf.fill((0, 0, 0))
            z = self.zoom
            scaled = pygame.transform.scale(fr, (int(S.SCREEN_W * z), int(S.SCREEN_H * z)))
            cx, cy = court.net_x, court.center_y
            surf.blit(scaled, (int(cx - cx * z) + ox, int(cy - cy * z) + oy))
        elif ox or oy:
            surf.fill((0, 0, 0))
            surf.blit(fr, (ox, oy))
        else:
            surf.blit(fr, (0, 0))
        if self.fade > 0:
            self._overlay.fill((0, 0, 0, int(255 * self.fade)))
            surf.blit(self._overlay, (0, 0))

    def draw_ball(self, surf, b):
        court = self.court
        fx = self.a.fx
        sx, sy = court.to_screen(b.x, b.z, b.y)
        dsx, dsy = b.vx, b.vz - b.vy
        n = math.hypot(dsx, dsy)
        ux, uy = (dsx / n, dsy / n) if n > 0.01 else (1.0, 0.0)
        ang = angle_of(dsx, dsy)
        moving = b.speed() > 6 and not b.dead
        power = getattr(b, "power", 0.0)
        if self.level >= S.FIRE_LEVEL and moving:
            img = fx.get("bola_rastro", angle=ang)
            surf.blit(img, img.get_rect(center=(int(sx - ux * 16), int(sy - uy * 16))))
            img = fx.frame("bola_fogo", self.t, angle=ang)
            surf.blit(img, img.get_rect(center=(int(sx - ux * 8), int(sy - uy * 8))))
        elif (self.level >= 3 or power >= 0.5) and moving:
            img = fx.get("bola_rastro", angle=ang)
            surf.blit(img, img.get_rect(center=(int(sx - ux * 14), int(sy - uy * 14))))
            img = fx.get("bola_rapida", angle=ang)
            surf.blit(img, img.get_rect(center=(int(sx - ux * 5), int(sy - uy * 5))))
        else:
            if moving and power >= 0:
                for tx, ty, tz in b.trail[:-1]:
                    px, py = court.to_screen(tx, tz, ty)
                    pygame.draw.circle(surf, (214, 232, 58), (int(px), int(py)), 1)
            surf.blit(self.a.ball, (int(sx) - 3, int(sy) - 3))
        if self.flash_t > 0:
            r = 5 if self.flash_t > 0.05 else 3
            pygame.draw.circle(surf, WHITE, (int(sx), int(sy)), r)

    def draw_aim(self, surf):
        """Seta de direcao junto ao jogador e marcador de queda no outro lado (GAMEPLAY: mira)."""
        if self.demo or self.paused or self.phase != "play" or not self.app.config.get("aim", True):
            return
        h = self.human
        if not h.visible:
            return
        court = self.court
        b = self.ball
        serve = self.state == "serve" and self.server is h
        incoming = (b is not None and not b.dead and not b.out and b.phase != "toss" and b.side != h.side)
        tx, tz = self.aim_target(h)
        sx, sy = court.ground(h.x, h.z)
        ex, ey = court.ground(tx, tz)
        dx, dy = ex - sx, ey - sy
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        err = h.control_error()
        col = YELLOW if err < 0.2 else (255, 150, 60)
        # seta
        jx = jy = 0
        if err > 0.2:
            jx, jy = random.randint(-1, 1), random.randint(-1, 1)
        l0, l1 = 11, 24 - min(6.0, err * 4.0)
        p0 = (sx + ux * l0 + jx, sy + uy * l0 + jy)
        p1 = (sx + ux * l1 + jx, sy + uy * l1 + jy)
        tip = (p1[0] + ux * 5, p1[1] + uy * 5)
        px_, py_ = -uy, ux
        head = [tip, (p1[0] + px_ * 3.5, p1[1] + py_ * 3.5), (p1[0] - px_ * 3.5, p1[1] - py_ * 3.5)]
        pygame.draw.line(surf, BLACK, p0, p1, 4)
        pygame.draw.polygon(surf, BLACK, head)
        pygame.draw.polygon(surf, BLACK, head, 3)
        pygame.draw.line(surf, col, p0, p1, 2)
        pygame.draw.polygon(surf, col, head)
        # marcador de queda
        if serve or incoming:
            r = int((S.AIM_BASE_ERR + err) * S.PX_PER_M * 0.5) + 2
            cx, cy = int(ex), int(ey)
            pygame.draw.circle(surf, BLACK, (cx, cy), r + 1, 3)
            pygame.draw.circle(surf, col, (cx, cy), r, 1)
            for ddx, ddy in ((1, 0), (0, 1)):
                pygame.draw.line(surf, BLACK, (cx - ddx * 4, cy - ddy * 4), (cx + ddx * 4, cy + ddy * 4), 3)
                pygame.draw.line(surf, col, (cx - ddx * 3, cy - ddy * 3), (cx + ddx * 3, cy + ddy * 3), 1)

    def draw_tags(self, surf):
        fx = self.a.fx
        court = self.court
        show_tags = self.phase in ("entry", "countdown")
        for p in self.players:
            if not p.visible:
                continue
            sx, sy = court.ground(p.x, p.z)
            if show_tags:
                tag = "tag_voce" if p.human else ("tag_parceiro" if p.team == 0 else "tag_rival")
                fx.draw(surf, tag, sx, sy - 52, "midtop")
            if p.human and (show_tags or (self.marker_t > 0 and self.phase == "play")):
                img = fx.frame("marcador", self.t)
                surf.blit(img, img.get_rect(midtop=(int(sx), int(sy) - 40)))

    def draw_hud(self, surf):
        a = self.a
        f = a.font
        sc = self.score
        if self.hud_y < -50 or self.phase == "countdown":
            return
        hw, hh = a.hud_meta["size"]
        hx, hy = (S.SCREEN_W - hw) // 2, int(self.hud_y)
        surf.blit(a.hud_img, (hx, hy))
        slots = a.hud_meta["slots"]
        blink = (self.t % 0.4) < 0.2
        for ti, key in ((0, "portraits_A"), (1, "portraits_B")):
            for i, p in enumerate(self.teams[ti]):
                px, py = slots[key][i]
                a.portraits.draw(surf, "s_" + p.sheet_name, hx + px, hy + py)
                if self.phase == "play" and blink and self.can_hit(p):
                    pygame.draw.rect(surf, YELLOW, (hx + px - 1, hy + py - 1, 22, 22), 1)
            if sc.server == ti and self.phase in ("play", "between"):
                # bolinha do sacador do lado de fora do painel, na altura dos retratos
                a.ui.draw(surf, "icone_bola", hx - 4 if ti == 0 else hx + hw + 4, hy + 10, "topright" if ti == 0 else "topleft")
        for ti, key in ((0, "points_A"), (1, "points_B")):
            rx, ry, rw, rh = slots[key]
            txt = sc.score_text(ti)
            scale = 3 if len(txt) <= 2 else 2
            f.draw(surf, txt, hx + rx + rw // 2, hy + ry + rh // 2, WHITE, scale, "center")
        mx0 = hx + 100                       # coluna central: icone + texto alinhados a esquerda
        rx, ry, rw, rh = slots["timer"]
        a.ui.draw(surf, "icone_relogio", mx0, hy + ry)
        clock = fmt_time(self.time_left if self.time_left is not None else self.elapsed)
        f.draw(surf, clock, mx0 + 16, hy + ry + 2, YELLOW if self.sudden_death else WHITE)
        rx, ry, rw, rh = slots["meta"]
        a.ui.draw(surf, "icone_trofeu", mx0, hy + ry - 1)
        f.draw(surf, sc.meta_text(), mx0 + 16, hy + ry + 2, GREY)
        a.fx.draw(surf, "tag_voce", hx + 6, hy + 27)
        a.fx.draw(surf, "tag_rival", hx + hw - 6, hy + 27, "topright")
        if sc.is_deuce():
            f.draw(surf, "DEUCE", hx + hw // 2, hy + hh + 2, GREY, 1, "midtop")
        # medidor de velocidade
        vx, vy = hx + hw // 2 - 62, hy + hh + 4
        a.vel.draw(surf, f"vel_{self.level}", vx, vy)
        f.draw(surf, f"X{self.mult:.1f}", vx + 100, vy + 4, YELLOW if self.level >= S.FIRE_LEVEL else WHITE)
        if self.level >= S.FIRE_LEVEL:
            f.draw(surf, "EM CHAMAS!", vx + 48, vy + 18, (255, 150, 60), 1, "midtop", outline=BLACK)
        # vento
        if self.wind_on:
            wx, wy = S.SCREEN_W - 70, hy + 2
            a.ui.nine_slice(surf, "painel", (wx, wy, 66, 18))
            a.ui.draw(surf, "icone_vento", wx + 4, wy + 3)
            arrow = "↓" if self.wind > 0 else ("↑" if self.wind < 0 else "-")
            f.draw(surf, f"VENTO {arrow}", wx + 19, wy + 5, WHITE)

    def draw_countdown(self, surf):
        court = self.court
        pygame.draw.rect(surf, (0, 0, 0), (0, 0, S.SCREEN_W, 28))
        pygame.draw.rect(surf, (0, 0, 0), (0, S.SCREEN_H - 28, S.SCREEN_W, 28))
        name = COUNTDOWN[self.cd_i][0]
        cx, cy = court.net_x, court.center_y
        if name in ("3", "2", "1"):
            self.draw_big(surf, name, cx, cy - 12, pop_scale(self.phase_t))
            self.draw_big(surf, "PREPARAR", cx, cy + 44, 1.0)
        else:
            self.draw_big(surf, name, cx, cy - 4, pop_scale(self.phase_t))
        who = "VOCÊ" if self.server.human else ("PARCEIRO" if self.server.team == 0 else "RIVAL")
        self.a.font.draw(surf, f"SAQUE: {who}", cx, 40, WHITE, 1, "midtop", outline=BLACK)

    def draw_banner(self, surf):
        a = self.a
        f = a.font
        bn = self.banner
        y0 = 150
        ov = pygame.Surface((S.SCREEN_W, 62), pygame.SRCALPHA)
        ov.fill((10, 12, 20, 200))
        surf.blit(ov, (0, y0))
        t = self.phase_t
        title = bn["title"]
        x_title = 250 if bn["portrait"] else S.SCREEN_W // 2
        if bn["portrait"]:
            a.portraits.draw(surf, "l_" + bn["portrait"], 190, y0 + 8)
            img = a.big.get(title) if a.big.has(title) else f.render(title, YELLOW, 3, outline=BLACK, shadow=(0, 0, 0))
            draw_scaled(surf, img, x_title + img.get_width() // 2, y0 + 24, pop_scale(t))
            if bn["plus"] is not None:
                f.draw(surf, "+1", 470 + (0 if t > 0.3 else int((0.3 - t) * 20)), y0 + 12, GREEN, 2, "topleft", outline=BLACK)
        else:
            self.draw_big(surf, title, x_title, y0 + 24, pop_scale(t))
        f.draw(surf, bn["desc"], S.SCREEN_W // 2, y0 + 46, WHITE, 1, "midtop", outline=BLACK)

    def draw_end(self, surf):
        a = self.a
        f = a.font
        sc = self.score
        won = sc.winner == 0
        px, py, pw, ph = 140, 52, 360, 256
        a.ui.nine_slice(surf, "painel", (px, py, pw, ph))
        cx = S.SCREEN_W // 2
        self.draw_big(surf, "VITÓRIA!" if won else "DERROTA", cx, py + 30, pop_scale(self.phase_t, 0.4))
        if sc.kind == "padel":
            g = sc.history[-1] if sc.history else sc.games
            score_txt = f"{g[0]} - {g[1]}"
        else:
            score_txt = f"{sc.points[0]} - {sc.points[1]}"
        f.draw(surf, score_txt, cx, py + 52, WHITE, 3, "midtop", outline=BLACK)
        a.ui.draw(surf, "icone_relogio", cx - 52, py + 86)
        f.draw(surf, fmt_time(self.elapsed), cx - 36, py + 88, GREY)
        a.ui.draw(surf, "icone_trofeu", cx + 10, py + 86)
        f.draw(surf, f"+{self.coins}", cx + 26, py + 88, YELLOW)
        # tabela: colunas fixas
        c_name, c_pts, c_smash, c_vel = px + 20, px + 196, px + 254, px + 316
        ty = py + 110
        f.draw(surf, "PONTOS", c_pts, ty, DIM, 1, "midtop")
        f.draw(surf, "SMASH", c_smash, ty, DIM, 1, "midtop")
        f.draw(surf, "VEL MÁX", c_vel, ty, DIM, 1, "midtop")
        ty += 14
        for p in self.players:
            a.portraits.draw(surf, "s_" + p.sheet_name, c_name, ty - 4)
            f.draw(surf, p.name, c_name + 24, ty + 2, TEAM_COLORS[p.team])
            f.draw(surf, str(p.points_won), c_pts, ty + 2, WHITE, 1, "midtop")
            f.draw(surf, str(p.smashes), c_smash, ty + 2, WHITE, 1, "midtop")
            f.draw(surf, f"X{p.vmax:.1f}", c_vel, ty + 2, (255, 170, 80), 1, "midtop")
            ty += 20
        by = py + ph - 28
        draw_button(a, surf, "REVANCHE", cx - 120, by, 110, self.end_sel == 0)
        draw_button(a, surf, "VOLTAR AO CLUBE", cx + 10, by, 110, self.end_sel == 1)

    def draw_pause(self, surf):
        a = self.a
        f = a.font
        self._overlay.fill((10, 12, 20, 170))
        surf.blit(self._overlay, (0, 0))
        self.draw_big(surf, "PAUSA", S.SCREEN_W // 2, 104, 1.0, WHITE)
        f.draw(surf, f"MAIOR RALLY: {self.score.longest_rally}   VEL MÁX: X{self.max_mult:.1f}", S.SCREEN_W // 2, 128, YELLOW, 1, "midtop")
        if self.pause_menu:
            self.pause_menu.draw(surf)
        if self.app.overlay is None:
            draw_hints(a, surf, [("↑ ↓", "ESCOLHER"), ("E", "OK"), ("ESC", "CONTINUAR")])
