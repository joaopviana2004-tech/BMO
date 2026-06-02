"""Ponto de entrada do BMO OS.

Uso:
    python -m bmo_os.main             # janelado, ótimo pra desenvolver no PC
    python -m bmo_os.main --fullscreen # no Pi
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pygame

# permite rodar tanto como módulo quanto como script direto
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bmo_os.core import config
from bmo_os.core.app import App
from bmo_os.core.theme import Colors, LOGICAL_SIZE, render_text
from bmo_os.screens.agenda import AgendaScreen
from bmo_os.screens.aitest import AITestScreen
from bmo_os.screens.alert import AlertScreen
from bmo_os.screens.bmo_face import BMOFaceScreen
from bmo_os.screens.clock import ClockScreen
from bmo_os.screens.games import GamesScreen, draw_pong_icon, draw_space_invaders_icon
from bmo_os.screens.home import HomeScreen
from bmo_os.screens.gallery import GalleryScreen
from bmo_os.screens.photo import PHOTOS_DIR, PhotoScreen
from bmo_os.screens.pomodoro import PomodoroScreen
from bmo_os.screens.pong import PongAmbientScreen, PongScreen
from bmo_os.screens.settings import SettingsScreen
from bmo_os.screens.sysinfo import SysInfoScreen
from bmo_os.screens.shuffler import ShufflingAmbientScreen
from bmo_os.screens.sleep import SleepScreen
from bmo_os.screens.space_invaders import SpaceInvadersAmbientScreen, SpaceInvadersScreen
from bmo_os.screens.suspended import SuspendedScreen
from bmo_os.screens.tasks import TasksScreen
from bmo_os.services import audio
from bmo_os.services.camera import CameraService
from bmo_os.services.chat import ChatService
from bmo_os.services.gcalendar import CalendarService
from bmo_os.services.gpio_button import GPIOButton
from bmo_os.services.git_updates import GitUpdatesService
from bmo_os.services.notifications import EventAlerter
from bmo_os.services.sysinfo import SysInfoService
from bmo_os.services.todoist import TodoistService
from bmo_os.services.voice import VoiceService


def build_initial(app: App):
    # Cache pra reaproveitar a mesma instância de cada ambient — evita criar
    # uma WeatherService nova (e portanto uma thread) toda vez que a home volta.
    ambient_cache: dict = {}

    # Singleton de Todoist (thread + cache vivem aqui)
    todoist = TodoistService()
    # Detector de git updates (só usado pelo clock pra mostrar alerta)
    git_updates = GitUpdatesService()
    # Câmera (AI Camera no Pi). is_available=False quando offline (dev no PC)
    camera = CameraService()
    # Google Calendar (URLs secretas iCal) + disparador de avisos de evento
    calendar = CalendarService()
    alerter = EventAlerter()
    # Telemetria de hardware (tela SISTEMA). No PC mostra "--".
    sysinfo = SysInfoService()
    # Pomodoro é cacheado: o tempo de foco por tarefa (e o estado do timer)
    # sobrevive ao abrir/fechar a tela.
    pomodoro = PomodoroScreen(on_back=app.manager.pop, todoist=todoist)
    # Audição (wake word + Whisper). No PC degrada pra "indisponivel".
    voice = VoiceService()
    # BMO responde via LLM (OpenRouter). Degrada sem OPENROUTER_API_KEY.
    chat = ChatService()
    # Voz (TTS) desativada por enquanto — só texto no rodapé.
    tts = None

    # Botão físico de push-to-talk (GPIO): segura = grava, solta = transcreve
    # + BMO responde. No PC degrada (ok=False); use o botão da tela TESTE.
    def _ptt_done(text):
        # delega pro handler (definido abaixo) que pergunta ao LLM e, se ele
        # pedir, abre a tela correspondente. Late binding resolve o nome.
        handle_ai_response(text)

    ptt_pin = int(os.environ.get("PTT_GPIO", "17"))
    ptt_button = GPIOButton(
        ptt_pin,
        on_press=lambda: voice.ptt_begin(on_done=_ptt_done),
        on_release=voice.ptt_end,
    )

    def cleanup_hardware() -> None:
        """Libera hardware (mic, câmera, GPIO) ANTES do restart por execv.
        Sem isso, libs em C (libcamera, lgpio) deixam fds abertos que
        sobrevivem ao execv e o processo novo não reivindica câmera/botão."""
        try:
            voice.set_enabled(False)
        except Exception:
            pass
        try:
            voice.stop_monitor()
        except Exception:
            pass
        try:
            camera.stop()
        except Exception:
            pass
        try:
            ptt_button.close()
        except Exception:
            pass
        # fecha o pin factory do gpiozero (libera todos os pinos)
        try:
            from gpiozero import Device
            if getattr(Device, "pin_factory", None) is not None:
                Device.pin_factory.close()
        except Exception:
            pass
    # Fila de ações dos comandos de voz: o wake-loop roda em thread, então
    # empilhamos a navegação aqui e executamos no main thread (frame_hook).
    voice_queue: list = []
    voice_lock = threading.Lock()

    def voice_enqueue(fn):
        with voice_lock:
            voice_queue.append(fn)

    def _instantiate_ambient(mode):
        if mode == "face":
            return BMOFaceScreen(on_open_home=open_home, camera=camera, tts=tts)
        if mode == "pong":
            return PongAmbientScreen(on_open_home=open_home)
        if mode == "invaders":
            return SpaceInvadersAmbientScreen(on_open_home=open_home)
        # default: clock
        return ClockScreen(on_open_home=open_home, git_updates=git_updates)

    def make_ambient():
        mode = config.get("ambient_mode")
        if mode not in ambient_cache:
            if mode == "shuffle":
                # cria todas as ambient screens uma vez e deixa o shuffler ciclar
                ambient_cache[mode] = ShufflingAmbientScreen([
                    _instantiate_ambient("clock"),
                    _instantiate_ambient("face"),
                    _instantiate_ambient("pong"),
                    _instantiate_ambient("invaders"),
                ])
            else:
                ambient_cache[mode] = _instantiate_ambient(mode)
        return ambient_cache[mode]

    def go_ambient() -> None:
        app.manager.replace(make_ambient())

    def select_ambient(mode: str) -> None:
        config.set_value("ambient_mode", mode)
        go_ambient()

    def open_home() -> None:
        app.manager.push(make_home())

    def make_games_screen():
        return GamesScreen(
            on_back=app.manager.pop,
            games=[
                {
                    "label": "Space Invaders",
                    "draw_icon": draw_space_invaders_icon,
                    "launch": lambda: app.manager.push(
                        SpaceInvadersScreen(on_back=app.manager.pop)
                    ),
                },
                {
                    "label": "Pong",
                    "draw_icon": draw_pong_icon,
                    "launch": lambda: app.manager.push(
                        PongScreen(on_back=app.manager.pop)
                    ),
                },
            ],
        )

    def open_suspend() -> None:
        # Suspende: display off + FPS baixo. Wake → vai direto pro ambient.
        app.manager.push(SuspendedScreen(on_wake=go_ambient))

    def make_home() -> HomeScreen:
        return HomeScreen(
            on_back=go_ambient,
            on_open_sleep=lambda: app.manager.push(
                SleepScreen(on_back=app.manager.pop, on_select_mode=select_ambient)
            ),
            on_open_suspend=open_suspend,
            on_open_games=lambda: app.manager.push(make_games_screen()),
            on_open_tasks=lambda: app.manager.push(
                TasksScreen(on_back=app.manager.pop, todoist=todoist)
            ),
            on_open_agenda=lambda: app.manager.push(
                AgendaScreen(on_back=app.manager.pop, calendar=calendar)
            ),
            on_open_pomodoro=lambda: app.manager.push(pomodoro),
            on_open_photo=lambda: app.manager.push(
                PhotoScreen(
                    on_back=app.manager.pop,
                    camera=camera,
                    on_open_gallery=lambda: app.manager.push(
                        GalleryScreen(on_back=app.manager.pop, photos_dir=PHOTOS_DIR)
                    ),
                )
            ),
            on_open_sysinfo=lambda: app.manager.push(
                SysInfoScreen(on_back=app.manager.pop, sysinfo=sysinfo)
            ),
            on_open_teste=lambda: app.manager.push(
                AITestScreen(on_back=app.manager.pop, voice=voice, camera=camera,
                             sysinfo=sysinfo, chat=chat, button=ptt_button,
                             on_respond=handle_ai_response)
            ),
            on_open_settings=lambda: app.manager.push(make_settings()),
        )

    def on_setting_change(key, value) -> None:
        if key == "voice_enabled":
            voice.set_enabled(bool(value))
        elif key == "mic_device" and config.get("voice_enabled"):
            # reabre a escuta no novo microfone
            voice.set_enabled(False)
            voice.set_enabled(True)

    def make_settings() -> SettingsScreen:
        return SettingsScreen(
            on_back=app.manager.pop,
            on_open=app.manager.push,
            on_change=on_setting_change,
            mic_options=voice.list_input_devices,
            on_cleanup=cleanup_hardware,
        )

    # ---- comandos de voz -> navegação (executados no main thread) ----
    def _cmd(fn):
        return lambda: voice_enqueue(fn)

    voice.register_command(["agenda", "calendario", "compromisso"],
                           _cmd(lambda: app.manager.push(AgendaScreen(on_back=app.manager.pop, calendar=calendar))))
    voice.register_command(["foco", "pomodoro", "concentra"],
                           _cmd(lambda: app.manager.push(pomodoro)))
    voice.register_command(["tarefa", "tarefas", "kanban", "board"],
                           _cmd(lambda: app.manager.push(TasksScreen(on_back=app.manager.pop, todoist=todoist))))
    voice.register_command(["sistema", "hardware", "temperatura", "cpu"],
                           _cmd(lambda: app.manager.push(SysInfoScreen(on_back=app.manager.pop, sysinfo=sysinfo))))
    voice.register_command(["foto", "fotos", "camera"],
                           _cmd(lambda: app.manager.push(
                               PhotoScreen(on_back=app.manager.pop, camera=camera,
                                           on_open_gallery=lambda: app.manager.push(
                                               GalleryScreen(on_back=app.manager.pop, photos_dir=PHOTOS_DIR))))))
    voice.register_command(["configura", "ajuste", "settings"], _cmd(lambda: app.manager.push(make_settings())))
    voice.register_command(["menu", "inicio", "casa", "home"], _cmd(open_home))
    voice.register_command(["relogio", "horas", "tela inicial", "descanso"], _cmd(go_ambient))

    def do_update() -> None:
        """Baixa a última versão (git reset --hard origin/main) e reinicia.
        Libera o hardware antes do execv (ver cleanup_hardware)."""
        try:
            cleanup_hardware()
        except Exception:
            pass
        root = str(config.REPO_ROOT)
        try:
            subprocess.run(["git", "-C", root, "fetch", "--quiet", "origin", "main"],
                           timeout=60, check=False)
            subprocess.run(["git", "-C", root, "reset", "--hard", "origin/main"],
                           timeout=60, check=False)
        except Exception:
            pass
        pygame.quit()
        os.execv(sys.executable, [sys.executable, *sys.argv])

    # ---- LLM pode abrir telas / agir: chave (do JSON do chat) -> ação ----
    # As chaves espelham SCREENS_DOC em services/chat.py.
    screen_actions = {
        "agenda": lambda: app.manager.push(AgendaScreen(on_back=app.manager.pop, calendar=calendar)),
        "tarefas": lambda: app.manager.push(TasksScreen(on_back=app.manager.pop, todoist=todoist)),
        "foco": lambda: app.manager.push(pomodoro),
        "sistema": lambda: app.manager.push(SysInfoScreen(on_back=app.manager.pop, sysinfo=sysinfo)),
        "foto": lambda: app.manager.push(
            PhotoScreen(on_back=app.manager.pop, camera=camera,
                        on_open_gallery=lambda: app.manager.push(
                            GalleryScreen(on_back=app.manager.pop, photos_dir=PHOTOS_DIR)))),
        "jogos": lambda: app.manager.push(make_games_screen()),
        "pong": lambda: app.manager.push(PongScreen(on_back=app.manager.pop)),
        "invaders": lambda: app.manager.push(SpaceInvadersScreen(on_back=app.manager.pop)),
        "configuracoes": lambda: app.manager.push(make_settings()),
        # relógio explícito (NÃO o ambient configurado, que pode ser face/pong)
        "relogio": lambda: app.manager.replace(_instantiate_ambient("clock")),
        "home": open_home,
        "atualizar": do_update,
    }

    def handle_ai_response(text: str) -> None:
        """Roda na thread de voz: manda o texto pro LLM e, conforme a resposta,
        cria tarefa no Todoist e/ou enfileira a navegação pra main thread."""
        if not (text and chat.available):
            return
        chat.ask(text)   # atualiza last_msg / last_error / last_screen / last_task
        task = (getattr(chat, "last_task", "") or "").strip()
        if task:
            try:
                todoist.create(task)
            except Exception:
                pass
        action = screen_actions.get((getattr(chat, "last_screen", "") or "").strip())
        if action is not None:
            voice_enqueue(action)

    def frame_hook(_dt: float) -> None:
        # Roda todo frame (main thread).
        # 1) drena comandos de voz pendentes (a thread de voz só enfileira)
        while True:
            with voice_lock:
                fn = voice_queue.pop(0) if voice_queue else None
            if fn is None:
                break
            try:
                fn()
            except Exception:
                pass
        # 2) se um evento está próximo, empilha a AlertScreen por cima de
        # qualquer tela (relógio, jogo, suspended...)
        if isinstance(app.manager.current, AlertScreen):
            return
        snap = calendar.get()
        if not snap.ok:
            return
        warn = int(config.get("event_warning_min") or 10)
        ev = alerter.check(snap.events, warn)
        if ev is not None:
            app.manager.push(AlertScreen(event=ev, on_dismiss=app.manager.pop))

    app.frame_hook = frame_hook

    # estado do rodapé de voz: guarda a última resposta + até quando exibi-la
    ai_overlay = {"msg": "", "until": 0.0}
    RESP_SHOW_S = 7.0

    def draw_voice_overlay(canvas) -> None:
        """Rodapé POR CIMA de qualquer tela: GRAVANDO / PENSANDO durante o
        push-to-talk e a resposta do BMO por alguns segundos depois."""
        busy = getattr(voice, "busy", False)
        status = (getattr(voice, "status", "") or "").lower()
        now = time.time()
        msg = (getattr(chat, "last_msg", "") or "").strip()
        thinking = (msg == "...")   # LLM em andamento (chat.ask marca "...")
        # detecta nova resposta do BMO pra exibir por RESP_SHOW_S segundos
        if msg and msg != "..." and msg != ai_overlay["msg"]:
            ai_overlay["msg"] = msg
            ai_overlay["until"] = now + RESP_SHOW_S
        showing_resp = now < ai_overlay["until"] and bool(ai_overlay["msg"])
        if not (busy or thinking or showing_resp):
            return

        if busy and ("grav" in status or "ouv" in status):
            label, color, body = "GRAVANDO", Colors.RED, ""
        elif busy or thinking:
            label, color, body = "PENSANDO", Colors.YELLOW, ""
        else:
            label, color, body = "BMO", Colors.CYAN, ai_overlay["msg"]

        w, h = LOGICAL_SIZE
        bar_h = 16
        strip = pygame.Surface((w, bar_h))
        strip.set_alpha(205)
        strip.fill((0, 0, 0))
        canvas.blit(strip, (0, h - bar_h))
        cy = h - bar_h // 2
        pygame.draw.circle(canvas, color, (8, cy), 3)
        lbl = render_text(label, 9, color, pixel=False)
        canvas.blit(lbl, lbl.get_rect(midleft=(16, cy)))
        if body:
            avail = w - (16 + lbl.get_width() + 8) - 6
            maxn = max(8, avail // 4)   # ~4px por char no font 8
            body = body if len(body) <= maxn else body[: maxn - 1] + "."
            img = render_text(body, 8, Colors.WHITE, pixel=False)
            canvas.blit(img, img.get_rect(midleft=(16 + lbl.get_width() + 8, cy)))

    app.overlay_hook = draw_voice_overlay
    return make_ambient()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fullscreen", action="store_true")
    args = parser.parse_args()

    # mixer precisa ser inicializado ANTES do pygame.init (App.__init__)
    # pra os pre_init params (sample rate, buffer) valerem
    audio.init()
    audio.set_volume((config.get("volume") or 100) / 100)

    app = App(fullscreen=args.fullscreen)
    app.run(build_initial(app))


if __name__ == "__main__":
    main()
