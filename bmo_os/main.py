"""Ponto de entrada do BMO OS.

Uso:
    python -m bmo_os.main             # janelado, ótimo pra desenvolver no PC
    python -m bmo_os.main --fullscreen # no Pi
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# permite rodar tanto como módulo quanto como script direto
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bmo_os.core import config
from bmo_os.core.app import App
from bmo_os.screens.bmo_face import BMOFaceScreen
from bmo_os.screens.clock import ClockScreen
from bmo_os.screens.games import GamesScreen, draw_space_invaders_icon
from bmo_os.screens.home import HomeScreen
from bmo_os.screens.settings import SettingsScreen
from bmo_os.screens.sleep import SleepScreen
from bmo_os.screens.space_invaders import SpaceInvadersScreen
from bmo_os.screens.tasks import TasksScreen
from bmo_os.services.git_updates import GitUpdatesService
from bmo_os.services.todoist import TodoistService


def build_initial(app: App):
    # Cache pra reaproveitar a mesma instância de cada ambient — evita criar
    # uma WeatherService nova (e portanto uma thread) toda vez que a home volta.
    ambient_cache: dict = {}

    # Singleton de Todoist (thread + cache vivem aqui)
    todoist = TodoistService()
    # Detector de git updates (só usado pelo clock pra mostrar alerta)
    git_updates = GitUpdatesService()

    def make_ambient():
        mode = config.get("ambient_mode")
        if mode not in ambient_cache:
            if mode == "face":
                ambient_cache[mode] = BMOFaceScreen(on_open_home=open_home)
            else:
                ambient_cache[mode] = ClockScreen(on_open_home=open_home, git_updates=git_updates)
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
            ],
        )

    def make_home() -> HomeScreen:
        return HomeScreen(
            on_back=go_ambient,
            on_open_sleep=lambda: app.manager.push(
                SleepScreen(on_back=app.manager.pop, on_select_mode=select_ambient)
            ),
            on_open_games=lambda: app.manager.push(make_games_screen()),
            on_open_tasks=lambda: app.manager.push(
                TasksScreen(on_back=app.manager.pop, todoist=todoist)
            ),
            on_open_settings=lambda: app.manager.push(
                SettingsScreen(on_back=app.manager.pop, on_ambient_changed=lambda _m: None)
            ),
        )

    return make_ambient()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fullscreen", action="store_true")
    args = parser.parse_args()

    app = App(fullscreen=args.fullscreen)
    app.run(build_initial(app))


if __name__ == "__main__":
    main()
