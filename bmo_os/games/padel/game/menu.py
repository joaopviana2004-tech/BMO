"""Menu de nova partida (storyboard_02): painel em duas colunas com as opcoes a esquerda e a
pre-visualizacao da quadra (lado escolhido, parceiro, rivais) a direita."""
import pygame

from . import settings as S
from .menus import MenuList, draw_button, draw_hints, draw_panel_title
from .ui import BLACK, BLUE, DIM, GREEN, GREY, WHITE, YELLOW

PALETTE_RGB = {"azul": (47, 111, 214), "verde": (61, 155, 76), "terra": (200, 100, 46), "indoor": (62, 79, 179)}


def default_options(palette="azul", court_name="QUADRA 1 - AZUL"):
    return dict(palette=palette, court_name=court_name, mode=1, difficulty=1, time=1, scoring=0,
                games=1, points=1, side=0, partner=0, wind=1)


class MatchMenu:
    """Overlay. `on_play(options)` e `on_back()` sao chamados ao confirmar."""

    ROWS = ["MODO", "DIFICULDADE", "TEMPO MÁXIMO", "PLACAR", "META", "LADO", "PARCEIRO", "VENTO"]

    def __init__(self, app, options, on_play, on_back):
        self.app = app
        self.a = app.assets
        self.o = options
        self.on_play = on_play
        self.on_back = on_back
        self.t = 0.0
        self.pw, self.ph = 420, 244
        self.px, self.py = (S.SCREEN_W - self.pw) // 2, (S.SCREEN_H - self.ph) // 2
        items = []
        for row in self.ROWS:
            items.append(dict(label=row, value=(lambda r=row: self.value(r)), change=(lambda d, r=row: self.change(r, d)),
                              enabled=(lambda r=row: self.enabled(r))))
        items.append(dict(label="JOGAR", action=self.play))
        items.append(dict(label="VOLTAR", action=self.back))
        self.list = MenuList(app, items, self.px + 14, self.py + 28, 236, row_h=20)
        self.list.jump_on_confirm = True
        self.list.on_escape = self.back

    # ------------------------------------------------------------------ valores
    def enabled(self, row):
        return not (row == "PARCEIRO" and self.o["mode"] == 0)

    def value(self, row):
        o = self.o
        if row == "MODO":
            return ["1 X 1", "2 X 2 COM BOTS"][o["mode"]]
        if row == "DIFICULDADE":
            return S.DIFFICULTY[o["difficulty"]]["name"]
        if row == "TEMPO MÁXIMO":
            t = S.TIME_LIMITS[o["time"]]
            return "SEM LIMITE" if t is None else f"{t} MIN"
        if row == "PLACAR":
            return ["PADEL (GAMES)", "PONTOS CORRIDOS"][o["scoring"]]
        if row == "META":
            if o["scoring"] == 0:
                return f"SET DE {S.GAMES_PER_SET[o['games']]} GAMES"
            return f"ATÉ {S.POINT_LIMITS[o['points']]} PONTOS"
        if row == "LADO":
            return ["ESQUERDA", "DIREITA"][o["side"]]
        if row == "PARCEIRO":
            if o["mode"] == 0:
                return "-"
            return S.NAMES[S.PARTNERS[o["partner"]]]
        if row == "VENTO":
            return ["DESLIGADO", "LIGADO"][o["wind"]]
        return ""

    def change(self, row, d):
        o = self.o
        if row == "MODO":
            o["mode"] = (o["mode"] + d) % 2
        elif row == "DIFICULDADE":
            o["difficulty"] = (o["difficulty"] + d) % len(S.DIFFICULTY)
        elif row == "TEMPO MÁXIMO":
            o["time"] = (o["time"] + d) % len(S.TIME_LIMITS)
        elif row == "PLACAR":
            o["scoring"] = (o["scoring"] + d) % 2
        elif row == "META":
            if o["scoring"] == 0:
                o["games"] = (o["games"] + d) % len(S.GAMES_PER_SET)
            else:
                o["points"] = (o["points"] + d) % len(S.POINT_LIMITS)
        elif row == "LADO":
            o["side"] = (o["side"] + d) % 2
        elif row == "PARCEIRO":
            if o["mode"] == 1:
                o["partner"] = (o["partner"] + d) % len(S.PARTNERS)
        elif row == "VENTO":
            o["wind"] = (o["wind"] + d) % 2

    def play(self):
        self.on_play(dict(self.o))

    def back(self):
        self.on_back()

    # ------------------------------------------------------------------ entrada
    def handle_event(self, ev):
        self.list.handle_event(ev)

    def update(self, dt):
        self.t += dt

    # ------------------------------------------------------------------ desenho
    def draw_preview(self, surf, x, y, w, h):
        """Mini quadra deitada com o lado escolhido realcado e os retratos posicionados."""
        a = self.a
        o = self.o
        col = PALETTE_RGB.get(o["palette"], PALETTE_RGB["azul"])
        pygame.draw.rect(surf, BLACK, (x - 2, y - 2, w + 4, h + 4))
        pygame.draw.rect(surf, col, (x, y, w, h))
        line = (230, 235, 245)
        sx = int(w * 0.3025)                       # linha de saque a 6,95 m da rede
        for lx in (x + w // 2 - sx, x + w // 2 + sx):
            pygame.draw.line(surf, line, (lx, y), (lx, y + h - 1))
        pygame.draw.line(surf, line, (x + w // 2 - sx, y + h // 2), (x + w // 2 + sx, y + h // 2))
        pygame.draw.rect(surf, (40, 40, 48), (x + w // 2 - 1, y - 2, 2, h + 4))
        my_side = o["side"]
        hl = pygame.Surface((w // 2, h), pygame.SRCALPHA)
        hl.fill((255, 220, 90, 70))
        surf.blit(hl, (x + my_side * (w // 2), y))
        a.font.draw(surf, "VOCÊ", x + w // 4 + my_side * (w // 2), y - 12, YELLOW, 1, "midtop")
        a.font.draw(surf, "RIVAIS", x + w // 4 + (1 - my_side) * (w // 2), y - 12, (255, 120, 110), 1, "midtop")
        doubles = o["mode"] == 1
        mine = ["timeA_p1"] + ([S.PARTNERS[o["partner"]]] if doubles else [])
        theirs = ["timeB_p1"] + (["timeB_p2"] if doubles else [])
        for team_idx, names in ((my_side, mine), (1 - my_side, theirs)):
            cx = x + w // 4 + team_idx * (w // 2)
            if len(names) == 1:
                a.portraits.draw(surf, "s_" + names[0], cx, y + h // 2, "center")
            else:
                a.portraits.draw(surf, "s_" + names[0], cx, y + h // 4 + 2, "center")
                a.portraits.draw(surf, "s_" + names[1], cx, y + 3 * h // 4 - 2, "center")

    def draw(self, surf):
        a = self.a
        f = a.font
        ov = pygame.Surface((S.SCREEN_W, S.SCREEN_H), pygame.SRCALPHA)
        ov.fill((8, 10, 18, 150))
        surf.blit(ov, (0, 0))
        px, py, pw, ph = self.px, self.py, self.pw, self.ph
        draw_panel_title(a, surf, (px, py, pw, ph), f"NOVA PARTIDA - {self.o['court_name']}")
        self.list.draw(surf)
        # coluna da direita
        rx = px + 268
        rw = pw - 268 - 14
        f.draw(surf, "QUADRA", rx + rw // 2, py + 30, DIM, 1, "midtop")
        cw, ch = 130, 66
        self.draw_preview(surf, rx + (rw - cw) // 2, py + 56, cw, ch)
        y = py + 134
        f.draw(surf, "DIFICULDADE", rx + rw // 2, y, DIM, 1, "midtop")
        a.ui.draw(surf, f"estrelas_{S.DIFFICULTY[self.o['difficulty']]['stars']}", rx + rw // 2, y + 12, "midtop")
        f.draw(surf, S.DIFFICULTY[self.o["difficulty"]]["name"], rx + rw // 2, y + 28, YELLOW, 1, "midtop")
        y += 48
        pygame.draw.line(surf, (58, 67, 88), (rx, y), (rx + rw, y))
        y += 6
        lines = [self.value("PLACAR"), self.value("META"), "TEMPO " + self.value("TEMPO MÁXIMO"),
                 "VENTO " + self.value("VENTO")]
        for ln in lines:
            f.draw(surf, ln, rx + rw // 2, y, GREY, 1, "midtop")
            y += 12
        draw_hints(a, surf, [("← →", "MUDAR"), ("↑ ↓", "OPÇÃO"), ("E", "OK"), ("ESC", "VOLTAR")])
