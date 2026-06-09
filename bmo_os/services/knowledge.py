"""Segundo Cérebro do Bimo — grafo de conhecimento das notas Obsidian.

Lê os .md espelhados do Drive (Bimo/Conhecimento -> knowledge/ do perfil,
via drive_sync) e monta o grafo no estilo Obsidian:
    nó     = uma nota (.md)
    aresta = um [[wikilink]] de uma nota pra outra
    ghost  = alvo de link que (ainda) não tem arquivo — aparece apagadinho

O parse é leve (regex, sem dependência) e cacheado por assinatura da pasta
(qtd de arquivos + mtimes): scan() pode ser chamado todo frame que só
reprocessa quando algo mudou no disco — ex: o drive_sync acabou de baixar
notas novas.

É a fundação do RAG local (V3): por ora alimenta a tela CEREBRO
(visualização do grafo); depois os mesmos nós viram chunks da base vetorial.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

# [[Alvo]], [[Alvo|apelido]], [[Alvo#secao]] — captura só o Alvo
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:[#\|][^\]]*)?\]\]")
# #tag no meio do texto (evita # de heading markdown exigindo não-espaço depois)
TAG_RE = re.compile(r"(?:^|\s)#([\w\-/]+)", re.UNICODE)
MAX_PREVIEW_LINES = 3


@dataclass
class Note:
    id: str                 # stem minúsculo (chave do grafo)
    title: str              # nome do arquivo sem .md
    path: Path
    mtime: float
    links: set = field(default_factory=set)    # ids de notas alvo
    tags: list = field(default_factory=list)
    preview: list = field(default_factory=list)  # primeiras linhas de texto


@dataclass
class Graph:
    notes: dict             # id -> Note
    edges: list             # (id_origem, id_alvo) — só entre notas existentes
    ghosts: set             # ids linkados sem arquivo correspondente

    @property
    def empty(self) -> bool:
        return not self.notes

    def degree(self, nid: str) -> int:
        d = 0
        for a, b in self.edges:
            if a == nid or b == nid:
                d += 1
        return d


def _parse_note(path: Path) -> Note:
    note = Note(id=path.stem.lower(), title=path.stem, path=path,
                mtime=path.stat().st_mtime)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return note
    note.links = {m.group(1).strip().lower()
                  for m in WIKILINK_RE.finditer(text) if m.group(1).strip()}
    note.links.discard(note.id)   # auto-link não vira aresta
    seen: list = []
    for m in TAG_RE.finditer(text):
        t = m.group(1).lower()
        if t not in seen:
            seen.append(t)
    note.tags = seen[:6]
    # preview: primeiras linhas "de verdade" (pula frontmatter/headings vazios)
    lines = []
    in_front = False
    for i, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if i == 0 and line == "---":
            in_front = True
            continue
        if in_front:
            if line == "---":
                in_front = False
            continue
        if not line or line.startswith("#") and not line.lstrip("#").strip():
            continue
        lines.append(line)
        if len(lines) >= MAX_PREVIEW_LINES:
            break
    note.preview = lines
    return note


class KnowledgeService:
    def __init__(self, knowledge_dir: Path) -> None:
        self.dir = Path(knowledge_dir)
        self._lock = threading.Lock()
        self._sig: tuple = ()
        self._graph = Graph(notes={}, edges=[], ghosts=set())

    def _signature(self, files: list[Path]) -> tuple:
        try:
            return tuple(sorted((f.name, f.stat().st_mtime) for f in files))
        except OSError:
            return ()

    def scan(self) -> Graph:
        """Grafo atual (cacheado; re-parseia só quando a pasta mudou)."""
        try:
            files = [f for f in self.dir.glob("*.md") if f.is_file()]
        except OSError:
            files = []
        sig = self._signature(files)
        with self._lock:
            if sig == self._sig:
                return self._graph
        notes = {}
        for f in files:
            try:
                n = _parse_note(f)
                notes[n.id] = n
            except Exception:
                continue
        edges, ghosts = [], set()
        for n in notes.values():
            for target in n.links:
                if target in notes:
                    edges.append((n.id, target))
                else:
                    ghosts.add(target)
        graph = Graph(notes=notes, edges=edges, ghosts=ghosts)
        with self._lock:
            self._sig = sig
            self._graph = graph
        return graph
