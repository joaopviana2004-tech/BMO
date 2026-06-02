"""Voz do BMO (TTS) — fala robótica via eSpeak-NG.

O eSpeak-NG gera o WAV em `--stdout` e tocamos pelo **mixer do pygame** (mesma
saída dos efeitos), então respeita o volume do BMO e não disputa o device de
playback com o ALSA. Sem pygame mixer, cai pro modo em que o próprio eSpeak-NG
toca direto.

Fala em thread (fila) — `speak()` não bloqueia o render loop. Degrada com
elegância: sem eSpeak-NG instalado, `available=False` e `speak()` é no-op (no
PC de dev é o caso comum).

Setup no Pi:
    sudo apt install espeak-ng

Ajuste fino por env (voz robótica = pitch baixo + fala um pouco lenta):
    BMO_TTS_VOICE  voz/idioma do eSpeak (default pt-br; tente pt-br+m1..m7)
    BMO_TTS_SPEED  palavras/min (default 150; menor = mais robótico/claro)
    BMO_TTS_PITCH  tom 0-99 (default 30; menor = mais grave/robô)
    BMO_TTS_GAP    pausa entre palavras x10ms (default 6)

Teste rápido no terminal do Pi:
    espeak-ng -v pt-br -s 150 -p 30 "Oi, eu sou o BMO"
"""
from __future__ import annotations

import io
import os
import queue
import shutil
import subprocess
import threading

import pygame

from ..core import config

ESPEAK_BIN = shutil.which("espeak-ng") or shutil.which("espeak")

VOICE = os.environ.get("BMO_TTS_VOICE", "pt-br")
SPEED = os.environ.get("BMO_TTS_SPEED", "150")
PITCH = os.environ.get("BMO_TTS_PITCH", "30")
GAP = os.environ.get("BMO_TTS_GAP", "6")


class TTSService:
    def __init__(self) -> None:
        self.available = ESPEAK_BIN is not None
        self.error = "" if self.available else "espeak-ng nao instalado"
        self.last_text = ""
        self._speaking = False
        self._q: "queue.Queue[str]" = queue.Queue()
        self._proc = None
        self._lock = threading.Lock()
        if self.available:
            threading.Thread(target=self._loop, daemon=True).start()

    @property
    def speaking(self) -> bool:
        return self._speaking

    def _volume(self) -> float:
        try:
            return max(0.0, min(1.0, (config.get("volume") or 100) / 100))
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

    def _say(self, text: str) -> None:
        cmd_common = [ESPEAK_BIN, "-v", VOICE, "-s", str(SPEED),
                      "-p", str(PITCH), "-g", str(GAP)]
        # 1) preferido: gera WAV e toca pelo mixer do pygame (volume + sem
        #    disputa de device). Só se o mixer estiver de pé.
        if pygame.mixer.get_init():
            try:
                proc = subprocess.Popen(
                    cmd_common + ["--stdout", text],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                with self._lock:
                    self._proc = proc
                wav, _ = proc.communicate()
                with self._lock:
                    self._proc = None
                if wav:
                    snd = pygame.mixer.Sound(file=io.BytesIO(wav))
                    snd.set_volume(self._volume())
                    ch = snd.play()
                    if ch is not None:
                        while ch.get_busy():
                            pygame.time.wait(40)
                    return
            except Exception:
                pass
        # 2) fallback: o próprio eSpeak-NG toca direto (sai no ALSA padrão)
        proc = subprocess.Popen(
            cmd_common + [text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self._lock:
            self._proc = proc
        proc.wait()
        with self._lock:
            self._proc = None
