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

import hashlib
import json
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ..core import config


def chunk_hash(text: str) -> str:
    """Hash curto do texto do chunk — chave de cache do embedding (build) e
    detecção de chunk alterado (runtime). Igual no builder e na Rasp."""
    return hashlib.sha1((text or "").encode("utf-8", "ignore")).hexdigest()[:16]

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
        # índice vetorial (RAG denso) — carregado de .rag_index/index.json,
        # gerado no PC e entregue à Rasp (ver vector_index.py / build_rag_index.py)
        self._vindex = None
        self._vindex_mtime = -1.0

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

    # ---------- helpers de busca (compartilhados léxico + híbrido) ----------

    def _terms(self, query: str) -> list[str]:
        return [t for t in re.split(r"\W+", self._fold(query))
                if len(t) >= 2 and t not in self._STOPWORDS]

    @staticmethod
    def _chunk_level() -> int:
        try:
            return int(config.get("rag_chunk_level"))
        except (TypeError, ValueError):
            return 2

    def _note_base(self, note: "Note", terms: list[str]) -> tuple[str, float]:
        """(título folded, bônus de nota) — título 4/termo, tags 3/termo."""
        ftitle = self._fold(note.title)
        ftags = [self._fold(t) for t in note.tags]
        base = 0.0
        for term in terms:
            if term in ftitle:
                base += 4.0
            if any(term in tg for tg in ftags):
                base += 3.0
        return ftitle, base

    def _chunk_score(self, ftitle: str, base: float, ftext: str, fsec: str,
                     terms: list[str]) -> tuple[float, int]:
        """Pontua 1 chunk. Termo FORA do título discrimina (peso 3x); bater no
        NOME da seção pesa 5x — senão a intro (que repete o título) ganha sempre.
        Retorna (score, posição do 1º termo no texto)."""
        score = base
        first = -1
        for term in terms:
            weight = 1.0 if term in ftitle else 3.0
            if fsec and term in fsec:
                score += 5.0 * weight
            n = ftext.count(term)
            if n:
                score += min(n, 5) * weight
                pos = ftext.find(term)
                if first < 0 or pos < first:
                    first = pos
        return score, first

    def _make_hit(self, note: "Note", section: str, text: str, score: float,
                  first: int, source: str, snippet_chars: int = 600) -> dict:
        start = max(0, (first if first >= 0 else 0) - snippet_chars // 3)
        snippet = " ".join(text[start:start + snippet_chars].split())
        return {"title": note.title, "section": section, "tags": note.tags,
                "snippet": snippet, "score": round(float(score), 1), "source": source}

    def _score_note(self, note: "Note", terms: list[str], level: int,
                    source: str = "lexico") -> dict | None:
        """Melhor chunk da nota pros termos (hit padrão) ou None."""
        try:
            text = note.path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        ftitle, base = self._note_base(note, terms)
        best = None
        for ch in chunk_markdown(text, level):
            score, first = self._chunk_score(
                ftitle, base, self._fold(ch["text"]), self._fold(ch["section"]), terms)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, ch["section"], ch["text"], first)
        if best is None:
            return None
        return self._make_hit(note, best[1], best[2], best[0], best[3], source)

    def search(self, query: str, k: int = 3) -> list[dict]:
        """Busca LÉXICA por chunk (palavra-chave): o melhor chunk de cada uma das
        k melhores notas, com `section`. Ver search_hybrid pra denso+grafo."""
        graph = self.scan()
        terms = self._terms(query)
        if not terms or graph.empty:
            return []
        level = self._chunk_level()
        hits = [h for h in (self._score_note(n, terms, level)
                            for n in graph.notes.values()) if h]
        hits.sort(key=lambda h: -h["score"])
        return hits[:k]

    # ---------- busca HÍBRIDA (vetorial + léxico + grafo) ----------

    def _load_vindex(self):
        """Carrega o índice vetorial de .rag_index/index.json (recarrega quando o
        arquivo muda — o PC manda um novo). None se não existe/corrompido."""
        path = self.dir / ".rag_index" / "index.json"
        try:
            mt = path.stat().st_mtime
        except OSError:
            self._vindex, self._vindex_mtime = None, -1.0
            return None
        if self._vindex is not None and mt == self._vindex_mtime:
            return self._vindex
        try:
            from .vector_index import VectorIndex
            d = json.loads(path.read_text(encoding="utf-8"))
            self._vindex = VectorIndex.from_dict(d)
        except Exception:  # noqa: BLE001
            self._vindex = None
        self._vindex_mtime = mt
        return self._vindex

    def _note_chunks_map(self, note: "Note") -> dict:
        """{seção: texto} dos chunks da nota (pra mapear hit denso -> texto)."""
        try:
            text = note.path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return {}
        m: dict = {}
        for ch in chunk_markdown(text, self._chunk_level()):
            m.setdefault(ch["section"], ch["text"])
        return m

    def _dense_search(self, query: str, terms: list[str], level: int, graph) -> list[dict]:
        vindex = self._load_vindex()
        if vindex is None or not vindex.ready:
            return []
        from . import embeddings
        qv = embeddings.embed_one(query)
        if not qv:
            return []
        out = []
        dense_k = int(config.get("rag_dense_k") or 6)
        for d in vindex.search(qv, k=dense_k):
            note = graph.notes.get(d["note_id"])
            if note is None:
                continue
            txt = self._note_chunks_map(note).get(d["section"])
            if txt is None:
                continue
            ftitle, base = self._note_base(note, terms)
            score, first = self._chunk_score(
                ftitle, base, self._fold(txt), self._fold(d["section"]), terms)
            hit = self._make_hit(note, d["section"], txt, score, first, "denso")
            hit["dense"] = float(d["score"])
            out.append(hit)
        return out

    @staticmethod
    def _hit_key(hit: dict) -> tuple:
        return (hit["title"].lower(), hit.get("section", ""))

    def _rrf(self, lists: list[list[dict]], c: int = 60) -> list[dict]:
        """Reciprocal Rank Fusion das listas (léxico + denso) por chunk."""
        agg: dict = {}
        for lst in lists:
            for rank, h in enumerate(lst):
                key = self._hit_key(h)
                rr = 1.0 / (c + rank)
                e = agg.get(key)
                if e is None:
                    agg[key] = {"hit": dict(h), "rrf": rr}
                else:
                    e["rrf"] += rr
                    hit = e["hit"]
                    if h.get("score", 0) > hit.get("score", 0):
                        hit["score"] = h["score"]
                    if h.get("dense", 0) > hit.get("dense", 0):
                        hit["dense"] = h.get("dense", 0)
                    if h.get("source") and hit.get("source") != h["source"]:
                        hit["source"] = "hibrido"
        out = []
        for e in agg.values():
            h = e["hit"]
            h["rrf"] = round(e["rrf"], 4)
            h.setdefault("dense", 0.0)
            out.append(h)
        out.sort(key=lambda h: -h["rrf"])
        return out

    def _graph_neighbors(self, seeds: list[dict], terms: list[str], level: int,
                         graph, max_add: int = 2) -> list[dict]:
        """Expansão de grafo: puxa o melhor chunk dos VIZINHOS ([[links]], 1 hop)
        das notas-semente — contexto relacional que vetor/léxico não dão."""
        if not seeds or int(config.get("rag_graph_hops") or 0) <= 0:
            return []
        adj: dict = {}
        for a, b in graph.edges:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        have = {self._hit_key(h) for h in seeds}
        seed_notes = [h["title"].lower() for h in seeds]
        added: list[dict] = []
        for nid in seed_notes:
            for nb in adj.get(nid, ()):
                note = graph.notes.get(nb)
                if note is None:
                    continue
                hit = self._score_note(note, terms, level, source="grafo")
                if hit is None or self._hit_key(hit) in have:
                    continue
                hit.setdefault("dense", 0.0)
                hit["rrf"] = 0.0
                have.add(self._hit_key(hit))
                added.append(hit)
                if len(added) >= max_add:
                    return added
        return added

    def search_hybrid(self, query: str, k: int = 3) -> list[dict]:
        """RAG híbrido: funde busca LÉXICA + DENSA (vetorial, cosseno) por RRF e
        EXPANDE pelo grafo de [[links]]. Cai pro léxico se faltar índice/endpoint
        de embedding. Cada hit ganha `score` (léxico), `dense` (cosseno 0-1),
        `source` (lexico|denso|hibrido|grafo) e `rrf`. Devolve k principais +
        alguns vizinhos de grafo como contexto extra."""
        graph = self.scan()
        terms = self._terms(query)
        if not terms or graph.empty:
            return []
        level = self._chunk_level()

        lex = [h for h in (self._score_note(n, terms, level)
                           for n in graph.notes.values()) if h]
        lex.sort(key=lambda h: -h["score"])
        lex = lex[:8]

        dense = self._dense_search(query, terms, level, graph) \
            if config.get("rag_hybrid") else []

        if not dense:
            for h in lex:
                h.setdefault("dense", 0.0)
            return lex[:k]

        fused = self._rrf([lex, dense])
        top = fused[:k]
        return top + self._graph_neighbors(top, terms, level, graph, max_add=2)

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
