"""Sons 8-bit gerados em runtime via numpy + pygame.sndarray.

Sem assets de áudio no repo — todo som é uma onda quadrada/sweep/ruído
gerado no boot e cacheado. Som = chiptune simples, satisfatório.

Uso (chama de qualquer lugar):
    from ..services import audio
    audio.play("tick")
    audio.play_bmo_voice()        # voz aleatória do BMO (8 clipes)
    audio.set_volume(0.5)         # 0..1

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
    alarm       — pomodoro troca de fase (bip-bip-bip discreto)
    plim        — notificação chegou (ding leve)

ESTE MÓDULO É O ÚNICO DONO DA SAÍDA DE SOM. Toda reprodução (efeitos E a
voz do BMO, via tts.py) passa pelo mixer do pygame daqui — nunca por player
externo (mpg123/ffplay), que abriria um 2º handle de ALSA e disputaria o
device (era a causa de voz cortada no início e efeitos mudos no Pi).

Anti-suspend (o conserto do atraso no Pi):
    O ALSA/PipeWire do Pi SUSPENDE o device após ~segundos de silêncio; o
    resume leva centenas de ms — sons curtos eram engolidos inteiros e tudo
    parecia atrasado. init() deixa um loop de SILÊNCIO tocando num canal
    reservado: o device nunca dorme e todo play() sai instantâneo.

Canais reservados:
    0 = keep-alive (silêncio em loop)      1 = VOZ do BMO (tts.py)
    Efeitos usam os demais — a fala nunca é roubada por um tick/explosão,
    e parar a fala não cala os efeitos (e vice-versa).

Latência:
    44100Hz + buffer 512 samples = ~11.6ms de mixer (256 dava underrun no
    Pi = estalos/atraso). Override: BMO_AUDIO_BUFFER no .env.

Sem numpy ou sem audio device → init() volta False e play() é no-op.
"""
from __future__ import annotations

import os
import random

import pygame

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:
    np = None
    HAS_NUMPY = False


SAMPLE_RATE = 44100
BUFFER_SAMPLES = int(os.environ.get("BMO_AUDIO_BUFFER", "512"))
NUM_CHANNELS = 32
CH_KEEPALIVE = 0   # silêncio em loop (segura o device acordado)
CH_VOICE = 1       # fala do BMO (tts.py) — canal exclusivo

# Estado do módulo (singleton)
_available = False
_sounds: dict[str, pygame.mixer.Sound] = {}
_bmo_voices: list[pygame.mixer.Sound] = []
_keepalive: pygame.mixer.Sound | None = None
_volume = 1.0       # 0.0 .. 1.0 — multiplicado em cada play()


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


def _beeps(freq: float, count: int, on: float, off: float,
           volume: float = 0.35) -> pygame.mixer.Sound:
    """Sequência de bips curtos iguais (bip-bip-bip), volume baixo e discreto."""
    n_on = int(SAMPLE_RATE * on)
    n_off = int(SAMPLE_RATE * off)
    t = np.arange(n_on, dtype=np.float32) / SAMPLE_RATE
    tone = np.sign(np.sin(2 * np.pi * freq * t)) * volume * _envelope(n_on, 0.08, 0.35)
    silence = np.zeros(n_off, dtype=np.float32)
    chunks = []
    for i in range(count):
        chunks.append(tone)
        if i < count - 1:
            chunks.append(silence)
    return _to_stereo((np.concatenate(chunks) * 32767).astype(np.int16))


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


def _voice_phrase(notes: list[float], durations: list[float],
                  volume: float = 0.55) -> pygame.mixer.Sound:
    """Sequência de notas square — base da voz do BMO."""
    out_chunks = []
    for freq, dur in zip(notes, durations):
        n = int(SAMPLE_RATE * dur)
        t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
        wave = np.sign(np.sin(2 * np.pi * freq * t)) * volume
        # envelope curto por nota pra dar staccato
        a = max(1, int(n * 0.06))
        d = max(1, int(n * 0.18))
        env = np.ones(n, dtype=np.float32)
        env[:a] = np.linspace(0, 1, a)
        env[-d:] = np.linspace(1, 0, d)
        out_chunks.append(wave * env)
    wave = np.concatenate(out_chunks)
    return _to_stereo((wave * 32767).astype(np.int16))


# Frases curtas que viram a "voz" do BMO — chiptune com notas musicais reais.
# Mid-high range (~500-1000Hz) pra soar como um personagem pequeno.
_BMO_VOICE_PATTERNS = [
    # "ba-doo"
    ([784, 587], [0.07, 0.11]),
    # "ba-do-DEE!"
    ([523, 659, 784], [0.05, 0.05, 0.10]),
    # "doo-baa"
    ([784, 523], [0.07, 0.13]),
    # "DEE-do-bo"
    ([880, 659, 523], [0.05, 0.05, 0.10]),
    # "ba-ba-DII!"
    ([523, 523, 784], [0.04, 0.04, 0.11]),
    # "doh-DAH-buh"
    ([659, 880, 587], [0.07, 0.05, 0.09]),
    # "ba-be-DEE-bo"
    ([587, 587, 880, 523], [0.04, 0.04, 0.04, 0.09]),
    # "EEK-doo?"
    ([1047, 587], [0.04, 0.11]),
    # "boooop"
    ([440, 440], [0.05, 0.10]),
    # "blip-bloop"
    ([880, 659, 784, 523], [0.04, 0.04, 0.04, 0.10]),
]


# ---------- API pública ----------

def init() -> None:
    """Inicializa o mixer, gera os sons e liga o keep-alive. Idempotente."""
    global _available, _sounds, _bmo_voices, _keepalive
    if _available:
        return
    if not HAS_NUMPY:
        return
    try:
        # pre_init define params do mixer (sample rate, buffer); PRECISA rodar
        # antes de qualquer mixer.init real (incl. o que pygame.init() faz).
        pygame.mixer.pre_init(SAMPLE_RATE, -16, 2, BUFFER_SAMPLES)
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
            "bounce":    _square_wave(1320, 0.05, 0.55),
            "point":     _two_tone(880, 1320, 0.06, 0.10, 0.55),
            "snap":      _noise(0.06, 0.75),
            "alarm":     _beeps(740, 3, 0.08, 0.07, 0.32),
            "plim":      _two_tone(988, 1319, 0.05, 0.14, 0.4),
        }
        _bmo_voices = [_voice_phrase(notes, durs)
                       for notes, durs in _BMO_VOICE_PATTERNS]
        # Bastante canal pra suportar sons sobrepostos sem cortar.
        # Os 2 primeiros são RESERVADOS (keep-alive + voz) — efeitos via
        # Sound.play() nunca caem neles.
        pygame.mixer.set_num_channels(NUM_CHANNELS)
        pygame.mixer.set_reserved(2)
        # Anti-suspend: meio segundo de silêncio em loop infinito. Custa ~0
        # de CPU e impede o ALSA/PipeWire de suspender o device (a causa de
        # som atrasado/engolido no Pi).
        _keepalive = _to_stereo(np.zeros(SAMPLE_RATE // 2, dtype=np.int16))
        pygame.mixer.Channel(CH_KEEPALIVE).play(_keepalive, loops=-1)
        _available = True
    except Exception:
        _available = False


def set_volume(v: float) -> None:
    """Volume mestre 0..1. Aplicado em cada play() subsequente."""
    global _volume
    _volume = max(0.0, min(1.0, float(v)))


def play(name: str) -> None:
    """Toca um som pelo nome. Silencioso se mixer/sound indisponível."""
    if not _available or _volume <= 0:
        return
    s = _sounds.get(name)
    if s is not None:
        s.set_volume(_volume)
        s.play()


def play_bmo_voice() -> None:
    """Toca uma frase aleatória da 'voz' do BMO."""
    if not _available or _volume <= 0 or not _bmo_voices:
        return
    s = random.choice(_bmo_voices)
    s.set_volume(_volume)
    s.play()


def play_voice(sound, volume: float = 1.0):
    """Toca a FALA do BMO no canal reservado de voz (corta a fala anterior,
    nunca disputa com efeitos). Devolve o Channel ou None (sem mixer).

    tts.py decodifica o áudio INTEIRO pra memória e entrega o Sound aqui —
    zero streaming, zero player externo, começo nunca cortado."""
    if not _available or sound is None:
        return None
    try:
        ch = pygame.mixer.Channel(CH_VOICE)
        sound.set_volume(max(0.0, min(1.0, float(volume))))
        ch.play(sound)
        return ch
    except Exception:
        return None


def stop_voice() -> None:
    """Cala SÓ a voz do BMO (efeitos continuam)."""
    if not _available:
        return
    try:
        pygame.mixer.Channel(CH_VOICE).stop()
    except Exception:
        pass


def is_available() -> bool:
    return _available


def shutdown() -> None:
    global _available, _sounds, _bmo_voices, _keepalive
    _sounds = {}
    _bmo_voices = []
    _keepalive = None
    _available = False
    try:
        pygame.mixer.quit()
    except Exception:
        pass
