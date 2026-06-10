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

É a fundação do RAG local (V3): alimenta a tela CEREBRO, o RAG do chat e a
tool notes_write (o agente pode criar/atualizar notas aqui; o drive_sync
sobe pro Drive e o bimo_pc_sync.py puxa pro Obsidian do PC).

Escrita pelo agente: create | append | replace — arquivos .md achatados na
pasta do perfil (mesmo esquema do espelho Drive/Obsidian).
"""
from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# caracteres proibidos em nome de arquivo (Windows/Linux)
_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

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

    # palavras vazias do português coloquial: sobram só termos com conteúdo
    # (nomes curtos como "JP" passam — por isso o mínimo é 2 letras + stoplist)
    _STOPWORDS = {
        "a", "o", "e", "é", "as", "os", "ai", "la", "ne", "eh", "ta", "to",
        "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
        "um", "uma", "uns", "umas", "que", "quem", "qual", "quais", "como",
        "onde", "quando", "por", "pra", "para", "pro", "com", "sem", "sobre",
        "ele", "ela", "eles", "elas", "eu", "voce", "vc", "tu", "nos",
        "meu", "minha", "meus", "minhas", "seu", "sua", "seus", "suas",
        "me", "te", "se", "lhe", "ja", "nao", "sim", "mais", "menos",
        "muito", "pouco", "tem", "tenho", "faz", "fazer", "ser", "estar",
        "foi", "era", "sao", "esta", "estao", "oi", "ola", "oq", "obrigado",
        "tudo", "bem", "bom", "boa", "dia", "tarde", "noite", "hoje",
        "anotei", "anotou", "escrevi", "nota", "notas", "fala", "diz",
        "sabe", "conhece", "lembra", "coisa", "coisas", "ent", "dai",
    }

    @staticmethod
    def _fold(s: str) -> str:
        """minúsculas sem acento — busca tolerante a acentuação."""
        nfkd = unicodedata.normalize("NFKD", s.lower())
        return "".join(c for c in nfkd if not unicodedata.combining(c))

    def search(self, query: str, k: int = 3, snippet_chars: int = 600) -> list[dict]:
        """Busca por palavras-chave nas notas: título (peso 4), tags (3) e
        conteúdo (1 por ocorrência, com teto). Sem embeddings de propósito —
        roda em milissegundos na rasp e não depende de nada externo.

        Retorna [{title, tags, snippet, score}] das k melhores notas; snippet
        é a janela de texto em volta do primeiro termo achado. score >= 4
        significa que bateu em título ou tag (match forte)."""
        graph = self.scan()
        terms = [t for t in re.split(r"\W+", self._fold(query))
                 if len(t) >= 2 and t not in self._STOPWORDS]
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
                                   "snippet": snippet, "score": score}))
        scored.sort(key=lambda x: -x[0])
        return [hit for _, hit in scored[:k]]

    # ---------- escrita (tool notes_write do chat) ----------

    @staticmethod
    def _safe_filename(title: str) -> str:
        """Título -> nome de arquivo .md seguro (achatado, estilo Obsidian)."""
        name = _UNSAFE_NAME_RE.sub("", (title or "").strip())
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            name = "Nota"
        if name.lower().endswith(".md"):
            name = name[:-3].strip() or "Nota"
        if len(name) > 100:
            name = name[:100].strip()
        return f"{name}.md"

    def _find_path(self, title: str) -> Path | None:
        """Acha o .md pelo título (case-insensitive no stem)."""
        want = self._safe_filename(title).lower()
        stem = want[:-3] if want.endswith(".md") else want
        try:
            for p in self.dir.glob("*.md"):
                if p.stem.lower() == stem:
                    return p
        except OSError:
            pass
        return None

    def read_full(self, title: str) -> str:
        """Conteúdo integral de uma nota (pra append/replace informado)."""
        path = self._find_path(title)
        if path is None:
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    def write(self, title: str, body: str, *, mode: str = "create") -> dict:
        """Grava nota local. mode: create | append | replace.

        Retorna {ok, title, path, error?}. Invalida o cache do grafo."""
        mode = (mode or "create").strip().lower()
        if mode not in ("create", "append", "replace"):
            return {"ok": False, "error": f"mode invalido: {mode}"}
        fname = self._safe_filename(title)
        display = fname[:-3] if fname.lower().endswith(".md") else fname
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._find_path(title) or (self.dir / fname)
        body = (body or "").rstrip()
        if mode == "create" and path.exists():
            return {"ok": False, "error": f"nota ja existe: {display}"}
        if mode == "append":
            if path.exists():
                try:
                    old = path.read_text(encoding="utf-8", errors="ignore").rstrip()
                except OSError:
                    old = ""
                body = f"{old}\n\n{body}".strip() if old else body
            elif not body.strip():
                return {"ok": False, "error": "nota nao existe p/ append"}
        elif mode == "replace" and not path.exists():
            # replace em nota inexistente = create
            pass
        if not body.strip() and mode != "replace":
            return {"ok": False, "error": "conteudo vazio"}
        try:
            path.write_text(body + "\n", encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": str(e)[:80]}
        with self._lock:
            self._sig = ()   # força re-scan do grafo
        return {"ok": True, "title": path.stem, "path": path}
