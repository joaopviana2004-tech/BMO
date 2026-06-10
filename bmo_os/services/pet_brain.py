"""Cérebro proativo do BMO — decide quando ele fala SOZINHO.

Hoje o BMO só responde quando chamado. Aqui ele ganha iniciativa: a cada tick
(chamado pelo frame_hook do main, já no main thread) olha os sinais disponíveis
e, com PARCIMÔNIA (cooldowns), devolve uma falinha — ou None.

Modularidade: recebe pet_state + (opcionalmente) sysinfo/calendar/todoist e lê
todos DEFENSIVAMENTE (getattr/try). Sem nenhum serviço, ele ainda solta as
falinhas baseadas em humor/horário. Câmera/mic não são requisitos.

O main é quem decide SE é hora de ouvir (tela ambiente, BMO não ocupado); este
módulo decide só O QUE dizer e respeita os intervalos pra não cansar.
"""
from __future__ import annotations

import datetime as dt
import random
import time

from . import pet_state as ps

# Intervalo mínimo entre QUALQUER duas falas espontâneas (segundos) + jitter.
GLOBAL_GAP_S = 110.0
GLOBAL_JITTER_S = 70.0

# Falinhas de "tempero" — comentários soltos, tom de parceiro, sem motivo específico.
FLAVOR_LINES = [
    "Sistemas estáveis. Uptime impecável, modéstia à parte.",
    "Tava aqui pensando... cache é só memória com ego.",
    "Se precisar de mim, é só falar. Ou digitar do PC, agora dá.",
    "Dia bom pra refatorar alguma coisa, hein.",
    "Rodando a trinta frames e zero arrependimentos.",
    "Backlog não se resolve sozinho, só avisando.",
]

GREET_BACK = ["Voltou. Bom timing.", "Aí sim. Retomamos de onde paramos?",
              "Opa, presença detectada.", "De volta ao posto."]
LONELY_LINES = ["Movimento zero por aqui. Tudo certo aí?",
                "Modo idle faz tempo. Quer fazer alguma coisa?",
                "Sem interação há um tempo. Topa um jogo rápido?"]
HOT_LINES = ["CPU passando dos setenta graus. Fica de olho.",
             "Tô esquentando aqui. Throttle à vista se continuar.",
             "Temperatura subindo. Nada crítico ainda, mas avisei."]


class PetBrain:
    def __init__(self, pet_state, sysinfo=None, calendar=None, todoist=None) -> None:
        self.pet = pet_state
        self.sysinfo = sysinfo
        self.calendar = calendar
        self.todoist = todoist
        self._last_any = 0.0
        self._next_gap = GLOBAL_GAP_S
        self._last: dict[str, float] = {}     # cooldown por chave
        self._daily: dict[str, str] = {}      # chaves "uma vez por dia"
        # começa "aquecido": não fala nos primeiros segundos de boot
        self._last_any = time.time()

    # ---------- helpers de cooldown ----------

    def _cool(self, key: str, secs: float) -> bool:
        """True se a chave já pode falar de novo (respeitando o cooldown dela)."""
        return time.time() - self._last.get(key, 0.0) >= secs

    def _once_today(self, key: str) -> bool:
        return self._daily.get(key) != dt.date.today().isoformat()

    def _fire(self, key: str, phrase: str, *, daily: bool = False) -> str:
        now = time.time()
        self._last[key] = now
        self._last_any = now
        self._next_gap = GLOBAL_GAP_S + random.uniform(0, GLOBAL_JITTER_S)
        if daily:
            self._daily[key] = dt.date.today().isoformat()
        return phrase

    # ---------- decisão ----------

    def tick(self) -> str | None:
        """Devolve uma falinha pra dizer agora, ou None. Chamar todo frame."""
        now = time.time()
        if now - self._last_any < self._next_gap:
            return None

        snap = None
        try:
            snap = self.pet.get() if self.pet is not None else None
        except Exception:
            snap = None

        # 1) Alguém ACABOU de chegar (só com câmera) — prioridade máxima.
        if snap is not None and getattr(snap, "just_arrived", False):
            if self._cool("greet", 90):
                return self._fire("greet", random.choice(GREET_BACK))

        # 2) CPU quente (só faz sentido com sysinfo real; no PC temp=None).
        temp = self._temp_c()
        if temp is not None and temp >= 72.0 and self._cool("hot", 1200):
            return self._fire("hot", random.choice(HOT_LINES))

        # 3) Agenda do dia — comenta UMA vez por dia se há compromissos.
        n_ev = self._events_today()
        if n_ev > 0 and self._once_today("agenda") and self._cool("agenda", 60):
            plural = "compromissos" if n_ev > 1 else "compromisso"
            return self._fire("agenda", f"Na agenda de hoje: {n_ev} {plural}.",
                              daily=True)

        # 4) Streak de convívio — uma vez por dia, se 3+ dias seguidos.
        streak = getattr(snap, "streak", 0) if snap else 0
        if streak >= 3 and self._once_today("streak") and self._cool("streak", 60):
            return self._fire("streak",
                              f"{streak} dias seguidos de atividade. Consistência boa.",
                              daily=True)

        # 5) Tarefas esperando no quadro.
        n_todo = self._todo_count()
        if n_todo >= 3 and self._cool("tasks", 1800):
            return self._fire("tasks", "O quadro tem tarefa acumulando. Só dizendo.")

        # 6) Carente/entediado — só fala se há alguém (câmera) OU de vez em quando.
        mood = getattr(snap, "mood", "") if snap else ""
        present = getattr(snap, "present", False) if snap else False
        if mood in (ps.MOOD_LONELY, ps.MOOD_BORED) and self._cool("lonely", 600):
            if present or random.random() < 0.3:
                return self._fire("lonely", random.choice(LONELY_LINES))

        # 7) Tempero aleatório — baixinha frequência, mais quando animado.
        excited = mood == ps.MOOD_EXCITED
        chance = 0.05 if excited else 0.02
        if self._cool("flavor", 300) and random.random() < chance:
            return self._fire("flavor", random.choice(FLAVOR_LINES))

        return None

    # ---------- leitura defensiva dos serviços ----------

    def _temp_c(self):
        try:
            snap = self.sysinfo.get()
            return getattr(snap, "temp_c", None)
        except Exception:
            return None

    def _events_today(self) -> int:
        try:
            snap = self.calendar.get()
            if not getattr(snap, "ok", False):
                return 0
            return len(getattr(snap, "events", []) or [])
        except Exception:
            return 0

    def _todo_count(self) -> int:
        try:
            snap = self.todoist.get()
            if not getattr(snap, "ok", False):
                return 0
            return sum(1 for t in getattr(snap, "tasks", []) or []
                       if getattr(t, "section_key", "") in ("to-do", "doing"))
        except Exception:
            return 0
