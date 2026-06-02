"""Voz do BMO (TTS) — Edge TTS (neural, online) > Piper (neural, local) > eSpeak.

Backend por env BMO_TTS_BACKEND: "edge" | "piper" | "espeak" | "auto" (default).
auto = Edge TTS se a lib estiver instalada (precisa de internet), senão Piper
(se houver binário + modelo), senão eSpeak-NG.

--- Edge TTS (PADRÃO — voz Francisca pt-BR) ---
Incorporado a partir do módulo de laboratório `bmo_voz.py` (voz Microsoft Edge,
GRÁTIS, sem chave). Voz e ajustes calibrados no lab: Francisca, +13% velocidade,
+18Hz tom, +24% volume. Sintetiza um MP3 e toca pelo mixer do pygame (ou por um
player externo como mpg123, se o mixer não decodificar MP3). Requer internet.
Setup no Pi:  pip install edge-tts   (e, p/ o fallback externo: apt install mpg123)
Env:
    BMO_TTS_EDGE_VOICE   (default pt-BR-FranciscaNeural; tb AntonioNeural/ThalitaNeural)
    BMO_TTS_EDGE_RATE / BMO_TTS_EDGE_PITCH / BMO_TTS_EDGE_VOLUME

Sintetiza num arquivo temporário e toca pelo **mixer do pygame** (respeita o
volume da config `tts_volume`, sem disputar o device). Fala em thread (fila) —
`speak()` não bloqueia o render loop. Degrada: sem backend, `available=False`.

--- Piper (recomendado: voz pt-BR natural) ---
Setup no Pi:
    pip install piper-tts                 # instala o binário 'piper'
    mkdir -p bmo_os/assets/piper
    cd bmo_os/assets/piper
    # baixe um modelo pt-BR (.onnx + .onnx.json), ex. faber-medium:
    BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium
    wget $BASE/pt_BR-faber-medium.onnx
    wget $BASE/pt_BR-faber-medium.onnx.json
Env:
    BMO_TTS_PIPER_BIN     binário do piper (default: 'piper' no PATH)
    BMO_TTS_PIPER_MODEL   caminho do .onnx (default: 1º .onnx em assets/piper/)
    BMO_TTS_PIPER_LENGTH  ritmo (default 1.0; >1 = mais devagar)

--- eSpeak-NG (fallback robótico) ---
    sudo apt install espeak-ng
    BMO_TTS_VOICE / BMO_TTS_SPEED / BMO_TTS_PITCH / BMO_TTS_GAP
"""
from __future__ import annotations

import asyncio
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import unicodedata
import wave
from pathlib import Path

import numpy as np
import pygame

from ..core import config

# Edge TTS é opcional (precisa de internet). Sem a lib, cai pra piper/espeak.
try:
    import edge_tts  # type: ignore
    HAS_EDGE = True
except Exception:
    edge_tts = None  # type: ignore
    HAS_EDGE = False

# Remove emojis e pictogramas (o TTS soletraria ou engasgaria neles).
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0001F1E6-\U0001F1FF"
    "️‍"
    "]+",
    flags=re.UNICODE,
)
# "1" (padrão) = tira acentos antes de mandar pro TTS. Em alguns modelos Piper
# pt-BR a fala soa melhor COM acento — nesse caso ponha BMO_TTS_STRIP_ACCENTS=0.
STRIP_ACCENTS = os.environ.get("BMO_TTS_STRIP_ACCENTS", "1").strip().lower() not in (
    "0", "false", "no", "nao", "off")

_QUOTE_MAP = {
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "–": "-", "—": "-", "…": "...",
}


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def clean_for_tts(text: str, strip_accents: bool = STRIP_ACCENTS) -> str:
    """Deixa só texto limpo pro TTS: sem emoji, sem markdown/símbolos, aspas e
    travessões normalizados, espaços colapsados. `strip_accents` tira acentos
    (bom p/ piper/espeak; o Edge é neural e pronuncia acento certinho, então ali
    fica False)."""
    text = (text or "").strip()
    if not text:
        return ""
    text = _EMOJI_RE.sub(" ", text)
    for k, v in _QUOTE_MAP.items():
        text = text.replace(k, v)
    # tira marcação/símbolos que o TTS leria errado (asteriscos de ação, etc.)
    text = re.sub(r"[*_`#~>|<\[\]{}\\/^=+@]", " ", text)
    if strip_accents:
        text = _strip_accents(text)
    # mantém só letra/dígito/espaço e pontuação básica de fala
    text = re.sub(r"[^\w\s.,!?;:'\"-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ----- Edge TTS (voz Francisca pt-BR; valores calibrados no laboratório) -----
EDGE_VOICE = os.environ.get("BMO_TTS_EDGE_VOICE", "pt-BR-FranciscaNeural")
EDGE_RATE = os.environ.get("BMO_TTS_EDGE_RATE", "+13%")    # velocidade
EDGE_PITCH = os.environ.get("BMO_TTS_EDGE_PITCH", "+18Hz")  # tom
EDGE_VOLUME = os.environ.get("BMO_TTS_EDGE_VOLUME", "+24%")  # volume (no áudio gerado)
# Players de MP3 externos (fallback se o mixer do pygame não decodificar MP3).
_MP3_PLAYERS = ["mpg123", "ffplay", "cvlc", "mpv"]

# ----- Piper -----
PIPER_BIN = shutil.which(os.environ.get("BMO_TTS_PIPER_BIN", "piper"))
PIPER_LENGTH = os.environ.get("BMO_TTS_PIPER_LENGTH", "1.0")
_ASSETS_PIPER = Path(__file__).resolve().parent.parent / "assets" / "piper"


def _find_piper_model() -> str:
    env = os.environ.get("BMO_TTS_PIPER_MODEL", "").strip()
    if env:
        return env if Path(env).exists() else ""
    if _ASSETS_PIPER.exists():
        models = sorted(_ASSETS_PIPER.glob("*.onnx"))
        if models:
            # preferência: faber-medium (escolha do usuário); senão o 1º
            for m in models:
                low = m.name.lower()
                if "faber" in low and "medium" in low:
                    return str(m)
            return str(models[0])
    return ""


PIPER_MODEL = _find_piper_model()

# ----- eSpeak-NG -----
ESPEAK_BIN = shutil.which("espeak-ng") or shutil.which("espeak")
VOICE = os.environ.get("BMO_TTS_VOICE", "pt-br")
SPEED = os.environ.get("BMO_TTS_SPEED", "150")
PITCH = os.environ.get("BMO_TTS_PITCH", "30")
GAP = os.environ.get("BMO_TTS_GAP", "6")

BACKEND_PREF = os.environ.get("BMO_TTS_BACKEND", "auto").strip().lower()


def _resolve_backend() -> str:
    piper_ok = bool(PIPER_BIN and PIPER_MODEL)
    if BACKEND_PREF == "edge":
        return "edge" if HAS_EDGE else "none"
    if BACKEND_PREF == "piper":
        return "piper" if piper_ok else "none"
    if BACKEND_PREF == "espeak":
        return "espeak" if ESPEAK_BIN else "none"
    # auto: Edge (voz Francisca, mais natural) > Piper (local) > eSpeak
    if HAS_EDGE:
        return "edge"
    if piper_ok:
        return "piper"
    if ESPEAK_BIN:
        return "espeak"
    return "none"


class TTSService:
    def __init__(self) -> None:
        self.backend = _resolve_backend()
        self.available = self.backend in ("edge", "piper", "espeak")
        self.error = "" if self.available else self._why_unavailable()
        self.last_text = ""
        self._speaking = False
        self._q: "queue.Queue[str]" = queue.Queue()
        self._proc = None
        self._lock = threading.Lock()
        if self.available:
            threading.Thread(target=self._loop, daemon=True).start()

    def _why_unavailable(self) -> str:
        if BACKEND_PREF == "edge" and not HAS_EDGE:
            return "edge-tts nao instalado"
        if BACKEND_PREF == "piper" and not PIPER_BIN:
            return "piper nao instalado"
        if BACKEND_PREF == "piper" and not PIPER_MODEL:
            return "falta modelo .onnx do piper"
        return "sem edge/piper/espeak"

    @property
    def speaking(self) -> bool:
        return self._speaking

    def _volume(self) -> float:
        try:
            v = config.get("tts_volume")
            if v is None:
                v = 100
            return max(0.0, min(1.0, v / 100))
        except Exception:
            return 1.0

    # ---------- API ----------

    def speak(self, text: str) -> None:
        """Enfileira uma fala (não bloqueia). Limpa o texto antes (sem emoji/
        markdown) pra o áudio sair certinho. No Edge mantém os acentos."""
        text = clean_for_tts(text, strip_accents=(self.backend != "edge"))
        if not text or not self.available:
            return
        # tts_volume=0 = mudo: nem sintetiza (economiza rede/CPU no Edge)
        if self._volume() <= 0.0:
            return
        self.last_text = text
        self._q.put(text)

    def stop(self) -> None:
        """Esvazia a fila e corta a fala atual."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
        try:
            pygame.mixer.stop()
        except Exception:
            pass
        try:
            pygame.mixer.music.stop()   # corta o MP3 do Edge, se estiver tocando
        except Exception:
            pass

    # ---------- worker ----------

    def _loop(self) -> None:
        while True:
            text = self._q.get()
            self._speaking = True
            try:
                self._say(text)
            except Exception as e:
                self.error = str(e)[:60]
            finally:
                self._speaking = False

    def _load_sound(self, path: str):
        """Carrega o WAV e devolve um pygame.Sound já no rate/canais do mixer.
        Reamostra à mão — o Piper/eSpeak geram 22050Hz e o mixer roda 44100Hz;
        tocar sem reamostrar sai a 2x (curto, agudo, 'cortado')."""
        init = pygame.mixer.get_init()
        if not init:
            return None
        mix_rate, _mix_size, mix_chans = init
        try:
            with wave.open(path, "rb") as w:
                rate = w.getframerate()
                chans = w.getnchannels()
                width = w.getsampwidth()
                raw = w.readframes(w.getnframes())
        except Exception:
            # se não der pra ler o header, deixa o pygame tentar do jeito dele
            return pygame.mixer.Sound(path)
        if width != 2 or not raw:
            return pygame.mixer.Sound(path)
        data = np.frombuffer(raw, dtype=np.int16)
        if chans > 1:                      # mixa pra mono
            data = data.reshape(-1, chans).mean(axis=1).astype(np.int16)
        if rate != mix_rate and data.size:  # reamostra (interp linear)
            n_out = int(round(data.size * mix_rate / rate))
            x_old = np.linspace(0.0, 1.0, data.size, endpoint=False)
            x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
            data = np.interp(x_new, x_old, data).astype(np.int16)
        if mix_chans == 2:                 # casa com os canais do mixer
            data = np.column_stack([data, data])
        return pygame.sndarray.make_sound(np.ascontiguousarray(data))

    def _say(self, text: str) -> None:
        # Edge gera MP3; piper/espeak geram WAV. Toca pelo mixer do pygame com
        # o volume da config (sem disputar o device). Apaga o temp no fim.
        is_mp3 = (self.backend == "edge")
        path = None
        try:
            fd, path = tempfile.mkstemp(suffix=".mp3" if is_mp3 else ".wav", prefix="bmo_tts_")
            os.close(fd)
            if not self._synth(text, path) or os.path.getsize(path) <= 64:
                return
            if is_mp3:
                self._play_mp3(path)
            else:
                self._play_wav(path)
        finally:
            if path:
                try:
                    os.remove(path)
                except Exception:
                    pass

    def _play_wav(self, path: str) -> None:
        if pygame.mixer.get_init():
            snd = self._load_sound(path)
            if snd is not None:
                snd.set_volume(self._volume())
                ch = snd.play()
                if ch is not None:
                    while ch.get_busy():
                        pygame.time.wait(40)
            return
        # sem mixer (raro): toca via aplay
        ap = shutil.which("aplay")
        if ap:
            subprocess.run([ap, "-q", path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _play_mp3(self, path: str) -> None:
        """Toca o MP3 do Edge. Tenta o mixer.music do pygame (respeita o volume);
        se a build do SDL_mixer não decodificar MP3, cai pra um player externo."""
        if pygame.mixer.get_init():
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.set_volume(self._volume())
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.wait(40)
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass
                return
            except Exception:
                pass   # mixer não tocou MP3 — tenta player externo
        self._play_external(path)

    def _play_external(self, path: str) -> None:
        for p in _MP3_PLAYERS:
            exe = shutil.which(p)
            if not exe:
                continue
            if p == "mpg123":
                cmd = [exe, "-q", path]
            elif p == "ffplay":
                cmd = [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
            elif p == "cvlc":
                cmd = [exe, "--play-and-exit", "--intf", "dummy", path]
            else:  # mpv
                cmd = [exe, "--no-video", "--really-quiet", path]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self._lock:
                self._proc = proc
            proc.wait()
            with self._lock:
                self._proc = None
            return
        self.error = "sem player de mp3 (apt install mpg123)"

    def _synth(self, text: str, path: str) -> bool:
        """Gera o áudio no `path` (MP3 p/ edge, WAV p/ piper/espeak)."""
        if self.backend == "edge":
            return self._synth_edge(text, path)
        if self.backend == "piper":
            return self._synth_piper(text, path)
        if self.backend == "espeak":
            return self._synth_espeak(text, path)
        return False

    def _synth_edge(self, text: str, path: str) -> bool:
        """Edge TTS (voz Francisca) -> MP3. Roda o asyncio na thread do worker
        (que não tem event loop próprio, então asyncio.run é seguro)."""
        if not HAS_EDGE:
            return False
        try:
            async def _gen():
                comm = edge_tts.Communicate(
                    text, EDGE_VOICE, rate=EDGE_RATE, pitch=EDGE_PITCH, volume=EDGE_VOLUME)
                await comm.save(path)
            asyncio.run(_gen())
            return os.path.getsize(path) > 64
        except Exception as e:
            self.error = f"edge: {str(e)[:50]}"
            return False

    def _synth_piper(self, text: str, path: str) -> bool:
        cmd = [PIPER_BIN, "-m", PIPER_MODEL, "-f", path,
               "--length_scale", str(PIPER_LENGTH)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self._lock:
            self._proc = proc
        try:
            proc.communicate(input=text.encode("utf-8"), timeout=30)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            return False
        finally:
            with self._lock:
                self._proc = None
        return proc.returncode == 0

    def _synth_espeak(self, text: str, path: str) -> bool:
        cmd = [ESPEAK_BIN, "-v", VOICE, "-s", str(SPEED),
               "-p", str(PITCH), "-g", str(GAP), "-w", path, text]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self._lock:
            self._proc = proc
        proc.wait()
        with self._lock:
            self._proc = None
        return proc.returncode == 0
