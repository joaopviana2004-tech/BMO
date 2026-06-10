#!/usr/bin/env python3
"""Converse com o Bimo digitando do PC (teste da futura extensão desktop).

A mensagem viaja pela rede local até o Bimo (porta 8377) e entra no MESMO
caminho da fala: LLM (incl. o provedor LOCAL/Ollama, se escolhido em
SETTINGS -> IA), memória, busca nas notas do Obsidian (tool notes_query),
abertura de telas e a voz — o Bimo FALA a resposta na rasp e ela também
volta aqui no terminal.

Uso:
    python scripts/bimo_chat.py 192.168.0.109            # REPL interativo
    python scripts/bimo_chat.py 192.168.0.109 -m "oi!"   # uma mensagem e sai
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

PORT = 8377

# console do Windows costuma ser cp1252 e quebra nos emojis do Bimo
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def send(host: str, text: str, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        f"http://{host}:{PORT}/chat",
        data=json.dumps({"text": text}).encode(),
        method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def show(res: dict) -> None:
    msg = (res.get("msg") or "").strip()
    err = (res.get("error") or "").strip()
    if msg:
        print(f"bimo> {msg}")
    extras = []
    if res.get("screen"):
        extras.append(f"abriu a tela '{res['screen']}'")
    if res.get("task"):
        extras.append(f"criou a tarefa '{res['task']}'")
    if extras:
        print(f"      [{' / '.join(extras)}]")
    if err and not msg:
        print(f"erro> {err}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Chat de texto com o Bimo.")
    parser.add_argument("bimo", help="IP do Bimo na rede (ex: 192.168.0.109)")
    parser.add_argument("-m", "--message", default="",
                        help="manda UMA mensagem e sai (senao abre o REPL)")
    args = parser.parse_args()

    if args.message:
        try:
            show(send(args.bimo, args.message))
            return 0
        except Exception as e:
            print(f"erro> nao falei com o Bimo em {args.bimo}:{PORT} — {e}")
            return 1

    print(f"Conversando com o Bimo em {args.bimo}:{PORT}")
    print("(Ctrl+C ou linha vazia pra sair)\n")
    while True:
        try:
            text = input("voce> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not text:
            break
        try:
            show(send(args.bimo, text))
        except urllib.error.URLError as e:
            print(f"erro> sem resposta do Bimo ({e.reason}) — ele esta ligado?")
        except Exception as e:
            print(f"erro> {e}")
    print("tchau!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
