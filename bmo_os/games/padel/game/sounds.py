"""Efeitos sonoros sintetizados com numpy e musica (music.py). Nao ha arquivos de audio no projeto.

Volumes vem de config.py (0..10). A musica toca num canal reservado, em loop, com crossfade.
"""
import numpy as np
import pygame

from . import music

SR = 22050


def _wave(freq, dur, decay=12.0, noise=0.0, vol=0.5, freq2=None, sweep=None):
    n = int(SR * dur)
    t = np.arange(n) / SR
    if sweep:
        f = np.linspace(freq, sweep, n)
        w = np.sin(2 * np.pi * np.cumsum(f) / SR)
    else:
        w = np.sin(2 * np.pi * freq * t)
    if freq2:
        w += 0.5 * np.sin(2 * np.pi * freq2 * t)
    if noise:
        w += noise * np.random.uniform(-1, 1, n)
    w *= np.exp(-decay * t) * vol
    return w


def _noise_swell(dur, vol=0.4, rise=0.25, decay=3.0, lowpass=0.85):
    """Torcida: ruido filtrado que sobe e desce."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    w = np.random.uniform(-1, 1, n)
    out = np.zeros(n)
    acc = 0.0
    for i in range(n):            # passa-baixa simples (IIR)
        acc = lowpass * acc + (1 - lowpass) * w[i]
        out[i] = acc
    env = np.minimum(t / rise, 1.0) * np.exp(-decay * np.maximum(t - rise, 0.0))
    return out * env * vol * 6.0


def _snd(w):
    a = (np.clip(w, -1, 1) * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(np.ascontiguousarray(np.column_stack([a, a])))


def _seq(*parts):
    return np.concatenate(parts)


class _Silent:
    """Substituto mudo (usado pela partida de demonstracao atras do menu)."""
    ok = False

    def __getattr__(self, _name):
        return lambda *a, **k: None


class Sounds:
    def __init__(self, sfx_volume=8, music_volume=6):
        self.ok = False
        self.s = {}
        self.music_cache = {}
        self.current = None
        self.music_ch = None
        self.sfx_vol = sfx_volume / 10.0
        self.mus_vol = music_volume / 10.0
        self.duck = 1.0
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(SR, -16, 2, 512, allowedchanges=0)
            pygame.mixer.set_num_channels(16)
            pygame.mixer.set_reserved(1)
            self.music_ch = pygame.mixer.Channel(0)
            self.s = {
                "hit": _snd(_wave(420, 0.09, decay=35, noise=0.5, vol=0.55)),
                "hit_strong": _snd(_seq(_wave(300, 0.05, decay=30, noise=0.8, vol=0.7), _wave(480, 0.10, decay=30, noise=0.3, vol=0.5))),
                "serve": _snd(_wave(380, 0.12, decay=28, noise=0.4, vol=0.55)),
                "swing": _snd(_wave(900, 0.16, decay=14, noise=1.0, vol=0.18, sweep=300)),
                "bounce": _snd(_wave(170, 0.10, decay=30, noise=0.15, vol=0.45)),
                "vidro": _snd(_wave(1500, 0.14, decay=22, freq2=2300, vol=0.35)),
                "grade": _snd(_wave(300, 0.12, decay=25, noise=0.9, vol=0.35)),
                "net": _snd(_wave(110, 0.18, decay=18, noise=0.3, vol=0.4)),
                "step": _snd(_wave(120, 0.05, decay=60, noise=0.6, vol=0.12)),
                "point": _snd(_seq(_wave(660, 0.10, decay=10, vol=0.4), _wave(880, 0.18, decay=8, vol=0.4))),
                "fault": _snd(_wave(200, 0.30, decay=6, freq2=150, vol=0.4)),
                "game": _snd(_seq(_wave(523, 0.12, decay=8, vol=0.4), _wave(659, 0.12, decay=8, vol=0.4),
                                  _wave(784, 0.25, decay=6, vol=0.4))),
                "crowd": _snd(_noise_swell(1.4, vol=0.35)),
                "crowd_big": _snd(_noise_swell(2.2, vol=0.5, rise=0.35, decay=2.0)),
                "fire": _snd(_seq(_wave(200, 0.25, decay=6, noise=1.0, vol=0.35, sweep=900), _wave(1200, 0.2, decay=10, noise=0.6, vol=0.25))),
                "tick": _snd(_wave(1200, 0.06, decay=40, vol=0.3)),
                "go": _snd(_seq(_wave(880, 0.08, decay=20, vol=0.35), _wave(1320, 0.22, decay=9, vol=0.35))),
                "menu": _snd(_wave(900, 0.05, decay=40, vol=0.3)),
                "select": _snd(_seq(_wave(700, 0.06, decay=25, vol=0.3), _wave(1000, 0.10, decay=20, vol=0.3))),
                "back": _snd(_seq(_wave(700, 0.06, decay=25, vol=0.25), _wave(500, 0.10, decay=20, vol=0.25))),
                "pause": _snd(_wave(600, 0.12, decay=14, freq2=450, vol=0.3)),
            }
            self.ok = True
            for name in ("clube", "partida"):     # pre-renderiza para nao engasgar na primeira troca
                self._music(name)
        except Exception as exc:  # sem placa de som, driver etc: o jogo segue mudo
            print("audio desativado:", exc)

    # ------------------------------------------------------------------ efeitos
    def play(self, name, vol=1.0):
        if self.ok and name in self.s:
            snd = self.s[name]
            snd.set_volume(self.sfx_vol * vol)
            snd.play()

    def set_sfx_volume(self, v10):
        self.sfx_vol = max(0, min(10, v10)) / 10.0
        self.play("menu")

    # ------------------------------------------------------------------ musica
    def _music(self, name):
        if name not in self.music_cache:
            self.music_cache[name] = music.render(name)
        return self.music_cache[name]

    def play_music(self, name, fade_ms=700, loop=True):
        if not self.ok or name == self.current:
            return
        self.current = name
        if name is None:
            self.music_ch.fadeout(fade_ms)
            return
        snd = self._music(name)
        self.music_ch.set_volume(self.mus_vol * self.duck)
        self.music_ch.play(snd, loops=-1 if loop else 0, fade_ms=fade_ms)

    def stop_music(self, fade_ms=500):
        self.play_music(None, fade_ms)

    def set_music_volume(self, v10):
        self.mus_vol = max(0, min(10, v10)) / 10.0
        if self.ok:
            self.music_ch.set_volume(self.mus_vol * self.duck)

    def set_duck(self, factor):
        """Abaixa a musica (pausa, fim de partida) sem parar."""
        self.duck = factor
        if self.ok:
            self.music_ch.set_volume(self.mus_vol * self.duck)

    def jingle(self, name):
        """Toca vitoria/derrota por cima da musica abaixada."""
        if not self.ok:
            return
        snd = self._music(name)
        snd.set_volume(self.mus_vol)
        snd.play()


SILENT = _Silent()
