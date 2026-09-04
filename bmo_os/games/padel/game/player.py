"""Jogador da partida: movimento com aceleracao (e corrida com shift), limites da meia-quadra e animacao."""
from . import settings as S
from .court import hyp, right_z


class Player:
    def __init__(self, idx, name, sheet_name, side, control, team=0, base_z=0.0):
        self.idx = idx
        self.name = name
        self.sheet_name = sheet_name
        self.side = side              # -1 esquerda, +1 direita (lado atual da quadra)
        self.control = control        # "p1" (humano) | "ai"
        self.team = team              # 0 = time do jogador, 1 = rivais
        self.base_z = base_z          # metade da quadra (z) que este jogador cobre nas duplas
        self.role = "back"            # "back" (fundo) | "net" (rede)
        self.x = side * 7.0
        self.z = base_z
        self.vx = self.vz = 0.0
        self.speed = S.PLAYER_SPEED
        self.accel = S.PLAYER_ACCEL
        self.locked = False           # travado durante o toss do saque
        self.visible = True
        self.walk_target = None       # movimento automatico (entrada em quadra)
        # corrida
        self.sprinting = False
        self.sprint_t = 10.0          # segundos desde que parou de correr (erro de controle decai)
        self.dust_t = 0.0
        # animacao
        self.anim_t = 0.0
        self.action = None            # forehand | backhand | smash | serve
        self.action_t = 0.0
        self.action_len = 0.0
        # golpes
        self.shot_req = None
        self.shot_t = 0.0
        self.aim = (0.0, 0.0)         # (eixo x, eixo z) do controle
        self.ai_target_z = 0.0
        self.ai_depth = 0.0
        self.ai_miss = None
        self.hit_cd = 0.0
        # estatisticas
        self.points_won = 0
        self.smashes = 0
        self.vmax = 1.0
        self.errors = 0

    @property
    def human(self):
        return self.control == "p1"

    @property
    def right_z(self):
        return right_z(self.side)

    @property
    def moving(self):
        return hyp(self.vx, self.vz) > 0.7

    # ------------------------------------------------------------------ golpes
    def request_shot(self, kind):
        self.shot_req = kind
        self.shot_t = S.INPUT_BUFFER

    def clear_shot(self):
        self.shot_req = None
        self.shot_t = 0.0
        self.ai_miss = None

    def play(self, action, sheet):
        self.action = action
        self.action_t = 0.0
        self.action_len = sheet.duration("side_" + action)

    def control_error(self):
        """Metros extras de erro no golpe por estar correndo (ou ter acabado de correr)."""
        if self.sprinting:
            return S.SPRINT_ERR
        return S.SPRINT_ERR * max(0.0, 1.0 - self.sprint_t / S.SPRINT_SETTLE)

    # ------------------------------------------------------------------ movimento
    def _bounds(self):
        if self.side < 0:
            return -S.COURT_HALF_L + 0.4, -0.45
        return 0.45, S.COURT_HALF_L - 0.4

    def move(self, dt, mx, mz, sprint=False):
        spd = self.speed * (S.SPRINT_MULT if sprint else 1.0)
        for axis, m in (("vx", mx), ("vz", mz)):
            v = getattr(self, axis)
            target = m * spd
            if abs(m) > 0.1:
                if v < target:
                    v = min(v + self.accel * dt, target)
                else:
                    v = max(v - self.accel * dt, target)
            else:
                v *= max(0.0, 1.0 - 12.0 * dt)
            setattr(self, axis, v)
        sp = hyp(self.vx, self.vz)
        if sp > spd:
            self.vx *= spd / sp
            self.vz *= spd / sp
        self.x += self.vx * dt
        self.z += self.vz * dt
        lo, hi = self._bounds()
        self.x = min(max(self.x, lo), hi)
        self.z = min(max(self.z, -S.COURT_HALF_W + 0.3), S.COURT_HALF_W - 0.3)
        self.sprinting = bool(sprint) and (abs(mx) > 0.1 or abs(mz) > 0.1)

    def stop(self, dt):
        self.vx *= max(0.0, 1.0 - 12.0 * dt)
        self.vz *= max(0.0, 1.0 - 12.0 * dt)
        self.sprinting = False

    def place(self, x, z):
        self.x, self.z = x, z
        self.vx = self.vz = 0.0
        self.action = None
        self.locked = False
        self.walk_target = None
        self.sprinting = False
        self.sprint_t = 10.0
        self.clear_shot()

    def walk_step(self, dt):
        """Anda automaticamente ate walk_target (usado na entrada em quadra). Devolve True ao chegar."""
        if self.walk_target is None:
            return True
        tx, tz = self.walk_target
        dx, dz = tx - self.x, tz - self.z
        d = hyp(dx, dz)
        if d < 0.15:
            self.walk_target = None
            self.vx = self.vz = 0.0
            self.x, self.z = tx, tz
            return True
        sp = min(self.speed * 0.8, d / dt)
        self.vx, self.vz = dx / d * sp, dz / d * sp
        self.x += self.vx * dt
        self.z += self.vz * dt
        return False

    def update(self, dt):
        self.anim_t += dt * (1.5 if self.sprinting else 1.0)
        if self.sprinting:
            self.sprint_t = 0.0
        else:
            self.sprint_t += dt
        if self.action is not None:
            self.action_t += dt
            if self.action_t >= self.action_len:
                self.action = None
        if self.shot_req is not None:
            self.shot_t -= dt
            if self.shot_t <= 0:
                self.clear_shot()
        if self.hit_cd > 0:
            self.hit_cd -= dt

    # ------------------------------------------------------------------ desenho
    def current_frame(self, sheet):
        toward_net_flip = self.side > 0   # sprite 'side' olha para a direita; o jogador da direita olha para a esquerda
        if self.action is not None:
            anim = "side_" + self.action
            i = self.action_t * sheet.fps_of(anim)
            return sheet.frame(anim, i, toward_net_flip)
        if self.moving:
            if abs(self.vz) > abs(self.vx) * 1.3:
                anim = "front_run" if self.vz > 0 else "back_run"
                flip = False
            else:
                anim = "side_run"
                flip = self.vx < 0
        else:
            anim = "side_idle"
            flip = toward_net_flip
        return sheet.frame(anim, self.anim_t * sheet.fps_of(anim), flip)

    def draw(self, surf, court, sheet):
        if not self.visible:
            return
        sx, sy = court.ground(self.x, self.z)
        img = self.current_frame(sheet)
        surf.blit(img, (int(sx) - 16, int(sy) - 29))
