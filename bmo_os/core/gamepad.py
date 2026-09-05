"""Controle (gamepad) → os mesmos Actions do resto do BMO.

É o "segundo módulo" que a docstring do core/input.py já previa: ele não fala
com tela nenhuma, só posta `ACTION_EVENT` igual ao teclado e ao toque. Por isso
o controle passa a funcionar em TODAS as telas de uma vez, sem que nenhuma
precise saber que ele existe.

Mapeamento (nomes do SDL, que já traduz o layout de cada controle):

    d-pad / analógico esquerdo   UP · DOWN · LEFT · RIGHT
    A (sul)                      A       confirmar
    B (leste)                    B       voltar
    START                        MENU
    BACK/SELECT                  B

O analógico precisa de duas coisas que o d-pad não precisa: zona morta, pra
tremor de mola não virar navegação; e repetição com atraso, pra segurar pro
lado andar item a item em vez de disparar sessenta por segundo ou um só.

Sem controle plugado a classe é inerte — nada de exceção, nada de log a cada
quadro. Plugar e desplugar no meio do uso funciona (o SDL avisa por evento).
"""
from __future__ import annotations

import pygame

from .input import Action, post

try:                                    # pragma: no cover - depende do build
    from pygame._sdl2 import controller as sdl_controller
except Exception:
    sdl_controller = None

# Fora deste raio o analógico conta como direção. 0.5 é alto de propósito: o
# analógico aqui navega menu, e menu errado por encostar sem querer irrita mais
# do que ter que empurrar com vontade.
ZONA_MORTA = 0.5
# Segurar pro lado: espera este tanto antes de começar a repetir...
REPETE_APOS_S = 0.42
# ...e daí anda um item a cada este tanto.
REPETE_CADA_S = 0.13

BOTOES = {}
EIXO_X = EIXO_Y = None
if sdl_controller is not None:
    BOTOES = {
        pygame.CONTROLLER_BUTTON_A: Action.A,
        pygame.CONTROLLER_BUTTON_B: Action.B,
        pygame.CONTROLLER_BUTTON_START: Action.MENU,
        pygame.CONTROLLER_BUTTON_BACK: Action.B,
        pygame.CONTROLLER_BUTTON_DPAD_UP: Action.UP,
        pygame.CONTROLLER_BUTTON_DPAD_DOWN: Action.DOWN,
        pygame.CONTROLLER_BUTTON_DPAD_LEFT: Action.LEFT,
        pygame.CONTROLLER_BUTTON_DPAD_RIGHT: Action.RIGHT,
    }
    EIXO_X = pygame.CONTROLLER_AXIS_LEFTX
    EIXO_Y = pygame.CONTROLLER_AXIS_LEFTY

# Joystick sem perfil do SDL (controle genérico): índices típicos de um layout
# estilo Xbox. É rede de segurança — com perfil, o caminho acima é o que vale.
JOY_BOTOES = {0: Action.A, 1: Action.B, 6: Action.B, 7: Action.MENU}

EVENTOS = (
    pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERAXISMOTION,
    pygame.CONTROLLERDEVICEADDED, pygame.CONTROLLERDEVICEREMOVED,
    pygame.JOYBUTTONDOWN, pygame.JOYAXISMOTION, pygame.JOYHATMOTION,
    pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED,
)

# Do eixo pro par de Actions (negativo, positivo).
_EIXOS = {0: (Action.LEFT, Action.RIGHT), 1: (Action.UP, Action.DOWN)}


class Gamepad:
    def __init__(self) -> None:
        self._controllers: dict[int, object] = {}
        self._joysticks: dict[int, object] = {}
        # direção digital que o analógico está indicando agora, por eixo
        self._eixo: dict[int, int] = {0: 0, 1: 0}
        self._proxima_repeticao: dict[int, float] = {0: 0.0, 1: 0.0}
        self._hat = (0, 0)
        self.ok = False
        try:
            pygame.joystick.init()
            if sdl_controller is not None:
                sdl_controller.init()
            for i in range(pygame.joystick.get_count()):
                self._abrir(i)
            self.ok = True
        except Exception as exc:
            print("[gamepad] desativado:", exc)

    # ---------- dispositivos ----------

    @property
    def conectado(self) -> bool:
        return bool(self._controllers or self._joysticks)

    def _abrir(self, indice: int) -> None:
        try:
            if sdl_controller is not None and sdl_controller.is_controller(indice):
                c = sdl_controller.Controller(indice)
                self._controllers[c.get_instance_id()] = c
                print(f"[gamepad] controle: {c.name}")
                return
        except Exception:
            pass
        try:
            j = pygame.joystick.Joystick(indice)
            j.init()
            self._joysticks[j.get_instance_id()] = j
            print(f"[gamepad] joystick: {j.get_name()}")
        except Exception:
            pass

    def _fechar(self, iid: int) -> None:
        self._controllers.pop(iid, None)
        self._joysticks.pop(iid, None)
        self._eixo = {0: 0, 1: 0}

    # ---------- eventos ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        """Traduz um evento de controle em Action(s). Silencioso pro resto."""
        t = event.type
        if t in (pygame.CONTROLLERDEVICEADDED, pygame.JOYDEVICEADDED):
            self._abrir(getattr(event, "device_index", 0))
            return
        if t in (pygame.CONTROLLERDEVICEREMOVED, pygame.JOYDEVICEREMOVED):
            self._fechar(getattr(event, "instance_id", -1))
            return

        if t == pygame.CONTROLLERBUTTONDOWN:
            acao = BOTOES.get(event.button)
            if acao is not None:
                post(acao)
            return

        if t == pygame.JOYBUTTONDOWN:
            # Só vale pro joystick cru: com perfil do SDL o evento de controller
            # já cobriu, e tratar os dois faria cada botão contar em dobro.
            if event.instance_id in self._joysticks:
                acao = JOY_BOTOES.get(event.button)
                if acao is not None:
                    post(acao)
            return

        if t == pygame.JOYHATMOTION:
            x, y = event.value
            if (x, y) != self._hat:
                self._hat = (x, y)
                if x < 0:
                    post(Action.LEFT)
                elif x > 0:
                    post(Action.RIGHT)
                if y > 0:
                    post(Action.UP)          # no hat do SDL, +1 é pra cima
                elif y < 0:
                    post(Action.DOWN)
            return

        if t in (pygame.CONTROLLERAXISMOTION, pygame.JOYAXISMOTION):
            eixo = getattr(event, "axis", -1)
            if eixo in (0, 1):
                self._ler_eixo(eixo, event.value / 32768.0
                               if abs(event.value) > 1.5 else float(event.value))

    def _ler_eixo(self, eixo: int, valor: float) -> None:
        """Converte a posição analógica em -1, 0 ou +1 e dispara na virada."""
        direcao = 0
        if valor <= -ZONA_MORTA:
            direcao = -1
        elif valor >= ZONA_MORTA:
            direcao = 1
        if direcao == self._eixo.get(eixo, 0):
            return
        self._eixo[eixo] = direcao
        if direcao == 0:
            return
        negativa, positiva = _EIXOS[eixo]
        post(negativa if direcao < 0 else positiva)
        self._proxima_repeticao[eixo] = REPETE_APOS_S

    # ---------- quadro ----------

    def update(self, dt: float) -> None:
        """Repetição de quem está segurando o analógico. Sem isso, empurrar e
        manter andaria um item só e a navegação pareceria travada."""
        for eixo, direcao in self._eixo.items():
            if direcao == 0:
                continue
            self._proxima_repeticao[eixo] -= dt
            if self._proxima_repeticao[eixo] > 0.0:
                continue
            self._proxima_repeticao[eixo] = REPETE_CADA_S
            negativa, positiva = _EIXOS[eixo]
            post(negativa if direcao < 0 else positiva)
