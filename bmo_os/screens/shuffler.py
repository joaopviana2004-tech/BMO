"""Shuffler — wrapper que alterna entre vários ambient screens.

Usado pelo modo "shuffle" (config ambient_mode = "shuffle"): a cada 10-30s
escolhe aleatoriamente outra tela ambient e mostra ela.

Cada screen embrulhada continua tendo seu próprio `handle_event`/`update`/
`draw` — só rotaciona qual é a "atual". Inputs (incluindo TAP pra abrir a
home) caem direto na screen atual, então o shuffler é transparente.
"""
from __future__ import annotations

import random

import pygame


SWITCH_MIN_S = 10.0
SWITCH_MAX_S = 30.0


class ShufflingAmbientScreen:
    def __init__(self, screens: list) -> None:
        assert len(screens) > 0, "shuffler precisa de pelo menos 1 screen"
        self._screens = screens
        self._idx = random.randrange(len(screens))
        self._t_since_switch = 0.0
        self._next_switch = random.uniform(SWITCH_MIN_S, SWITCH_MAX_S)

    @property
    def current(self):
        return self._screens[self._idx]

    def enter(self) -> None:
        self.current.enter()

    def exit(self) -> None:
        self.current.exit()

    def handle_event(self, event: pygame.event.Event) -> None:
        self.current.handle_event(event)

    def update(self, dt: float) -> None:
        self._t_since_switch += dt
        self.current.update(dt)
        if self._t_since_switch >= self._next_switch and len(self._screens) > 1:
            new_idx = self._idx
            while new_idx == self._idx:
                new_idx = random.randrange(len(self._screens))
            self.current.exit()
            self._idx = new_idx
            self.current.enter()
            self._t_since_switch = 0.0
            self._next_switch = random.uniform(SWITCH_MIN_S, SWITCH_MAX_S)

    def draw(self, surface: pygame.Surface) -> None:
        self.current.draw(surface)
