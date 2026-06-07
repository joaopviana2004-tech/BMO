"""Estado emocional do BMO — o que o torna um *pet* e não só uma interface.

Serviço daemon (igual weather/todoist) que mantém HUMOR, ENERGIA, AFETO e
STREAK de convívio. Tudo derivado de sinais que SEMPRE existem (hora do dia,
ociosidade, toques na tela) — nada aqui depende de câmera ou microfone. A
presença por câmera (`note_presence`) é um BÔNUS opcional: se não houver
câmera, o pet continua vivo normalmente.

Persistência leve em `bmo_pet.json` (raiz do repo, gitignored): só o que faz
sentido sobreviver ao reboot (afeto, streak, último dia visto, total de toques).
Energia/humor são voláteis (recalculados a cada tick).

Uso:
    pet = PetState()
    pet.touch("pet")          # registrou um carinho
    snap = pet.get()          # snapshot thread-safe (mood, energy, affection...)
    pet.note_presence(True)   # OPCIONAL: a câmera viu alguém
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass

from ..core import config

PET_PATH = config.REPO_ROOT / "bmo_pet.json"

# Humores possíveis (lidos pela face pra escolher expressão/ritmo).
MOOD_LOVING = "loving"     # acabou de receber carinho
MOOD_EXCITED = "excited"   # animado (alta energia + interação recente)
MOOD_HAPPY = "happy"       # padrão de bom humor
MOOD_SLEEPY = "sleepy"     # madrugada / pouca energia
MOOD_LONELY = "lonely"     # faz um tempinho que ninguém aparece
MOOD_BORED = "bored"       # faz MUITO tempo sem interação
MOOD_NEUTRAL = "neutral"

# Quanto cada tipo de toque soma de afeto (com retorno decrescente — ver _bump).
TOUCH_AFFECTION = {
    "pet": 3.0,        # cafuné (toques rápidos)
    "tickle": 2.5,     # cócegas (arrasto rápido)
    "talk": 2.0,       # conversou com o BMO (voz/chat)
    "feed": 4.0,       # alimentou/brincou
    "tap": 1.0,        # toque simples
    "poke": -0.5,      # cutucou demais (leve incômodo, nunca pune de verdade)
}

# Janelas de tempo (segundos) que classificam a ociosidade.
LONELY_AFTER_S = 240.0     # 4 min sem interação -> carente
BORED_AFTER_S = 900.0      # 15 min -> entediado
LOVING_WINDOW_S = 6.0      # carinho recente mantém o humor "amoroso"
EXCITED_WINDOW_S = 45.0    # interação recente + energia alta -> animado

AFFECTION_MAX = 100.0
# Decaimento gentil de afeto por dia SEM aparecer (sem punição agressiva).
AFFECTION_DECAY_PER_DAY = 4.0


@dataclass
class PetSnapshot:
    mood: str = MOOD_HAPPY
    energy: float = 0.7         # 0..1 (função do horário + interação)
    affection: float = 30.0     # 0..100 (persistido)
    streak: int = 0             # dias seguidos de convívio
    idle_s: float = 0.0         # segundos desde a última interação
    present: bool = False       # câmera viu alguém recentemente? (bônus)
    just_arrived: bool = False  # alguém ACABOU de chegar (sobe 1 tick)


def _energy_for_hour(hour: int) -> float:
    """Curva de energia ao longo do dia (sem hardware — só relógio)."""
    if hour < 6:
        return 0.18           # madrugada: sonolento
    if hour < 9:
        return 0.55           # acordando
    if hour < 12:
        return 0.92           # manhã a todo vapor
    if hour < 14:
        return 0.7            # pós-almoço
    if hour < 19:
        return 0.85           # tarde
    if hour < 22:
        return 0.55           # noite
    return 0.3                # tarde da noite


class PetState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # --- persistido ---
        self._affection = 30.0
        self._streak = 0
        self._last_seen = ""        # ISO date da última interação registrada
        self._total_touches = 0
        self._load()

        # --- volátil ---
        self._last_interaction = time.time()
        self._last_touch_t = 0.0
        self._touch_boost = 0.0     # energia extra de uma interação recente (decai)
        self._present = False
        self._present_until = 0.0   # presença "expira" pra não ficar grudada
        self._just_arrived = False
        self._snapshot = PetSnapshot(affection=self._affection, streak=self._streak)

        self._dirty = False
        self._last_persist = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ---------- persistência ----------

    def _load(self) -> None:
        try:
            import json
            if PET_PATH.exists():
                data = json.loads(PET_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._affection = float(data.get("affection", 30.0))
                    self._streak = int(data.get("streak", 0))
                    self._last_seen = str(data.get("last_seen", ""))
                    self._total_touches = int(data.get("total_touches", 0))
                    self._decay_for_absence()
        except Exception:
            pass

    def _decay_for_absence(self) -> None:
        """Aplica o decaimento gentil de afeto por dias sem aparecer (no load)."""
        if not self._last_seen:
            return
        try:
            last = dt.date.fromisoformat(self._last_seen)
            days = (dt.date.today() - last).days
            if days > 1:
                self._affection = max(0.0, self._affection - AFFECTION_DECAY_PER_DAY * (days - 1))
        except Exception:
            pass

    def _persist_unlocked(self) -> None:
        try:
            import json
            PET_PATH.write_text(json.dumps({
                "affection": round(self._affection, 1),
                "streak": self._streak,
                "last_seen": self._last_seen,
                "total_touches": self._total_touches,
            }, indent=2), encoding="utf-8")
            self._dirty = False
        except Exception:
            pass

    # ---------- eventos de interação ----------

    def touch(self, kind: str = "tap") -> None:
        """Registra uma interação (toque/cafuné/conversa). Sobe afeto+energia."""
        with self._lock:
            now = time.time()
            self._last_interaction = now
            self._last_touch_t = now
            self._total_touches += 1
            self._touch_boost = min(0.35, self._touch_boost + 0.18)
            self._bump(TOUCH_AFFECTION.get(kind, 1.0))
            self._mark_day(now)
            self._dirty = True

    def feed(self) -> None:
        self.touch("feed")

    def note_presence(self, present: bool) -> None:
        """BÔNUS opcional: a câmera detectou (ou não) alguém. Sem câmera, nunca
        é chamado e o pet segue funcionando só com toque/relógio."""
        with self._lock:
            now = time.time()
            if present:
                # alguém apareceu depois de >20s ausente => "chegou agora"
                if not self._present and now > self._present_until + 20.0:
                    self._just_arrived = True
                    self._last_interaction = now   # presença conta como convívio
                    self._mark_day(now)
                    self._dirty = True
                self._present = True
                self._present_until = now + 4.0    # presença vale por 4s
            # ausência é resolvida no _loop ao expirar _present_until

    def _bump(self, delta: float) -> None:
        """Soma afeto com retorno decrescente (fica mais difícil perto do máximo)."""
        if delta >= 0:
            room = 1.0 - (self._affection / AFFECTION_MAX)
            self._affection = min(AFFECTION_MAX, self._affection + delta * max(0.15, room))
        else:
            self._affection = max(0.0, self._affection + delta)

    def _mark_day(self, now: float) -> None:
        """Atualiza streak no 1º contato do dia (chamado dentro do lock)."""
        today = dt.date.today().isoformat()
        if self._last_seen == today:
            return
        try:
            yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            if self._last_seen == yesterday:
                self._streak += 1
            else:
                self._streak = 1
        except Exception:
            self._streak = max(1, self._streak)
        self._last_seen = today

    # ---------- loop de recálculo ----------

    def _loop(self) -> None:
        while True:
            self._recompute()
            time.sleep(0.5)

    def _recompute(self) -> None:
        now = time.time()
        with self._lock:
            # presença expira
            if self._present and now > self._present_until:
                self._present = False
            # boost de energia decai suave
            self._touch_boost = max(0.0, self._touch_boost - 0.02)

            hour = time.localtime(now).tm_hour
            energy = min(1.0, _energy_for_hour(hour) + self._touch_boost)
            idle = now - self._last_interaction
            since_touch = now - self._last_touch_t

            mood = self._classify(energy, idle, since_touch)

            just = self._just_arrived
            self._just_arrived = False

            self._snapshot = PetSnapshot(
                mood=mood, energy=energy, affection=self._affection,
                streak=self._streak, idle_s=idle, present=self._present,
                just_arrived=just,
            )

            # persiste no máximo a cada 20s quando há algo novo
            if self._dirty and now - self._last_persist > 20.0:
                self._persist_unlocked()
                self._last_persist = now

    def _classify(self, energy: float, idle: float, since_touch: float) -> str:
        if since_touch < LOVING_WINDOW_S:
            return MOOD_LOVING
        if energy < 0.3:
            return MOOD_SLEEPY
        if idle > BORED_AFTER_S:
            return MOOD_BORED
        if idle > LONELY_AFTER_S:
            return MOOD_LONELY
        if energy > 0.75 and since_touch < EXCITED_WINDOW_S:
            return MOOD_EXCITED
        if self._present:
            return MOOD_HAPPY
        return MOOD_HAPPY if energy >= 0.5 else MOOD_NEUTRAL

    # ---------- acesso ----------

    def get(self) -> PetSnapshot:
        with self._lock:
            return self._snapshot

    def flush(self) -> None:
        """Força gravação (chamar antes de restart/execv pra não perder afeto)."""
        with self._lock:
            if self._dirty:
                self._persist_unlocked()
