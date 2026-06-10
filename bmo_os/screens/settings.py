"""Configurações do BMO — menu de categorias + sub-telas (estilo CRT P&B).

SettingsScreen é o MENU: SOM / TELA / SISTEMA / IA / Voltar. Cada categoria
abre uma SettingsListScreen (lista genérica de itens 'cycle'/'action'/'mic').

Itens 'cycle' giram com LEFT/RIGHT (ou TAP cicla pra frente). 'action'
disparam com A/TAP. 'mic' é um cycle dinâmico que lista os microfones.
on_change(key, value) avisa o main pra aplicar efeitos vivos (volume, ambient,
voz, mic).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pygame

from ..core import config, session, theme_state
from ..core import input as bmo_input
from ..core.theme import render_text
from ..core.widgets import (
    CRT_BLACK, CRT_DIM, CRT_WHITE,
    SAFE_INSET, draw_crt_corners, draw_scanlines,
    LOGICAL_SIZE,
)
from ..services import audio

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHUTDOWN_CONFIRM_S = 3.0


# ---------- formatadores ----------

def _fmt_timeout(v) -> str:
    return f"{int(v)}S"


def _fmt_ambient(v) -> str:
    return config.AMBIENT_MODE_LABELS.get(v, str(v).upper())


def _fmt_theme(v) -> str:
    return theme_state.THEME_LABELS.get(v, str(v).upper())


def _fmt_pct(v) -> str:
    return f"{int(v)}%"


def _fmt_onoff(v) -> str:
    return "ON" if v else "OFF"


def _fmt_warn(v) -> str:
    return f"{int(v)}MIN"


def _fmt_provider(v) -> str:
    return config.LLM_PROVIDER_LABELS.get(v, str(v).upper())


def _short_model(m: str) -> str:
    """Encurta o ID do modelo pro display CRT: tira o prefixo 'autor/' e o
    sufixo ':free', e trunca. Ex.: 'meta/llama-3.3-70b-instruct' -> 'LLAMA-3.3-70.'"""
    m = (m or "").strip()
    if not m:
        return "--"
    m = m.split("/")[-1].replace(":free", "")
    return (m if len(m) <= 14 else m[:13] + ".").upper()


# ---------- itens por categoria ----------

def _som_items():
    return [
        {"type": "cycle", "key": "volume", "label": "Volume",
         "options": config.VOLUME_OPTIONS, "format": _fmt_pct},
    ]


def _tela_items():
    return [
        {"type": "cycle", "key": "brightness", "label": "Brilho",
         "options": config.BRIGHTNESS_OPTIONS, "format": _fmt_pct},
        {"type": "cycle", "key": "theme", "label": "Tema",
         "options": theme_state.THEME_OPTIONS, "format": _fmt_theme},
    ]


def _sistema_items():
    return [
        {"type": "cycle", "key": "idle_timeout_s", "label": "Standby",
         "options": config.IDLE_TIMEOUT_OPTIONS, "format": _fmt_timeout},
        {"type": "cycle", "key": "ambient_mode", "label": "Ambient",
         "options": config.AMBIENT_MODE_OPTIONS, "format": _fmt_ambient},
        {"type": "cycle", "key": "event_warning_min", "label": "Aviso evento",
         "options": config.EVENT_WARNING_OPTIONS, "format": _fmt_warn},
        {"type": "action", "key": "update", "label": "Atualizar"},
        {"type": "action", "key": "shutdown", "label": "Desligar"},
    ]


def _ia_items():
    return [
        {"type": "cycle", "key": "llm_provider", "label": "IA provedor",
         "options": config.LLM_PROVIDERS, "format": _fmt_provider},
        {"type": "llm_model", "key": "llm_model", "label": "IA modelo",
         "provider_key": "llm_provider", "models": "chat"},
        {"type": "cycle", "key": "vision_provider", "label": "Visao prov",
         "options": config.LLM_PROVIDERS, "format": _fmt_provider},
        {"type": "llm_model", "key": "vision_model", "label": "Visao modelo",
         "provider_key": "vision_provider", "models": "vision"},
        {"type": "cycle", "key": "voice_enabled", "label": "BMO me ouve",
         "options": [False, True], "format": _fmt_onoff},
        {"type": "cycle", "key": "mic_button_enabled", "label": "Botao de fala",
         "options": [False, True], "format": _fmt_onoff},
        {"type": "mic", "key": "mic_device", "label": "Microfone"},
        {"type": "cycle", "key": "tts_volume", "label": "Voz BMO",
         "options": config.VOLUME_OPTIONS, "format": _fmt_pct},
        {"type": "cycle", "key": "camera_face_tracking", "label": "BMO te ve",
         "options": [False, True], "format": _fmt_onoff},
        {"type": "action", "key": "gen_voice_cache", "label": "Gerar vozes"},
    ]


def _conta_items():
    return [
        # 'info' = linha somente-leitura (mostra a conta logada)
        {"type": "info", "key": "account", "label": "Conta"},
        # abre o LOGIN (QR) por cima — conecta/troca a conta SEM wipe.
        # É a saída do modo local/convidado sem precisar de logout.
        {"type": "action", "key": "connect", "label": "Conectar conta"},
        {"type": "action", "key": "logout", "label": "Trocar usuario"},
    ]


def _account_display() -> str:
    """E-mail (ou nome) do perfil ativo, encurtado pro CRT. 'local' sem sessão."""
    prof = session.current()
    if prof is None:
        return "local"
    label = (prof.get("email") or prof.get("name") or prof.get("sub") or "?").strip()
    return label if len(label) <= 22 else label[:21] + "."


CATEGORIES = [
    ("SOM", _som_items),
    ("TELA", _tela_items),
    ("SISTEMA", _sistema_items),
    ("IA", _ia_items),
    ("CONTA", _conta_items),
]


# ============================================================
# MENU de categorias
# ============================================================

class SettingsScreen:
    voice_announce = "Configurações."   # BMO anuncia ao abrir (cacheado)

    def __init__(self, *, on_back, on_open, on_change=None, mic_options=None,
                 on_cleanup=None, tts=None, on_logout=None,
                 on_connect=None) -> None:
        self.on_back = on_back
        self.on_open = on_open          # push de uma sub-tela
        self.on_change = on_change
        self.mic_options = mic_options
        self.on_cleanup = on_cleanup    # libera hardware antes do restart/desligar
        self.tts = tts                  # serviço de voz (pra ação "Gerar vozes")
        self.on_logout = on_logout      # Wipe & Load (main.do_logout)
        self.on_connect = on_connect    # abre o LOGIN QR por cima (main.do_connect)
        self._index = 0
        self._rows = [label for label, _ in CATEGORIES] + ["Voltar"]

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT:
            return
        a = event.action
        if a == bmo_input.Action.UP:
            self._index = (self._index - 1) % len(self._rows); audio.play("tick")
        elif a == bmo_input.Action.DOWN:
            self._index = (self._index + 1) % len(self._rows); audio.play("tick")
        elif a in (bmo_input.Action.A, bmo_input.Action.RIGHT):
            self._activate()
        elif a == bmo_input.Action.B:
            audio.play("back"); self.on_back()
        elif a == bmo_input.Action.TAP and getattr(event, "pos", None):
            for i, r in enumerate(self._row_rects()):
                if r.collidepoint(event.pos):
                    if i == self._index:
                        self._activate()
                    else:
                        self._index = i
                    return

    def _activate(self) -> None:
        if self._index >= len(CATEGORIES):
            audio.play("back"); self.on_back(); return
        audio.play("select")
        label, items_fn = CATEGORIES[self._index]
        # on_back da sub = mesmo pop do menu: com a sub no topo, pop volta
        # pro menu; com o menu no topo, pop sai das configs.
        self.on_open(SettingsListScreen(
            title=label, items=items_fn(), on_back=self.on_back,
            on_change=self.on_change, mic_options=self.mic_options,
            on_cleanup=self.on_cleanup, tts=self.tts, on_logout=self.on_logout,
            on_connect=self.on_connect,
        ))

    def update(self, dt: float) -> None: ...

    def _row_rects(self):
        top, step = 44, 24
        return [pygame.Rect(40, top + i * step, LOGICAL_SIZE[0] - 80, 20)
                for i in range(len(self._rows))]

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        title = render_text("SETTINGS", 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 6)))
        for i, (row, rect) in enumerate(zip(self._rows, self._row_rects())):
            selected = (i == self._index)
            if selected:
                pygame.draw.rect(surface, CRT_WHITE, rect)
                pygame.draw.polygon(surface, CRT_BLACK, [
                    (rect.left + 6, rect.centery - 4), (rect.left + 6, rect.centery + 4),
                    (rect.left + 12, rect.centery)])
                fg, x = CRT_BLACK, rect.left + 18
            else:
                fg, x = CRT_DIM, rect.left + 10
            img = render_text(row.upper(), 11, fg)
            surface.blit(img, img.get_rect(midleft=(x, rect.centery)))
            if i < len(CATEGORIES):  # seta ">" indicando submenu
                arrow = ">" if not selected else ""
                if arrow:
                    a = render_text(arrow, 11, fg)
                    surface.blit(a, a.get_rect(midright=(rect.right - 8, rect.centery)))


# ============================================================
# Sub-tela: lista de configs de uma categoria
# ============================================================

class SettingsListScreen:
    def __init__(self, *, title, items, on_back, on_change=None, mic_options=None,
                 on_cleanup=None, tts=None, on_logout=None,
                 on_connect=None) -> None:
        self.title = title
        self.items = items
        self.on_back = on_back
        self.on_change = on_change
        self.mic_options = mic_options or (lambda: [])
        self.on_cleanup = on_cleanup
        self.tts = tts
        self.on_logout = on_logout
        self.on_connect = on_connect
        self._index = 0
        self._status = ""
        self._action = None
        self._delay_until = 0.0
        self._shutdown_confirm_until = 0.0
        self._logout_confirm_until = 0.0
        self._watch_voice = False   # mostrando o progresso de "Gerar vozes"?
        self._t = 0.0
        self._rows = items + [{"type": "action", "key": "back", "label": "Voltar"}]

    def enter(self) -> None: ...
    def exit(self) -> None: ...

    # ---------- input ----------

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != bmo_input.ACTION_EVENT or self._action is not None:
            return
        a = event.action
        if a == bmo_input.Action.UP:
            self._index = (self._index - 1) % len(self._rows); audio.play("tick")
        elif a == bmo_input.Action.DOWN:
            self._index = (self._index + 1) % len(self._rows); audio.play("tick")
        elif a == bmo_input.Action.LEFT:
            self._cycle_current(-1)
        elif a == bmo_input.Action.RIGHT:
            self._cycle_current(+1)
        elif a == bmo_input.Action.A:
            self._activate()
        elif a == bmo_input.Action.B:
            audio.play("back"); self.on_back()
        elif a == bmo_input.Action.TAP and getattr(event, "pos", None):
            self._handle_tap(event.pos)

    def _handle_tap(self, pos) -> None:
        rects = self._row_rects()
        cur = rects[self._index]
        if self._left_arrow(cur).collidepoint(pos):
            self._cycle_current(-1); return
        if self._right_arrow(cur).collidepoint(pos):
            self._cycle_current(+1); return
        for i, r in enumerate(rects):
            if r.collidepoint(pos):
                if i == self._index:
                    self._activate()
                else:
                    self._index = i
                return

    @staticmethod
    def _llm_table(item):
        return config.LLM_VISION_MODELS if item.get("models") == "vision" else config.LLM_MODELS

    def _llm_provider(self, item):
        table = self._llm_table(item)
        p = config.get(item["provider_key"])
        return p if p in table else config.LLM_PROVIDERS[0]

    def _llm_model_key(self, item):
        suffix = "_vision_model" if item.get("models") == "vision" else "_model"
        return f"{self._llm_provider(item)}{suffix}"

    def _options_for(self, item):
        if item["type"] == "mic":
            return ["(padrao)"] + list(self.mic_options())
        if item["type"] == "llm_model":
            return list(self._llm_table(item).get(self._llm_provider(item), []))
        return item["options"]

    def _mic_current_display(self):
        cur = (config.get("mic_device") or "").strip()
        return cur if cur else "(padrao)"

    def _cycle_current(self, direction: int) -> None:
        item = self._rows[self._index]
        if item["type"] not in ("cycle", "mic", "llm_model"):
            return
        options = self._options_for(item)
        if not options:
            return
        if item["type"] == "mic":
            key = "mic_device"
            cur = self._mic_current_display()
            idx = options.index(cur) if cur in options else 0
            new_disp = options[(idx + direction) % len(options)]
            new_val = "" if new_disp == "(padrao)" else new_disp
        elif item["type"] == "llm_model":
            # a chave depende do provedor escolhido (ex: openrouter_model / nvidia_vision_model)
            key = self._llm_model_key(item)
            cur = config.get(key)
            idx = options.index(cur) if cur in options else 0
            new_val = options[(idx + direction) % len(options)]
        else:
            key = item["key"]
            cur = config.get(key)
            idx = options.index(cur) if cur in options else 0
            new_val = options[(idx + direction) % len(options)]
        config.set_value(key, new_val)
        if key == "volume":
            audio.set_volume(new_val / 100)
        audio.play("tick")
        if self.on_change:
            self.on_change(key, new_val)

    def _activate(self) -> None:
        item = self._rows[self._index]
        if item["type"] in ("cycle", "mic", "llm_model"):
            self._cycle_current(+1); return
        key = item["key"]
        if key == "back":
            audio.play("back"); self.on_back()
        elif key == "update":
            audio.play("select"); self._status = "Atualizando..."; self._action = "pull"
        elif key == "shutdown":
            audio.play("select")
            if self._t < self._shutdown_confirm_until:
                self._status = "Desligando..."; self._action = "shutdown"
            else:
                self._shutdown_confirm_until = self._t + SHUTDOWN_CONFIRM_S
                self._status = "Toque DESLIGAR de novo p/ confirmar"
        elif key == "connect":
            audio.play("select")
            if self.on_connect is None:
                self._status = "Indisponivel nesta build"
            else:
                self.on_connect()   # LOGIN QR por cima; sucesso reinicia logado
        elif key == "logout":
            audio.play("select")
            if self.on_logout is None:
                self._status = "Indisponivel nesta build"
            elif self._t < self._logout_confirm_until:
                # flush no Drive + wipe do perfil + restart (não retorna)
                self._status = "Salvando e encerrando..."
                self._action = "logout"
            else:
                self._logout_confirm_until = self._t + SHUTDOWN_CONFIRM_S
                self._status = "Toque de novo p/ trocar usuario"
        elif key == "gen_voice_cache":
            audio.play("select")
            if self.tts is None or getattr(self.tts, "backend", "") != "edge":
                self._status = "Voz indisponivel (edge off)"
            else:
                self._watch_voice = True
                self.tts.ensure_cache_async()   # gera as frases faltantes em background
                self._status = "Vozes: verificando..."

    # ---------- update ----------

    def update(self, dt: float) -> None:
        self._t += dt
        if self._action == "pull":
            self._action = None; self._do_pull()
        elif self._action == "restart" and self._t >= self._delay_until:
            self._action = None; self._restart()
        elif self._action == "shutdown":
            self._action = None; self._do_shutdown()
        elif self._action == "logout":
            self._action = None
            if self.on_logout is not None:
                self.on_logout()   # flush -> wipe -> execv (não retorna)
        if (self._shutdown_confirm_until > 0 and self._t >= self._shutdown_confirm_until
                and self._status.startswith("Toque DESLIGAR")):
            self._shutdown_confirm_until = 0.0; self._status = ""
        if (self._logout_confirm_until > 0 and self._t >= self._logout_confirm_until
                and self._status.startswith("Toque de novo")):
            self._logout_confirm_until = 0.0; self._status = ""
        # progresso ao vivo da geração de vozes
        if self._watch_voice and self.tts is not None:
            self._status = "Vozes: " + (getattr(self.tts, "cache_status", "") or "...")
            if not getattr(self.tts, "cache_building", False) and "ok" in self._status:
                self._watch_voice = False   # terminou; congela o "ok N/N"

    # ---------- layout ----------

    def _row_rects(self):
        # passo/altura menores quando a categoria tem muitos itens (IA), pra caber tudo
        n = len(self._rows)
        if n > 10:
            step, top, hgt = 17, 30, 15
        elif n > 9:
            step, top, hgt = 19, 32, 17
        elif n > 7:
            step, top, hgt = 20, 36, 18
        else:
            step, top, hgt = 22, 40, 18
        return [pygame.Rect(20, top + i * step, LOGICAL_SIZE[0] - 40, hgt)
                for i in range(n)]

    def _left_arrow(self, row): return pygame.Rect(row.right - 38, row.top, 16, row.height)
    def _right_arrow(self, row): return pygame.Rect(row.right - 16, row.top, 16, row.height)

    # ---------- draw ----------

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(CRT_BLACK)
        draw_scanlines(surface)
        draw_crt_corners(surface, margin=SAFE_INSET)
        theme_state.draw_status_bar(surface, top_pad=SAFE_INSET + 4, right_pad=SAFE_INSET + 4)
        title = render_text(self.title, 10, CRT_DIM)
        surface.blit(title, title.get_rect(midtop=(LOGICAL_SIZE[0] // 2, SAFE_INSET + 6)))

        for i, (item, rect) in enumerate(zip(self._rows, self._row_rects())):
            selected = (i == self._index)
            fg = CRT_BLACK if selected else CRT_DIM
            if selected:
                pygame.draw.rect(surface, CRT_WHITE, rect)
                pygame.draw.polygon(surface, CRT_BLACK, [
                    (rect.left + 5, rect.centery - 4), (rect.left + 5, rect.centery + 4),
                    (rect.left + 11, rect.centery)])
                label_x = rect.left + 16
            else:
                label_x = rect.left + 8

            label_txt = item["label"].upper()
            if item.get("key") == "shutdown" and self._t < self._shutdown_confirm_until:
                label_txt = "DESLIGAR?"
            if item.get("key") == "logout" and self._t < self._logout_confirm_until:
                label_txt = "TROCAR USUARIO?"
            label = render_text(label_txt, 9, fg)
            surface.blit(label, label.get_rect(midleft=(label_x, rect.centery)))

            if item["type"] == "info":
                val = _account_display() if item["key"] == "account" else ""
                val_img = render_text(val, 9, fg, pixel=False)
                surface.blit(val_img, val_img.get_rect(midright=(rect.right - 8, rect.centery)))
            elif item["type"] in ("cycle", "mic", "llm_model"):
                if item["type"] == "mic":
                    cur = self._mic_current_display()
                    val = cur if len(cur) <= 12 else cur[:11] + "."
                elif item["type"] == "llm_model":
                    val = _short_model(config.get(self._llm_model_key(item)))
                else:
                    val = item["format"](config.get(item["key"]))
                val_img = render_text(val, 9, fg, pixel=False)
                if selected:
                    surface.blit(val_img, val_img.get_rect(midright=(rect.right - 46, rect.centery)))
                    la, ra = self._left_arrow(rect), self._right_arrow(rect)
                    pygame.draw.polygon(surface, CRT_BLACK, [
                        (la.right - 3, la.centery - 4), (la.right - 3, la.centery + 4), (la.left + 3, la.centery)])
                    pygame.draw.polygon(surface, CRT_BLACK, [
                        (ra.left + 3, ra.centery - 4), (ra.left + 3, ra.centery + 4), (ra.right - 3, ra.centery)])
                else:
                    surface.blit(val_img, val_img.get_rect(midright=(rect.right - 8, rect.centery)))

        if self._status:
            bright = "OK" in self._status or "Atualizando" in self._status
            color = CRT_WHITE if bright else CRT_DIM
            msg = render_text(self._status, 9, color)
            surface.blit(msg, msg.get_rect(midbottom=(LOGICAL_SIZE[0] // 2, LOGICAL_SIZE[1] - SAFE_INSET - 4)))

    # ---------- ações de sistema ----------

    def _git(self, *args, timeout=60):
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, timeout=timeout, check=False)

    def _do_pull(self) -> None:
        """Atualiza forçando o espelhamento do origin/main (fetch + reset --hard).

        Kiosk deve seguir o main exatamente; isso ignora mudanças locais e
        evita o frágil 'git pull --ff-only' (que quebra com arquivo modificado
        ou 'cannot fast-forward to multiple branches')."""
        try:
            fetch = self._git("fetch", "--quiet", "origin", "main")
            if fetch.returncode != 0:
                first = (fetch.stderr or fetch.stdout).strip().split("\n", 1)[0]
                self._status = ("Fetch falhou: " + first)[:36]; return
            local = self._git("rev-parse", "HEAD").stdout.strip()
            remote = self._git("rev-parse", "origin/main").stdout.strip()
            reset = self._git("reset", "--hard", "origin/main")
            if reset.returncode != 0:
                first = (reset.stderr or reset.stdout).strip().split("\n", 1)[0]
                self._status = ("Reset falhou: " + first)[:36]; return
        except FileNotFoundError:
            self._status = "git nao instalado"; return
        except Exception as e:
            self._status = ("Erro: " + str(e))[:36]; return
        self._status = "Ja atualizado, reiniciando..." if local == remote else "OK! Reiniciando..."
        self._delay_until = self._t + 1.5
        self._action = "restart"

    def _restart(self) -> None:
        # libera mic/câmera/GPIO antes do execv (libs em C deixam fds abertos
        # que sobrevivem ao execv e travam o processo novo)
        if self.on_cleanup:
            try:
                self.on_cleanup()
            except Exception:
                pass
        pygame.quit()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    def _do_shutdown(self) -> None:
        if self.on_cleanup:
            try:
                self.on_cleanup()
            except Exception:
                pass
        pygame.quit()
        if sys.platform == "win32":
            os.system("shutdown /s /t 0")
        else:
            rc = os.system("sudo -n shutdown -h now")
            if rc != 0:
                os.system("shutdown -h now")
        sys.exit(0)
