"""Botão físico de push-to-talk via GPIO (gpiozero).

Liga callbacks de pressionar/soltar a um botão num pino GPIO. Botão ligado
entre o pino e o GND (pull-up interno ligado → sem resistor). Enquanto
pressionado, o BMO grava; ao soltar, transcreve.

Degrada com elegância: sem gpiozero ou fora do Pi, ok=False e não faz nada
(no PC use o botão da tela TESTE).

Ligação (padrão PTT_GPIO=17):
    botão entre GPIO17 (pino físico 11) e GND (pino físico 9). Sem resistor.
    Troque o pino com a env PTT_GPIO.
"""
from __future__ import annotations

try:
    from gpiozero import Button
    HAS_GPIO = True
except Exception:  # pragma: no cover - só roda no Pi
    Button = None  # type: ignore
    HAS_GPIO = False


class GPIOButton:
    def __init__(self, pin: int, on_press, on_release) -> None:
        self.ok = False
        self.error = ""
        self.pressed = False   # estado atual (pra debug na tela TESTE)
        self._btn = None
        if not HAS_GPIO:
            self.error = "gpiozero indisponivel"
            return
        try:
            # pull_up: botão entre o pino e o GND. bounce_time evita repique.
            self._btn = Button(pin, pull_up=True, bounce_time=0.05)
            # embrulha os callbacks pra rastrear o estado do botão (a tela TESTE
            # lê self.pressed / is_pressed). gpiozero chama isto numa thread.
            self._btn.when_pressed = self._wrap(on_press, True)
            self._btn.when_released = self._wrap(on_release, False)
            self.ok = True
        except Exception as e:
            self.error = f"gpio: {str(e)[:50]}"
            self._btn = None

    def _wrap(self, fn, pressed: bool):
        def handler():
            self.pressed = pressed
            if fn:
                fn()
        return handler

    def close(self) -> None:
        """Libera o pino GPIO. Necessário antes do execv do restart: o lgpio
        deixa o fd aberto e o processo novo não consegue reivindicar o pino."""
        if self._btn is not None:
            try:
                self._btn.close()
            except Exception:
                pass
            self._btn = None
        self.ok = False

    @property
    def is_pressed(self) -> bool:
        """Estado do botão. Lê direto do pino (gpiozero) quando dá — assim
        reflete a realidade mesmo se um callback se perdeu; senão usa o
        último estado visto pelos callbacks."""
        if self._btn is not None:
            try:
                return bool(self._btn.is_pressed)
            except Exception:
                pass
        return self.pressed
