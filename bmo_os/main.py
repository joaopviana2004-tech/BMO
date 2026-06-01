"""Ponto de entrada do BMO OS.

Uso:
    python -m bmo_os.main             # janelado, ótimo pra desenvolver no PC
    python -m bmo_os.main --fullscreen # no Pi
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

# permite rodar tanto como módulo quanto como script direto
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bmo_os.core import config
from bmo_os.core.app import App
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
from bmo_os.services.gcalendar import CalendarService
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
    # Audição (wake word "BMO" + Whisper). No PC degrada pra "indisponivel".
    voice = VoiceService()
    # Fila de ações dos comandos de voz: o wake-loop roda em thread, então
    # empilhamos a navegação aqui e executamos no main thread (frame_hook).
    voice_queue: list = []
    voice_lock = threading.Lock()

    def voice_enqueue(fn):
        with voice_lock:
            voice_queue.append(fn)

    def _instantiate_ambient(mode):
        if mode == "face":
            return BMOFaceScreen(on_open_home=open_home, camera=camera)
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
                AITestScreen(on_back=app.manager.pop, voice=voice, camera=camera)
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
