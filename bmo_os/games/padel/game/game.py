"""Aplicacao: janela, loop principal, tela de titulo (com partida de bots ao fundo) e troca de cenas."""
import math

import pygame

from . import config
from . import settings as S
from .assets import Assets
from .club import ClubScene
from .input import CONTROLLER_EVENTS, Input
from .match import MatchScene, demo_options
from .menu import MatchMenu, default_options
from .menus import ControlsScreen, MenuList, OptionsMenu, draw_hints
from .sounds import Sounds
from .ui import BLACK, DIM, GREY, WHITE, YELLOW

VERSION = "0.2"


class TitleScene:
    def __init__(self, app):
        self.app = app
        self.a = app.assets
        self.t = 0.0
        self.menu = None
        self.arena_i = 0
        self.demo = MatchScene(app, demo_options(S.ARENAS[self.arena_i]), demo=True)
        self.overlay = pygame.Surface((S.SCREEN_W, S.SCREEN_H), pygame.SRCALPHA)
        self.overlay.fill((8, 10, 18, 150))
        items = [
            dict(label="ENTRAR NO CLUBE", action=app.to_club),
            dict(label="PARTIDA RÁPIDA", action=self.quick_match),
            dict(label="QUADRA", value=lambda: S.ARENAS[self.arena_i].upper(), change=self.change_arena),
            dict(label="CONTROLES", action=app.open_controls),
            dict(label="OPÇÕES", action=app.open_options),
            dict(label="SAIR", action=app.quit),
        ]
        self.list = MenuList(app, items, S.SCREEN_W // 2 - 84, 152, 168)
        app.sounds.play_music("clube")

    def change_arena(self, d):
        self.arena_i = (self.arena_i + d) % len(S.ARENAS)
        self.demo = MatchScene(self.app, demo_options(S.ARENAS[self.arena_i]), demo=True)

    def quick_match(self):
        pal = S.ARENAS[self.arena_i]
        opts = self.app.quick_options.get(pal) or default_options(pal, f"QUADRA {pal.upper()}")

        def play(o):
            self.app.quick_options[pal] = dict(o)
            self.app.start_match(o, on_finish=lambda m: self.app.to_menu())

        def back():
            self.menu = None

        self.menu = MatchMenu(self.app, opts, play, back)

    def in_menu(self):
        return True

    def handle_event(self, ev):
        if self.menu is not None:
            self.menu.handle_event(ev)
            return
        self.list.handle_event(ev)

    def update(self, dt):
        self.t += dt
        self.demo.update(dt)
        if self.menu is not None:
            self.menu.update(dt)

    def draw(self, surf):
        a = self.a
        f = a.font
        self.demo.draw(surf)
        surf.blit(self.overlay, (0, 0))
        if self.menu is not None:
            self.menu.draw(surf)
            return
        cx = S.SCREEN_W // 2
        bob = int(math.sin(self.t * 2.0) * 3)
        f.draw(surf, "THE PADEL GAME", cx, 56 + bob, YELLOW, 4, "midtop", outline=BLACK, shadow=(0, 0, 0))
        # bola quicando ao lado do titulo
        bx = cx + 190
        by = 96 - int(abs(math.sin(self.t * 3.2)) * 22)
        a.fx.draw(surf, "sombra_bola", bx, 98, "center")
        surf.blit(a.ball, (bx - 3, by - 3))
        f.draw(surf, "PIXEL ART  -  REGRAS DO PADEL  -  1X1 OU 2X2 COM BOTS", cx, 108, GREY, 1, "midtop")
        self.list.draw(surf)
        if self.app.overlay is None:
            draw_hints(a, surf, [("↑ ↓", "ESCOLHER"), ("← →", "MUDAR"), ("E", "OK"), ("F11", "TELA CHEIA")])
        f.draw(surf, f"V{VERSION}", S.SCREEN_W - 6, S.SCREEN_H - 14, DIM, 1, "topright")


class App:
    def __init__(self):
        pygame.mixer.pre_init(22050, -16, 2, 512, allowedchanges=0)
        pygame.init()
        pygame.display.set_caption("The Padel Game")
        self.config = config.load()
        self.screen = pygame.display.set_mode((S.SCREEN_W, S.SCREEN_H), pygame.SCALED | pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.assets = Assets()
        self.sounds = Sounds(self.config["sfx"], self.config["music"])
        self.input = Input()
        self.running = True
        self.club = None
        self.quick_options = {}
        self.overlay = None
        self.fullscreen = False
        self.apply_fullscreen()
        self.scene = TitleScene(self)

    # ------------------------------------------------------------------ cenas
    def to_menu(self):
        self.scene = TitleScene(self)

    def to_club(self):
        if self.club is None:
            self.club = ClubScene(self)
        self.club.enter()
        self.scene = self.club

    def start_match(self, options, on_finish=None):
        self.scene = MatchScene(self, options, on_finish=on_finish or (lambda m: self.to_menu()))

    def start_match_from_club(self, court, options):
        ex, ey, ew, eh = court["entrance"]
        back_y = ey + eh + 12 if court["entrance_side"] == "bottom" else ey - 12

        def back(_match):
            self.club.place(ex + ew // 2, back_y)
            self.club.enter()
            self.scene = self.club

        self.start_match(options, on_finish=back)

    # ------------------------------------------------------------------ overlays e config
    def open_options(self):
        self.overlay = OptionsMenu(self, self.close_overlay)

    def open_controls(self):
        self.overlay = ControlsScreen(self, self.close_overlay)

    def close_overlay(self):
        self.overlay = None

    def apply_fullscreen(self):
        want = bool(self.config.get("fullscreen"))
        if want != self.fullscreen:
            pygame.display.toggle_fullscreen()
            self.fullscreen = want

    def toggle_fullscreen(self):
        self.config["fullscreen"] = not self.fullscreen
        config.save(self.config)
        self.apply_fullscreen()

    def quit(self):
        self.running = False

    # ------------------------------------------------------------------ loop
    def run(self):
        while self.running:
            dt = min(self.clock.tick(S.FPS) / 1000.0, 1.0 / 20.0)
            target = self.overlay if self.overlay is not None else self.scene
            in_menu = self.overlay is not None or (self.scene.in_menu() if hasattr(self.scene, "in_menu") else True)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
                elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_F11:
                    self.toggle_fullscreen()
                elif ev.type in CONTROLLER_EVENTS:
                    for kev in self.input.translate(ev, in_menu):
                        target.handle_event(kev)
                else:
                    target.handle_event(ev)
            if self.overlay is None or isinstance(self.scene, TitleScene):
                self.scene.update(dt)
            if self.overlay is not None:
                self.overlay.update(dt)
            self.scene.draw(self.screen)
            if self.overlay is not None:
                self.overlay.draw(self.screen)
            pygame.display.flip()
        config.save(self.config)
        pygame.quit()
