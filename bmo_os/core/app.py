"""Loop principal + scaler pixel-perfect.

Renderiza em surface 400x240 e escala 2x (nearest) pra janela 800x480.
No Pi, ative kiosk com SDL_VIDEODRIVER=kmsdrm pra rodar sem X.
"""
from __future__ import annotations

import os
import sys

import pygame

from . import input as bmo_input
from . import theme_state
from .screen_manager import ScreenManager
from .theme import Colors, FPS, LOGICAL_SIZE, WINDOW_SIZE


class App:
    def __init__(self, *, fullscreen: bool = False) -> None:
        pygame.init()
        flags = pygame.SCALED | pygame.NOFRAME
        if fullscreen:
            flags |= pygame.FULLSCREEN
        self.window = pygame.display.set_mode(WINDOW_SIZE, flags)
        pygame.display.set_caption("BMO OS")
        pygame.mouse.set_visible(False)
        self.canvas = pygame.Surface(LOGICAL_SIZE).convert()
        self.clock = pygame.time.Clock()
        self.manager = ScreenManager()
        self.running = True

    def _to_logical(self, pos: tuple[int, int]) -> tuple[int, int]:
        win_w, win_h = self.window.get_size()
        lx = int(pos[0] * LOGICAL_SIZE[0] / win_w)
        ly = int(pos[1] * LOGICAL_SIZE[1] / win_h)
        return (lx, ly)

    def run(self, initial_screen) -> None:
        self.manager.push(initial_screen)
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            theme_state.apply_theme()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F4:
                    self.running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    bmo_input.dispatch_touch(self._to_logical(event.pos))
                elif event.type == pygame.KEYDOWN:
                    bmo_input.dispatch_keyboard(event)
                self.manager.handle_event(event)

            self.manager.update(dt)
            self.canvas.fill(Colors.BG_DARK)
            self.manager.draw(self.canvas)
            scaled = pygame.transform.scale(self.canvas, self.window.get_size())
            self.window.blit(scaled, (0, 0))
            pygame.display.flip()

        pygame.quit()
        sys.exit(0)
