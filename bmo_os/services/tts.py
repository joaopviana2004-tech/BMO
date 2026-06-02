"""Voz do BMO (TTS) — Piper (neural, natural) ou eSpeak-NG (robótico).

Backend por env BMO_TTS_BACKEND: "piper" | "espeak" | "auto" (default).
auto = usa Piper se houver binário + modelo, senão cai pro eSpeak-NG.

Sintetiza num WAV temporário e toca pelo **mixer do pygame** (respeita o volume
da config `tts_volume`, sem disputar o device). Fala em thread (fila) — `speak()`
não bloqueia o render loop. Degrada: sem backend, `available=False` e é no-op.

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

import os
import queue
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np
import pygame

from ..core import config

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
    if BACKEND_PREF == "piper":
        return "piper" if piper_ok else "none"
    if BACKEND_PREF == "espeak":
        return "espeak" if ESPEAK_BIN else "none"
    # auto: prefere piper (mais natural), senão espeak
    if piper_ok:
        return "piper"
    if ESPEAK_BIN:
        return "espeak"
    return "none"


class TTSService:
    def __init__(self) -> None:
        self.backend = _resolve_backend()
        self.available = self.backend in ("piper", "espeak")
        self.error = "" if self.available else self._why_unavailable()
        self.last_text = ""
        self._speaking = False
        self._q: "queue.Queue[str]" = queue.Queue()
        self._proc = None
        self._lock = threading.Lock()
        if self.available:
            threading.Thread(target=self._loop, daemon=True).start()

    def _why_unavailable(self) -> str:
        if BACKEND_PREF == "piper" and not PIPER_BIN:
            return "piper nao instalado"
        if BACKEND_PREF == "piper" and not PIPER_MODEL:
            return "falta modelo .onnx do piper"
        return "sem piper/espeak"

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
        """Enfileira uma fala (não bloqueia)."""
        text = (text or "").strip()
        if not text or not self.available:
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
        # sintetiza num arquivo WAV (seekable — header correto) e toca pelo
        # mixer do pygame com o volume da config.
        path = None
        try:
            fd, path = tempfile.mkstemp(suffix=".wav", prefix="bmo_tts_")
            os.close(fd)
            if not self._synth(text, path) or os.path.getsize(path) <= 44:
                return
            if pygame.mixer.get_init():
                snd = self._load_sound(path)
                if snd is not None:
                    snd.set_volume(self._volume())
                    ch = snd.play()
                    if ch is not None:
                        while ch.get_busy():
                            pygame.time.wait(40)
            else:
                # sem mixer (raro): toca via aplay
                ap = shutil.which("aplay")
                if ap:
                    subprocess.run([ap, "-q", path],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            if path:
                try:
                    os.remove(path)
                except Exception:
                    pass

    def _synth(self, text: str, path: str) -> bool:
        """Gera o WAV no `path`. Retorna True se deu certo."""
        if self.backend == "piper":
            return self._synth_piper(text, path)
        if self.backend == "espeak":
            return self._synth_espeak(text, path)
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
