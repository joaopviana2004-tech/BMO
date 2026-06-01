"""Audição do BMO — wake word "BMO" + comando de voz (Whisper.cpp).

Pipeline (só roda no Pi com as libs; no PC degrada e mostra "indisponível"):
  microfone (sounddevice) -> wake word (Porcupine) -> grava a fala até o
  silêncio -> transcreve (pywhispercpp, modelo ggml small) -> casa com um
  comando registrado -> executa.

Tudo é import opcional e embrulhado em try/except — sem as libs o app roda
normal e a tela de TESTE / settings mostram o status. O push-to-talk
(record_and_transcribe) funciona sem wake word, então dá pra testar o Whisper
sozinho antes de configurar o Porcupine.

Setup no Pi (resumo):
    pip install sounddevice pywhispercpp pvporcupine
    sudo apt install libportaudio2
  - Whisper: baixe/aponte o modelo ggml small (pywhispercpp baixa sozinho na
    1a vez, ou aponte WHISPER_MODEL pra um .bin).
  - Wake word "BMO": crie a keyword no Picovoice Console, baixe o .ppn pra
    assets/bmo.ppn e ponha PORCUPINE_ACCESS_KEY no .env. Sem isso, o wake word
    fica off (mas o push-to-talk continua).
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import numpy as np

from ..core import config

# ----- imports opcionais -----
try:
    import sounddevice as sd
    HAS_AUDIO = True
    AUDIO_ERR = ""
except Exception as _e:
    # erro comum no Pi: "PortAudio library not found" (falta libportaudio2)
    sd = None  # type: ignore
    HAS_AUDIO = False
    AUDIO_ERR = str(_e)[:48]

try:
    from pywhispercpp.model import Model as _WhisperModel
    HAS_WHISPER = True
except Exception:
    _WhisperModel = None  # type: ignore
    HAS_WHISPER = False

try:
    import pvporcupine
    HAS_PORCUPINE = True
except Exception:
    pvporcupine = None  # type: ignore
    HAS_PORCUPINE = False

SAMPLE_RATE = 16000          # Whisper e Porcupine trabalham em 16kHz mono
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
PPN_PATH = Path(__file__).resolve().parent.parent / "assets" / "bmo.ppn"

# endpointing simples por energia (grava a fala até o silêncio)
SILENCE_RMS = 0.012          # abaixo disso = silêncio
MAX_UTTERANCE_S = 6.0
SILENCE_HANG_S = 0.8         # silêncio contínuo que encerra a fala


class VoiceService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.status = "offline"
        self.last_text = ""
        self._level = 0.0
        self._busy = False
        self._monitor_stream = None
        self._wake_thread = None
        self._wake_stop = threading.Event()
        self._commands: list[tuple[list[str], object]] = []
        self._whisper = None

        if not HAS_AUDIO:
            self.status = AUDIO_ERR or "sem sounddevice"
        elif not HAS_WHISPER:
            self.status = "sem whisper"
        else:
            self.status = "pronto"

        if config.get("voice_enabled"):
            self.set_enabled(True)

    # ---------- disponibilidade ----------

    @property
    def available(self) -> bool:
        return HAS_AUDIO and HAS_WHISPER

    @property
    def wakeword_available(self) -> bool:
        return (HAS_AUDIO and HAS_PORCUPINE
                and bool(os.environ.get("PORCUPINE_ACCESS_KEY"))
                and PPN_PATH.exists())

    # ---------- dispositivos de microfone ----------

    @staticmethod
    def list_input_devices() -> list[str]:
        if not HAS_AUDIO:
            return []
        try:
            seen, out = set(), []
            for dev in sd.query_devices():
                if dev.get("max_input_channels", 0) > 0:
                    name = dev["name"]
                    if name not in seen:
                        seen.add(name)
                        out.append(name)
            return out
        except Exception:
            return []

    def _device_index(self):
        """Resolve o índice do mic escolhido em config (substring), ou None (padrão)."""
        want = (config.get("mic_device") or "").strip().lower()
        if not want or not HAS_AUDIO:
            return None
        try:
            for i, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) > 0 and want in dev["name"].lower():
                    return i
        except Exception:
            pass
        return None

    # ---------- nível do mic (medidor da tela de teste) ----------

    def level(self) -> float:
        with self._lock:
            return self._level

    def start_monitor(self) -> None:
        if not HAS_AUDIO or self._monitor_stream is not None:
            return

        def cb(indata, frames, t, status):
            rms = float(np.sqrt(np.mean(np.square(indata[:, 0])))) if frames else 0.0
            with self._lock:
                self._level = min(1.0, rms * 4.0)

        try:
            self._monitor_stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                device=self._device_index(), callback=cb, blocksize=1024,
            )
            self._monitor_stream.start()
        except Exception:
            self._monitor_stream = None

    def stop_monitor(self) -> None:
        s, self._monitor_stream = self._monitor_stream, None
        if s is not None:
            try:
                s.stop(); s.close()
            except Exception:
                pass
        with self._lock:
            self._level = 0.0

    # ---------- whisper ----------

    def _ensure_whisper(self):
        if self._whisper is None and HAS_WHISPER:
            self._whisper = _WhisperModel(WHISPER_MODEL)
        return self._whisper

    def _transcribe(self, audio: "np.ndarray") -> str:
        model = self._ensure_whisper()
        if model is None:
            return ""
        try:
            segs = model.transcribe(audio, language="pt")
            return " ".join(s.text for s in segs).strip()
        except Exception:
            return ""

    def _record_utterance(self) -> "np.ndarray | None":
        """Grava do mic até o silêncio (ou MAX_UTTERANCE_S). Bloqueante."""
        if not HAS_AUDIO:
            return None
        chunks: list = []
        t_prev = time.time()
        silence_t = 0.0
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                device=self._device_index(), blocksize=1024) as stream:
                while True:
                    block, _ = stream.read(1024)
                    mono = block[:, 0]
                    chunks.append(mono.copy())
                    rms = float(np.sqrt(np.mean(np.square(mono))))
                    with self._lock:
                        self._level = min(1.0, rms * 4.0)
                    now = time.time()
                    silence_t = (silence_t + (now - t_prev)) if rms < SILENCE_RMS else 0.0
                    t_prev = now
                    total_s = sum(len(c) for c in chunks) / SAMPLE_RATE
                    if silence_t >= SILENCE_HANG_S and len(chunks) > 8:
                        break
                    if total_s >= MAX_UTTERANCE_S:
                        break
        except Exception:
            return None
        if not chunks:
            return None
        return np.concatenate(chunks)

    # ---------- push-to-talk (tela de teste) ----------

    def record_and_transcribe(self, on_done=None) -> None:
        """Grava uma fala e transcreve em thread. Resultado em self.last_text."""
        if self._busy or not self.available:
            return
        self._busy = True
        self.status = "ouvindo..."

        def work():
            audio = self._record_utterance()
            self.status = "processando..."
            text = self._transcribe(audio) if audio is not None else ""
            with self._lock:
                self.last_text = text
            self.status = "pronto"
            self._busy = False
            if on_done:
                try:
                    on_done(text)
                except Exception:
                    pass
            self._dispatch(text)

        threading.Thread(target=work, daemon=True).start()

    @property
    def busy(self) -> bool:
        return self._busy

    # ---------- comandos ----------

    def register_command(self, phrases: list[str], action) -> None:
        self._commands.append(([p.lower() for p in phrases], action))

    def _dispatch(self, text: str) -> None:
        low = (text or "").lower()
        if not low:
            return
        for phrases, action in self._commands:
            if any(p in low for p in phrases):
                try:
                    action()
                except Exception:
                    pass
                return

    # ---------- wake word (loop em background) ----------

    def set_enabled(self, on: bool) -> None:
        config.set_value("voice_enabled", bool(on))
        if on:
            self._start_wake()
        else:
            self._stop_wake()

    def _start_wake(self) -> None:
        if self._wake_thread is not None:
            return
        if not self.wakeword_available:
            self.status = "wake word indisponivel"
            return
        self._wake_stop.clear()
        self._wake_thread = threading.Thread(target=self._wake_loop, daemon=True)
        self._wake_thread.start()

    def _stop_wake(self) -> None:
        self._wake_stop.set()
        self._wake_thread = None
        if self.available:
            self.status = "pronto"

    def _wake_loop(self) -> None:
        try:
            handle = pvporcupine.create(
                access_key=os.environ["PORCUPINE_ACCESS_KEY"],
                keyword_paths=[str(PPN_PATH)],
            )
        except Exception:
            self.status = "wake word falhou"
            self._wake_thread = None
            return
        self.status = "ouvindo 'BMO'"
        try:
            with sd.InputStream(samplerate=handle.sample_rate, channels=1,
                                dtype="int16", device=self._device_index(),
                                blocksize=handle.frame_length) as stream:
                while not self._wake_stop.is_set():
                    block, _ = stream.read(handle.frame_length)
                    if handle.process(block[:, 0]) >= 0:
                        # detectou "BMO" -> grava e transcreve o comando
                        self.status = "ouvindo..."
                        audio = self._record_utterance()
                        self.status = "processando..."
                        text = self._transcribe(audio) if audio is not None else ""
                        with self._lock:
                            self.last_text = text
                        self._dispatch(text)
                        self.status = "ouvindo 'BMO'"
        except Exception:
            self.status = "wake word erro"
        finally:
            try:
                handle.delete()
            except Exception:
                pass
            self._wake_thread = None
