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
import unicodedata
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

    # ---------- busca (tool notes_query do chat / futuro RAG) ----------

    @staticmethod
    def _fold(s: str) -> str:
        """minúsculas sem acento — busca tolerante a acentuação."""
        nfkd = unicodedata.normalize("NFKD", s.lower())
        return "".join(c for c in nfkd if not unicodedata.combining(c))

    def search(self, query: str, k: int = 3, snippet_chars: int = 600) -> list[dict]:
        """Busca por palavras-chave nas notas: título (peso 4), tags (3) e
        conteúdo (1 por ocorrência, com teto). Sem embeddings de propósito —
        roda em milissegundos na rasp e não depende de nada externo.

        Retorna [{title, tags, snippet}] das k melhores notas; snippet é a
        janela de texto em volta do primeiro termo achado."""
        graph = self.scan()
        terms = [t for t in re.split(r"\W+", self._fold(query)) if len(t) >= 3]
        if not terms or graph.empty:
            return []
        scored = []
        for note in graph.notes.values():
            try:
                text = note.path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            folded = self._fold(text)
            title = self._fold(note.title)
            tags = [self._fold(t) for t in note.tags]
            score = 0.0
            first_hit = -1
            for term in terms:
                if term in title:
                    score += 4.0
                if any(term in tg for tg in tags):
                    score += 3.0
                n = folded.count(term)
                if n:
                    score += min(n, 6)   # teto: nota gigante não domina tudo
                    pos = folded.find(term)
                    if first_hit < 0 or pos < first_hit:
                        first_hit = pos
            if score <= 0:
                continue
            start = max(0, (first_hit if first_hit >= 0 else 0) - snippet_chars // 3)
            snippet = " ".join(text[start:start + snippet_chars].split())
            scored.append((score, {"title": note.title, "tags": note.tags,
                                   "snippet": snippet}))
        scored.sort(key=lambda x: -x[0])
        return [hit for _, hit in scored[:k]]
