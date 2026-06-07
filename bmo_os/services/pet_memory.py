"""Memória do BMO — fatos sobre o usuário que sobrevivem entre conversas.

Sem isso o chat é *stateless*: o BMO esquece você a cada fala. Aqui guardamos
um nome e uns poucos fatos curtos ("gosta de café", "trabalha com X") num
`bmo_memory.json` (raiz, gitignored) e oferecemos um `summary()` que o chat
injeta no system prompt — é o que faz o BMO te chamar pelo nome e lembrar de
coisas suas.

Totalmente opcional e tolerante a falha: se o arquivo não existir/der erro,
tudo volta vazio e o chat funciona igual a antes.
"""
from __future__ import annotations

import json
import threading

from ..core import config

MEMORY_PATH = config.REPO_ROOT / "bmo_memory.json"

MAX_FACTS = 12          # teto de fatos (os mais novos ganham espaço dos antigos)
MAX_FACT_LEN = 80       # corta fatos muito longos (evita poluir o prompt)


class PetMemory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._name = ""
        self._facts: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            if MEMORY_PATH.exists():
                data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._name = str(data.get("name", "")).strip()
                    facts = data.get("facts", [])
                    if isinstance(facts, list):
                        self._facts = [str(f).strip()[:MAX_FACT_LEN]
                                       for f in facts if str(f).strip()][:MAX_FACTS]
        except Exception:
            pass

    def _persist_unlocked(self) -> None:
        try:
            MEMORY_PATH.write_text(json.dumps({
                "name": self._name,
                "facts": self._facts,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ---------- escrita ----------

    def set_name(self, name: str) -> None:
        name = (name or "").strip()[:40]
        if not name:
            return
        with self._lock:
            if name != self._name:
                self._name = name
                self._persist_unlocked()

    def add_facts(self, facts) -> None:
        """Adiciona fatos novos (lista de strings), deduplicando e respeitando o
        teto. Aceita também uma string única. Silencioso em qualquer erro."""
        if not facts:
            return
        if isinstance(facts, str):
            facts = [facts]
        changed = False
        with self._lock:
            existing_low = {f.lower() for f in self._facts}
            for raw in facts:
                f = str(raw).strip()[:MAX_FACT_LEN]
                if not f or f.lower() in existing_low:
                    continue
                self._facts.append(f)
                existing_low.add(f.lower())
                changed = True
            if len(self._facts) > MAX_FACTS:
                self._facts = self._facts[-MAX_FACTS:]
                changed = True
            if changed:
                self._persist_unlocked()

    def clear(self) -> None:
        with self._lock:
            self._name = ""
            self._facts = []
            self._persist_unlocked()

    # ---------- leitura ----------

    @property
    def name(self) -> str:
        with self._lock:
            return self._name

    def facts(self) -> list[str]:
        with self._lock:
            return list(self._facts)

    def summary(self) -> str:
        """Bloco curto pro system prompt do chat. "" quando não há nada."""
        with self._lock:
            if not self._name and not self._facts:
                return ""
            parts = []
            if self._name:
                parts.append(f"O nome do usuario e {self._name}.")
            if self._facts:
                parts.append("Coisas que voce sabe sobre ele: "
                             + "; ".join(self._facts) + ".")
            return " ".join(parts)
