"""Tela CEREBRO — visualização do grafo de conhecimento (Segundo Cérebro).

O "Oráculo Visual" do Melhorias_BMO.md: minimapa de nós interagíveis
mostrando como as notas do Obsidian se conectam. Estilo terminal/matrix
(verde sobre preto, fixo — não segue o tema claro/escuro de propósito).

- nó      = nota .md (raio cresce com o nº de conexões)
- linha   = [[wikilink]] entre notas
- fantasma= link pra nota que não existe (círculo vazado, apagado)

Layout força-dirigido rodando ao vivo (repulsão + molas + gravidade pro
centro): o grafo "respira" e se organiza sozinho na tela.

Controles (tudo sem botão, design minimalista):
- TAP num nó           seleciona / deseleciona
- ARRASTAR um nó       move ele (a física segue dali)
- ARRASTAR o vazio     desloca a câmera (pan)
- PINÇA (2 dedos)      zoom in/out (roda do mouse também, p/ dev no PC)
- 2 TOQUES num nó      SPLIT: esquerda o grafo centralizado no nó (mesma
                       escala), direita a nota inteira
- no painel da nota    toque em cima rola pra cima, embaixo rola pra baixo
- LEFT/RIGHT           cicla a seleção | A re-sincroniza | B/MENU volta
                       (no split, B fecha o split primeiro)
"""
from __future__ import annotations

import math
import random

import pygame

from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import SAFE_INSET, draw_scanlines, LOGICAL_SIZE
from ..services import audio

# paleta matrix fixa (independe do tema)
MX_BG = (3, 10, 5)
MX_BRIGHT = (110, 255, 140)
MX_MID = (50, 170, 85)
MX_DIM = (22, 80, 42)
MX_GHOST = (16, 55, 30)
MX_GLOW = (9, 34, 19)        # halo dos nós + contorno do cérebro (bem fraco)
MX_PULSE = (160, 255, 185)   # pacote de dados correndo na aresta
MX_CORE = (225, 255, 235)    # núcleo aceso do nó

MAX_NODES = 80          # acima disso, mostra os mais conectados
AREA_TOP = 30
AREA_BOTTOM = 36        # reserva do rodapé (info da nota)

# física do layout (Fruchterman–Reingold + separação mínima; k escala com nº de nós)
FR_K_SCALE = 1.28
FR_ATTRACT = 0.85
MIN_NODE_SEP = 26.0     # separação mínima dura entre nós (mundo) — anti-assaroca
GRAVITY = 0.05          # puxa pra um blob compacto/preenchido (a separação
                        # garante o mínimo, então pode ser forte sem amontoar)
DAMPING = 0.88
MAX_SPEED = 55.0
SETTLE_STEPS = 90

# interação
ZOOM_MIN, ZOOM_MAX = 0.5, 3.0
DOUBLE_TAP_S = 0.45     # janela do toque duplo
DRAG_PX = 7             # deslocamento mínimo pra virar arrasto (e não tap)
NOTE_SCROLL_LINES = 4   # linhas roladas por toque no painel da nota

W, H = LOGICAL_SIZE


def _to_logical(pos: tuple[int, int]) -> tuple[int, int]:
    """Converte coords da janela física pro canvas lógico 400x240."""
    w, h = pygame.display.get_window_size()
    if w <= 0 or h <= 0:
        return pos
    return (pos[0] * W // w, pos[1] * H // h)


class _Body:
    __slots__ = ("x", "y", "vx", "vy")

    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = x, y
        self.vx = self.vy = 0.0


class BrainScreen:
    voice_announce = "Segundo cérebro na tela."

    def __init__(self, *, on_back, knowledge, get_sync=None) -> None:
        self.on_back = on_back
        self.knowledge = knowledge
        self.get_sync = get_sync or (lambda: None)
        self._graph = None
        self._bodies: dict[str, _Body] = {}
        self._order: list[str] = []     # ids exibidos (estável p/ ciclar seleção)
        self._selected = ""
        self._t = 0.0
        self._scan_t = 0.0
        self._rng = random.Random(42)
        # câmera: ponto do MUNDO que fica no centro da viewport + zoom
        self._cam = [W / 2.0, (AREA_TOP + H - AREA_BOTTOM) / 2.0]
        self._zoom = 1.0
        # gesto de 1 dedo/mouse em andamento (drag de nó, pan ou tap)
        self._press: dict | None = None
        # pinça: dedos ativos {finger_id: (x, y)} e distância anterior
        self._fingers: dict[int, tuple[float, float]] = {}
        self._pinch_d: float | None = None
        # toque duplo
        self._last_tap_nid = ""
        self._last_tap_t = -10.0
        # split view (nota aberta à direita)
        self._split = ""                  # id da nota no painel ("" = fechado)
        self._note_lines: list[str] = []  # linhas já quebradas pro painel
        self._note_scroll = 0

    def enter(self) -> None:
        self._refresh(force=True)
        # abrir a tela já pede um espelho fresco do Drive (não bloqueia)
        sync = self.get_sync()
        if sync is not None:
            sync.request_knowledge_sync()

    def exit(self) -> None: ...

    # ---------- dados ----------

    def _refresh(self, force: bool = False) -> None:
        graph = self.knowledge.scan()
        if graph is self._graph and not force:
            return
        self._graph = graph
        ids = list(graph.notes.keys())
        # cap: mantém os nós mais conectados (hub do conhecimento)
        if len(ids) > MAX_NODES:
            ids.sort(key=graph.degree, reverse=True)
            ids = ids[:MAX_NODES]
        shown = set(ids)
        # fantasmas só dos nós exibidos (e só alguns, pra não poluir)
        ghosts = []
        for src, n in graph.notes.items():
            if src not in shown:
                continue
            for t in n.links:
                if t in graph.ghosts and t not in ghosts:
                    ghosts.append(t)
        ghosts = ghosts[: max(0, MAX_NODES - len(ids)) // 2]
        prev_n = len(self._order)
        self._order = ids + ghosts
        reshuffle = force or abs(len(self._order) - prev_n) >= 2
        self._seed_positions(respread=reshuffle)
        # remove corpos de nós que saíram
        for nid in list(self._bodies):
            if nid not in self._order:
                del self._bodies[nid]
        if reshuffle:
            self._settle_layout(SETTLE_STEPS)
            self._fit_view()
        if self._selected not in self._order:
            self._selected = ""
        if self._split and self._split not in graph.notes:
            self._close_split()

    def _shown_edges(self) -> list:
        g = self._graph
        if g is None:
            return []
        shown = set(self._order)
        out = []
        for a, b in g.edges:
            if a in shown and b in shown:
                out.append((a, b))
        for src, n in g.notes.items():
            if src not in shown:
                continue
            for t in n.links:
                if t in shown and t in g.ghosts:
                    out.append((src, t))
        return out

    # ---------- câmera (mundo <-> tela) ----------

    def _view_rect(self) -> pygame.Rect:
        """Viewport do grafo: tela toda, ou metade esquerda no split."""
        if self._split:
            return pygame.Rect(0, 0, W // 2, H)
        return pygame.Rect(0, 0, W, H)

    def _w2s(self, x: float, y: float) -> tuple[float, float]:
        vc = self._view_rect().center
        return ((x - self._cam[0]) * self._zoom + vc[0],
                (y - self._cam[1]) * self._zoom + vc[1])

    def _s2w(self, px: float, py: float) -> tuple[float, float]:
        vc = self._view_rect().center
        return ((px - vc[0]) / self._zoom + self._cam[0],
                (py - vc[1]) / self._zoom + self._cam[1])

    def _apply_zoom(self, factor: float, anchor: tuple[float, float]) -> None:
        """Zoom mantendo o ponto do mundo sob `anchor` (coords de tela) parado."""
        new = min(max(self._zoom * factor, ZOOM_MIN), ZOOM_MAX)
        if abs(new - self._zoom) < 1e-4:
            return
        wx, wy = self._s2w(*anchor)
        vc = self._view_rect().center
        self._zoom = new
        self._cam[0] = wx - (anchor[0] - vc[0]) / new
        self._cam[1] = wy - (anchor[1] - vc[1]) / new

    def _fit_view(self) -> None:
        """Enquadra todos os nós: câmera no centro da nuvem + zoom que cabe na
        viewport com margem (evita o grafo cramped/amontoado)."""
        bodies = [self._bodies[n] for n in self._order if n in self._bodies]
        if not bodies:
            return
        xs = [b.x for b in bodies]
        ys = [b.y for b in bodies]
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        gw = max(1.0, maxx - minx)
        gh = max(1.0, maxy - miny)
        view = self._view_rect()
        avail_w = view.width - 2 * (SAFE_INSET + 6)
        avail_h = (H - AREA_TOP - AREA_BOTTOM) - 2 * 6
        z = min(avail_w / gw, avail_h / gh)
        self._zoom = min(max(z, ZOOM_MIN), ZOOM_MAX)
        self._cam = [(minx + maxx) / 2.0, (miny + maxy) / 2.0]

    # ---------- split (nota à direita) ----------

    def _note_panel(self) -> pygame.Rect:
        return pygame.Rect(W // 2, 0, W - W // 2, H)

    def _open_split(self, nid: str) -> None:
        g = self._graph
        note = g.notes.get(nid) if g else None
        if note is None:
            return
        audio.play("select")
        self._split = nid
        self._selected = nid
        self._note_scroll = 0
        self._note_lines = self._load_note_lines(note)
        # centraliza o nó na metade esquerda SEM mexer na escala
        b = self._bodies.get(nid)
        if b is not None:
            self._cam = [b.x, b.y]

    def _close_split(self) -> None:
        self._split = ""
        self._note_lines = []
        self._note_scroll = 0
        # devolve a câmera pro centro do mundo na tela cheia
        self._cam = [W / 2.0, (AREA_TOP + H - AREA_BOTTOM) / 2.0]

    def _load_note_lines(self, note) -> list[str]:
        """Lê o .md inteiro e quebra em linhas que cabem no painel direito."""
        try:
            text = note.path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ["(nao consegui ler a nota)"]
        # tira frontmatter --- ... ---
        raw_lines = text.splitlines()
        if raw_lines and raw_lines[0].strip() == "---":
            for i in range(1, len(raw_lines)):
                if raw_lines[i].strip() == "---":
                    raw_lines = raw_lines[i + 1:]
                    break
        max_w = self._note_panel().width - 14   # padding + trilho do scroll
        out: list[str] = []
        for raw in raw_lines:
            line = raw.rstrip()
            if not line:
                if out and out[-1] != "":
                    out.append("")
                continue
            out.extend(self._wrap(line, max_w))
        while out and out[-1] == "":
            out.pop()
        return out or ["(nota vazia)"]

    @staticmethod
    def _wrap(line: str, max_w: int) -> list[str]:
        """Quebra por palavra medindo no font real (uma vez, ao abrir)."""
        words = line.split(" ")
        out, cur = [], ""
        for word in words:
            cand = f"{cur} {word}".strip()
            if render_text(cand, 8, MX_MID, pixel=False).get_width() <= max_w:
                cur = cand
                continue
            if cur:
                out.append(cur)
            # palavra maior que o painel: quebra na marra
            while render_text(word, 8, MX_MID, pixel=False).get_width() > max_w:
                lo, hi = 1, len(word)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if render_text(word[:mid], 8, MX_MID,
                                   pixel=False).get_width() <= max_w:
                        lo = mid
                    else:
                        hi = mid - 1
                out.append(word[:lo])
                word = word[lo:]
            cur = word
        if cur:
            out.append(cur)
        return out

    def _note_visible_lines(self) -> int:
        # painel: título (16px) + corpo até a borda
        return max(1, (H - SAFE_INSET * 2 - 18) // 11)

    def _scroll_note(self, direction: int) -> None:
        vis = self._note_visible_lines()
        max_off = max(0, len(self._note_lines) - vis)
        new = min(max(self._note_scroll + direction * NOTE_SCROLL_LINES, 0), max_off)
        if new != self._note_scroll:
            self._note_scroll = new
            audio.play("tick")

    # ---------- input ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == bmo_input.ACTION_EVENT:
            self._handle_action(event)
            return
        # ---- gestos raw: arrasto de nó, pan, pinça e zoom de scroll ----
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._press_down(_to_logical(event.pos))
        elif event.type == pygame.MOUSEMOTION:
            if self._press is not None and pygame.mouse.get_pressed()[0]:
                self._press_move(_to_logical(event.pos))
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._press_up()
        elif event.type == pygame.MOUSEWHEEL:
            anchor = _to_logical(pygame.mouse.get_pos())
            if self._view_rect().collidepoint(anchor):
                self._apply_zoom(1.15 if event.y > 0 else 1 / 1.15, anchor)
            elif self._split and self._note_panel().collidepoint(anchor):
                self._scroll_note(-1 if event.y > 0 else 1)
        elif event.type == pygame.FINGERDOWN:
            self._fingers[event.finger_id] = (event.x * W, event.y * H)
            if len(self._fingers) >= 2:
                self._press = None          # virou pinça: cancela drag/tap
                self._pinch_d = None
        elif event.type == pygame.FINGERMOTION:
            if event.finger_id in self._fingers:
                self._fingers[event.finger_id] = (event.x * W, event.y * H)
                self._update_pinch()
        elif event.type == pygame.FINGERUP:
            self._fingers.pop(event.finger_id, None)
            self._pinch_d = None

    def _handle_action(self, event) -> None:
        a = event.action
        if a in (bmo_input.Action.B, bmo_input.Action.MENU):
            audio.play("back")
            if self._split:
                self._close_split()
            else:
                self.on_back()
        elif a in (bmo_input.Action.LEFT, bmo_input.Action.RIGHT) and self._order:
            audio.play("tick")
            step = -1 if a == bmo_input.Action.LEFT else 1
            if self._selected in self._order:
                i = (self._order.index(self._selected) + step) % len(self._order)
            else:
                i = 0
            self._selected = self._order[i]
            if self._split and self._graph and self._selected in self._graph.notes:
                self._open_split(self._selected)
        elif a == bmo_input.Action.A:
            sync = self.get_sync()
            if sync is not None:
                audio.play("select")
                sync.request_knowledge_sync()
        elif a == bmo_input.Action.TAP and getattr(event, "pos", None):
            pos = event.pos
            if self._back_btn().collidepoint(pos):
                audio.play("back")
                if self._split:
                    self._close_split()
                else:
                    self.on_back()
            elif self._split and self._note_panel().collidepoint(pos):
                # metade de cima rola pra cima, de baixo pra baixo (sem botão)
                self._scroll_note(-1 if pos[1] < H // 2 else 1)
            # toques no grafo são tratados nos eventos raw (press/drag/duplo)

    def _node_at(self, pos: tuple[int, int]) -> str:
        """Nó sob o toque, em coords de TELA (área de toque cresce com o zoom)."""
        g = self._graph
        best, best_d = "", 1e9
        for nid in self._order:
            b = self._bodies.get(nid)
            if b is None:
                continue
            sx, sy = self._w2s(b.x, b.y)
            d = math.hypot(pos[0] - sx, pos[1] - sy)
            r_node = (3 + min(5, g.degree(nid))) if (g and nid in g.notes) else 3
            if d <= max(12.0, r_node * self._zoom + 8) and d < best_d:
                best, best_d = nid, d
        return best

    def _press_down(self, pos) -> None:
        if self._back_btn().collidepoint(pos):
            return                      # o ACTION TAP cuida do botão
        if len(self._fingers) >= 2:
            return                      # pinça em andamento
        if not self._view_rect().collidepoint(pos):
            return                      # painel da nota rola via ACTION TAP
        nid = self._node_at(pos)
        # toque duplo = segundo tap rápido no MESMO nó (decidido no soltar,
        # pra não atrapalhar quem seleciona e já arrasta)
        dbl = bool(nid and nid == self._last_tap_nid
                   and self._t - self._last_tap_t <= DOUBLE_TAP_S)
        self._press = {"pos": pos, "nid": nid, "moved": False, "dbl": dbl}

    def _press_move(self, pos) -> None:
        p = self._press
        if p is None:
            return
        if not p["moved"]:
            dx, dy = pos[0] - p["pos"][0], pos[1] - p["pos"][1]
            if dx * dx + dy * dy < DRAG_PX * DRAG_PX:
                return
            p["moved"] = True
        if p["nid"]:
            # arrasta o nó: ele segue o dedo (em coords do mundo)
            b = self._bodies.get(p["nid"])
            if b is not None:
                b.x, b.y = self._s2w(*pos)
                b.vx = b.vy = 0.0
        else:
            # arrasta o vazio: pan da câmera
            last = p["pos"]
            self._cam[0] -= (pos[0] - last[0]) / self._zoom
            self._cam[1] -= (pos[1] - last[1]) / self._zoom
        p["pos"] = pos

    def _press_up(self) -> None:
        p, self._press = self._press, None
        if p is None:
            return
        if p["moved"]:
            self._last_tap_nid = ""     # arrasto não conta como tap
            return
        nid = p["nid"]
        if not nid:
            self._last_tap_nid = ""
            return
        if p["dbl"] and self._graph and nid in self._graph.notes:
            self._last_tap_nid = ""
            self._open_split(nid)
            return
        # tap simples: seleciona/deseleciona e arma o relógio do duplo
        audio.play("tick")
        self._selected = "" if nid == self._selected else nid
        self._last_tap_nid, self._last_tap_t = nid, self._t

    def _update_pinch(self) -> None:
        if len(self._fingers) < 2:
            return
        pts = list(self._fingers.values())[:2]
        d = math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1])
        mid = ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2)
        if self._pinch_d is not None and self._pinch_d > 1.0:
            self._apply_zoom(d / self._pinch_d, mid)
        self._pinch_d = d

    # ---------- física ----------

    def _confine(self, b) -> None:
        """Mantém o corpo dentro de uma ELIPSE (em vez do retângulo): a nuvem
        de nós ganha formato oval/cérebro em vez de encostar nos cantos."""
        cx = W / 2.0
        cy = (AREA_TOP + H - AREA_BOTTOM) / 2.0
        rx = (W - 2 * (SAFE_INSET + 10)) / 2.0
        ry = (H - AREA_TOP - AREA_BOTTOM) / 2.0
        nx, ny = (b.x - cx) / rx, (b.y - cy) / ry
        m = math.hypot(nx, ny)
        if m > 1.0:
            b.x = cx + nx / m * rx
            b.y = cy + ny / m * ry

    def _layout_k(self) -> float:
        n = max(len(self._order), 1)
        vw = W - 2 * (SAFE_INSET + 10)
        vh = H - AREA_TOP - AREA_BOTTOM
        return math.sqrt(vw * vh / n) * FR_K_SCALE

    def _seed_positions(self, *, respread: bool = False) -> None:
        """Anéis por distância BFS a partir do hub (nota mais conectada)."""
        if not self._order:
            return
        g = self._graph
        cx, cy = W / 2, (AREA_TOP + H - AREA_BOTTOM) / 2
        k = self._layout_k()

        adj: dict[str, set[str]] = {nid: set() for nid in self._order}
        for a, b in self._shown_edges():
            if a in adj and b in adj:
                adj[a].add(b)
                adj[b].add(a)

        notes_only = [n for n in self._order if g and n in g.notes]
        hub = max(notes_only, key=g.degree) if (g and notes_only) else self._order[0]
        level: dict[str, int] = {hub: 0}
        queue = [hub]
        qi = 0
        while qi < len(queue):
            cur = queue[qi]
            qi += 1
            for nb in adj.get(cur, ()):
                if nb not in level:
                    level[nb] = level[cur] + 1
                    queue.append(nb)
        max_lv = max(level.values()) if level else 0
        for nid in self._order:
            if nid not in level:
                level[nid] = max_lv + 1

        by_lv: dict[int, list[str]] = {}
        for nid, lv in level.items():
            by_lv.setdefault(lv, []).append(nid)

        for lv, nodes in by_lv.items():
            nodes.sort()
            ring = k * (lv + 0.35) * 1.15
            for i, nid in enumerate(nodes):
                if not respread and nid in self._bodies:
                    continue
                if lv == 0 and len(nodes) == 1:
                    self._bodies[nid] = _Body(cx, cy)
                    continue
                ang = math.tau * i / max(1, len(nodes)) + lv * 0.55
                jitter = self._rng.uniform(0.92, 1.08)
                self._bodies[nid] = _Body(
                    cx + math.cos(ang) * ring * jitter,
                    cy + math.sin(ang) * ring * jitter,
                )

    def _physics_step(self, dt: float, *, dragging: str, cool: float = 1.0) -> None:
        if not self._order:
            return
        bodies = self._bodies
        ids = self._order
        cx = W / 2
        cy = (AREA_TOP + H - AREA_BOTTOM) / 2
        k = self._layout_k()
        k2 = k * k
        rep_scale = cool
        for i, a in enumerate(ids):
            ba = bodies[a]
            for b_id in ids[i + 1:]:
                bb = bodies[b_id]
                dx, dy = ba.x - bb.x, ba.y - bb.y
                d = math.hypot(dx, dy)
                if d < 0.5:
                    dx, dy = self._rng.uniform(-1, 1), self._rng.uniform(-1, 1)
                    d = 0.5
                fr = (k2 / d) * rep_scale
                if d < MIN_NODE_SEP:
                    fr += (MIN_NODE_SEP - d) * 2.8 * rep_scale
                fx, fy = fr * dx / d, fr * dy / d
                ba.vx += fx * dt
                ba.vy += fy * dt
                bb.vx -= fx * dt
                bb.vy -= fy * dt
        for a, b in self._shown_edges():
            ba, bb = bodies.get(a), bodies.get(b)
            if ba is None or bb is None:
                continue
            dx, dy = bb.x - ba.x, bb.y - ba.y
            d = math.hypot(dx, dy) or 0.5
            fa = (d * d / k) * FR_ATTRACT * rep_scale
            fx, fy = fa * dx / d, fa * dy / d
            ba.vx += fx * dt
            ba.vy += fy * dt
            bb.vx -= fx * dt
            bb.vy -= fy * dt
        for nid in ids:
            b = bodies[nid]
            if nid == dragging:
                b.vx = b.vy = 0.0
                continue
            b.vx += (cx - b.x) * GRAVITY
            b.vy += (cy - b.y) * GRAVITY
            b.vx *= DAMPING
            b.vy *= DAMPING
            sp = math.hypot(b.vx, b.vy)
            if sp > MAX_SPEED:
                b.vx *= MAX_SPEED / sp
                b.vy *= MAX_SPEED / sp
            b.x += b.vx * dt * 6
            b.y += b.vy * dt * 6
            self._confine(b)

    def _settle_layout(self, steps: int) -> None:
        dt = 1.0 / 30.0
        for i in range(max(0, steps)):
            cool = 1.0 + 0.5 * (1.0 - i / max(1, steps - 1))
            self._physics_step(dt, dragging="", cool=cool)
            self._separate("", iters=2)

    def _separate(self, dragging: str, iters: int = 6) -> None:
        """Empurra à força qualquer par mais perto que MIN_NODE_SEP. Garante a
        distância mínima pedida, independente da física (anti-amontoado).

        Várias passadas (Gauss-Seidel) pra convergir nos aglomerados densos;
        os nós ficam dentro dos limites da área visível."""
        ids = self._order
        bodies = self._bodies
        sep = MIN_NODE_SEP
        sep2 = sep * sep
        n = len(ids)
        for _ in range(max(1, iters)):
            moved = False
            for i in range(n):
                ba = bodies.get(ids[i])
                if ba is None:
                    continue
                for j in range(i + 1, n):
                    bb = bodies.get(ids[j])
                    if bb is None:
                        continue
                    dx, dy = ba.x - bb.x, ba.y - bb.y
                    d2 = dx * dx + dy * dy
                    if d2 >= sep2:
                        continue
                    if d2 < 1e-6:
                        dx, dy = self._rng.uniform(-1, 1), self._rng.uniform(-1, 1)
                        d2 = dx * dx + dy * dy or 1.0
                    d = math.sqrt(d2)
                    overlap = sep - d
                    ux, uy = dx / d, dy / d
                    moved = True
                    if ids[i] == dragging:
                        bb.x -= ux * overlap
                        bb.y -= uy * overlap
                    elif ids[j] == dragging:
                        ba.x += ux * overlap
                        ba.y += uy * overlap
                    else:
                        ba.x += ux * overlap * 0.5
                        ba.y += uy * overlap * 0.5
                        bb.x -= ux * overlap * 0.5
                        bb.y -= uy * overlap * 0.5
            # mantém tudo dentro da elipse (formato oval/cérebro)
            for nid in ids:
                b = bodies.get(nid)
                if b is None or nid == dragging:
                    continue
                self._confine(b)
            if not moved:
                break

    def update(self, dt: float) -> None:
        self._t += dt
        self._scan_t += dt
        if self._scan_t >= 3.0:   # pega notas recém-baixadas pelo drive_sync
            self._scan_t = 0.0
            self._refresh()
        if not self._order:
            return
        dt = min(dt, 0.05)
        dragging = self._press["nid"] if (self._press and self._press["moved"]) else ""
        # forças de layout suaves ao vivo (o settle já organizou): deixa a
        # separação mandar no espaçamento e o grafo só "respira".
        # iterações de separação caem com o nº de nós (protege o pior caso no Pi)
        self._physics_step(dt, dragging=dragging, cool=0.3)
        n = len(self._order)
        self._separate(dragging, iters=6 if n <= 45 else (4 if n <= 65 else 3))
        # no split a câmera segue o nó aberto, suave, sem mudar a escala
        if self._split:
            b = self._bodies.get(self._split)
            if b is not None:
                k = min(1.0, dt * 5)
                self._cam[0] += (b.x - self._cam[0]) * k
                self._cam[1] += (b.y - self._cam[1]) * k

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(MX_BG)
        draw_scanlines(surface)

        g = self._graph
        if g is None or g.empty:
            self._draw_back_btn(surface)
            title = render_text("SEGUNDO CEREBRO", 10, MX_MID)
            surface.blit(title, title.get_rect(midtop=(W // 2, SAFE_INSET)))
            self._draw_empty(surface)
            return

        view = self._view_rect()
        surface.set_clip(view)
        self._draw_graph(surface, g)
        surface.set_clip(None)

        if self._split:
            pygame.draw.line(surface, MX_DIM, (view.right, 0), (view.right, H), 1)
            self._draw_note_panel(surface, g)
        else:
            title = render_text("SEGUNDO CEREBRO", 10, MX_MID)
            surface.blit(title, title.get_rect(midtop=(W // 2, SAFE_INSET)))
            self._draw_footer(surface, g)
        self._draw_back_btn(surface)

    def _draw_graph(self, surface, g) -> None:
        view = self._view_rect()
        self._draw_brain_backdrop(surface, view)
        ghosts = g.ghosts
        t = self._t
        # ── arestas + pacotes de dados correndo (visual de rede) ──
        for a, b in self._shown_edges():
            ba, bb = self._bodies.get(a), self._bodies.get(b)
            if ba is None or bb is None:
                continue
            ax, ay = self._w2s(ba.x, ba.y)
            bx, by = self._w2s(bb.x, bb.y)
            sel = self._selected in (a, b)
            ghost = a in ghosts or b in ghosts
            color = MX_BRIGHT if sel else (MX_GHOST if ghost else MX_DIM)
            pygame.draw.line(surface, color, (ax, ay), (bx, by), 1)
            if ghost:
                continue
            # pulso = nota que viaja pela conexão (fase estável por aresta)
            ph = (hash((a, b)) & 1023) / 1023.0
            frac = (t * (0.35 + ph * 0.3) + ph) % 1.0
            px = int(ax + (bx - ax) * frac)
            py = int(ay + (by - ay) * frac)
            pygame.draw.circle(surface, MX_PULSE if sel else MX_MID,
                               (px, py), 2 if sel else 1)
        # ── nós: ponto com brilho (halo gradiente + núcleo aceso) ──
        for nid in self._order:
            b = self._bodies.get(nid)
            if b is None:
                continue
            sx, sy = self._w2s(b.x, b.y)
            pos = (int(sx), int(sy))
            if nid in ghosts:
                pygame.draw.circle(surface, MX_GLOW, pos, max(3, int(4 * self._zoom)))
                pygame.draw.circle(surface, MX_GHOST, pos, max(2, int(3 * self._zoom)), 1)
                continue
            deg = g.degree(nid)
            r = max(2, int((3 + min(5, deg)) * self._zoom))
            pygame.draw.circle(surface, MX_GLOW, pos, r + 4)   # halo externo
            pygame.draw.circle(surface, MX_DIM, pos, r + 2)    # halo interno
            if nid == self._selected:
                pulse = 2 + int((math.sin(t * 5) + 1) * 1.5)
                pygame.draw.circle(surface, MX_BRIGHT, pos, r + pulse, 1)
                pygame.draw.circle(surface, MX_BRIGHT, pos, r)
                pygame.draw.circle(surface, MX_CORE, pos, max(1, r // 2))
            else:
                pygame.draw.circle(surface, MX_MID, pos, r)
                pygame.draw.circle(surface, MX_CORE, pos, max(1, r // 2))
                if deg >= 5:                                    # hub: anel extra
                    pygame.draw.circle(surface, MX_MID, pos, r + 4, 1)
        # label flutuando no nó selecionado
        if self._selected and self._selected in self._bodies:
            self._draw_selection(surface, g)

    def _draw_brain_backdrop(self, surface, view: pygame.Rect) -> None:
        """Contorno enrugado (giros) + fissura central, bem fraco ao fundo:
        emoldura os nós num formato de cérebro sem competir com a rede."""
        cx = view.centerx
        cy = (AREA_TOP + (H - AREA_BOTTOM)) // 2
        rx = view.width * 0.43
        ry = (H - AREA_TOP - AREA_BOTTOM) * 0.46
        # córtex externo (circunvolução)
        cortex = []
        for i in range(60):
            a = math.tau * i / 60
            wob = 1.0 + 0.09 * math.sin(a * 7) + 0.05 * math.sin(a * 13 + 1.3)
            cortex.append((cx + math.cos(a) * rx * wob, cy + math.sin(a) * ry * wob))
        pygame.draw.lines(surface, MX_GLOW, True, cortex, 1)
        # uma dobra interna (dá profundidade sem virar mapa de contorno)
        inner = []
        for i in range(44):
            a = math.tau * i / 44
            wob = 1.0 + 0.10 * math.sin(a * 6 + 2.2)
            inner.append((cx + math.cos(a) * rx * 0.6 * wob,
                          cy + math.sin(a) * ry * 0.6 * wob))
        pygame.draw.lines(surface, MX_GLOW, True, inner, 1)
        # fissura longitudinal (separa os hemisférios)
        fissure = []
        for i in range(15):
            f = i / 14.0
            fissure.append((cx + math.sin(f * math.tau * 1.5) * 6,
                            cy - ry * 0.84 + ry * 1.68 * f))
        pygame.draw.lines(surface, MX_GLOW, False, fissure, 1)

    def _draw_back_btn(self, surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, MX_BG, rect)
        pygame.draw.rect(surface, MX_MID, rect, 1)
        pygame.draw.polygon(surface, MX_BRIGHT, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        label = "VOLTAR" if self._split else "MENU"
        img = render_text(label, 8, MX_BRIGHT, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _draw_selection(self, surface, g) -> None:
        b = self._bodies[self._selected]
        note = g.notes.get(self._selected)
        name = note.title if note else self._selected
        img = render_text(name[:24], 8, MX_BRIGHT, pixel=False)
        sx, sy = self._w2s(b.x, b.y)
        y = sy - 14 if sy > AREA_TOP + 20 else sy + 14
        rect = img.get_rect(center=(int(sx), int(y)))
        rect.clamp_ip(self._view_rect())
        pygame.draw.rect(surface, MX_BG, rect.inflate(6, 2))
        surface.blit(img, rect)

    def _draw_note_panel(self, surface, g) -> None:
        panel = self._note_panel()
        note = g.notes.get(self._split)
        if note is None:
            return
        x = panel.left + 6
        y = SAFE_INSET
        title = render_text(note.title[:26], 9, MX_BRIGHT, pixel=False)
        surface.blit(title, (x, y))
        y += 14
        pygame.draw.line(surface, MX_DIM, (x, y), (panel.right - 6, y), 1)
        y += 4
        vis = self._note_visible_lines()
        for line in self._note_lines[self._note_scroll:self._note_scroll + vis]:
            if line:
                img = render_text(line, 8, MX_MID, pixel=False)
                surface.blit(img, (x, y))
            y += 11
        # trilho de scroll: 1px na borda, minimalista (sem botões)
        total = len(self._note_lines)
        if total > vis:
            track = pygame.Rect(panel.right - 3, SAFE_INSET + 18, 1,
                                H - SAFE_INSET * 2 - 18)
            pygame.draw.rect(surface, MX_GHOST, track)
            knob_h = max(8, track.height * vis // total)
            max_off = total - vis
            knob_y = track.top + (track.height - knob_h) * self._note_scroll // max_off
            pygame.draw.rect(surface, MX_MID,
                             pygame.Rect(track.left - 1, knob_y, 3, knob_h))

    def _draw_footer(self, surface, g) -> None:
        cx = W // 2
        y = H - SAFE_INSET - 2
        note = g.notes.get(self._selected) if self._selected else None
        if note is not None:
            tags = " ".join("#" + t for t in note.tags[:3])
            info = f"{note.title}  [{g.degree(note.id)} conexoes]  {tags}".strip()
            img = render_text(info[:52], 8, MX_BRIGHT, pixel=False)
            surface.blit(img, img.get_rect(midbottom=(cx, y)))
            if note.preview:
                prev = render_text(note.preview[0][:56], 8, MX_DIM, pixel=False)
                surface.blit(prev, prev.get_rect(midbottom=(cx, y - 11)))
        else:
            sync = self.get_sync()
            stat = getattr(sync, "knowledge_status", "") if sync else "sem conta"
            info = f"{len(g.notes)} notas - {len(g.edges)} conexoes"
            if stat:
                info += f"  ({stat})"
            img = render_text(info, 8, MX_MID, pixel=False)
            surface.blit(img, img.get_rect(midbottom=(cx, y)))
            hint = render_text("toque seleciona - 2 toques abre - arrasta/pinca",
                               8, MX_DIM, pixel=False)
            surface.blit(hint, hint.get_rect(midbottom=(cx, y - 11)))

    def _draw_empty(self, surface) -> None:
        cx, cy = W // 2, H // 2
        sync = self.get_sync()
        # cérebro vazio: um nó solitário piscando
        pulse = 3 + int((math.sin(self._t * 3) + 1) * 2)
        pygame.draw.circle(surface, MX_DIM, (cx, cy - 16), pulse, 1)
        lines = [
            ("CEREBRO VAZIO", 10, MX_MID),
            ("coloque notas .md em Bimo/Conhecimento", 8, MX_DIM),
            ("no seu Google Drive (via app do Bimo)", 8, MX_DIM),
        ]
        if sync is None:
            lines.append(("(entre com uma conta Google pra sincronizar)", 8, MX_GHOST))
        else:
            stat = getattr(sync, "knowledge_status", "")
            if stat:
                lines.append((f"drive: {stat}", 8, MX_GHOST))
        y = cy + 2
        for text, size, color in lines:
            img = render_text(text, size, color, pixel=(size >= 10))
            surface.blit(img, img.get_rect(midtop=(cx, y)))
            y += size + 6
