"""Camada de input lógico.

Hoje só lê touch (vem como mouse no pygame). Quando os botões físicos
chegarem via GPIO, basta um segundo módulo que emite os mesmos Actions
no mesmo evento USEREVENT — nenhuma tela precisa mudar.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import pygame


class Action(Enum):
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    A = auto()       # botão vermelho — confirmar
    B = auto()       # botão verde — voltar
    MENU = auto()    # triângulo — abrir menu
    TAP = auto()     # toque na tela (com posição)
    BACK = auto()


ACTION_EVENT = pygame.event.custom_type()


@dataclass(frozen=True)
class InputEvent:
    action: Action
    pos: tuple[int, int] | None = None  # preenchido em TAP


KEY_MAP = {
    pygame.K_UP: Action.UP,
    pygame.K_DOWN: Action.DOWN,
    pygame.K_LEFT: Action.LEFT,
    pygame.K_RIGHT: Action.RIGHT,
    pygame.K_RETURN: Action.A,
    pygame.K_SPACE: Action.A,
    pygame.K_ESCAPE: Action.B,
    pygame.K_BACKSPACE: Action.B,
    pygame.K_TAB: Action.MENU,
}


def dispatch_keyboard(event: pygame.event.Event) -> None:
    if event.type == pygame.KEYDOWN and event.key in KEY_MAP:
        post(KEY_MAP[event.key])


def dispatch_touch(logical_pos: tuple[int, int]) -> None:
    post(Action.TAP, pos=logical_pos)


def post(action: Action, *, pos: tuple[int, int] | None = None) -> None:
    pygame.event.post(
        pygame.event.Event(ACTION_EVENT, action=action, pos=pos)
    )
