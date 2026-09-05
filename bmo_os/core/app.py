"""Loop principal + scaler pixel-perfect.

Renderiza em surface 400x240 e escala 2x (nearest) pra janela 800x480.
No Pi, ative kiosk com SDL_VIDEODRIVER=kmsdrm pra rodar sem X.
"""
from __future__ import annotations

import os
import sys

import pygame

from . import config
from . import gamepad as bmo_gamepad
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
        # Overlay reutilizado pra dimming (config "brightness")
        self._dim_overlay = pygame.Surface(LOGICAL_SIZE)
        self._dim_overlay.fill((0, 0, 0))
        self.clock = pygame.time.Clock()
        # Controle: so traduz pros mesmos Actions do teclado/toque, entao vale
        # em toda tela sem que nenhuma precise saber que ele existe.
        self.gamepad = bmo_gamepad.Gamepad()
        self.manager = ScreenManager()
        self.running = True
        # Hook opcional chamado todo frame (depois do update, antes do draw).
        # Usado pra avisos de evento (main.py empilha a AlertScreen aqui).
        self.frame_hook = None
        # Hook opcional pra desenhar POR CIMA de qualquer tela (depois do draw
        # do screen, antes do dimming). Usado pelo overlay de voz (push-to-talk
        # funciona em qualquer tela e mostra gravando/pensando/falando).
        self.overlay_hook = None
        # Botão de mic virtual (MicButton); aparece nas telas com
        # show_mic_button=True. main.py atribui aqui.
        self.mic_button = None
        self._mic_pressed = False   # segurando o botão de mic agora? (grava enquanto True)
        # Hook opcional chamado quando a tela do topo MUDA (push/pop/replace).
        # main.py usa pra o BMO anunciar a tela ("aqui está ..."). Recebe a tela nova.
        self.on_screen_change = None
        self._last_screen_seen = None

    def _mic_visible(self) -> bool:
        return (self.mic_button is not None
                and config.get("mic_button_enabled")
                and getattr(self.manager.current, "show_mic_button", False))

    def _mic_hit(self, logical_pos) -> bool:
        if not self._mic_visible():
            return False
        return self.mic_button.rect_for(self.manager.current).collidepoint(logical_pos)

    def _to_logical(self, pos: tuple[int, int]) -> tuple[int, int]:
        win_w, win_h = self.window.get_size()
        lx = int(pos[0] * LOGICAL_SIZE[0] / win_w)
        ly = int(pos[1] * LOGICAL_SIZE[1] / win_h)
        return (lx, ly)

    def run(self, initial_screen) -> None:
        self.manager.push(initial_screen)
        while self.running:
            # screens podem pedir um FPS menor (ex: SuspendedScreen quer 5)
            target_fps = getattr(self.manager.current, "preferred_fps", FPS)
            dt = self.clock.tick(target_fps) / 1000.0
            theme_state.apply_theme()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_F4, pygame.K_f):
                    self.running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    logical = self._to_logical(event.pos)
                    # se o toque caiu no botão de mic (telas que o exibem),
                    # COMEÇA a gravar (grava enquanto segurar) e NÃO repassa o
                    # toque pra tela. O soltar (MOUSEBUTTONUP) encerra a gravação.
                    if self._mic_hit(logical):
                        self._mic_pressed = True
                        self.mic_button.press()
                    else:
                        bmo_input.dispatch_touch(logical)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if self._mic_pressed:
                        self._mic_pressed = False
                        self.mic_button.release()
                elif event.type == pygame.KEYDOWN:
                    bmo_input.dispatch_keyboard(event)
                elif event.type in bmo_gamepad.EVENTOS:
                    # Vira Action pro BMO — e o evento CRU segue para a tela do
                    # topo mesmo assim: o Padel le o controle direto, com o
                    # mapa de golpes dele, que o Action nao saberia expressar.
                    self.gamepad.handle_event(event)
                self.manager.handle_event(event)

            self.gamepad.update(dt)      # repeticao de quem segura o analogico
            self.manager.update(dt)
            if self.frame_hook is not None:
                self.frame_hook(dt)
            # detecta troca de tela (após updates/pushes deste frame)
            cur = self.manager.current
            if cur is not self._last_screen_seen:
                self._last_screen_seen = cur
                if self.on_screen_change is not None:
                    try:
                        self.on_screen_change(cur)
                    except Exception:
                        pass
            self.canvas.fill(Colors.BG_DARK)
            self.manager.draw(self.canvas)
            if self.overlay_hook is not None:
                self.overlay_hook(self.canvas)
            if self._mic_visible():
                cur = self.manager.current
                self.mic_button.draw(self.canvas, self.mic_button.rect_for(cur))
            # dimming software (overlay preto translúcido por cima do canvas)
            brightness = int(config.get("brightness") or 100)
            if brightness < 100:
                self._dim_overlay.set_alpha(int((100 - brightness) * 2.55))
                self.canvas.blit(self._dim_overlay, (0, 0))
            scaled = pygame.transform.scale(self.canvas, self.window.get_size())
            self.window.blit(scaled, (0, 0))
            pygame.display.flip()

        pygame.quit()
        sys.exit(0)
