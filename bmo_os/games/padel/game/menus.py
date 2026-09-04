"""Widgets de menu compartilhados: botao, rodape de dicas, lista de itens, opcoes e controles.

Todos os menus do jogo desenham com estas funcoes para manter o mesmo alinhamento:
- botoes sempre com largura >= texto + 16 (nada vaza)
- linhas de valor com o valor alinhado a direita e < > em posicao fixa
"""
import pygame

from . import config
from . import settings as S
from .ui import BLACK, BLUE, DIM, GREEN, GREY, WHITE, YELLOW

BTN_H = 18
ROW_H = 22
CONFIRM = S.HUMAN_KEYS["confirm"]
UP = (pygame.K_UP, pygame.K_w)
DOWN = (pygame.K_DOWN, pygame.K_s)
LEFT = (pygame.K_LEFT, pygame.K_a)
RIGHT = (pygame.K_RIGHT, pygame.K_d)


def draw_button(a, surf, label, x, y, w, active, anchor="topleft"):
    f = a.font
    w = max(w, f.width(label) + 16)
    if anchor == "center":
        x -= w // 2
    a.ui.nine_slice(surf, "botao_hover" if active else "botao_normal", (x, y, w, BTN_H))
    f.draw(surf, label, x + w // 2, y + 5, WHITE if active else GREY, 1, "midtop")
    return w


def keycap_width(a, label):
    name = f"tecla_{label}"
    return a.ui.rects[name].w if a.ui.has(name) else max(14, a.font.width(label) + 6)


def draw_keycap(a, surf, label, x, y):
    """Tecla do atlas quando existe; senao desenha uma generica com o mesmo visual."""
    name = f"tecla_{label}"
    if a.ui.has(name):
        a.ui.draw(surf, name, x, y)
        return a.ui.rects[name].w
    w = keycap_width(a, label)
    a.ui.nine_slice(surf, "painel_claro", (x, y, w, 14))
    a.font.draw(surf, label, x + w // 2, y + 2, (30, 34, 44), 1, "midtop")
    return w


def draw_hints(a, surf, hints, x=6, y=None):
    """hints: [(tecla ou lista de teclas, texto)]. Painel no rodape com largura calculada pelo conteudo."""
    f = a.font
    y = S.SCREEN_H - 20 if y is None else y
    items = []
    w = 6
    for keys, txt in hints:
        keys = [keys] if isinstance(keys, str) else list(keys)
        kw = sum(keycap_width(a, k) for k in keys) + 2 * (len(keys) - 1)
        items.append((keys, txt, w, kw))
        w += kw + 4 + f.width(txt) + 10
    a.ui.nine_slice(surf, "painel", (x, y - 4, w, 20))
    for keys, txt, ox, kw in items:
        kx = x + ox
        for k in keys:
            kx += draw_keycap(a, surf, k, kx, y) + 2
        f.draw(surf, txt, x + ox + kw + 4, y + 3, WHITE)
    return w


def draw_panel_title(a, surf, rect, title):
    px, py, pw, ph = rect
    a.ui.nine_slice(surf, "painel", rect)
    pygame.draw.rect(surf, (27, 79, 150), (px + 1, py + 1, pw - 2, 18))
    a.font.draw(surf, title, px + pw // 2, py + 5, WHITE, 1, "midtop")


def draw_meter(surf, x, y, value, total=10, w=6, h=8, gap=2):
    for i in range(total):
        col = GREEN if i < value else DIM
        pygame.draw.rect(surf, col, (x + i * (w + gap), y, w, h))


class MenuList:
    """Lista vertical de itens. Item = dict(label, value=fn|None, change=fn(d)|None, action=fn|None,
    enabled=fn|None, meter=fn|None). Linhas com `action` viram botoes; linhas com `value` mostram
    'ROTULO ...... < VALOR >'."""

    def __init__(self, app, items, x, y, w, row_h=ROW_H):
        self.app = app
        self.a = app.assets
        self.items = items
        self.x, self.y, self.w, self.row_h = x, y, w, row_h
        self.sel = 0
        self.on_escape = None
        self.jump_on_confirm = False      # confirmar numa linha de valor pula para o primeiro botao
        self._fix_sel(+1)

    def _enabled(self, i):
        en = self.items[i].get("enabled")
        return en() if en else True

    def _fix_sel(self, d):
        n = len(self.items)
        for _ in range(n):
            if self._enabled(self.sel):
                return
            self.sel = (self.sel + d) % n

    def move(self, d):
        self.sel = (self.sel + d) % len(self.items)
        self._fix_sel(d)
        self.app.sounds.play("menu")

    @property
    def height(self):
        return len(self.items) * self.row_h

    def handle_event(self, ev):
        if ev.type != pygame.KEYDOWN:
            return False
        k = ev.key
        it = self.items[self.sel]
        if k in UP:
            self.move(-1)
        elif k in DOWN:
            self.move(+1)
        elif k in LEFT and it.get("change"):
            it["change"](-1)
            self.app.sounds.play("menu")
        elif k in RIGHT and it.get("change"):
            it["change"](+1)
            self.app.sounds.play("menu")
        elif k in CONFIRM:
            if it.get("action"):
                self.app.sounds.play("select")
                it["action"]()
            elif it.get("change"):
                if self.jump_on_confirm:
                    for j, o in enumerate(self.items):
                        if o.get("action"):
                            self.sel = j
                            break
                else:
                    it["change"](+1)
                self.app.sounds.play("menu")
        elif k == pygame.K_ESCAPE and self.on_escape:
            self.app.sounds.play("back")
            self.on_escape()
        else:
            return False
        return True

    def draw(self, surf):
        a, f = self.a, self.a.font
        for i, it in enumerate(self.items):
            y = self.y + i * self.row_h
            sel = i == self.sel
            en = self._enabled(i)
            if it.get("action") and not it.get("value"):
                draw_button(a, surf, it["label"], self.x, y, self.w, sel)
                continue
            col = WHITE if sel else (GREY if en else DIM)
            if sel:
                a.ui.draw(surf, "icone_seta_dir", self.x - 4, y + 2)
            f.draw(surf, it["label"], self.x + 12, y + 4, col)
            val = it["value"]() if it.get("value") else ""
            if it.get("meter"):
                draw_meter(surf, self.x + self.w - 110, y + 5, it["meter"]())
            f.draw(surf, val, self.x + self.w - 12, y + 4, YELLOW if sel else col, 1, "topright")
            if sel and en and it.get("change"):
                vw = f.width(val) + (86 if it.get("meter") else 0)
                f.draw(surf, "<", self.x + self.w - 12 - vw - 10, y + 4, BLUE)
                f.draw(surf, ">", self.x + self.w - 6, y + 4, BLUE)


class Overlay:
    """Base para telas por cima de qualquer cena (opcoes, controles)."""

    def __init__(self, app, on_back):
        self.app = app
        self.a = app.assets
        self.on_back = on_back
        self.t = 0.0

    def in_menu(self):
        return True

    def update(self, dt):
        self.t += dt

    def back(self):
        self.app.sounds.play("back")
        self.on_back()

    def dim(self, surf, alpha=170):
        ov = pygame.Surface((S.SCREEN_W, S.SCREEN_H), pygame.SRCALPHA)
        ov.fill((8, 10, 18, alpha))
        surf.blit(ov, (0, 0))


class OptionsMenu(Overlay):
    def __init__(self, app, on_back):
        super().__init__(app, on_back)
        cfg = app.config
        snd = app.sounds

        def vol(key, setter):
            def change(d):
                cfg[key] = max(0, min(10, cfg[key] + d))
                setter(cfg[key])
                config.save(cfg)
            return change

        def toggle(key, after=None):
            def change(_d):
                cfg[key] = not cfg[key]
                config.save(cfg)
                if after:
                    after()
            return change

        items = [
            dict(label="MÚSICA", value=lambda: str(cfg["music"]), meter=lambda: cfg["music"],
                 change=vol("music", snd.set_music_volume)),
            dict(label="EFEITOS", value=lambda: str(cfg["sfx"]), meter=lambda: cfg["sfx"],
                 change=vol("sfx", snd.set_sfx_volume)),
            dict(label="TELA CHEIA", value=lambda: "LIGADA" if cfg["fullscreen"] else "DESLIGADA",
                 change=toggle("fullscreen", app.apply_fullscreen)),
            dict(label="MIRA (SETA E ALVO)", value=lambda: "LIGADA" if cfg["aim"] else "DESLIGADA",
                 change=toggle("aim")),
            dict(label="VOLTAR", action=self.back),
        ]
        self.pw, self.ph = 300, 24 + len(items) * ROW_H + 40
        self.px, self.py = (S.SCREEN_W - self.pw) // 2, (S.SCREEN_H - self.ph) // 2
        self.menu = MenuList(app, items, self.px + 16, self.py + 30, self.pw - 32)
        self.menu.on_escape = self.back

    def handle_event(self, ev):
        self.menu.handle_event(ev)

    def draw(self, surf):
        self.dim(surf)
        draw_panel_title(self.a, surf, (self.px, self.py, self.pw, self.ph), "OPÇÕES")
        self.menu.draw(surf)
        self.a.font.draw(surf, "AS OPÇÕES SÃO SALVAS AUTOMATICAMENTE", S.SCREEN_W // 2, self.py + self.ph - 18, DIM, 1, "midtop")
        draw_hints(self.a, surf, [("← →", "MUDAR"), ("↑ ↓", "OPÇÃO"), ("ESC", "VOLTAR")])


class ControlsScreen(Overlay):
    ROWS = [
        ("MOVER", "WASD / SETAS", "ANALÓGICO / D-PAD"),
        ("CORRER (SEGURE)", "SHIFT", "RB / RT"),
        ("GOLPE", "Z / J / ESPAÇO", "B"),
        ("GOLPE FORTE", "X / K", "Y"),
        ("LOB", "C / L", "A"),
        ("DEIXADINHA", "V / I", "X"),
        ("SAQUE", "ESPAÇO", "B"),
        ("USAR / CONFIRMAR", "E / ENTER", "A / B"),
        ("PAUSA", "ESC", "START"),
    ]
    NOTES = [
        "SEGURE UMA DIREÇÃO PARA MIRAR: A SETA MOSTRA PARA ONDE A BOLA VAI",
        "CORRENDO VOCÊ CHEGA ANTES, MAS O ALVO FICA MAIOR (MENOS PRECISÃO)",
        "SMASH: GOLPE FORTE COM A BOLA ALTA.  VOLEIO: ANTES DO QUIQUE, PERTO DA REDE",
    ]

    def __init__(self, app, on_back):
        super().__init__(app, on_back)
        self.pw, self.ph = 500, 40 + len(self.ROWS) * 16 + 16 + len(self.NOTES) * 12 + 36
        self.px, self.py = (S.SCREEN_W - self.pw) // 2, (S.SCREEN_H - self.ph) // 2

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN and (ev.key in CONFIRM or ev.key == pygame.K_ESCAPE):
            self.back()

    def draw(self, surf):
        self.dim(surf)
        a, f = self.a, self.a.font
        px, py, pw, ph = self.px, self.py, self.pw, self.ph
        draw_panel_title(a, surf, (px, py, pw, ph), "CONTROLES")
        c1, c2, c3 = px + 16, px + 180, px + 350
        y = py + 28
        f.draw(surf, "AÇÃO", c1, y, DIM)
        f.draw(surf, "TECLADO", c2, y, DIM)
        f.draw(surf, "CONTROLE", c3, y, DIM)
        y += 14
        for name, kb, pad in self.ROWS:
            f.draw(surf, name, c1, y, GREY)
            f.draw(surf, kb, c2, y, WHITE)
            f.draw(surf, pad, c3, y, WHITE)
            y += 16
        pygame.draw.line(surf, (58, 67, 88), (px + 12, y + 2), (px + pw - 12, y + 2))
        y += 10
        for line in self.NOTES:
            f.draw(surf, line, px + pw // 2, y, YELLOW, 1, "midtop")
            y += 12
        draw_button(a, surf, "VOLTAR", px + pw // 2, py + ph - 26, 90, True, anchor="center")
