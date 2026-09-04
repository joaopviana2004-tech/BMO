"""Musica chiptune sintetizada em tempo de execucao (nao ha arquivos de audio no projeto).

Cada trilha e descrita como padroes de notas por voz (lead, baixo, acordes) e uma grade de bateria
por semicolcheia. `render(nome)` devolve um pygame.mixer.Sound pronto para tocar em loop.
"""
import numpy as np
import pygame

SR = 22050
NOTE_NAMES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def midi(name):
    """'A4' -> 69. None ou '.' = pausa."""
    if name in (None, ".", "-"):
        return None
    return 12 * (int(name[-1]) + 1) + NOTE_NAMES[name[:-1]]


def freq(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def osc(kind, f, n):
    t = np.arange(n) / SR
    ph = (f * t) % 1.0
    if kind == "square":
        return np.where(ph < 0.5, 1.0, -1.0)
    if kind == "pulse":
        return np.where(ph < 0.25, 1.0, -1.0)
    if kind == "tri":
        return 4.0 * np.abs(ph - 0.5) - 1.0
    if kind == "saw":
        return 2.0 * ph - 1.0
    return np.sin(2 * np.pi * f * t)


def envelope(n, gate, a=0.004, d=0.06, s=0.7, r=0.03):
    """ADSR em amostras: `gate` = duracao da nota tocada, o resto e release."""
    t = np.arange(n) / SR
    e = np.ones(n) * s
    na = min(n, max(1, int(a * SR)))
    nd = max(1, int(d * SR))
    e[:na] = np.linspace(0.0, 1.0, na)
    seg = slice(na, min(n, na + nd))
    ln = e[seg].shape[0]
    if ln:
        e[seg] = np.linspace(1.0, s, ln)
    nr = max(1, int(r * SR))
    g = min(gate, n)
    if g < n:
        e[g:] = 0.0
    start = max(0, g - nr)
    e[start:g] *= np.linspace(1.0, 0.0, g - start)
    return e


def render_voice(pattern, bpm, total, kind, vol, s=0.7, d=0.06, detune=0.0, legato=0.92):
    """pattern: lista de (nota, batidas). Preenche `total` amostras (loop exato)."""
    out = np.zeros(total)
    beat = 60.0 / bpm
    pos = 0.0
    for name, beats in pattern:
        dur = beats * beat
        i0 = int(round(pos * SR))
        n = int(round(dur * SR))
        pos += dur
        m = midi(name)
        if m is None or n <= 0 or i0 >= total:
            continue
        n = min(n, total - i0)
        f = freq(m)
        w = osc(kind, f, n)
        if detune:
            w = 0.6 * w + 0.4 * osc(kind, f * (1 + detune), n)
        gate = max(1, int(n * legato))
        out[i0:i0 + n] += w * envelope(n, gate, d=d, s=s) * vol
    return out


def render_chords(chords, bpm, total, vol=0.07, kind="sine"):
    """chords: lista de (lista de notas, batidas). Notas longas e suaves."""
    out = np.zeros(total)
    beat = 60.0 / bpm
    pos = 0.0
    for notes, beats in chords:
        dur = beats * beat
        i0 = int(round(pos * SR))
        n = min(int(round(dur * SR)), total - i0)
        pos += dur
        if n <= 0:
            continue
        for name in notes:
            w = osc(kind, freq(midi(name)), n)
            out[i0:i0 + n] += w * envelope(n, int(n * 0.95), a=0.03, d=0.3, s=0.8, r=0.08) * vol
    return out


def _kick(n):
    t = np.arange(n) / SR
    f = 110.0 * np.exp(-t * 28.0) + 38.0
    ph = np.cumsum(f) / SR
    return np.sin(2 * np.pi * ph) * np.exp(-t * 20.0)


def _snare(n, rng):
    t = np.arange(n) / SR
    return (rng.uniform(-1, 1, n) * 0.8 + 0.3 * np.sin(2 * np.pi * 185 * t)) * np.exp(-t * 26.0)


def _hat(n, rng, open_=False):
    t = np.arange(n) / SR
    w = rng.uniform(-1, 1, n)
    w = np.diff(w, prepend=0.0)          # "passa-alta" barato
    return w * np.exp(-t * (18.0 if open_ else 70.0)) * 0.5


def render_drums(grid, bpm, total, vol=0.5, seed=7):
    """grid: dict com strings por semicolcheia ('x' toca, 'o' hat aberto, '.' nada), repetidas ate encher."""
    rng = np.random.default_rng(seed)
    out = np.zeros(total)
    step = 60.0 / bpm / 4.0
    nstep = int(round(step * SR))
    lens = {"kick": int(0.16 * SR), "snare": int(0.14 * SR), "hat": int(0.08 * SR)}
    for name, pat in grid.items():
        pat = pat.replace(" ", "")
        L = len(pat)
        i = 0
        while i * nstep < total:
            ch = pat[i % L]
            if ch != ".":
                i0 = i * nstep
                n = min(lens[name], total - i0)
                if name == "kick":
                    w = _kick(n) * 1.0
                elif name == "snare":
                    w = _snare(n, rng) * 0.7
                else:
                    w = _hat(n, rng, open_=(ch == "o")) * (0.5 if ch == "o" else 0.35)
                out[i0:i0 + n] += w * vol
            i += 1
    return out


def _bar(*items):
    return list(items)


# --------------------------------------------------------------------------- trilhas
def track_clube():
    """Trilha calma (titulo e clube): 96 BPM, 8 compassos, Cmaj7 Am7 Dm7 G7."""
    bpm = 96
    bars = 8
    total = int(round(bars * 4 * 60.0 / bpm * SR))
    arps = [
        ["E4", "G4", "B4", "D5", "B4", "G4", "E4", "G4"],
        ["E4", "G4", "A4", "C5", "A4", "G4", "E4", "C4"],
        ["F4", "A4", "C5", "D5", "C5", "A4", "F4", "A4"],
        ["B4", "D5", "F5", "D5", "B4", "G4", "D4", "G4"],
    ]
    lead = []
    for bar in arps:
        lead += [(n, 0.5) for n in bar]
    lead += [("E5", 1.5), ("D5", 0.5), ("B4", 1.5), (".", 0.5),
             ("C5", 1.0), ("B4", 0.5), ("A4", 0.5), ("E4", 1.5), (".", 0.5),
             ("F4", 1.0), ("A4", 1.0), ("C5", 1.5), ("D5", 0.5),
             ("B4", 1.0), ("D5", 1.0), ("F5", 1.0), ("D5", 1.0)]
    roots = ["C2", "A1", "D2", "G1"] * 2
    fifths = ["G2", "E2", "A2", "D2"] * 2
    bass = []
    for r, f in zip(roots, fifths):
        bass += [(r, 1.5), (f, 0.5), (r, 1.0), (f, 1.0)]
    chords = [(["E3", "G3", "B3"], 4), (["E3", "G3", "C4"], 4), (["F3", "A3", "C4"], 4), (["F3", "G3", "B3"], 4)] * 2
    drums = {"kick": "x.....x...x.....", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x."}
    mix = (render_voice(lead, bpm, total, "pulse", 0.16, s=0.5, d=0.12, legato=0.85)
           + render_voice(bass, bpm, total, "tri", 0.30, s=0.8, d=0.05)
           + render_chords(chords, bpm, total, vol=0.06)
           + render_drums(drums, bpm, total, vol=0.35))
    return mix


def track_partida():
    """Trilha da partida: 150 BPM, 8 compassos, C G Am F C G F G."""
    bpm = 150
    bars = 8
    total = int(round(bars * 4 * 60.0 / bpm * SR))
    lead = []
    for bar in (["E5", "G5", "C6", "G5", "E5", "C5", "D5", "E5"],
                ["D5", "G5", "B5", "G5", "D5", "B4", "C5", "D5"],
                ["C5", "E5", "A5", "E5", "C5", "A4", "B4", "C5"],
                ["A4", "C5", "F5", "C5", "A4", "F4", "G4", "A4"]):
        lead += [(n, 0.5) for n in bar]
    lead += [("G5", 1.0), ("E5", 0.5), ("C5", 0.5), ("D5", 1.0), ("E5", 1.0),
             ("D5", 1.0), ("B4", 0.5), ("G4", 0.5), ("A4", 1.0), ("B4", 1.0),
             ("C5", 0.5), ("D5", 0.5), ("E5", 0.5), ("F5", 0.5), ("A5", 1.0), ("G5", 1.0),
             ("F5", 0.5), ("E5", 0.5), ("D5", 0.5), ("B4", 0.5), ("D5", 2.0)]
    roots = ["C2", "G1", "A1", "F1", "C2", "G1", "F1", "G1"]
    bass = []
    for r in roots:
        up = r[:-1] + str(int(r[-1]) + 1)
        bass += [(r, 0.5), (up, 0.5)] * 4
    chords = [(["E3", "G3", "C4"], 4), (["D3", "G3", "B3"], 4), (["E3", "A3", "C4"], 4), (["F3", "A3", "C4"], 4),
              (["E3", "G3", "C4"], 4), (["D3", "G3", "B3"], 4), (["F3", "A3", "C4"], 4), (["D3", "G3", "B3"], 4)]
    drums = {"kick": "x...x...x...x...", "snare": "....x.......x...", "hat": "x.o.x.x.x.o.x.x."}
    mix = (render_voice(lead, bpm, total, "square", 0.14, s=0.55, d=0.08, detune=0.004, legato=0.8)
           + render_voice(bass, bpm, total, "tri", 0.32, s=0.85, d=0.04, legato=0.7)
           + render_chords(chords, bpm, total, vol=0.045)
           + render_drums(drums, bpm, total, vol=0.5))
    return mix


def jingle(notes, bpm=180, kind="square"):
    total = int(round(sum(b for _, b in notes) * 60.0 / bpm * SR)) + int(0.4 * SR)
    mix = render_voice(notes, bpm, total, kind, 0.25, s=0.6, d=0.1, legato=0.9)
    low = [(n[:-1] + str(int(n[-1]) - 1) if n != "." else ".", b) for n, b in notes]
    mix += render_voice(low, bpm, total, "tri", 0.2, s=0.8, d=0.1, legato=0.9)
    return mix


TRACKS = {
    "clube": track_clube,
    "partida": track_partida,
    "vitoria": lambda: jingle([("C5", 0.5), ("E5", 0.5), ("G5", 0.5), ("C6", 1.5), ("G5", 0.5), ("C6", 2.0)]),
    "derrota": lambda: jingle([("E4", 1.0), ("D#4", 1.0), ("D4", 1.0), ("C#4", 2.5)], bpm=120, kind="tri"),
}


def to_sound(mix, gain=0.85):
    mix = np.tanh(mix * 1.4)
    peak = np.max(np.abs(mix)) or 1.0
    a = (mix / peak * gain * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(np.ascontiguousarray(np.column_stack([a, a])))


def render(name):
    return to_sound(TRACKS[name]())
