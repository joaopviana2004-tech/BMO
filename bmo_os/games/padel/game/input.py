"""Entrada unificada: teclado + controle (gamepad).

Mapeamento igual ao MinimumTennis (GamepadInputManager):
  analogico esquerdo / d-pad = mover        botao LESTE (B no Xbox / circulo) = golpe normal e saque
  botao SUL (A / X)          = lob          botao NORTE (Y / triangulo)        = golpe forte
  botao OESTE (X / quadrado) = deixadinha   START = pausa      BACK = voltar
Nos menus: d-pad/analogico navega, A ou B confirma, BACK/B... (B confirma; BACK volta).

Os botoes viram eventos KEYDOWN sinteticos (as cenas so conhecem teclas), e o analogico entra
no eixo de movimento junto com o teclado via `axis()`.
"""
import pygame

try:
    from pygame._sdl2 import controller as sdl_controller
except Exception:  # pragma: no cover
    sdl_controller = None

from . import settings as S

DEADZONE = 0.35

# botao do controle -> tecla equivalente
BUTTON_KEYS = {
    pygame.CONTROLLER_BUTTON_B: pygame.K_SPACE,       # leste: golpe normal / saque / confirmar
    pygame.CONTROLLER_BUTTON_A: pygame.K_c,           # sul: lob
    pygame.CONTROLLER_BUTTON_Y: pygame.K_x,           # norte: golpe forte
    pygame.CONTROLLER_BUTTON_X: pygame.K_v,           # oeste: deixadinha
    pygame.CONTROLLER_BUTTON_START: pygame.K_ESCAPE,  # pausa
    pygame.CONTROLLER_BUTTON_BACK: pygame.K_ESCAPE,   # voltar
    pygame.CONTROLLER_BUTTON_DPAD_UP: pygame.K_UP,
    pygame.CONTROLLER_BUTTON_DPAD_DOWN: pygame.K_DOWN,
    pygame.CONTROLLER_BUTTON_DPAD_LEFT: pygame.K_LEFT,
    pygame.CONTROLLER_BUTTON_DPAD_RIGHT: pygame.K_RIGHT,
}
MENU_CONFIRM_BUTTONS = (pygame.CONTROLLER_BUTTON_A,)   # nos menus o A tambem confirma


# joystick generico (sem mapeamento SDL): indices tipicos de um controle estilo Xbox no Windows
JOY_BUTTONS = {0: pygame.CONTROLLER_BUTTON_A, 1: pygame.CONTROLLER_BUTTON_B, 2: pygame.CONTROLLER_BUTTON_X,
               3: pygame.CONTROLLER_BUTTON_Y, 6: pygame.CONTROLLER_BUTTON_BACK, 7: pygame.CONTROLLER_BUTTON_START}
CONTROLLER_EVENTS = (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERAXISMOTION, pygame.CONTROLLERDEVICEADDED,
                     pygame.CONTROLLERDEVICEREMOVED, pygame.JOYBUTTONDOWN, pygame.JOYAXISMOTION,
                     pygame.JOYHATMOTION, pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED)


def key_event(key):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="", scancode=0, synthetic=True)


class Input:
    def __init__(self):
        self.controllers = {}
        self.joysticks = {}
        self.stick = [0.0, 0.0]
        self._nav = [0, 0]           # ultima direcao "digital" do analogico (para navegar menus)
        self._hat = (0, 0)
        self.ok = False
        try:
            pygame.joystick.init()
            if sdl_controller is not None:
                sdl_controller.init()
            for i in range(pygame.joystick.get_count()):
                self._add(i)
            self.ok = True
        except Exception as exc:
            print("controle desativado:", exc)

    def _add(self, index):
        try:
            if sdl_controller is not None and sdl_controller.is_controller(index):
                c = sdl_controller.Controller(index)
                self.controllers[c.id] = c
                print("controle conectado:", c.name)
            else:
                j = pygame.joystick.Joystick(index)
                self.joysticks[j.get_instance_id()] = j
                print("joystick generico conectado:", j.get_name())
        except Exception as exc:
            print("controle nao reconhecido:", exc)

    def _is_generic(self, ev):
        return getattr(ev, "instance_id", None) in self.joysticks

    @property
    def connected(self):
        return bool(self.controllers)

    def translate(self, ev, in_menu=False):
        """Converte um evento de controle em eventos de teclado. Devolve lista (pode ser vazia)."""
        out = []
        if ev.type == pygame.JOYDEVICEADDED:
            self._add(ev.device_index)
        elif ev.type in (pygame.CONTROLLERDEVICEREMOVED, pygame.JOYDEVICEREMOVED):
            iid = getattr(ev, "instance_id", None)
            self.controllers.pop(iid, None)
            self.joysticks.pop(iid, None)
            self.stick = [0.0, 0.0]
        elif ev.type == pygame.CONTROLLERBUTTONDOWN:
            out += self._button(ev.button, in_menu)
        elif ev.type == pygame.CONTROLLERAXISMOTION:
            out += self._axis(ev.axis, ev.value / 32767.0)
        # fallback: joystick sem mapeamento de controle
        elif ev.type == pygame.JOYBUTTONDOWN and self._is_generic(ev):
            if ev.button in JOY_BUTTONS:
                out += self._button(JOY_BUTTONS[ev.button], in_menu)
        elif ev.type == pygame.JOYAXISMOTION and self._is_generic(ev):
            if ev.axis in (0, 1):
                out += self._axis(ev.axis, ev.value)
        elif ev.type == pygame.JOYHATMOTION and self._is_generic(ev):
            hx, hy = ev.value
            if hx and hx != self._hat[0]:
                out.append(key_event(pygame.K_RIGHT if hx > 0 else pygame.K_LEFT))
            if hy and hy != self._hat[1]:
                out.append(key_event(pygame.K_UP if hy > 0 else pygame.K_DOWN))
            self._hat = (hx, hy)
        return out

    def _button(self, button, in_menu):
        if in_menu and button in MENU_CONFIRM_BUTTONS:
            return [key_event(pygame.K_RETURN)]
        if button in BUTTON_KEYS:
            return [key_event(BUTTON_KEYS[button])]
        return []

    def _axis(self, axis, v):
        if axis == pygame.CONTROLLER_AXIS_LEFTX:
            self.stick[0] = v
            return self._nav_edge(0, v, pygame.K_LEFT, pygame.K_RIGHT)
        if axis == pygame.CONTROLLER_AXIS_LEFTY:
            self.stick[1] = v
            return self._nav_edge(1, v, pygame.K_UP, pygame.K_DOWN)
        return []

    def _nav_edge(self, i, v, neg_key, pos_key):
        d = -1 if v < -0.6 else (1 if v > 0.6 else 0)
        if d == self._nav[i]:
            return []
        self._nav[i] = d
        if d < 0:
            return [key_event(neg_key)]
        if d > 0:
            return [key_event(pos_key)]
        return []

    def rumble(self, low=0.3, high=0.5, ms=120):
        """Vibra o controle (se houver). low/high em 0..1."""
        try:
            for c in self.controllers.values():
                c.rumble(low, high, ms)
            for j in self.joysticks.values():
                j.rumble(low, high, ms)
        except Exception:
            pass

    def sprint(self):
        """Shift no teclado ou os gatilhos/ombros do controle (segurado)."""
        k = pygame.key.get_pressed()
        if any(k[c] for c in S.HUMAN_KEYS["sprint"]):
            return True
        try:
            for c in self.controllers.values():
                if c.get_button(pygame.CONTROLLER_BUTTON_RIGHTSHOULDER) or c.get_button(pygame.CONTROLLER_BUTTON_LEFTSHOULDER):
                    return True
                if c.get_axis(pygame.CONTROLLER_AXIS_TRIGGERRIGHT) > 8000:
                    return True
            for j in self.joysticks.values():
                if j.get_numbuttons() > 5 and (j.get_button(4) or j.get_button(5)):
                    return True
        except Exception:
            pass
        return False

    def axis(self):
        """Eixo de movimento (-1..1, -1..1) combinando teclado e analogico esquerdo."""
        k = pygame.key.get_pressed()
        K = S.HUMAN_KEYS
        mx = (1 if any(k[c] for c in K["right"]) else 0) - (1 if any(k[c] for c in K["left"]) else 0)
        mz = (1 if any(k[c] for c in K["down"]) else 0) - (1 if any(k[c] for c in K["up"]) else 0)
        if mx == 0 and abs(self.stick[0]) > DEADZONE:
            mx = max(-1.0, min(1.0, self.stick[0]))
        if mz == 0 and abs(self.stick[1]) > DEADZONE:
            mz = max(-1.0, min(1.0, self.stick[1]))
        return float(mx), float(mz)
