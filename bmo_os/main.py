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

from bmo_os.core.app import App
from bmo_os.screens.clock import ClockScreen
from bmo_os.screens.home import HomeScreen
from bmo_os.screens.placeholder import PlaceholderScreen
from bmo_os.screens.settings import SettingsScreen
from bmo_os.screens.sleep import SleepScreen


def build_initial(app: App):
    def open_home() -> None:
        app.manager.push(make_home())

    def make_home() -> HomeScreen:
        return HomeScreen(
            on_back=app.manager.pop,
            on_open_sleep=lambda: app.manager.push(SleepScreen(on_back=app.manager.pop)),
            on_open_games=lambda: app.manager.push(PlaceholderScreen("BMO'S GAMES", app.manager.pop)),
            on_open_settings=lambda: app.manager.push(SettingsScreen(on_back=app.manager.pop)),
        )

    return ClockScreen(on_open_home=open_home)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fullscreen", action="store_true")
    args = parser.parse_args()

    app = App(fullscreen=args.fullscreen)
    app.run(build_initial(app))


if __name__ == "__main__":
    main()
