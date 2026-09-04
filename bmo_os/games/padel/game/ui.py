"""Atlas de sprites, fonte pixel (fonte_5x7), painel 9-slice e efeitos animados."""
import math

import pygame

WHITE = (246, 246, 246)
BLACK = (17, 17, 17)
YELLOW = (250, 220, 90)
GREEN = (120, 220, 120)
RED = (235, 90, 80)
GREY = (170, 175, 185)
DIM = (110, 115, 125)
DARK = (20, 22, 30)
BLUE = (90, 150, 240)


class Atlas:
    """Conjunto de sprites recortados de uma imagem, descritos por um dict nome -> [x, y, w, h]."""

    def __init__(self, img, rects, anims=None):
        self.img = img
        self.rects = {k: pygame.Rect(v) for k, v in rects.items()}
        self.anims = anims or {}
        self._cache = {}

    def has(self, name):
        return name in self.rects

    def get(self, name, flip=False, scale=1, angle=0):
        key = (name, flip, scale, angle)
        s = self._cache.get(key)
        if s is None:
            s = self.img.subsurface(self.rects[name])
            if flip:
                s = pygame.transform.flip(s, True, False)
            if scale != 1:
                s = pygame.transform.scale_by(s, scale)
            if angle:
                s = pygame.transform.rotate(s, angle)
            self._cache[key] = s
        return s

    def frame(self, anim, t, flip=False, scale=1, angle=0):
        meta = self.anims.get(anim, {"frames": 1})
        n = meta.get("frames", 1)
        if n <= 1:
            return self.get(anim, flip, scale, angle)
        i = int(t * meta.get("fps", 8)) % n
        return self.get(f"{anim}_{i}", flip, scale, angle)

    def anim_len(self, anim):
        meta = self.anims.get(anim, {"frames": 1})
        return meta.get("frames", 1) / meta.get("fps", 8)

    def draw(self, surf, name, x, y, anchor="topleft", flip=False, scale=1, angle=0):
        img = self.get(name, flip, scale, angle)
        r = img.get_rect()
        setattr(r, anchor, (int(x), int(y)))
        surf.blit(img, r)
        return r

    def nine_slice(self, surf, name, rect, b=4):
        src = self.rects[name]
        x, y, w, h = [int(v) for v in rect]
        sw, sh = src.w, src.h
        cols = [(0, b), (b, sw - b), (sw - b, sw)]
        dcols = [(x, b), (x + b, w - 2 * b), (x + w - b, b)]
        rows = [(0, b), (b, sh - b), (sh - b, sh)]
        drows = [(y, b), (y + b, h - 2 * b), (y + h - b, b)]
        for (sy0, sy1), (dy, dh) in zip(rows, drows):
            for (sx0, sx1), (dx, dw) in zip(cols, dcols):
                if dw <= 0 or dh <= 0:
                    continue
                piece = self.img.subsurface((src.x + sx0, src.y + sy0, sx1 - sx0, sy1 - sy0))
                if piece.get_size() != (dw, dh):
                    piece = pygame.transform.scale(piece, (dw, dh))
                surf.blit(piece, (dx, dy))


class PixelFont:
    """Fonte 5x7 maiuscula (celula 6x10). Renderiza com cor, escala inteira, contorno e sombra."""

    def __init__(self, img, meta):
        self.img = img
        self.cw, self.ch = meta["cell"]
        self.adv = meta["advance"]
        self.chars = meta["chars"]
        self._glyph = {}
        self._cache = {}

    def _g(self, ch):
        idx = self.chars.get(ch)
        if idx is None:
            idx = self.chars.get("?", 0)
        g = self._glyph.get(idx)
        if g is None:
            g = self.img.subsurface((idx * self.cw, 0, self.cw, self.ch))
            self._glyph[idx] = g
        return g

    def width(self, text, scale=1):
        return len(text) * self.adv * scale

    def height(self, scale=1):
        return self.ch * scale

    def render(self, text, color=WHITE, scale=1, outline=None, shadow=None):
        text = text.upper()
        key = (text, color, scale, outline, shadow)
        s = self._cache.get(key)
        if s is not None:
            return s
        w = max(1, len(text) * self.adv)
        base = pygame.Surface((w, self.ch), pygame.SRCALPHA)
        for i, ch in enumerate(text):
            base.blit(self._g(ch), (i * self.adv, 0))
        if color != WHITE:
            base.fill(tuple(color[:3]) + (255,), special_flags=pygame.BLEND_RGBA_MULT)
        if scale != 1:
            base = pygame.transform.scale_by(base, scale)
        if outline or shadow:
            pad = scale if outline else 0
            sh = scale if shadow else 0
            out = pygame.Surface((base.get_width() + 2 * pad + sh, base.get_height() + 2 * pad + sh), pygame.SRCALPHA)
            mask = pygame.mask.from_surface(base)
            if shadow:
                shs = mask.to_surface(setcolor=tuple(shadow[:3]) + (255,), unsetcolor=(0, 0, 0, 0))
                out.blit(shs, (pad + sh, pad + sh))
            if outline:
                ols = mask.to_surface(setcolor=tuple(outline[:3]) + (255,), unsetcolor=(0, 0, 0, 0))
                for dx in (-pad, 0, pad):
                    for dy in (-pad, 0, pad):
                        if dx or dy:
                            out.blit(ols, (pad + dx, pad + dy))
            out.blit(base, (pad, pad))
            base = out
        if len(self._cache) > 600:
            self._cache.clear()
        self._cache[key] = base
        return base

    def draw(self, surf, text, x, y, color=WHITE, scale=1, anchor="topleft", outline=None, shadow=None):
        img = self.render(text, color, scale, outline, shadow)
        r = img.get_rect()
        setattr(r, anchor, (int(x), int(y)))
        surf.blit(img, r)
        return r


class Effect:
    def __init__(self, atlas, anim, x, z, y=0.0, flip=False, scale=1, follow=None, life=None,
                 loop=False, offset=(0.0, 0.0), rise=0.0):
        self.atlas = atlas
        self.anim = anim
        self.x, self.z, self.y = x, z, y
        self.flip = flip
        self.scale = scale
        self.follow = follow          # objeto com x, z, y (a bola) para seguir
        self.offset = offset
        self.loop = loop
        self.t = 0.0
        self.life = life if life is not None else atlas.anim_len(anim)
        self.rise = rise
        self.done = False

    def update(self, dt):
        self.t += dt
        self.y += self.rise * dt
        if self.follow is not None:
            self.x = self.follow.x + self.offset[0]
            self.z = self.follow.z + self.offset[1]
            self.y = self.follow.y
        if not self.loop and self.t >= self.life:
            self.done = True


class Effects:
    def __init__(self, atlas, court):
        self.atlas = atlas
        self.court = court
        self.items = []

    def spawn(self, anim, x, z, y=0.0, **kw):
        e = Effect(self.atlas, anim, x, z, y, **kw)
        self.items.append(e)
        return e

    def clear(self):
        self.items.clear()

    def update(self, dt):
        for e in self.items:
            e.update(dt)
        self.items = [e for e in self.items if not e.done]

    def draw(self, surf):
        for e in self.items:
            img = self.atlas.frame(e.anim, e.t, e.flip, e.scale)
            sx, sy = self.court.to_screen(e.x, e.z, e.y)
            surf.blit(img, img.get_rect(center=(int(sx), int(sy))))


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) * (1 - t)


def pop_scale(t, dur=0.25, start=1.8):
    """Escala 'pop': comeca grande e encolhe ate 1.0 em `dur` segundos."""
    if t >= dur:
        return 1.0
    return start - (start - 1.0) * ease_out(t / dur)


def draw_scaled(surf, img, cx, cy, scale):
    if scale != 1.0:
        w, h = img.get_size()
        img = pygame.transform.scale(img, (max(1, int(w * scale)), max(1, int(h * scale))))
    surf.blit(img, img.get_rect(center=(int(cx), int(cy))))


def fmt_time(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def angle_of(dx, dy):
    """Angulo (graus, anti-horario) para pygame.transform.rotate a partir de um vetor de tela."""
    if dx == 0 and dy == 0:
        return 0
    return round(math.degrees(math.atan2(-dy, dx)) / 15) * 15
