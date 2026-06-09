"""Gravador offline-first do Bimo — áudio bruto direto no disco.

Pensado pra aulas/reuniões/insights SEM depender de internet:
    REC -> grava WAV incremental na memória local -> STOP -> o arquivo
    entra na fila de sync do Drive (drive_sync faz upload + checksum e
    DESTRÓI o arquivo local — "Sync & Destroy").

Robustez a queda de energia: cada bloco do mic é escrito no disco na hora
(nada fica só em RAM). Enquanto grava, o arquivo é um `.part`; só no STOP
ele vira `.wav` (o sync ignora `.part`, então gravação interrompida não
sobe pela metade — fica no disco pra recuperação manual).

Formato: WAV 16kHz mono int16 (~1.9 MB/min) — suficiente pra transcrição
e leve pro upload. Usa sounddevice (mesma lib da voz); no PC sem mic
degrada com status "indisponivel".

Arbitragem do mic: o ALSA do Pi só aceita UM stream de captura por vez,
então o gravador suspende o wake word/monitor do VoiceService enquanto
grava (mesmo padrão do push-to-talk) e restaura no STOP.
"""
from __future__ import annotations

import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    import sounddevice as sd
    HAS_AUDIO = True
    AUDIO_ERR = ""
except Exception as _e:
    sd = None  # type: ignore
    HAS_AUDIO = False
    AUDIO_ERR = str(_e)[:48]

SAMPLE_RATE = 16000
BLOCK = 2048
PART_SUFFIX = ".part"


class RecorderService:
    def __init__(self, *, voice=None, recordings_dir: Path) -> None:
        self.voice = voice                      # VoiceService (arbitragem do mic)
        self.dir = Path(recordings_dir)
        self.recording = False
        self.elapsed = 0.0                      # segundos da gravação corrente
        self.level = 0.0                        # 0..1 — VU meter da tela
        self.status = "pronto" if HAS_AUDIO else (AUDIO_ERR or "sem sounddevice")
        self.last_file = ""                     # nome do último .wav fechado
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return HAS_AUDIO

    # ---------- fila local ----------

    def pending(self) -> list[Path]:
        """WAVs fechados aguardando o Sync & Destroy (mais antigo primeiro)."""
        try:
            return sorted(self.dir.glob("*.wav"))
        except OSError:
            return []

    # ---------- gravação ----------

    def toggle(self) -> None:
        if self.recording:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self.recording or not HAS_AUDIO:
            return
        self.recording = True
        self.elapsed = 0.0
        self._stop.clear()
        self.status = "gravando"
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.recording:
            return
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=5.0)

    def _device_index(self):
        if self.voice is not None:
            try:
                return self.voice._device_index()
            except Exception:
                return None
        return None

    def _worker(self) -> None:
        # mic exclusivo: pausa wake word/monitor do VoiceService
        state = None
        if self.voice is not None:
            try:
                state = self.voice._suspend_listeners()
            except Exception:
                state = None

        self.dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        part = self.dir / f"rec_{stamp}.wav{PART_SUFFIX}"
        wav = None
        t0 = time.time()
        try:
            wav = wave.open(str(part), "wb")
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                device=self._device_index(), blocksize=BLOCK) as stream:
                while not self._stop.is_set():
                    block, _ = stream.read(BLOCK)
                    mono = block[:, 0]
                    wav.writeframes(mono.tobytes())   # bloco -> disco na hora
                    rms = float(np.sqrt(np.mean(np.square(
                        mono.astype(np.float32) / 32768.0))))
                    self.level = min(1.0, rms * 4.0)
                    self.elapsed = time.time() - t0
        except Exception as e:
            self.status = f"erro: {str(e)[:40]}"
        finally:
            if wav is not None:
                try:
                    wav.close()   # fecha o header (nframes correto)
                except Exception:
                    pass
            self.level = 0.0
            self.recording = False
            if self.voice is not None and state is not None:
                try:
                    self.voice._resume_listeners(state)
                except Exception:
                    pass
        # gravação íntegra: .part vira .wav e entra na fila do sync
        try:
            if part.exists() and part.stat().st_size > 44:   # > header WAV
                final = part.with_suffix("")                 # remove ".part"
                part.rename(final)
                self.last_file = final.name
                if not self.status.startswith("erro"):
                    self.status = "salvo localmente"
            else:
                part.unlink(missing_ok=True)
                if not self.status.startswith("erro"):
                    self.status = "nada gravado"
        except OSError:
            pass
