"""Ponto de entrada:  python -m game.main   (ou  python game/main.py)"""
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.game import App  # noqa: E402


def main():
    App().run()


if __name__ == "__main__":
    main()
