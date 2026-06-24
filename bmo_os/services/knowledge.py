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

from ..core import config

# caracteres proibidos em nome de arquivo (Windows/Linux)
_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# [[Alvo]], [[Alvo|apelido]], [[Alvo#secao]] — captura só o Alvo
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:[#\|][^\]]*)?\]\]")
# #tag no meio do texto (evita # de heading markdown exigindo não-espaço depois)
TAG_RE = re.compile(r"(?:^|\s)#([\w\-/]+)", re.UNICODE)
MAX_PREVIEW_LINES = 3


def _strip_frontmatter(lines: list[str]) -> list[str]:
    """Remove o bloco --- ... --- do topo (frontmatter YAML do Obsidian)."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return lines[i + 1:]
    return lines


def chunk_markdown(text: str, level: int = 2) -> list[dict]:
    """Quebra o markdown em CHUNKS por headings do nível `level` (2 = "##").

    Cada chunk é a unidade de busca/RAG: {"section": titulo do heading,
    "text": corpo}. O trecho ANTES do 1º heading do nível vira um chunk de
    seção "" (intro). level <= 0 (ou nota sem headings desse nível) => 1 chunk
    com a nota inteira (comportamento antigo). Mantida em sincronia com a
    prévia do painel web (ChunkPreview no app.tsx)."""
    lines = _strip_frontmatter((text or "").splitlines())
    if level <= 0:
        body = "\n".join(lines).strip()
        return [{"section": "", "text": body}] if body else []
    prefix = "#" * level + " "      # "## " casa só o nível exato (### não bate)
    chunks: list[dict] = []
    section = ""
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body or section:
            chunks.append({"section": section, "text": body})

    for raw in lines:
        if raw.lstrip().startswith(prefix):
            flush()
            section = raw.lstrip()[level:].strip()
            buf = []
        else:
            buf.append(raw)
    flush()
    return chunks or [{"section": "", "text": "\n".join(lines).strip()}]


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
        """Busca por palavras-chave, agora no nível de CHUNK (seção "##").

        Cada nota é quebrada por `rag_chunk_level` (config) e cada chunk é
        pontuado: título da nota (4/termo), tags (3), nome da seção (2) e
        conteúdo do chunk (1 por ocorrência, com teto). Retorna o MELHOR chunk
        de cada uma das k melhores notas: [{title, section, tags, snippet,
        score}]. snippet = janela em volta do 1º termo DENTRO do chunk, então o
        que vai pro LLM é a seção certa (não a nota toda). score >= 4 = bateu em
        título/tag (match forte, usado pelo RAG automático). level 0 = nota
        inteira (1 chunk, section="")."""
        graph = self.scan()
        terms = [t for t in re.split(r"\W+", self._fold(query))
                 if len(t) >= 2 and t not in self._STOPWORDS]
        if not terms or graph.empty:
            return []
        try:
            level = int(config.get("rag_chunk_level"))
        except (TypeError, ValueError):
            level = 2
        scored = []
        for note in graph.notes.values():
            try:
                text = note.path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            title = self._fold(note.title)
            tags = [self._fold(t) for t in note.tags]
            base = 0.0
            for term in terms:
                if term in title:
                    base += 4.0
                if any(term in tg for tg in tags):
                    base += 3.0
            best = None   # (score, hit) — só o melhor chunk da nota
            for ch in chunk_markdown(text, level):
                folded = self._fold(ch["text"])
                fsec = self._fold(ch["section"])
                score = base
                first_hit = -1
                for term in terms:
                    # termo que NÃO está no título DISCRIMINA o chunk (ex.: "membros"
                    # numa nota "ADCR Bela Vista"); termo que já está no título é
                    # generico p/ a nota toda e não deve decidir QUAL chunk vence —
                    # senão o chunk de intro, que repete o título, ganha sempre.
                    weight = 1.0 if term in title else 3.0
                    if fsec and term in fsec:
                        score += 5.0 * weight   # bater no NOME da seção (heading) é forte
                    n = folded.count(term)
                    if n:
                        score += min(n, 5) * weight   # conteúdo (teto p/ repetição não dominar)
                        pos = folded.find(term)
                        if first_hit < 0 or pos < first_hit:
                            first_hit = pos
                if score <= 0:
                    continue
                start = max(0, (first_hit if first_hit >= 0 else 0) - snippet_chars // 3)
                snippet = " ".join(ch["text"][start:start + snippet_chars].split())
                if best is None or score > best[0]:
                    best = (score, {"title": note.title, "section": ch["section"],
                                    "tags": note.tags, "snippet": snippet,
                                    "score": score})
            if best is not None:
                scored.append(best)
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

    def delete(self, title: str) -> dict:
        """Apaga uma nota local pelo título OU id (stem). Retorna
        {ok, title, name, path, error?}. Invalida o cache do grafo. A exclusão
        no Drive é feita por quem chama (drive_sync.delete_note) pra a nota não
        voltar no próximo sync."""
        path = self._find_path(title)
        if path is None or not path.exists():
            return {"ok": False, "error": "nota nao encontrada"}
        name, stem = path.name, path.stem
        try:
            path.unlink()
        except OSError as e:
            return {"ok": False, "error": str(e)[:80]}
        with self._lock:
            self._sig = ()   # força re-scan do grafo
        return {"ok": True, "title": stem, "name": name, "path": path}

    def relink(self, old: str, new: str) -> dict:
        """Reaponta os [[old]] -> [[new]] em TODAS as notas (útil ao excluir/
        renomear um nó referenciado: quem apontava pro antigo passa a apontar
        pro novo). Preserva alias e seção ([[old|x]] -> [[new|x]]). Casa o alvo
        por id (case-insensitive). Retorna {ok, count, changed:[paths]}."""
        old_id = (old or "").strip().lower()
        if old_id.endswith(".md"):
            old_id = old_id[:-3]
        new_title = (new or "").strip()
        if not old_id or not new_title:
            return {"ok": False, "error": "old/new vazio"}
        link_re = re.compile(r"\[\[([^\]\|#]+)((?:[#\|][^\]]*)?)\]\]")

        def repl(m: "re.Match") -> str:
            if m.group(1).strip().lower() == old_id:
                return f"[[{new_title}{m.group(2) or ''}]]"
            return m.group(0)

        changed: list[Path] = []
        try:
            files = [f for f in self.dir.glob("*.md") if f.is_file()]
        except OSError:
            files = []
        for p in files:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            new_text = link_re.sub(repl, text)
            if new_text != text:
                try:
                    p.write_text(new_text, encoding="utf-8")
                    changed.append(p)
                except OSError:
                    pass
        with self._lock:
            self._sig = ()
        return {"ok": True, "count": len(changed), "changed": changed}
