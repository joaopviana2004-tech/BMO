"""Carregamento de sprites, arenas, mapa, UI, efeitos e fontes."""
import json
import os

import pygame

from . import settings as S
from .ui import Atlas, PixelFont


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _img(*parts, alpha=True):
    path = os.path.join(S.ASSETS, *parts)
    img = pygame.image.load(path)
    return img.convert_alpha() if alpha else img.convert()


class Sheet:
    """Spritesheet de jogador: linhas por animacao (ver assets/sprites/*.json)."""

    def __init__(self, name):
        base = os.path.join(S.ASSETS, "sprites", f"jogador_{name}")
        self.img = pygame.image.load(base + ".png").convert_alpha()
        meta = _load_json(base + ".json")
        self.fw, self.fh = meta["frame"]
        self.rows = meta["rows"]
        self.fps = meta["fps"]
        self._cache = {}

    def frames(self, anim):
        return self.rows[anim]["frames"]

    def fps_of(self, anim):
        return self.fps.get(anim.split("_", 1)[1], 8)

    def duration(self, anim):
        return self.frames(anim) / self.fps_of(anim)

    def frame(self, anim, i, flip=False):
        row = self.rows[anim]
        i = int(i) % row["frames"]
        key = (anim, i, flip)
        surf = self._cache.get(key)
        if surf is None:
            surf = self.img.subsurface((i * self.fw, row["row"] * self.fh, self.fw, self.fh))
            if flip:
                surf = pygame.transform.flip(surf, True, False)
            self._cache[key] = surf
        return surf


class Assets:
    def __init__(self):
        self._sheets = {}
        self._arenas = {}
        self._map = None
        self.ball = _img("sprites", "bola.png")

        # fonte pixel e UI
        self.font = PixelFont(_img("ui", "fonte_5x7.png"), _load_json(os.path.join(S.ASSETS, "ui", "fonte_5x7.json")))
        ui_meta = _load_json(os.path.join(S.ASSETS, "ui", "ui.json"))
        self.ui = Atlas(_img("ui", "ui.png"), ui_meta["rects"])
        fx_meta = _load_json(os.path.join(S.ASSETS, "efeitos", "efeitos.json"))
        self.fx = Atlas(_img("efeitos", "efeitos.png"), fx_meta["rects"], fx_meta["anims"])
        self.big = Atlas(_img("ui", "textos_grandes.png"), _load_json(os.path.join(S.ASSETS, "ui", "textos_grandes.json")))
        retr = _load_json(os.path.join(S.ASSETS, "ui", "retratos.json"))
        rects = {f"s_{k}": v for k, v in retr["small"].items()}
        rects.update({f"l_{k}": v for k, v in retr["large"].items()})
        self.portraits = Atlas(_img("ui", "retratos.png"), rects)
        self.hud_img = _img("ui", "hud_placar.png")
        self.hud_meta = _load_json(os.path.join(S.ASSETS, "ui", "hud_placar.json"))
        self.vel = Atlas(_img("ui", "hud_velocidade.png"), _load_json(os.path.join(S.ASSETS, "ui", "hud_velocidade.json")))

    def sheet(self, name):
        if name not in self._sheets:
            self._sheets[name] = Sheet(name)
        return self._sheets[name]

    def arena(self, palette):
        """Tela de partida completa (640x360) + metadados em espaco de tela."""
        if palette not in self._arenas:
            base = os.path.join(S.ASSETS, "arenas", f"partida_{palette}")
            img = pygame.image.load(base + ".png").convert()
            self._arenas[palette] = (img, _load_json(base + ".json"))
        return self._arenas[palette]

    def club_map(self):
        if self._map is None:
            base = os.path.join(S.ASSETS, "mapa", "mapa_clube")
            img = pygame.image.load(base + ".png").convert()
            self._map = (img, _load_json(base + ".json"))
        return self._map
