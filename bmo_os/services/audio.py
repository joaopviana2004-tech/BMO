"""Sons 8-bit gerados em runtime via numpy + pygame.sndarray.

Sem assets de áudio no repo — todo som é uma onda quadrada/sweep/ruído
gerado no boot e cacheado. Som = chiptune simples, satisfatório.

Uso (chama de qualquer lugar):
    from ..services import audio
    audio.play("tick")

Sons disponíveis:
    tick        — navegação (carrossel, cycler)
    select      — confirmar (A, tap)
    back        — voltar (B, HOME)
    click       — ação genérica (move card)
    laser       — tiro do player
    explosion   — inimigo destruído
    damage      — player toma dano
    fail        — game over
    win         — vitória
    bounce      — pong: paddle bate na bola
    point       — pong: ponto marcado
    snap        — câmera dispara

Sem numpy ou sem audio device → init() volta False e play() é no-op.
"""
from __future__ import annotations

import pygame

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    np = None
    HAS_NUMPY = False


SAMPLE_RATE = 22050

# Estado do módulo (singleton)
_available = False
_sounds: dict[str, pygame.mixer.Sound] = {}


# ---------- síntese das ondas ----------

def _envelope(n: int, attack_ratio: float = 0.02, decay_ratio: float = 0.2):
    env = np.ones(n, dtype=np.float32)
    a = max(1, int(n * attack_ratio))
    d = max(1, int(n * decay_ratio))
    env[:a] = np.linspace(0, 1, a)
    env[-d:] = np.linspace(1, 0, d)
    return env


def _to_stereo(wave) -> pygame.mixer.Sound:
    stereo = np.column_stack([wave, wave])
    stereo = np.ascontiguousarray(stereo, dtype=np.int16)
    return pygame.sndarray.make_sound(stereo)


def _square_wave(freq: float, duration: float, volume: float = 0.5,
                 attack: float = 0.02, decay: float = 0.2) -> pygame.mixer.Sound:
    n = int(SAMPLE_RATE * duration)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    wave = np.sign(np.sin(2 * np.pi * freq * t)) * volume
    env = _envelope(n, attack, decay)
    return _to_stereo((wave * env * 32767).astype(np.int16))


def _sweep(freq_start: float, freq_end: float, duration: float,
           volume: float = 0.5) -> pygame.mixer.Sound:
    n = int(SAMPLE_RATE * duration)
    freq = np.linspace(freq_start, freq_end, n, dtype=np.float32)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    wave = np.sign(np.sin(phase)) * volume
    env = _envelope(n, 0.01, 0.3)
    return _to_stereo((wave * env * 32767).astype(np.int16))


def _noise(duration: float, volume: float = 0.5) -> pygame.mixer.Sound:
    n = int(SAMPLE_RATE * duration)
    wave = np.random.uniform(-1, 1, n).astype(np.float32) * volume
    env = _envelope(n, 0.01, 0.4)
    return _to_stereo((wave * env * 32767).astype(np.int16))


def _two_tone(f1: float, f2: float, dur1: float, dur2: float,
              volume: float = 0.5) -> pygame.mixer.Sound:
    n1 = int(SAMPLE_RATE * dur1)
    n2 = int(SAMPLE_RATE * dur2)
    t1 = np.arange(n1, dtype=np.float32) / SAMPLE_RATE
    t2 = np.arange(n2, dtype=np.float32) / SAMPLE_RATE
    w1 = np.sign(np.sin(2 * np.pi * f1 * t1)) * volume
    w2 = np.sign(np.sin(2 * np.pi * f2 * t2)) * volume
    wave = np.concatenate([w1, w2])
    env = _envelope(n1 + n2, 0.01, 0.25)
    return _to_stereo((wave * env * 32767).astype(np.int16))


# ---------- API pública ----------

def init() -> None:
    """Inicializa o mixer e gera os sons. Idempotente."""
    global _available, _sounds
    if _available:
        return
    if not HAS_NUMPY:
        return
    try:
        # pre_init define os parâmetros; precisa rodar ANTES do mixer.init real.
        pygame.mixer.pre_init(SAMPLE_RATE, -16, 2, 256)
        pygame.mixer.init()
    except pygame.error:
        return
    try:
        _sounds = {
            "tick":      _square_wave(880, 0.04, 0.4),
            "select":    _two_tone(660, 990, 0.04, 0.07, 0.5),
            "back":      _two_tone(990, 660, 0.04, 0.07, 0.45),
            "click":     _square_wave(660, 0.05, 0.45),
            "laser":     _sweep(1500, 400, 0.10, 0.55),
            "explosion": _noise(0.20, 0.7),
            "damage":    _sweep(440, 110, 0.28, 0.55),
            "fail":      _two_tone(330, 165, 0.15, 0.30, 0.55),
            "win":       _two_tone(660, 990, 0.10, 0.18, 0.55),
            "bounce":    _square_wave(1320, 0.04, 0.45),
            "point":     _two_tone(880, 1320, 0.06, 0.10, 0.55),
            "snap":      _noise(0.06, 0.75),
        }
        # Volume MÁXIMO em todos
        for s in _sounds.values():
            s.set_volume(1.0)
        # Reserva canais (mais que o default 8) pra não cortar sons curtos
        pygame.mixer.set_num_channels(16)
        _available = True
    except Exception:
        _available = False


def play(name: str) -> None:
    """Toca um som pelo nome. Silencioso se mixer/sound indisponível."""
    if not _available:
        return
    s = _sounds.get(name)
    if s is not None:
        s.play()


def is_available() -> bool:
    return _available


def shutdown() -> None:
    global _available, _sounds
    _sounds = {}
    _available = False
    try:
        pygame.mixer.quit()
    except Exception:
        pass
