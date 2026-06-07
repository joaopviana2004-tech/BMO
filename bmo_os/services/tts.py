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
import hashlib
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
    # pronúncia: "BMO" some na voz da Francisca (soletra/buga). Falamos "bimu".
    # Só afeta a FALA (o texto exibido na tela continua "BMO").
    text = re.sub(r"\bbmo\b", "bimu", text, flags=re.IGNORECASE)
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

# Prosódia (rate, pitch) por HUMOR do pet — aplicada SÓ na fala dinâmica (não
# cacheada), pra a voz combinar com o estado de espírito. None = usa o padrão.
MOOD_VOICE = {
    "excited": ("+30%", "+34Hz"),   # eletrico, agudo
    "loving":  ("+8%",  "+24Hz"),   # fofo
    "happy":   ("+15%", "+20Hz"),
    "lonely":  ("+4%",  "+12Hz"),
    "bored":   ("+0%",  "+8Hz"),
    "sleepy":  ("-10%", "+2Hz"),    # devagar, grave
}
# Players de MP3 externos (fallback se o mixer do pygame não decodificar MP3).
_MP3_PLAYERS = ["mpg123", "ffplay", "cvlc", "mpv"]

# ----- Cache de frases fixas (tocam direto do disco, sem rede = instantâneo) -----
# Só vale pro Edge (MP3). Pré-geradas em background no 1º boot e persistidas.
_CACHE_DIR = Path(__file__).resolve().parent.parent / "assets" / "voice_cache"

# Frase falada ao ABRIR cada tela (as telas referenciam pelo mesmo texto no
# atributo `voice_announce`). Com acento — o Edge é neural e pronuncia melhor.
# Chaves = as mesmas que a LLM devolve em "screen" (chat.SCREENS_DOC). Quando o
# usuário PEDE pra IA abrir a tela, o BMO fala esta frase (cacheada) no lugar da
# resposta verbosa da LLM.
SCREEN_PHRASES = {
    "agenda": "Aqui está a sua agenda!",
    "tarefas": "Aqui estão as suas tarefas!",
    "foco": "Hora de focar!",
    "sistema": "Aqui está o sistema!",
    "foto": "Modo câmera ativado!",
    "jogos": "Bora jogar!",
    "pong": "Bora de Pong!",
    "invaders": "Bora pro espaço!",
    "flappy": "Bora voar!",
    "snake": "Bora de cobrinha!",
    "configuracoes": "Aqui estão as configurações!",
    "relogio": "Aqui está o relógio!",
    "home": "Voltando pro início!",
    "atualizar": "Já volto, tô me atualizando!",
}

# Saudações (a do boot é escolhida por horário) e falinhas divertidas do BMO.
GREETINGS = ["Olá!", "Oi!", "Bom dia!", "Boa tarde!", "Boa noite!", "E aí, beleza?"]
FUN_LINES = ["Eu sou o bimu!", "Quem quer jogar videogame?", "Vamos nessa!",
             "Beleza!", "Toca aqui!", "Que demais!", "Tô pronto!"]
# Confirmações de ação (faladas automaticamente quando o BMO faz algo).
CONFIRMS = ["Tarefa criada com sucesso!", "Pronto!", "Feito!", "Anotado!"]

# Tudo que será pré-gerado/cacheado. Quanto mais, mais respostas instantâneas.
CACHE_PHRASES = GREETINGS + list(SCREEN_PHRASES.values()) + FUN_LINES + CONFIRMS

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

# Default = "edge" (voz Francisca, o que o usuário quer). NÃO é "auto" de
# propósito: assim, sem edge-tts instalado, a voz fica indisponível (erro claro
# na tela TESTE) em vez de cair calado no Piper/eSpeak (que soaria masculino).
# Pra usar Piper/eSpeak, defina BMO_TTS_BACKEND=piper|espeak|auto no .env.
BACKEND_PREF = os.environ.get("BMO_TTS_BACKEND", "edge").strip().lower()


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
        # fila guarda (texto_limpo, humor) — humor "" = voz padrão
        self._q: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._proc = None
        self._lock = threading.Lock()
        # frases conhecidas (já limpas) que ficam em cache no disco
        self._canon = {clean_for_tts(p, strip_accents=False) for p in CACHE_PHRASES}
        # estado da geração do cache (pra tela SETTINGS mostrar)
        self.cache_building = False
        self.cache_status = ""
        if self.available:
            threading.Thread(target=self._loop, daemon=True).start()
            if self.backend == "edge":
                # pré-gera (em background) as frases fixas que ainda não existem.
                # Roda a cada boot — então "Atualizar" (restart) já regenera/completa
                # o cache automaticamente (ex.: frases novas vindas no update).
                threading.Thread(target=self._build_cache, daemon=True).start()

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

    def speak(self, text: str, mood: str = "") -> None:
        """Enfileira uma fala (não bloqueia). Limpa o texto antes (sem emoji/
        markdown) pra o áudio sair certinho. No Edge mantém os acentos.
        `mood` (opcional) ajusta tom/velocidade — só vale pra fala dinâmica;
        frases fixas cacheadas ignoram (mantêm o cache estável)."""
        text = clean_for_tts(text, strip_accents=(self.backend != "edge"))
        if not text or not self.available:
            return
        # tts_volume=0 = mudo: nem sintetiza (economiza rede/CPU no Edge)
        if self._volume() <= 0.0:
            return
        self.last_text = text
        self._q.put((text, (mood or "").strip().lower()))

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
            item = self._q.get()
            text, mood = item if isinstance(item, tuple) else (item, "")
            self._speaking = True
            try:
                self._say(text, mood)
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

    # ---------- cache de frases fixas (edge) ----------

    def _cache_path(self, cleaned_text: str) -> Path:
        """Caminho do MP3 cacheado p/ um texto JÁ LIMPO. Chave inclui voz+ajustes,
        então mudar a voz/efeitos gera arquivos novos (não toca os antigos)."""
        key = f"{EDGE_VOICE}|{EDGE_RATE}|{EDGE_PITCH}|{EDGE_VOLUME}|{cleaned_text}"
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return _CACHE_DIR / f"{h}.mp3"

    def _synth_into(self, cleaned_text: str, dest: Path) -> bool:
        """Sintetiza (Edge) num temp e só então RENOMEIA pro destino — escrita
        atômica, pro cache nunca conter MP3 truncado (ex.: se o processo morrer)."""
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False
        fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="bmo_tts_", dir=str(dest.parent))
        os.close(fd)
        try:
            if self._synth_edge(cleaned_text, tmp) and os.path.getsize(tmp) > 64:
                os.replace(tmp, dest)
                return True
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        return False

    def _cleaned_phrases(self) -> list:
        seen, out = set(), []
        for p in CACHE_PHRASES:
            c = clean_for_tts(p, strip_accents=False)
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def cache_counts(self) -> tuple:
        """(quantas frases fixas já estão no cache, total). Só faz sentido no edge."""
        if self.backend != "edge":
            return (0, 0)
        phrases = self._cleaned_phrases()
        have = sum(1 for c in phrases
                   if self._cache_path(c).exists() and self._cache_path(c).stat().st_size > 64)
        return (have, len(phrases))

    def ensure_cache_async(self) -> None:
        """Dispara a geração das frases faltantes em background (botão SETTINGS)."""
        if self.backend != "edge" or self.cache_building:
            return
        threading.Thread(target=self._build_cache, daemon=True).start()

    def _build_cache(self) -> None:
        """Verifica e gera as frases fixas que faltam no cache (em background).
        Atualiza cache_status ('gerando i/n' -> 'ok have/total') pra UI mostrar."""
        if self.backend != "edge":
            return
        self.cache_building = True
        try:
            phrases = self._cleaned_phrases()
            total = len(phrases)
            for i, cleaned in enumerate(phrases, 1):
                path = self._cache_path(cleaned)
                if path.exists() and path.stat().st_size > 64:
                    continue
                self.cache_status = f"gerando {i}/{total}"
                try:
                    self._synth_into(cleaned, path)
                except Exception:
                    pass
            have, tot = self.cache_counts()
            self.cache_status = f"ok {have}/{tot}"
        finally:
            self.cache_building = False

    def _say(self, text: str, mood: str = "") -> None:
        # `text` já vem limpo do speak(). Edge usa cache de frases fixas; o resto
        # (e textos dinâmicos) sintetiza num temporário e apaga depois.
        if self.backend == "edge":
            self._say_edge(text, mood)
        else:
            self._say_file(text)

    def _say_edge(self, text: str, mood: str = "") -> None:
        path = self._cache_path(text)
        # 1) já cacheado: toca direto (instantâneo, sem rede) e NÃO apaga.
        # (Cache usa a prosódia PADRÃO — humor não muda frases fixas.)
        if path.exists() and path.stat().st_size > 64:
            self._play_mp3(str(path))
            return
        # 2) frase fixa ainda não cacheada: sintetiza DENTRO do cache (persiste)
        if text in self._canon:
            if self._synth_into(text, path):
                self._play_mp3(str(path))
            return
        # 3) texto dinâmico (resposta do LLM): temporário, toca e apaga.
        # Só aqui o humor colore a voz (rate/pitch).
        rate, pitch = MOOD_VOICE.get(mood, (None, None))
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="bmo_tts_")
            os.close(fd)
            if self._synth_edge(text, tmp, rate=rate, pitch=pitch) and os.path.getsize(tmp) > 64:
                self._play_mp3(tmp)
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except Exception:
                    pass

    def _say_file(self, text: str) -> None:
        # piper/espeak -> WAV temporário tocado pelo mixer do pygame
        path = None
        try:
            fd, path = tempfile.mkstemp(suffix=".wav", prefix="bmo_tts_")
            os.close(fd)
            if not self._synth(text, path) or os.path.getsize(path) <= 64:
                return
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
        """Toca o MP3 da voz pelo PRÓPRIO mixer do pygame (mixer.music) — mesmo
        device dos efeitos sonoros. Isso evita a disputa de ALSA que dava com um
        player externo (mpg123 abria um 2º handle: cortava o início da voz e
        derrubava os efeitos). Player externo fica só de fallback se o SDL_mixer
        não decodificar MP3. mixer.music reamostra sozinho (não precisa casar rate)."""
        if pygame.mixer.get_init():
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.set_volume(self._volume())
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.wait(30)
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass
                return
            except Exception:
                pass   # build do SDL_mixer sem MP3 -> tenta player externo
        self._play_external(path)

    def _play_external(self, path: str) -> bool:
        """Toca por um player externo (1º disponível), bloqueante. Aplica o
        tts_volume onde o player suporta (mpg123/ffplay). Retorna True se tocou."""
        vol = self._volume()   # 0.0-1.0
        for p in _MP3_PLAYERS:
            exe = shutil.which(p)
            if not exe:
                continue
            if p == "mpg123":   # -f: escala linear de volume (32768 = 100%)
                cmd = [exe, "-q", "-f", str(int(max(0.0, min(1.0, vol)) * 32768)), path]
            elif p == "ffplay":
                cmd = [exe, "-nodisp", "-autoexit", "-loglevel", "quiet",
                       "-volume", str(int(vol * 100)), path]
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
            return True
        return False

    def _synth(self, text: str, path: str) -> bool:
        """Gera o áudio no `path` (MP3 p/ edge, WAV p/ piper/espeak)."""
        if self.backend == "edge":
            return self._synth_edge(text, path)
        if self.backend == "piper":
            return self._synth_piper(text, path)
        if self.backend == "espeak":
            return self._synth_espeak(text, path)
        return False

    def _synth_edge(self, text: str, path: str, rate: str | None = None,
                    pitch: str | None = None) -> bool:
        """Edge TTS (voz Francisca) -> MP3. Roda o asyncio na thread do worker
        (que não tem event loop próprio, então asyncio.run é seguro).
        rate/pitch (opcionais) sobrescrevem o padrão — usados pela voz emocional."""
        if not HAS_EDGE:
            return False
        use_rate = rate or EDGE_RATE
        use_pitch = pitch or EDGE_PITCH
        try:
            async def _gen():
                comm = edge_tts.Communicate(
                    text, EDGE_VOICE, rate=use_rate, pitch=use_pitch, volume=EDGE_VOLUME)
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
