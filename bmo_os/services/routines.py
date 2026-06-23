"""Leitor das rotinas/obrigações recorrentes — notas Obsidian `Rotinas*.md`.

A fonte da verdade das rotinas é uma (ou várias) nota(s) no Segundo Cérebro
(`knowledge/`, sincado do Obsidian). Cada linha é uma obrigação recorrente:

    - <quando> | <antecedência> | <texto> | #area

Exemplos:
    - toda quarta,domingo | véspera | Definir escala de mídia | #igreja
    - todo dia 5 | 3 dias antes | Fechar relatório da secretaria | #secretaria
    - toda sexta | no dia | Enviar status da semana | #trabalho

Campos:
  <quando>        dias da semana (seg,ter,qua,qui,sex,sab,dom — aceita por
                  extenso) OU "dia N" (do mês) OU "todo dia".
  <antecedência>  quando avisar relativo à ocorrência: "no dia" | "véspera" |
                  "N dias antes". (uma hora tipo "véspera 19h" é só uma dica.)
  <texto>         o que lembrar / título da task a criar.
  #area           igreja | trabalho | secretaria | hobby... (cai pro nome do
                  arquivo se omitido: "Rotinas - Igreja.md" -> igreja)

Parser leve (sem dependência). O motor só LÊ aqui; criar/editar rotina
conversando vem numa fase seguinte.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

WEEKDAYS = {
    "seg": 0, "segunda": 0, "ter": 1, "terca": 1, "terça": 1,
    "qua": 2, "quarta": 2, "qui": 3, "quinta": 3, "sex": 4, "sexta": 4,
    "sab": 5, "sabado": 5, "sábado": 5, "dom": 6, "domingo": 6,
}


class Routine:
    def __init__(self, when_pred, antec, text, area, time_hint, raw):
        self.when = when_pred      # (date) -> bool: a obrigação ocorre nesse dia?
        self.antec = antec         # dias de antecedência do aviso
        self.text = text
        self.area = area
        self.time_hint = time_hint
        self.raw = raw
        self.key = re.sub(r"\W+", "", (text + area).lower())[:48]


def _parse_when(spec: str):
    """<quando> -> predicado(date)->bool, ou None se não entender."""
    s = spec.strip().lower()
    # "dia N" do mês — tem prioridade (ex.: "dia 5", "todo dia 5" = mensal no 5)
    m = re.search(r"\bdia\s+(\d{1,2})\b", s)
    if m:
        n = int(m.group(1))
        return lambda d: d.day == n
    # "todo dia" SEM número = diário
    if "todo dia" in s or s in ("diario", "diária", "diaria", "diariamente"):
        return lambda d: True
    days = set()
    for tok in re.split(r"[,\s/&]+|\be\b", s):
        tok = tok.strip()
        if tok in WEEKDAYS:
            days.add(WEEKDAYS[tok])
    if days:
        return lambda d: d.weekday() in days
    return None


def _parse_antec(spec: str) -> int:
    s = spec.strip().lower()
    m = re.search(r"(\d+)\s*dias?\s*antes", s)
    if m:
        return int(m.group(1))
    if "véspera" in s or "vespera" in s:
        return 1
    return 0   # "no dia" / vazio


def _area_from_filename(stem: str) -> str:
    m = re.search(r"rotinas?\s*[-–—:]\s*(\w+)", stem.lower())
    return m.group(1) if m else ""


def load_routines(knowledge_dir) -> list[Routine]:
    """Lê todas as notas `Rotina*.md` da pasta do cérebro e devolve as regras."""
    out: list[Routine] = []
    try:
        files = [f for f in Path(knowledge_dir).glob("*.md")
                 if f.stem.lower().startswith("rotina")]
    except Exception:
        return out
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        area_default = _area_from_filename(f.stem)
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith(("-", "*")):
                continue
            body = line[1:].strip()
            parts = [p.strip() for p in body.split("|")]
            if len(parts) < 2 or not parts[0]:
                continue
            when_pred = _parse_when(parts[0])
            if when_pred is None:
                continue
            rest = parts[1:]
            area = area_default
            if rest and rest[-1].startswith("#"):
                area = rest[-1].lstrip("#").strip().lower() or area_default
                rest = rest[:-1]
            if len(rest) >= 2:
                antec_spec, text_spec = rest[0], rest[1]
            elif len(rest) == 1:
                antec_spec, text_spec = "", rest[0]
            else:
                continue
            text_spec = text_spec.strip()
            if not text_spec:
                continue
            mt = re.search(r"\b(\d{1,2})\s*h\b", antec_spec)
            time_hint = (mt.group(0).replace(" ", "") if mt else "")
            out.append(Routine(when_pred, _parse_antec(antec_spec),
                               text_spec, area, time_hint, body))
    return out


def due_today(routines: list[Routine], today: dt.date | None = None) -> list[dict]:
    """Rotinas que devem DISPARAR hoje (dia-do-aviso = ocorrência - antecedência).

    Retorna [{text, area, occur, antec, time_hint, key}] — `occur` é a data ISO
    em que a obrigação acontece (hoje, amanhã, etc.)."""
    today = today or dt.date.today()
    out = []
    for r in routines:
        occur = today + dt.timedelta(days=r.antec)
        try:
            hit = bool(r.when(occur))
        except Exception:
            hit = False
        if hit:
            out.append({
                "text": r.text, "area": r.area, "occur": occur.isoformat(),
                "antec": r.antec, "time_hint": r.time_hint, "key": r.key,
            })
    return out
