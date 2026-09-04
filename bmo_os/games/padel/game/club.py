"""Mapa do clube: o jogador anda livremente, a camera segue, e nas aberturas das quadras
aparece o balao [E] INICIAR JOGO que abre o menu de nova partida."""
import math

import pygame

from . import settings as S
from .menu import MatchMenu, default_options
from .menus import draw_hints
from .ui import WHITE, YELLOW, GREY

WALK_SPEED = 95.0   # px/s


class ClubScene:
    def __init__(self, app, sheet_name="timeA_p1"):
        self.app = app
        self.a = app.assets
        self.map_img, meta = self.a.club_map()
        self.meta = meta
        self.map_w, self.map_h = meta["size"]
        self.colliders = [pygame.Rect(r) for r in meta["colliders"]]
        self.courts = meta["courts"]
        self.npcs = meta["npcs"]
        self.sheet = self.a.sheet(sheet_name)
        self.npc_sheets = {n["sheet"]: self.a.sheet(n["sheet"]) for n in self.npcs}
        sx, sy = meta["spawn"]
        self.x, self.y = float(sx), float(sy)
        self.facing = "front"
        self.flip = False
        self.moving = False
        self.anim_t = 0.0
        self.cam = [0, 0]
        self.near_court = None
        self.menu = None
        self.options = {}     # opcoes lembradas por quadra
        self.hint_t = 6.0
        self.fade = 1.0

    # ------------------------------------------------------------------ util
    def feet_rect(self, x=None, y=None):
        x = self.x if x is None else x
        y = self.y if y is None else y
        return pygame.Rect(int(x) - 5, int(y) - 5, 10, 6)

    def _blocked(self, rect):
        return any(rect.colliderect(c) for c in self.colliders)

    def place(self, x, y):
        self.x, self.y = float(x), float(y)
        self.fade = 1.0
        self.menu = None

    def enter(self):
        """Chamado sempre que a cena do clube volta a ser a ativa."""
        self.fade = 1.0
        self.menu = None
        self.app.sounds.play_music("clube")

    def court_title(self, c):
        return f"QUADRA {c['id']} - {c['palette'].upper()}"

    def in_menu(self):
        return True

    # ------------------------------------------------------------------ loop
    def handle_event(self, ev):
        if self.menu is not None:
            self.menu.handle_event(ev)
            return
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key == pygame.K_ESCAPE:
            self.app.sounds.play("back")
            self.app.to_menu()
        elif ev.key in S.HUMAN_KEYS["confirm"] and self.near_court is not None:
            self.open_menu(self.near_court)

    def open_menu(self, court):
        opts = self.options.get(court["id"])
        if opts is None:
            opts = default_options(court["palette"], self.court_title(court))
            self.options[court["id"]] = opts
        self.app.sounds.play("select")

        def play(o):
            self.options[court["id"]] = dict(o)
            self.menu = None
            self.app.start_match_from_club(court, o)

        def back():
            self.menu = None

        self.menu = MatchMenu(self.app, opts, play, back)

    def update(self, dt):
        self.anim_t += dt
        self.hint_t -= dt
        if self.fade > 0:
            self.fade = max(0.0, self.fade - dt * 2.5)
        if self.menu is not None:
            self.menu.update(dt)
            self.moving = False
            return
        mx, my = self.app.input.axis()
        self.moving = bool(mx or my)
        if self.moving:
            n = math.hypot(mx, my)
            dx, dy = mx / n * WALK_SPEED * dt, my / n * WALK_SPEED * dt
            if not self._blocked(self.feet_rect(self.x + dx, self.y)):
                self.x += dx
            if not self._blocked(self.feet_rect(self.x, self.y + dy)):
                self.y += dy
            if abs(my) > abs(mx):
                self.facing = "front" if my > 0 else "back"
                self.flip = False
            else:
                self.facing = "side"
                self.flip = mx < 0
        self.x = min(max(self.x, 8), self.map_w - 8)
        self.y = min(max(self.y, 8), self.map_h - 8)

        self.cam[0] = int(min(max(self.x - S.SCREEN_W // 2, 0), self.map_w - S.SCREEN_W))
        self.cam[1] = int(min(max(self.y - S.SCREEN_H // 2, 0), self.map_h - S.SCREEN_H))

        fr = self.feet_rect().inflate(12, 12)
        self.near_court = None
        for c in self.courts:
            if fr.colliderect(pygame.Rect(c["entrance"])):
                self.near_court = c
                break

    # ------------------------------------------------------------------ desenho
    def draw(self, surf):
        a = self.a
        f = a.font
        cx, cy = self.cam
        surf.blit(self.map_img, (-cx, -cy))
        ents = []
        for n in self.npcs:
            sheet = self.npc_sheets[n["sheet"]]
            anim = n["facing"] + "_idle"
            ents.append((n["y"], sheet.frame(anim, self.anim_t * sheet.fps_of(anim)), n["x"], n["y"]))
        anim = self.facing + ("_walk" if self.moving else "_idle")
        ents.append((self.y, self.sheet.frame(anim, self.anim_t * self.sheet.fps_of(anim), self.flip), self.x, self.y))
        for _, img, x, y in sorted(ents, key=lambda e: e[0]):
            a.fx.draw(surf, "sombra_jogador", int(x) - cx, int(y) - cy, "center")
            surf.blit(img, (int(x) - cx - 16, int(y) - cy - 29))

        if self.near_court is not None and self.menu is None:
            # titulo da quadra
            title = self.court_title(self.near_court)
            w = f.width(title) + 16
            a.ui.nine_slice(surf, "painel", (S.SCREEN_W // 2 - w // 2, 4, w, 18))
            f.draw(surf, title, S.SCREEN_W // 2, 9, WHITE, 1, "midtop")
            # balao sobre o jogador
            bx, by = int(self.x) - cx, int(self.y) - cy - 44
            bw = 14 + 6 + f.width("INICIAR JOGO") + 12
            a.ui.nine_slice(surf, "painel_claro", (bx - bw // 2, by - 4, bw, 20))
            a.ui.draw(surf, "tecla_E", bx - bw // 2 + 5, by - 1)
            f.draw(surf, "INICIAR JOGO", bx - bw // 2 + 24, by + 2, (30, 34, 44))

        if self.menu is None and self.app.overlay is None:
            draw_hints(a, surf, [(("W", "A", "S", "D"), "ANDAR"), ("E", "USAR"), ("ESC", "MENU")])

        if self.menu is not None:
            self.menu.draw(surf)
        if self.fade > 0:
            ov = pygame.Surface((S.SCREEN_W, S.SCREEN_H))
            ov.fill((0, 0, 0))
            ov.set_alpha(int(255 * self.fade))
            surf.blit(ov, (0, 0))
