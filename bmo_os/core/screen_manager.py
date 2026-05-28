"""Pilha de telas (push/pop) com transições simples."""
from __future__ import annotations

from typing import Protocol

import pygame


class Screen(Protocol):
    def enter(self) -> None: ...
    def exit(self) -> None: ...
    def handle_event(self, event: pygame.event.Event) -> None: ...
    def update(self, dt: float) -> None: ...
    def draw(self, surface: pygame.Surface) -> None: ...


class ScreenManager:
    def __init__(self) -> None:
        self._stack: list[Screen] = []

    @property
    def current(self) -> Screen | None:
        return self._stack[-1] if self._stack else None

    def push(self, screen: Screen) -> None:
        if self.current is not None:
            self.current.exit()
        self._stack.append(screen)
        screen.enter()

    def pop(self) -> None:
        if not self._stack:
            return
        self._stack.pop().exit()
        if self.current is not None:
            self.current.enter()

    def replace(self, screen: Screen) -> None:
        while self._stack:
            self._stack.pop().exit()
        self.push(screen)

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.current:
            self.current.handle_event(event)

    def update(self, dt: float) -> None:
        if self.current:
            self.current.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        if self.current:
            self.current.draw(surface)
