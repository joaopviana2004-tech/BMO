"""Audição do BMO — wake word "BIMO" + comando de voz (Whisper.cpp).

Pipeline (só roda no Pi com as libs; no PC degrada e mostra "indisponível"):
  microfone (sounddevice) -> wake word (Porcupine) -> grava a fala até o
  silêncio -> transcreve (pywhispercpp, modelo ggml small) -> casa com um
  comando registrado -> executa.

Tudo é import opcional e embrulhado em try/except — sem as libs o app roda
normal e a tela de TESTE / settings mostram o status. O push-to-talk
(record_and_transcribe) funciona sem wake word, então dá pra testar o Whisper
sozinho antes de configurar o Porcupine.

Debug (pra tela TESTE): wake_count (ativações do wake word), last_wake (quando),
history (últimas frases reconhecidas, push-to-talk e wake word).

Setup no Pi (resumo):
    pip install sounddevice pywhispercpp pvporcupine
    sudo apt install libportaudio2
  - Whisper: baixe/aponte o modelo ggml small (pywhispercpp baixa sozinho na
    1a vez, ou aponte WHISPER_MODEL pra um .bin).
  - Wake word "robo": crie a keyword no Picovoice Console, baixe o .ppn pra
    assets/robo.ppn (ou aponte PORCUPINE_KEYWORD_PATH) e ponha
    PORCUPINE_ACCESS_KEY no .env. Pra testar JÁ sem criar .ppn, use uma
    keyword embutida: PORCUPINE_KEYWORD=computer (ou jarvis, picovoice...).
    Sem nada disso o wake word fica off (mas o push-to-talk continua).
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
import urllib.error
import urllib.request
import wave
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

# --- Whisper: defaults otimizados pra rodar frio no Pi ---
# Modelo: base (bom custo/beneficio). tiny = mais frio/rapido; small = +preciso.
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
# Threads do whisper.cpp (Pi4 = 4 cores). Menos threads = pico menor de calor.
try:
    WHISPER_THREADS = int(os.environ.get("WHISPER_THREADS", "0")) or min(4, os.cpu_count() or 4)
except ValueError:
    WHISPER_THREADS = min(4, os.cpu_count() or 4)
# audio_ctx menor encurta MUITO o encoder (parte mais pesada); 0 = completo (1500).
# 768 e suficiente pra comandos curtos e corta ~metade do trabalho.
try:
    WHISPER_AUDIO_CTX = int(os.environ.get("WHISPER_AUDIO_CTX", "768"))
except ValueError:
    WHISPER_AUDIO_CTX = 768

_DEFAULT_PPN = Path(__file__).resolve().parent.parent / "assets" / "robo.ppn"
PPN_PATH = Path(os.environ.get("PORCUPINE_KEYWORD_PATH", str(_DEFAULT_PPN)))
# Atalho pra testar JÁ: uma keyword embutida do Porcupine (ex: "computer",
# "jarvis", "picovoice"...). Se setada, usa ela em vez do robo.ppn.
PORCUPINE_BUILTIN = os.environ.get("PORCUPINE_KEYWORD", "").strip()
WAKE_NAME = (PORCUPINE_BUILTIN or "ROBO").upper()

# --- STT por API (compatível com OpenAI /audio/transcriptions) ---
# Tira TODA a inferência da Pi (sem calor) e usa whisper-large-v3 (mais preciso).
# Default: Groq (rápido, tier grátis). Serve qualquer endpoint compatível
# (OpenAI, NVIDIA, ou um faster-whisper-server self-hosted).
STT_BACKEND = os.environ.get("STT_BACKEND", "auto").strip().lower()   # auto|api|local
STT_API_URL = os.environ.get("STT_API_URL", "https://api.groq.com/openai/v1/audio/transcriptions")
STT_API_MODEL = os.environ.get("STT_API_MODEL", "whisper-large-v3-turbo")
STT_API_KEY = os.environ.get("STT_API_KEY", "").strip()

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
        self._hold = False           # push-to-talk físico: True enquanto o botão está pressionado
        self._commands: list[tuple[list[str], object]] = []
        self._whisper = None
        self._cap_rate = None        # taxa de captura resolvida p/ o mic (16k ou nativa)
        # --- debug ---
        self.wake_count = 0          # quantas vezes o wake word disparou
        self._last_wake = 0.0        # time.time() da última ativação
        self.history: list = []      # últimas frases reconhecidas ("src: texto")
        self.last_error = ""         # último erro de transcrição (HTTP/rede/vazio)
        self.last_audio = ""         # info do último áudio gravado (dur/peak)

        if not HAS_AUDIO:
            self.status = AUDIO_ERR or "sem sounddevice"
        elif self._use_api():
            self.status = "pronto (api)" if STT_API_KEY else "falta STT_API_KEY"
        elif not HAS_WHISPER:
            self.status = "sem whisper"
        else:
            self.status = "pronto"

        if config.get("voice_enabled"):
            self.set_enabled(True)

    # ---------- disponibilidade ----------

    def _use_api(self) -> bool:
        if STT_BACKEND == "local":
            return False
        if STT_BACKEND == "api":
            return True
        return bool(STT_API_KEY)   # auto: usa API se tiver chave

    @property
    def available(self) -> bool:
        if not HAS_AUDIO:
            return False
        if self._use_api():
            return bool(STT_API_KEY)
        return HAS_WHISPER

    @property
    def wakeword_available(self) -> bool:
        return (HAS_AUDIO and HAS_PORCUPINE
                and bool(os.environ.get("PORCUPINE_ACCESS_KEY"))
                and (bool(PORCUPINE_BUILTIN) or PPN_PATH.exists()))

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

    # ---------- taxa de captura (mics USB so falam 44.1/48k) ----------

    def _capture_rate(self) -> int:
        """Taxa em que o mic consegue abrir. Whisper/Porcupine querem 16k, mas
        muito mic USB (ex: C-Media PnP) so aceita 44100/48000 no device 'hw:'
        direto (sem reamostragem do ALSA). Resolve a melhor taxa nativa e o
        codigo reamostra pra 16k depois. Cacheia (so muda se trocar de mic)."""
        if self._cap_rate:
            return self._cap_rate
        rate = SAMPLE_RATE
        if HAS_AUDIO:
            dev = self._device_index()
            for cand in (SAMPLE_RATE, 48000, 44100, 32000, 22050):
                try:
                    sd.check_input_settings(device=dev, samplerate=cand,
                                            channels=1, dtype="float32")
                    rate = cand
                    break
                except Exception:
                    continue
        self._cap_rate = rate
        return rate

    @staticmethod
    def _resample(audio: "np.ndarray", src_rate: int, n_out=None) -> "np.ndarray":
        """Reamostra mono float32 de src_rate -> 16k. Se n_out for dado, devolve
        exatamente n_out amostras (usado no wake word, que exige frames fixos).
        Decima por media quando a razao e inteira (anti-alias barato); senao
        interpola linear."""
        if audio is None or audio.size == 0:
            return audio
        if n_out is None:
            if src_rate == SAMPLE_RATE:
                return audio
            n_out = max(1, int(round(audio.size * SAMPLE_RATE / src_rate)))
        if n_out == audio.size:
            return audio.astype(np.float32, copy=False)
        if src_rate % SAMPLE_RATE == 0:
            factor = src_rate // SAMPLE_RATE
            if audio.size == n_out * factor:        # caminho exato (wake/blocos)
                return audio.reshape(n_out, factor).mean(axis=1).astype(np.float32)
        x_old = np.linspace(0.0, 1.0, audio.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
        return np.interp(x_new, x_old, audio).astype(np.float32)

    # ---------- nível do mic (medidor da tela de teste) ----------

    def level(self) -> float:
        with self._lock:
            return self._level

    def _open_input_stream(self, **kw):
        """Abre um sd.InputStream com algumas tentativas. No Pi o ALSA costuma
        responder 'device unavailable' por uma fração de segundo logo depois de
        outro stream fechar — repetir resolve. Guarda o erro em last_error."""
        last = None
        for _ in range(6):
            try:
                return sd.InputStream(**kw)
            except Exception as e:
                last = e
                time.sleep(0.15)
        self.last_error = f"mic: {str(last)[:60]}"
        raise last

    # ---------- arbitragem do microfone (so um stream de captura por vez) ----------

    def _suspend_listeners(self) -> tuple:
        """Libera o mic pra uma gravacao exclusiva: para o monitor passivo e o
        wake loop. Devolve o estado pra _resume_listeners restaurar depois."""
        was_wake = self.listening
        if was_wake:
            self._stop_wake()
        had_monitor = self._monitor_stream is not None
        if had_monitor:
            self.stop_monitor()
        return (was_wake, had_monitor)

    def _resume_listeners(self, state: tuple) -> None:
        was_wake, had_monitor = state
        # wake primeiro: ele e o monitor são mutuamente exclusivos (start_monitor
        # não abre se o wake estiver escutando), então a ordem evita disputa.
        if was_wake:
            self._start_wake()
        if had_monitor:
            self.start_monitor()

    def start_monitor(self) -> None:
        # não abre se o wake word já segura o mic (só um stream de captura por
        # vez no ALSA — abrir um 2º dá 'device unavailable'/AlsaOpen failed).
        if not HAS_AUDIO or self._monitor_stream is not None or self.listening:
            return

        def cb(indata, frames, t, status):
            rms = float(np.sqrt(np.mean(np.square(indata[:, 0])))) if frames else 0.0
            with self._lock:
                self._level = min(1.0, rms * 4.0)

        try:
            self._monitor_stream = self._open_input_stream(
                samplerate=self._capture_rate(), channels=1, dtype="float32",
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
            try:
                self._whisper = _WhisperModel(WHISPER_MODEL, redirect_whispercpp_logs_to=False)
            except Exception:
                self._whisper = _WhisperModel(WHISPER_MODEL)
        return self._whisper

    def _whisper_params(self) -> dict:
        """Parâmetros enxutos: comando curto, sem fallback, encoder reduzido."""
        p = dict(
            language="pt",
            n_threads=WHISPER_THREADS,
            translate=False,
            single_segment=True,     # comando = uma frase curta
            no_context=True,         # não acumula contexto entre falas
            temperature_inc=0.0,     # desliga o fallback (não re-roda o modelo)
            print_progress=False,
            print_realtime=False,
        )
        if WHISPER_AUDIO_CTX > 0:
            p["audio_ctx"] = WHISPER_AUDIO_CTX
        return p

    @staticmethod
    def _normalize(audio: "np.ndarray") -> "np.ndarray":
        """Ganho automático: mic de webcam costuma ser baixo. Ganho capado em 8x
        pra não estourar ruído quando não há fala."""
        if audio is None or audio.size == 0:
            return audio
        peak = float(np.max(np.abs(audio)))
        if peak <= 0:
            return audio
        gain = min(8.0, 0.9 / peak)
        return (audio * gain).astype(np.float32)

    def _note_audio(self, audio) -> None:
        """Guarda duração + pico do áudio CRU (pré-normalização) pra debug."""
        if audio is None or getattr(audio, "size", 0) == 0:
            self.last_audio = "0s (nada gravado)"
            return
        dur = audio.size / SAMPLE_RATE
        peak = float(np.max(np.abs(audio)))
        self.last_audio = f"{dur:.1f}s pico{peak:.2f}"

    def _transcribe(self, audio: "np.ndarray") -> str:
        self.last_error = ""
        self._note_audio(audio)               # info do áudio cru (pré-normalização)
        audio = self._normalize(audio)
        if self._use_api():
            return self._transcribe_api(audio)
        return self._transcribe_local(audio)

    def _transcribe_local(self, audio: "np.ndarray") -> str:
        model = self._ensure_whisper()
        if model is None:
            return ""
        # tenta os params otimizados; cai pra versões mais simples se a build
        # do pywhispercpp não aceitar algum parâmetro.
        for params in (self._whisper_params(),
                       {"language": "pt", "n_threads": WHISPER_THREADS},
                       {"language": "pt"}):
            try:
                segs = model.transcribe(audio, **params)
                return " ".join(s.text for s in segs).strip()
            except (TypeError, AttributeError):
                continue
            except Exception:
                return ""
        return ""

    # ---------- STT por API (OpenAI-compatible) ----------

    def _transcribe_api(self, audio: "np.ndarray") -> str:
        if not STT_API_KEY:
            self.last_error = "falta STT_API_KEY"
            return ""
        try:
            text = self._post_transcription(self._to_wav_bytes(audio))
            if not text:
                self.last_error = "api: resposta vazia (audio mudo?)"
            return text
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "ignore")
            except Exception:
                pass
            msg = body
            try:
                msg = json.loads(body).get("error", {}).get("message", body)
            except Exception:
                pass
            self.last_error = f"HTTP {e.code}: {(msg or '').strip()[:90]}"
            return ""
        except urllib.error.URLError as e:
            self.last_error = f"rede: {str(e.reason)[:70]}"
            return ""
        except Exception as e:
            self.last_error = f"erro: {str(e)[:70]}"
            return ""

    @staticmethod
    def _to_wav_bytes(audio: "np.ndarray") -> bytes:
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        return buf.getvalue()

    @staticmethod
    def _post_transcription(wav: bytes) -> str:
        boundary = "----BMOFormBoundary8x4tZqueV0iceBMO"
        sep = ("--" + boundary).encode()
        parts: list = []

        def field(name: str, value: str) -> None:
            parts.append(sep + b"\r\n")
            parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            parts.append(str(value).encode() + b"\r\n")

        field("model", STT_API_MODEL)
        field("language", "pt")
        field("response_format", "json")
        field("temperature", "0")
        parts.append(sep + b"\r\n")
        parts.append(b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n')
        parts.append(b"Content-Type: audio/wav\r\n\r\n")
        parts.append(wav + b"\r\n")
        parts.append(("--" + boundary + "--\r\n").encode())
        body = b"".join(parts)

        req = urllib.request.Request(STT_API_URL, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {STT_API_KEY}")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        # User-Agent próprio: o padrão "Python-urllib" é barrado pelo Cloudflare
        # do Groq (HTTP 403, erro 1010). Qualquer UA não-urllib passa.
        req.add_header("User-Agent", "BMO-OS/1.0")
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("text") or "").strip()

    def _record_utterance(self) -> "np.ndarray | None":
        """Grava do mic até o silêncio (ou MAX_UTTERANCE_S). Bloqueante."""
        if not HAS_AUDIO:
            return None
        chunks: list = []
        t_prev = time.time()
        silence_t = 0.0
        cap = self._capture_rate()
        try:
            with self._open_input_stream(samplerate=cap, channels=1, dtype="float32",
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
                    total_s = sum(len(c) for c in chunks) / cap
                    if silence_t >= SILENCE_HANG_S and len(chunks) > 8:
                        break
                    if total_s >= MAX_UTTERANCE_S:
                        break
        except Exception:
            return None
        if not chunks:
            return None
        return self._resample(np.concatenate(chunks), cap)   # -> 16k pro Whisper/API

    # ---------- push-to-talk (tela de teste) ----------

    def record_and_transcribe(self, on_done=None) -> None:
        """Grava uma fala e transcreve em thread. Resultado em self.last_text.
        Suspende o monitor/wake (acesso exclusivo ao mic) e restaura no fim."""
        if self._busy or not self.available:
            return
        self._busy = True
        state = self._suspend_listeners()
        self.status = "ouvindo..."

        def work():
            text = ""
            try:
                audio = self._record_utterance()
                self.status = "processando..."
                text = self._transcribe(audio) if audio is not None else ""
                with self._lock:
                    self.last_text = text
                self._log(text, "fala")
                # status reflete o resultado (não sobrescreve o erro com "pronto")
                if text:
                    self.status = "pronto"
                elif self.last_error:
                    self.status = self.last_error[:40]
                else:
                    self.status = "vazio (sem fala?)"
            finally:
                self._resume_listeners(state)
                self._busy = False
            if on_done:
                try:
                    on_done(text)
                except Exception:
                    pass
            self._dispatch(text)

        threading.Thread(target=work, daemon=True).start()

    # ---------- push-to-talk físico (botão GPIO: grava enquanto segura) ----------

    def ptt_begin(self, on_done=None) -> None:
        """Começa a gravar (chamado ao PRESSIONAR o botão). Grava até ptt_end().
        Suspende monitor/wake pra ter o mic exclusivo (restaura no fim)."""
        if self._busy or not self.available or not HAS_AUDIO:
            return
        self._busy = True
        self._hold = True
        state = self._suspend_listeners()
        self.status = "gravando..."
        threading.Thread(target=self._hold_worker, args=(on_done, state), daemon=True).start()

    def ptt_end(self) -> None:
        """Para de gravar (chamado ao SOLTAR o botão) — o worker transcreve."""
        self._hold = False

    def _hold_worker(self, on_done, state) -> None:
        chunks: list = []
        text = ""
        cap = self._capture_rate()
        try:
            with self._open_input_stream(samplerate=cap, channels=1, dtype="float32",
                                         device=self._device_index(), blocksize=1024) as stream:
                while self._hold:
                    block, _ = stream.read(1024)
                    mono = block[:, 0]
                    chunks.append(mono.copy())
                    rms = float(np.sqrt(np.mean(np.square(mono))))
                    with self._lock:
                        self._level = min(1.0, rms * 4.0)
        except Exception as e:
            self.last_error = f"mic: {str(e)[:50]}"
        with self._lock:
            self._level = 0.0
        try:
            audio = self._resample(np.concatenate(chunks), cap) if chunks else None
            self.status = "processando..."
            text = self._transcribe(audio) if audio is not None else ""
            with self._lock:
                self.last_text = text
            self._log(text, "ptt")
            if text:
                self.status = "pronto"
            elif self.last_error:
                self.status = self.last_error[:40]
            else:
                self.status = "vazio (sem fala?)"
        finally:
            self._resume_listeners(state)
            self._busy = False
        if on_done:
            try:
                on_done(text)
            except Exception:
                pass
        self._dispatch(text)

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

    # ---------- debug ----------

    def _log(self, text: str, src: str) -> None:
        entry = f"{src}: {(text or '').strip() or '—'}"
        with self._lock:
            self.history.append(entry)
            self.history = self.history[-8:]

    @property
    def listening(self) -> bool:
        return self._wake_thread is not None

    def seconds_since_wake(self):
        return (time.time() - self._last_wake) if self._last_wake else None

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
            if PORCUPINE_BUILTIN:
                handle = pvporcupine.create(
                    access_key=os.environ["PORCUPINE_ACCESS_KEY"],
                    keywords=[PORCUPINE_BUILTIN],
                )
            else:
                handle = pvporcupine.create(
                    access_key=os.environ["PORCUPINE_ACCESS_KEY"],
                    keyword_paths=[str(PPN_PATH)],
                )
        except Exception:
            self.status = "wake word falhou"
            self._wake_thread = None
            return
        self.status = f"ouvindo '{WAKE_NAME}'"

        # mic so abre na taxa nativa (ex: 48k); Porcupine quer 16k em frames
        # fixos. Captura float32 no 'cap' e reamostra cada bloco pra frame_length.
        cap = self._capture_rate()
        resample = cap != handle.sample_rate
        read_len = (int(round(handle.frame_length * cap / handle.sample_rate))
                    if resample else handle.frame_length)

        def open_wake():
            s = self._open_input_stream(
                samplerate=cap, channels=1,
                dtype="float32" if resample else "int16",
                device=self._device_index(), blocksize=read_len)
            s.start()
            return s

        def next_frame(stream):
            block, _ = stream.read(read_len)
            mono = block[:, 0]
            if not resample:
                return mono                       # ja e int16 @16k
            frame = self._resample(mono, cap, n_out=handle.frame_length)
            return (np.clip(frame, -1.0, 1.0) * 32767.0).astype(np.int16)

        stream = None
        try:
            stream = open_wake()
            while not self._wake_stop.is_set():
                if handle.process(next_frame(stream)) >= 0:
                    # detectou a wake word -> libera o mic, grava e transcreve
                    self.wake_count += 1
                    self._last_wake = time.time()
                    self.status = "ouvindo..."
                    stream.stop(); stream.close(); stream = None
                    audio = self._record_utterance()
                    self.status = "processando..."
                    text = self._transcribe(audio) if audio is not None else ""
                    with self._lock:
                        self.last_text = text
                    self._log(text, "wake")
                    self._dispatch(text)
                    stream = open_wake()   # volta a ouvir o wake word
                    self.status = f"ouvindo '{WAKE_NAME}'"
        except Exception:
            self.status = "wake word erro"
        finally:
            if stream is not None:
                try:
                    stream.stop(); stream.close()
                except Exception:
                    pass
            try:
                handle.delete()
            except Exception:
                pass
            self._wake_thread = None
