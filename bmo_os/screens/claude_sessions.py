"""Tela CLAUDE — acompanha as sessões do Claude Code rodando no PC.

Uma linha por sessão: pasta, cronômetro do turno, o que está fazendo agora e
um traço por ferramenta já executada. Os dados vêm do painel que roda no PC
(claude-painel/server.mjs), lido pela ClaudeSessionsService.

Como a tela é preto-e-branco, o estado crítico — "precisa de você" — aparece
como **linha invertida piscando**: é o único que exige ação e tem que saltar
aos olhos de longe.

Modo menu: HOME sai, SYNC força refresh, cima/baixo rolam.
Modo ambient (descanso): toque volta pra home.
"""
from __future__ import annotations

import math
import time

import pygame

from ..core import input as bmo_input
from ..core.theme import LOGICAL_SIZE, render_text
from ..core.widgets import CRT_BLACK, CRT_DIM, CRT_WHITE, SAFE_INSET
from ..services import audio
from ..services.claude_sessions import ClaudeSession, ClaudeSessionsService

# Paleta curta de propósito: cor só onde ela carrega informação (o estado da
# sessão e o resultado de cada ferramenta). Texto e moldura seguem CRT — é o
# que impede a tela de virar um papagaio.
LARANJA = pygame.Color(232, 150, 42)    # trabalhando
VERMELHO = pygame.Color(226, 74, 62)    # precisa de você / falhou
VERDE = pygame.Color(64, 198, 148)      # concluída

COR_STATUS = {
    "working": LARANJA,
    "waiting": VERMELHO,
    "error": VERMELHO,
    "done": VERDE,
    "idle": CRT_DIM,
    "ended": CRT_DIM,
}

HEADER_Y = SAFE_INSET                    # 14
ROWS_TOP = HEADER_Y + 30                 # 44
ROW_H = 42
MAX_VISIBLE = 4                          # 44 + 4*42 = 212
FOOTER_Y = LOGICAL_SIZE[1] - SAFE_INSET  # 226

FONT_TITLE = 11
FONT_FOLDER = 11
FONT_CLOCK = 13
FONT_LINE = 9
FONT_HINT = 8

BLINK_HZ = 1.6

# Área rolável: começa embaixo do cabeçalho e vai até o rodapé.
LIST_TOP = ROWS_TOP                      # 44
LIST_H = MAX_VISIBLE * ROW_H             # 168
LIST_BOTTOM = LIST_TOP + LIST_H          # 212

# Arrasto com o dedo. O limiar separa "toquei" de "arrastei": sem ele, o
# tremor natural do dedo ao tocar viraria rolagem e a tela sairia sozinha.
DRAG_LIMIAR_PX = 4
TRILHO = pygame.Color(38, 38, 38)   # fundo da barra de rolagem (abaixo do DIM)
PEGADOR = pygame.Color(165, 165, 165)   # o cursor dela: precisa saltar num 5"

# Lado da célula do bichinho, em pixels lógicos. 1 mantém a arte pixel nítida
# (cada célula vira 2px de verdade no 800x480) e o bicho cabe na linha do título.
ESCALA_BICHO = 1
ATRITO = 0.88          # por 1/60s — desacelera o embalo depois que solta
VEL_MINIMA = 8.0       # px/s abaixo disso a inércia para (evita tremeliques)
# Teto de velocidade: dois eventos de movimento no mesmo milissegundo dariam
# uma divisão por ~0 e a lista dispararia até o fim num piscar.
VEL_MAXIMA = 1200.0

# O bichinho do Claude Code, célula a célula. Os "." são buraco de verdade
# (alpha zero): os olhos e os vãos entre as pernas mostram o fundo da linha,
# que é o que dá a silhueta — pintar de preto quebraria em cima da faixa lateral.
BICHO_CLAUDE = (
    ".########.",
    ".########.",
    ".#.####.#.",   # olhos
    "##########",   # bracinhos saindo dos dois lados
    "##########",
    ".########.",
    ".##.##.##.",   # três perninhas
    ".##.##.##.",
)

# Sprite pronto por (cor, escala): são ~60 quadradinhos por bicho e até 5 bichos
# por quadro — no Pi 4 não vale redesenhar isso 30x por segundo.
_sprites_bicho: dict[tuple, pygame.Surface] = {}


def sprite_bicho_claude(cor, escala: int = 1) -> pygame.Surface:
    chave = (cor.r, cor.g, cor.b, escala)
    img = _sprites_bicho.get(chave)
    if img is None:
        larg = len(BICHO_CLAUDE[0]) * escala
        alt = len(BICHO_CLAUDE) * escala
        img = pygame.Surface((larg, alt), pygame.SRCALPHA)
        for ly, linha in enumerate(BICHO_CLAUDE):
            for lx, c in enumerate(linha):
                if c == "#":
                    img.fill(cor, (lx * escala, ly * escala, escala, escala))
        _sprites_bicho[chave] = img
    return img


def desenhar_bicho_claude(surface: pygame.Surface, x: int, y: int,
                          cor, escala: int = 1) -> None:
    surface.blit(sprite_bicho_claude(cor, escala), (x, y))


def _mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def _fit(text: str, max_chars: int) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)] + "."


def _to_logical(pos: tuple[int, int]) -> tuple[int, int]:
    """Pixel físico da janela -> canvas lógico 400x240.

    Os eventos crus do pygame (MOUSEMOTION etc.) chegam na tela SEM passar
    pelo App._to_logical — só o ACTION_EVENT vem convertido. Mesmo helper do
    tasks.py, que também precisa dos eventos crus pra arrastar card.
    """
    w, h = pygame.display.get_window_size()
    if w <= 0 or h <= 0:
        return pos
    return (pos[0] * LOGICAL_SIZE[0] // w, pos[1] * LOGICAL_SIZE[1] // h)


class ClaudeSessionsScreen:
    voice_announce = "Suas sessoes do Claude."
    show_mic_button = False   # tela de monitoramento: nada cobrindo as linhas

    def __init__(
        self,
        *,
        on_back=None,
        on_open_home=None,
        claude: ClaudeSessionsService,
        ambient: bool = False,
    ) -> None:
        self.on_back = on_open_home or on_back
        self.claude = claude
        self.ambient = ambient
        self.scroll = 0.0        # deslocamento em PIXELS (não em linhas)
        self._t = 0.0
        self._sync_flash_until = 0.0
        # arrasto
        self._arrastando = False
        self._ultimo_y = 0
        self._y0 = 0
        self._andou = False
        self._vel = 0.0
        self._t_arrasto = 0.0

    def enter(self) -> None:
        self.claude.trigger_refresh()
        self.scroll = 0.0
        self._vel = 0.0

    def exit(self) -> None: ...

    # ---------- rolagem ----------

    def _max_scroll(self) -> float:
        n = len(self.claude.get().sessions)
        return max(0.0, n * ROW_H - LIST_H)

    def _clamp(self) -> None:
        teto = self._max_scroll()
        if self.scroll < 0.0:
            self.scroll = 0.0
            self._vel = 0.0
        elif self.scroll > teto:
            self.scroll = teto
            self._vel = 0.0

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        # embalo: depois que o dedo sai, a lista segue e vai parando
        if not self._arrastando and abs(self._vel) > VEL_MINIMA:
            self.scroll += self._vel * dt
            self._vel *= ATRITO ** max(1.0, dt * 60.0)
        elif not self._arrastando:
            self._vel = 0.0
        self._clamp()

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        # Eventos CRUS primeiro: são os únicos que dão o arrasto (o ACTION_EVENT
        # só existe no toque inicial, não no movimento do dedo).
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._iniciar_arrasto(_to_logical(event.pos))
            return
        if event.type == pygame.MOUSEMOTION:
            if self._arrastando and pygame.mouse.get_pressed()[0]:
                self._mover_arrasto(_to_logical(event.pos))
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._soltar_arrasto()
            return

        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        pos = getattr(event, "pos", None)

        if self.ambient:
            # O TAP nasce no APERTAR do dedo — sair aqui mataria toda rolagem
            # antes do primeiro pixel. Quem decide é o soltar, que já sabe se
            # o dedo andou. Teclado (A/MENU) não arrasta, então sai na hora.
            if action in (bmo_input.Action.A, bmo_input.Action.MENU) and pos is None:
                audio.play("select")
                self.on_back()
            return

        if action == bmo_input.Action.TAP and pos is not None:
            if self._back_btn().collidepoint(pos):
                audio.play("back")
                self.on_back()
            elif self._sync_btn().collidepoint(pos):
                audio.play("tick")
                self.claude.trigger_refresh()
                self._sync_flash_until = self._t + 0.4
            return

        if action in (bmo_input.Action.B, bmo_input.Action.MENU):
            audio.play("back")
            self.on_back()
        elif action == bmo_input.Action.UP:
            self.scroll -= ROW_H
            self._vel = 0.0
            self._clamp()
        elif action == bmo_input.Action.DOWN:
            self.scroll += ROW_H
            self._vel = 0.0
            self._clamp()
        elif action == bmo_input.Action.A:
            audio.play("tick")
            self.claude.trigger_refresh()
            self._sync_flash_until = self._t + 0.4

    # ---------- arrasto com o dedo ----------

    def _iniciar_arrasto(self, pos) -> None:
        if not self.ambient and (self._back_btn().collidepoint(pos)
                                 or self._sync_btn().collidepoint(pos)):
            return                      # botão do cabeçalho não rola a lista
        self._arrastando = True
        self._andou = False
        self._y0 = pos[1]
        self._ultimo_y = pos[1]
        self._vel = 0.0
        self._t_arrasto = time.monotonic()

    def _mover_arrasto(self, pos) -> None:
        dy = pos[1] - self._ultimo_y
        self._ultimo_y = pos[1]
        if abs(pos[1] - self._y0) >= DRAG_LIMIAR_PX:
            self._andou = True
        if dy == 0:
            return
        agora = time.monotonic()
        dt = max(1e-3, agora - self._t_arrasto)
        self._t_arrasto = agora
        # dedo sobe => conteúdo sobe => scroll aumenta
        self.scroll -= dy
        self._vel = max(-VEL_MAXIMA, min(VEL_MAXIMA, -dy / dt))
        self._clamp()

    def _soltar_arrasto(self) -> None:
        if not self._arrastando:
            return                      # arrasto nem chegou a começar
        self._arrastando = False
        if self._andou:
            return                      # foi rolagem: deixa a inércia correr
        self._vel = 0.0
        if self.ambient:                # toque limpo no descanso: volta pro menu
            audio.play("select")
            self.on_back()

    # ---------- hitboxes ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, HEADER_Y, 52, 16)

    def _sync_btn(self) -> pygame.Rect:
        return pygame.Rect(LOGICAL_SIZE[0] - SAFE_INSET - 52, HEADER_Y, 52, 16)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        snap = self.claude.get()
        self._draw_header(surface, snap)

        if not snap.sessions:
            self._draw_empty(surface, snap)
        else:
            # recorte: a linha que entra/sai é cortada na borda da área, senão
            # ela invadiria o cabeçalho e o rodapé durante o arrasto
            area = pygame.Rect(0, LIST_TOP, LOGICAL_SIZE[0], LIST_H)
            antigo = surface.get_clip()
            surface.set_clip(area)
            desloc = int(self.scroll)
            for i, sess in enumerate(snap.sessions):
                y = LIST_TOP + i * ROW_H - desloc
                if y > LIST_BOTTOM or y + ROW_H < LIST_TOP:
                    continue                  # fora da vista: nem desenha
                self._draw_row(surface, y, sess, snap.fetched_at)
            surface.set_clip(antigo)
            self._draw_scrollbar(surface, len(snap.sessions))

        self._draw_footer(surface, snap)

    # ---------- header ----------

    def _draw_header(self, surface, snap) -> None:
        if not self.ambient:
            self._draw_back_btn(surface)
            self._draw_sync_btn(surface)

        title = render_text("CLAUDE", FONT_TITLE, CRT_WHITE)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, HEADER_Y + 1)))

        # contadores coloridos pelo próprio status — a cor vira vocabulário:
        # a mesma que aparece na faixa lateral de cada linha.
        partes = [
            (str(snap.count("working")), " ativas", LARANJA),
            (str(snap.count("waiting")), " esperando", VERMELHO),
            (str(snap.count("done")), " prontas", VERDE),
        ]
        n_erro = snap.count("error")
        if n_erro:   # só aparece quando existe — senão é ruído fixo no topo
            partes.append((str(n_erro), " com erro", VERMELHO))
        larguras = []
        for num, rotulo, _ in partes:
            larguras.append(render_text(num, FONT_LINE, CRT_WHITE, pixel=False).get_width()
                            + render_text(rotulo + "   ", FONT_LINE, CRT_DIM, pixel=False).get_width())
        x = LOGICAL_SIZE[0] // 2 - sum(larguras) // 2
        for (num, rotulo, cor), _w in zip(partes, larguras):
            n_img = render_text(num, FONT_LINE, cor, pixel=False)
            surface.blit(n_img, (x, HEADER_Y + 16))
            x += n_img.get_width()
            r_img = render_text(rotulo + "   ", FONT_LINE, CRT_DIM, pixel=False)
            surface.blit(r_img, (x, HEADER_Y + 16))
            x += r_img.get_width()

        if self.ambient:
            clock = render_text(time.strftime("%H:%M"), FONT_LINE, CRT_DIM, pixel=False)
            surface.blit(clock, clock.get_rect(topright=(LOGICAL_SIZE[0] - SAFE_INSET, HEADER_Y + 2)))

    def _draw_back_btn(self, surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        pygame.draw.polygon(surface, CRT_WHITE, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        img = render_text("HOME", 8, CRT_WHITE, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _draw_sync_btn(self, surface) -> None:
        rect = self._sync_btn()
        flashing = self._t < self._sync_flash_until
        bg = CRT_WHITE if flashing else CRT_BLACK
        fg = CRT_BLACK if flashing else CRT_WHITE
        pygame.draw.rect(surface, bg, rect)
        pygame.draw.rect(surface, CRT_WHITE, rect, 1)
        ix, iy = rect.left + 9, rect.centery
        pygame.draw.arc(surface, fg, pygame.Rect(ix - 5, iy - 5, 10, 10),
                        -math.pi / 2, math.pi, 2)
        pygame.draw.polygon(surface, fg, [
            (ix, iy - 7), (ix + 4, iy - 4), (ix - 1, iy - 4),
        ])
        img = render_text("SYNC", 8, fg, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 18, rect.centery)))

    # ---------- linha de sessão ----------

    def _draw_row(self, surface, y: int, s: ClaudeSession, fetched_at: float) -> None:
        rect = pygame.Rect(SAFE_INSET, y, LOGICAL_SIZE[0] - SAFE_INSET * 2, ROW_H - 4)
        cor = COR_STATUS.get(s.status, CRT_DIM)

        # "precisa de você" pulsa em vermelho — é o único estado que cobra ação.
        alert = s.status == "waiting"
        pulso = alert and (math.sin(self._t * BLINK_HZ * math.pi * 2) > -0.3)

        pygame.draw.rect(surface, CRT_BLACK, rect)
        pygame.draw.rect(surface, cor if (alert and pulso) else CRT_DIM,
                         rect, 2 if alert else 1)
        # faixa lateral: o sinal que se lê de longe, sem precisar ler texto
        pygame.draw.rect(surface, cor, (rect.left, rect.top, 3, rect.height))
        fg = CRT_WHITE
        dim = CRT_DIM

        # linha 1: o bichinho do Claude + pasta ......... cronômetro
        desenhar_bicho_claude(surface, rect.left + 6, rect.top + 5, cor, ESCALA_BICHO)

        folder = render_text(_fit(s.folder, 24), FONT_FOLDER, fg, pixel=False)
        surface.blit(folder, folder.get_rect(topleft=(rect.left + 20, rect.top + 3)))

        elapsed = s.elapsed_s
        if s.running and fetched_at:
            # o snapshot pode ter até POLL_INTERVAL_S de idade: completa o
            # tempo decorrido desde o fetch pra o cronômetro não travar
            elapsed += max(0.0, time.time() - fetched_at)
        # o cronômetro também assume a cor do status: reforça o sinal sem
        # inventar cor nova (a linha concluída ficava verde de menos)
        cor_relogio = cor if s.status in ("working", "waiting", "done", "error") else fg
        clock = render_text(_mmss(elapsed) if s.elapsed_s or s.running else "--:--",
                            FONT_CLOCK, cor_relogio, pixel=False)
        surface.blit(clock, clock.get_rect(topright=(rect.right - 5, rect.top + 2)))

        # linha 2: o que importa agora, por status
        if s.status == "waiting":
            info = s.notice or "aguardando sua resposta"
        elif s.status == "error":
            info = f"falhou: {s.notice or 'desconhecido'}"
        elif s.status == "done":
            info = s.last_message or "turno concluido"
        elif s.current_tool:
            info = f"> {s.current_tool}"
        elif s.status == "working":
            info = "> pensando"
        elif s.status == "ended":
            # sessão encerrada NÃO está esperando prompt nenhum — dizer isso
            # era o que fazia toda linha morta parecer uma sessão ociosa viva
            info = s.last_message or s.prompt or "sessao encerrada"
        else:
            info = s.prompt or "aguardando prompt"
        cor_info = cor if s.status in ("waiting", "error") else CRT_WHITE
        img = render_text(_fit(info, 55), FONT_LINE, cor_info, pixel=False)
        surface.blit(img, img.get_rect(topleft=(rect.left + 20, rect.top + 17)))

        # linha 3: um traço por ferramenta + barra indeterminada enquanto roda
        self._draw_tools(surface, rect, s, fg, dim)

    def _draw_tools(self, surface, rect: pygame.Rect, s: ClaudeSession, fg, dim) -> None:
        """Um pontinho por ferramenta executada, e cada um diz o que aconteceu:

            vermelho = a ferramenta falhou
            âmbar    = mexeu em alguma coisa (Write/Edit/Bash)
            cinza    = só leu (Read/Grep/Glob)

        É a contagem real de tool calls — nunca uma estimativa de progresso.
        """
        ty = rect.top + 30
        x = rect.left + 20
        max_tracos = 40
        # mostra as ÚLTIMAS, não as primeiras: o que importa é o agora
        ticks = s.ticks[-max_tracos:] if len(s.ticks) > max_tracos else s.ticks

        for i, t in enumerate(ticks):
            px = x + i * 5
            if t.failed:
                # falha ganha um pontinho mais alto pra destacar no relevo
                pygame.draw.rect(surface, VERMELHO, (px, ty - 1, 3, 6))
            elif t.kind == "acao":
                pygame.draw.rect(surface, LARANJA, (px, ty, 3, 4))
            else:
                pygame.draw.rect(surface, CRT_DIM, (px, ty + 1, 3, 2))

        fim_x = x + len(ticks) * 5

        # ferramenta rodando agora: contorno pulsando na ponta da fila
        if s.current_tool:
            pulso = (math.sin(self._t * 5.0) * 0.5 + 0.5)
            if pulso > 0.35:
                pygame.draw.rect(surface, CRT_WHITE, (fim_x, ty - 1, 3, 6), 1)
            fim_x += 6

        # resumo numérico: total, e as falhas em vermelho se houver
        if s.tool_count:
            cortadas = s.tool_count - len(ticks)
            txt = f"{s.tool_count}" + (f"  (+{cortadas})" if cortadas > 0 else "")
            cnt = render_text(txt, 8, CRT_DIM, pixel=False)
            surface.blit(cnt, cnt.get_rect(midleft=(fim_x + 4, ty + 2)))
            fim_x += 4 + cnt.get_width()
        if s.fail_count:
            err = render_text(f"{s.fail_count} erro" + ("s" if s.fail_count > 1 else ""),
                              8, VERMELHO, pixel=False)
            surface.blit(err, err.get_rect(midleft=(fim_x + 5, ty + 2)))

        # barra indeterminada: NÃO existe percentual real de conclusão, então
        # ela só diz "ainda está rodando" — nunca "falta tanto".
        if s.running and s.status == "working":
            bar = pygame.Rect(rect.right - 66, ty + 1, 52, 3)
            span = bar.width - 14
            off = int((math.sin(self._t * 2.2) * 0.5 + 0.5) * span)
            pygame.draw.rect(surface, LARANJA, (bar.left + off, bar.top + 1, 14, 1))

    def _draw_scrollbar(self, surface, total: int) -> None:
        """Barra fina na borda direita — com rolagem contínua, seta piscando
        não diz mais nada: o que importa é ONDE você está na lista."""
        if total <= MAX_VISIBLE:
            return
        teto = self._max_scroll()
        x = LOGICAL_SIZE[0] - 7
        pygame.draw.rect(surface, TRILHO, (x, LIST_TOP, 3, LIST_H))
        altura = max(14, int(LIST_H * LIST_H / (total * ROW_H)))
        frac = (self.scroll / teto) if teto > 0 else 0.0
        y = LIST_TOP + int(frac * (LIST_H - altura))
        pygame.draw.rect(surface, PEGADOR, (x, y, 3, altura))

    # ---------- vazio / rodapé ----------

    def _draw_empty(self, surface, snap) -> None:
        cx = LOGICAL_SIZE[0] // 2
        cy = LOGICAL_SIZE[1] // 2
        if snap.ok:
            msg = "Nenhuma sessao aberta"
            hint = "mande um prompt no VS Code"
        else:
            msg = "Painel offline"
            hint = _fit(snap.error or self.claude.base_url(), 46)
        a = render_text(msg, 12, CRT_WHITE, pixel=False)
        b = render_text(hint, 9, CRT_DIM, pixel=False)
        surface.blit(a, a.get_rect(center=(cx, cy - 6)))
        surface.blit(b, b.get_rect(center=(cx, cy + 14)))

    def _draw_footer(self, surface, snap) -> None:
        if not snap.ok:
            img = render_text("sem contato com o painel do PC", FONT_HINT,
                              VERMELHO, pixel=False)
            surface.blit(img, img.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, FOOTER_Y)))
            return

        # legenda dos pontinhos: sem isso a cor é enfeite, com isso é vocabulário
        if snap.sessions:
            itens = [(LARANJA, "mexeu"), (CRT_DIM, "leu"), (VERMELHO, "falhou")]
            larg = sum(14 + render_text(t, FONT_HINT, CRT_DIM, pixel=False).get_width()
                       for _, t in itens)
            x = LOGICAL_SIZE[0] // 2 - larg // 2
            ly = FOOTER_Y - 6
            for cor, texto in itens:
                pygame.draw.rect(surface, cor, (x, ly - 2, 3, 4))
                img = render_text(texto, FONT_HINT, CRT_DIM, pixel=False)
                surface.blit(img, img.get_rect(midleft=(x + 6, ly)))
                x += 14 + img.get_width()
            return

        idade = max(0, int(time.time() - snap.fetched_at)) if snap.fetched_at else 0
        txt = ("toque para abrir o menu" if self.ambient
               else f"atualizado ha {idade}s    HOME / SYNC nos cantos")
        img = render_text(txt, FONT_HINT, CRT_DIM, pixel=False)
        surface.blit(img, img.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, FOOTER_Y)))
