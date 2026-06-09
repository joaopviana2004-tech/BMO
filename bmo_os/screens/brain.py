"""Tela CEREBRO — visualização do grafo de conhecimento (Segundo Cérebro).

O "Oráculo Visual" do Melhorias_BMO.md: minimapa de nós interagíveis
mostrando como as notas do Obsidian se conectam. Estilo terminal/matrix
(verde sobre preto, fixo — não segue o tema claro/escuro de propósito).

- nó      = nota .md (raio cresce com o nº de conexões)
- linha   = [[wikilink]] entre notas
- fantasma= link pra nota que não existe (círculo vazado, apagado)

Layout força-dirigido rodando ao vivo (repulsão + molas + gravidade pro
centro): o grafo "respira" e se organiza sozinho na tela.

Controles: TAP num nó (ou LEFT/RIGHT) seleciona e mostra título/tags/
conexões no rodapé; A re-sincroniza com o Drive; B volta.
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

MAX_NODES = 80          # acima disso, mostra os mais conectados
AREA_TOP = 30
AREA_BOTTOM = 36        # reserva do rodapé (info da nota)

# física do layout
REPULSION = 1800.0
SPRING_K = 0.06
SPRING_LEN = 46.0
GRAVITY = 0.035
DAMPING = 0.85
MAX_SPEED = 60.0


class _Body:
    __slots__ = ("x", "y", "vx", "vy")

    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = x, y
        self.vx = self.vy = 0.0


class BrainScreen:
    voice_announce = "Aqui está o seu cérebro!"

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
        self._order = ids + ghosts
        cx, cy = LOGICAL_SIZE[0] / 2, (AREA_TOP + LOGICAL_SIZE[1] - AREA_BOTTOM) / 2
        for nid in self._order:
            if nid not in self._bodies:
                ang = self._rng.uniform(0, math.tau)
                r = self._rng.uniform(10, 70)
                self._bodies[nid] = _Body(cx + math.cos(ang) * r,
                                          cy + math.sin(ang) * r)
        # remove corpos de nós que saíram
        for nid in list(self._bodies):
            if nid not in self._order:
                del self._bodies[nid]
        if self._selected not in self._order:
            self._selected = ""

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

    # ---------- input ----------

    def _back_btn(self) -> pygame.Rect:
        return pygame.Rect(SAFE_INSET, SAFE_INSET, 52, 16)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        a = event.action
        if a in (bmo_input.Action.B, bmo_input.Action.MENU):
            audio.play("back")
            self.on_back()
        elif a in (bmo_input.Action.LEFT, bmo_input.Action.RIGHT) and self._order:
            audio.play("tick")
            step = -1 if a == bmo_input.Action.LEFT else 1
            if self._selected in self._order:
                i = (self._order.index(self._selected) + step) % len(self._order)
            else:
                i = 0
            self._selected = self._order[i]
        elif a == bmo_input.Action.A:
            sync = self.get_sync()
            if sync is not None:
                audio.play("select")
                sync.request_knowledge_sync()
        elif a == bmo_input.Action.TAP and getattr(event, "pos", None):
            if self._back_btn().collidepoint(event.pos):
                audio.play("back")
                self.on_back()
            else:
                self._tap(event.pos)

    def _tap(self, pos) -> None:
        best, best_d = "", 18.0   # raio de toque generoso
        for nid in self._order:
            b = self._bodies.get(nid)
            if b is None:
                continue
            d = math.hypot(pos[0] - b.x, pos[1] - b.y)
            if d < best_d:
                best, best_d = nid, d
        if best:
            audio.play("tick")
            self._selected = "" if best == self._selected else best

    # ---------- física ----------

    def update(self, dt: float) -> None:
        self._t += dt
        self._scan_t += dt
        if self._scan_t >= 3.0:   # pega notas recém-baixadas pelo drive_sync
            self._scan_t = 0.0
            self._refresh()
        if not self._order:
            return
        dt = min(dt, 0.05)
        bodies = self._bodies
        ids = self._order
        cx = LOGICAL_SIZE[0] / 2
        cy = (AREA_TOP + LOGICAL_SIZE[1] - AREA_BOTTOM) / 2
        # repulsão O(n²) — ok pro cap de 80 nós a 30fps
        for i, a in enumerate(ids):
            ba = bodies[a]
            for b_id in ids[i + 1:]:
                bb = bodies[b_id]
                dx, dy = ba.x - bb.x, ba.y - bb.y
                d2 = dx * dx + dy * dy
                if d2 < 1.0:
                    dx, dy, d2 = self._rng.uniform(-1, 1), self._rng.uniform(-1, 1), 1.0
                f = REPULSION / d2
                d = math.sqrt(d2)
                fx, fy = f * dx / d, f * dy / d
                ba.vx += fx * dt; ba.vy += fy * dt
                bb.vx -= fx * dt; bb.vy -= fy * dt
        # molas nas arestas
        for a, b in self._shown_edges():
            ba, bb = bodies.get(a), bodies.get(b)
            if ba is None or bb is None:
                continue
            dx, dy = bb.x - ba.x, bb.y - ba.y
            d = math.hypot(dx, dy) or 1.0
            f = SPRING_K * (d - SPRING_LEN)
            fx, fy = f * dx / d, f * dy / d
            ba.vx += fx; ba.vy += fy
            bb.vx -= fx; bb.vy -= fy
        # gravidade pro centro + integração
        for nid in ids:
            b = bodies[nid]
            b.vx += (cx - b.x) * GRAVITY
            b.vy += (cy - b.y) * GRAVITY
            b.vx *= DAMPING; b.vy *= DAMPING
            sp = math.hypot(b.vx, b.vy)
            if sp > MAX_SPEED:
                b.vx *= MAX_SPEED / sp; b.vy *= MAX_SPEED / sp
            b.x += b.vx * dt * 6
            b.y += b.vy * dt * 6
            b.x = min(max(b.x, SAFE_INSET + 10), LOGICAL_SIZE[0] - SAFE_INSET - 10)
            b.y = min(max(b.y, AREA_TOP), LOGICAL_SIZE[1] - AREA_BOTTOM)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(MX_BG)
        draw_scanlines(surface)
        self._draw_back_btn(surface)
        title = render_text("SEGUNDO CEREBRO", 10, MX_MID)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET)))

        g = self._graph
        if g is None or g.empty:
            self._draw_empty(surface)
            return

        ghosts = g.ghosts
        # arestas
        for a, b in self._shown_edges():
            ba, bb = self._bodies.get(a), self._bodies.get(b)
            if ba is None or bb is None:
                continue
            sel = self._selected in (a, b)
            ghost = a in ghosts or b in ghosts
            color = MX_BRIGHT if sel else (MX_GHOST if ghost else MX_DIM)
            pygame.draw.line(surface, color, (ba.x, ba.y), (bb.x, bb.y), 1)
        # nós
        for nid in self._order:
            b = self._bodies.get(nid)
            if b is None:
                continue
            pos = (int(b.x), int(b.y))
            if nid in ghosts:
                pygame.draw.circle(surface, MX_GHOST, pos, 3, 1)
                continue
            r = 3 + min(5, g.degree(nid))
            if nid == self._selected:
                pulse = 2 + int((math.sin(self._t * 5) + 1) * 1.5)
                pygame.draw.circle(surface, MX_BRIGHT, pos, r + pulse, 1)
                pygame.draw.circle(surface, MX_BRIGHT, pos, r)
            else:
                pygame.draw.circle(surface, MX_MID, pos, r)
        # label flutuando no nó selecionado
        if self._selected and self._selected in self._bodies:
            self._draw_selection(surface, g)
        self._draw_footer(surface, g)

    def _draw_back_btn(self, surface) -> None:
        rect = self._back_btn()
        pygame.draw.rect(surface, MX_BG, rect)
        pygame.draw.rect(surface, MX_MID, rect, 1)
        pygame.draw.polygon(surface, MX_BRIGHT, [
            (rect.left + 6, rect.centery - 3),
            (rect.left + 6, rect.centery + 3),
            (rect.left + 3, rect.centery),
        ])
        img = render_text("MENU", 8, MX_BRIGHT, pixel=False)
        surface.blit(img, img.get_rect(midleft=(rect.left + 12, rect.centery)))

    def _draw_selection(self, surface, g) -> None:
        b = self._bodies[self._selected]
        note = g.notes.get(self._selected)
        name = note.title if note else self._selected
        img = render_text(name[:24], 8, MX_BRIGHT, pixel=False)
        y = b.y - 14 if b.y > AREA_TOP + 20 else b.y + 14
        rect = img.get_rect(center=(int(b.x), int(y)))
        rect.clamp_ip(surface.get_rect())
        pygame.draw.rect(surface, MX_BG, rect.inflate(6, 2))
        surface.blit(img, rect)

    def _draw_footer(self, surface, g) -> None:
        cx = LOGICAL_SIZE[0] // 2
        y = LOGICAL_SIZE[1] - SAFE_INSET - 2
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
            hint = render_text("toque num no - A sincroniza", 8, MX_DIM, pixel=False)
            surface.blit(hint, hint.get_rect(midbottom=(cx, y - 11)))

    def _draw_empty(self, surface) -> None:
        cx, cy = LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] // 2
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
