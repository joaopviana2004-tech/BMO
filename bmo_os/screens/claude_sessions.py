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

# Marcador ASCII por status (a fonte pixel não tem acento/símbolo)
GLYPH = {
    "idle": "-",
    "working": ">",
    "waiting": "!",
    "done": "*",
    "error": "X",
    "ended": ".",
}


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
        self.scroll = 0
        self._t = 0.0
        self._sync_flash_until = 0.0

    def enter(self) -> None:
        self.claude.trigger_refresh()

    def exit(self) -> None: ...

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        n = len(self.claude.get().sessions)
        max_scroll = max(0, n - MAX_VISIBLE)
        self.scroll = min(self.scroll, max_scroll)

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        action = event.action
        pos = getattr(event, "pos", None)

        if self.ambient:
            if action in (bmo_input.Action.TAP, bmo_input.Action.A,
                          bmo_input.Action.MENU):
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
            self.scroll = max(0, self.scroll - 1)
        elif action == bmo_input.Action.DOWN:
            n = len(self.claude.get().sessions)
            self.scroll = min(max(0, n - MAX_VISIBLE), self.scroll + 1)
        elif action == bmo_input.Action.A:
            audio.play("tick")
            self.claude.trigger_refresh()
            self._sync_flash_until = self._t + 0.4

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
            visible = snap.sessions[self.scroll: self.scroll + MAX_VISIBLE]
            for i, sess in enumerate(visible):
                y = ROWS_TOP + i * ROW_H
                self._draw_row(surface, y, sess, snap.fetched_at)
            self._draw_scroll_hints(surface, len(snap.sessions))

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

        # linha 1: marcador + pasta ......... cronômetro
        glyph = render_text(GLYPH.get(s.status, "-"), FONT_FOLDER, cor)
        surface.blit(glyph, glyph.get_rect(topleft=(rect.left + 7, rect.top + 4)))

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

    def _draw_scroll_hints(self, surface, total: int) -> None:
        if self.ambient or total <= MAX_VISIBLE:
            return
        if self.scroll > 0:
            pygame.draw.polygon(surface, CRT_DIM, [
                (LOGICAL_SIZE[0] - 8, ROWS_TOP + 4),
                (LOGICAL_SIZE[0] - 2, ROWS_TOP + 4),
                (LOGICAL_SIZE[0] - 5, ROWS_TOP),
            ])
        if self.scroll + MAX_VISIBLE < total:
            ybot = ROWS_TOP + MAX_VISIBLE * ROW_H - 8
            pygame.draw.polygon(surface, CRT_DIM, [
                (LOGICAL_SIZE[0] - 8, ybot),
                (LOGICAL_SIZE[0] - 2, ybot),
                (LOGICAL_SIZE[0] - 5, ybot + 4),
            ])

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
