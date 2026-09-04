"""Tela PADEL — roda o The Padel Game dentro do BMO.

O jogo mora em `bmo_os/games/padel/` e entra aqui **sem uma linha alterada**:
tudo que ele precisa é um alvo de desenho e uma lista de eventos por quadro. O
`App` dele já separa as duas coisas — `run()` é só o laço em volta — então esta
tela reimplementa esse laço e o resto do jogo segue igual.

O que NÃO herdamos do `App.__init__` original, e por quê:

    pygame.init() / set_mode()   a janela é do BMO, não do jogo
    mixer.pre_init()             o mixer já foi aberto pelo services/audio
    apply_fullscreen()           tela cheia quem decide é o BMO (--fullscreen)

O jogo desenha em 640x360. Aqui ele é reduzido para caber na ÁREA SEGURA
(372x212), não nos 400x240 inteiros: a moldura física cobre `SAFE_INSET` de
cada lado, e é justamente ali que ficam o placar (topo) e a barra de dicas
(rodapé). Escalar para a tela cheia deixaria os dois debaixo do plástico.

Controle: o `Input` do próprio jogo cuida do gamepad (API de controller do SDL2
com queda para joystick genérico). O BMO não liga o subsistema de joystick, ele
liga — então o Xbox por cabo funciona aqui sem nada a mais.
"""
from __future__ import annotations

import pygame

from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import CRT_BLACK, CRT_DIM, CRT_WHITE, SAFE_INSET

# Resolução nativa do jogo. Não é ajustável: o layout dele é desenhado nela.
JOGO_W, JOGO_H = 640, 360

# Caixa em que o jogo cabe sem nada debaixo da moldura.
CAIXA_W = LOGICAL_SIZE[0] - SAFE_INSET * 2      # 372
CAIXA_H = LOGICAL_SIZE[1] - SAFE_INSET * 2      # 212


def _encaixe() -> tuple[int, int, int, int]:
    """Onde e de que tamanho o quadro do jogo entra no canvas do BMO."""
    escala = min(CAIXA_W / JOGO_W, CAIXA_H / JOGO_H)
    w = int(JOGO_W * escala)
    h = int(JOGO_H * escala)
    return (LOGICAL_SIZE[0] - w) // 2, (LOGICAL_SIZE[1] - h) // 2, w, h


DEST_X, DEST_Y, DEST_W, DEST_H = _encaixe()


class PadelScreen:
    voice_announce = "O jogo de padel."
    show_mic_button = False    # o jogo usa a tela toda; botão flutuante atrapalha
    # O jogo é escrito para 60 fps (física e animações contam com isso). O BMO
    # roda a 30 por padrão e respeita este pedido enquanto a tela estiver no topo.
    preferred_fps = 60

    def __init__(self, *, on_back=None) -> None:
        self.on_back = on_back
        self._app = None
        self._quadro = None          # Surface 640x360 onde o jogo desenha
        self._eventos: list = []     # o que chegou desde o último passo
        self._erro = ""
        self._carregando = True      # mostra um aviso antes de travar carregando

    # ---------- ciclo de vida ----------

    def enter(self) -> None:
        # De propósito NÃO carregamos aqui: montar os assets e sintetizar os
        # sons leva um tempo visível, e enter() roda antes do primeiro draw —
        # o BMO ficaria congelado sem explicar por quê. O carregamento acontece
        # no primeiro update, depois que "CARREGANDO" já apareceu na tela.
        self._carregando = True

    def exit(self) -> None:
        if self._app is not None:
            try:
                from ..games.padel.game import config as padel_config
                padel_config.save(self._app.config)   # volume/mira que o jogador ajustou
            except Exception:
                pass
        self._silenciar()
        # Solta o jogo inteiro: ele segura spritesheets, atlas e áudio, e esta
        # tela pode ser aberta e fechada muitas vezes numa sessão.
        self._app = None
        self._quadro = None
        self._eventos.clear()

    def _silenciar(self) -> None:
        try:
            pygame.mixer.music.stop()
            pygame.mixer.stop()
        except Exception:
            pass

    # ---------- carregamento ----------

    def _montar(self) -> None:
        """Cria o App do jogo apontando o desenho para um Surface nosso."""
        from ..games.padel.game import config as padel_config
        from ..games.padel.game import settings as S
        from ..games.padel.game.assets import Assets
        from ..games.padel.game.game import App, TitleScene
        from ..games.padel.game.input import Input
        from ..games.padel.game.sounds import Sounds

        quadro = pygame.Surface((S.SCREEN_W, S.SCREEN_H)).convert()

        class AppEmbutido(App):
            """O App do jogo, sem as três coisas que são do dono da janela."""

            def __init__(interno):
                interno.config = padel_config.load()
                interno.screen = quadro
                interno.clock = pygame.time.Clock()
                interno.assets = Assets()
                try:
                    interno.sounds = Sounds(interno.config["sfx"], interno.config["music"])
                except Exception:
                    # Sem áudio o jogo continua jogável; um mixer ocupado ou num
                    # formato inesperado não pode impedir a partida.
                    interno.sounds = _SemSom()
                interno.input = Input()
                interno.running = True
                interno.club = None
                interno.quick_options = {}
                interno.overlay = None
                interno.fullscreen = False
                interno.scene = TitleScene(interno)

            def apply_fullscreen(interno):
                pass          # a janela não é do jogo

            def toggle_fullscreen(interno):
                pass

        self._quadro = quadro
        self._app = AppEmbutido()

    # ---------- entrada ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        # Só empilha; quem entrega ao jogo é o update, que é onde o quadro dele
        # acontece. Assim a ordem evento->update->draw fica igual à do laço
        # original e nada é processado duas vezes.
        if self._app is None:
            return
        if event.type in (pygame.KEYDOWN, pygame.KEYUP, pygame.MOUSEBUTTONDOWN,
                          pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION,
                          pygame.TEXTINPUT):
            self._eventos.append(event)
            return
        from ..games.padel.game.input import CONTROLLER_EVENTS
        if event.type in CONTROLLER_EVENTS:
            self._eventos.append(event)

    # ---------- quadro ----------

    def update(self, dt: float) -> None:
        if self._app is None:
            if not self._carregando:
                return                      # já falhou; não tenta de novo todo quadro
            self._carregando = False
            try:
                self._montar()
            except Exception as exc:
                self._erro = f"{type(exc).__name__}: {exc}"[:120]
            return

        app = self._app
        # O jogo conta com ~1/60 e protege contra travadas longas do mesmo jeito
        # que o laço original fazia.
        passo = min(dt, 1.0 / 20.0)

        alvo = app.overlay if app.overlay is not None else app.scene
        em_menu = app.overlay is not None or (
            app.scene.in_menu() if hasattr(app.scene, "in_menu") else True)

        from ..games.padel.game.input import CONTROLLER_EVENTS
        for ev in self._eventos:
            try:
                if ev.type in CONTROLLER_EVENTS:
                    for kev in app.input.translate(ev, em_menu):
                        alvo.handle_event(kev)
                else:
                    alvo.handle_event(ev)
            except Exception:
                pass                        # um evento torto não derruba a tela
        self._eventos.clear()

        try:
            if app.overlay is None or type(app.scene).__name__ == "TitleScene":
                app.scene.update(passo)
            if app.overlay is not None:
                app.overlay.update(passo)
            app.scene.draw(self._quadro)
            if app.overlay is not None:
                app.overlay.draw(self._quadro)
        except Exception as exc:
            self._erro = f"{type(exc).__name__}: {exc}"[:120]
            self._app = None
            self._silenciar()
            return

        # SAIR no menu do jogo derruba o `running` dele — é a saída natural,
        # e usá-la evita inventar um atalho que brigue com o ESC (que lá dentro
        # é pausa, não "voltar pro BMO").
        if not app.running and self.on_back is not None:
            self.on_back()

    # ---------- desenho ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)

        if self._erro:
            self._aviso(surface, "O jogo nao subiu", self._erro)
            return
        if self._app is None or self._quadro is None:
            self._aviso(surface, "CARREGANDO", "montando quadra e sons")
            return

        # smoothscale, não scale: em 0,58x o vizinho-mais-próximo joga fora
        # linhas inteiras e a fonte 5x7 do placar vira sujeira ilegível.
        surface.blit(pygame.transform.smoothscale(self._quadro, (DEST_W, DEST_H)),
                     (DEST_X, DEST_Y))

    def _aviso(self, surface: pygame.Surface, titulo: str, detalhe: str) -> None:
        cx = LOGICAL_SIZE[0] // 2
        cy = LOGICAL_SIZE[1] // 2
        a = render_text(titulo, 12, CRT_WHITE, pixel=False)
        surface.blit(a, a.get_rect(center=(cx, cy - 8)))
        if detalhe:
            b = render_text(detalhe[:52], 8, CRT_DIM, pixel=False)
            surface.blit(b, b.get_rect(center=(cx, cy + 12)))


class _SemSom:
    """Dublê do Sounds para quando o mixer não colaborar — engole tudo."""

    def __getattr__(self, _nome):
        return lambda *a, **k: None
