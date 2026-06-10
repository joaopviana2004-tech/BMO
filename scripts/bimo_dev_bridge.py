#!/usr/bin/env python3
"""Ponte Dev Hub: manda commits, CI e logs do PC/Cursor pro Bimo (POST /dev).

O Bimo mostra tudo na tela DEV HUB. Rode no PC enquanto desenvolve no Cursor.

Uso basico (vigia git + GitHub Actions + arquivo do Cursor):
    python scripts/bimo_dev_bridge.py 192.168.0.109 --repo .
    python scripts/bimo_dev_bridge.py 192.168.0.109 --repo . --repo ../Games

Enviar um evento manual (git hook, task do Cursor, terminal):
    python scripts/bimo_dev_bridge.py 192.168.0.109 --send commit \\
        --sha abc1234 --msg "fix audio" --author JP --repo BMO
    python scripts/bimo_dev_bridge.py 192.168.0.109 --send log \\
        --level error --text "TypeError no main.py" --source cursor
    python scripts/bimo_dev_bridge.py 192.168.0.109 --send ci \\
        --repo BMO --status success --branch main

Integracao com Cursor (opcional):
  1) Crie .bimo/dev_events.jsonl na raiz do projeto
  2) Em Cursor Settings > Hooks ou numa Task, append uma linha JSON por evento:
       {"type":"log","source":"cursor","level":"info","text":"Agent finished"}
  3) Este script vigia esse arquivo e envia pro Bimo automaticamente.

Git hook (post-commit automatico):
    python scripts/bimo_dev_bridge.py 192.168.0.109 --install-hook --repo .
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT = 8377
ROOT = Path(__file__).resolve().parent.parent
CURSOR_EVENTS = ".bimo/dev_events.jsonl"


def post(bimo: str, payload: dict, timeout: int = 8) -> bool:
    req = urllib.request.Request(
        f"http://{bimo}:{PORT}/dev",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp).get("ok", False)
    except Exception as e:
        print(f"  ! Bimo: {e}")
        return False


def git_latest(repo: Path) -> dict | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo), "log", "-1",
             "--format=%H|%s|%an|%ct"],
            stderr=subprocess.DEVNULL, text=True, timeout=10,
        ).strip()
    except Exception:
        return None
    if not out or "|" not in out:
        return None
    sha, msg, author, ts = out.split("|", 3)
    name = repo.name
    try:
        remote = subprocess.check_output(
            ["git", "-C", str(repo), "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).strip()
        if remote:
            part = remote.rstrip("/").replace(".git", "").split("/")[-1]
            if part:
                name = part
    except Exception:
        pass
    return {
        "type": "commit",
        "repo": name,
        "sha": sha[:12],
        "msg": msg[:120],
        "author": author[:40],
        "ts": float(ts),
    }


def gh_ci_runs(repo: Path, limit: int = 3) -> list[dict]:
    """CI via `gh run list` (precisa gh auth login)."""
    try:
        out = subprocess.check_output(
            ["gh", "run", "list", "--limit", str(limit), "--json",
             "headBranch,status,conclusion,name,createdAt"],
            cwd=str(repo), stderr=subprocess.DEVNULL, text=True, timeout=20,
        )
        runs = json.loads(out)
    except Exception:
        return []
    name = repo.name
    events = []
    status_map = {
        "completed": "unknown",
        "in_progress": "pending",
        "queued": "pending",
        "success": "success",
        "failure": "failure",
    }
    for r in runs:
        st = r.get("status", "")
        conc = r.get("conclusion") or ""
        if st == "completed":
            ci_st = status_map.get(conc, "unknown")
        else:
            ci_st = status_map.get(st, "pending")
        events.append({
            "type": "ci",
            "repo": name,
            "branch": (r.get("headBranch") or "main")[:24],
            "status": ci_st,
            "name": (r.get("name") or "CI")[:32],
        })
    return events


def read_cursor_events(path: Path, offset: int) -> tuple[list[dict], int]:
    """Le novas linhas JSONL do arquivo de eventos do Cursor."""
    if not path.is_file():
        return [], offset
    try:
        data = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return [], offset
    if len(data) < offset:
        offset = 0
    chunk = data[offset:]
    new_off = len(data)
    out = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            if isinstance(ev, dict) and ev.get("type"):
                out.append(ev)
        except json.JSONDecodeError:
            out.append({
                "type": "log",
                "source": "cursor",
                "level": "info",
                "text": line[:200],
            })
    return out, new_off


def install_hook(bimo: str, repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "post-commit"
    script = Path(__file__).resolve()
    py = sys.executable
    block = f'''
# bimo dev hub (auto)
"{py}" "{script}" {bimo} --send-commit-from-hook --repo "{repo.resolve()}"
'''
    old = ""
    if hook.is_file():
        old = hook.read_text(encoding="utf-8", errors="ignore")
        if "bimo dev hub" in old:
            print("hook ja instalado")
            return
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n" + old + block, encoding="utf-8")
    try:
        hook.chmod(hook.stat().st_mode | 0o111)
    except Exception:
        pass
    print(f"hook instalado: {hook}")


def send_commit_from_hook(bimo: str, repo: Path) -> None:
    ev = git_latest(repo)
    if ev:
        post(bimo, ev)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dev Hub bridge PC -> Bimo")
    parser.add_argument("bimo", nargs="?", default="",
                        help="IP do Bimo (ex: 192.168.0.109)")
    parser.add_argument("--repo", action="append", default=[],
                        help="pasta git pra vigiar (repita p/ varios)")
    parser.add_argument("--interval", type=int, default=12,
                        help="segundos entre polls (padrao 12)")
    parser.add_argument("--once", action="store_true", help="um ciclo e sai")
    parser.add_argument("--send", choices=["commit", "ci", "log"],
                        help="envia UM evento e sai")
    parser.add_argument("--sha", default="")
    parser.add_argument("--msg", default="")
    parser.add_argument("--author", default="")
    parser.add_argument("--repo-name", default="")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--status", default="success")
    parser.add_argument("--name", default="CI")
    parser.add_argument("--level", default="info")
    parser.add_argument("--text", default="")
    parser.add_argument("--source", default="cursor")
    parser.add_argument("--install-hook", action="store_true")
    parser.add_argument("--send-commit-from-hook", action="store_true")
    args = parser.parse_args()

    bimo = (args.bimo or os.environ.get("BIMO_IP", "")).strip()
    if not bimo:
        print("ERRO: informe o IP do Bimo ou defina BIMO_IP no ambiente")
        return 1

    repos = [Path(r).expanduser().resolve() for r in (args.repo or ["."])]
    if args.install_hook:
        for r in repos:
            if (r / ".git").is_dir():
                install_hook(bimo, r)
        return 0

    if args.send_commit_from_hook:
        for r in repos:
            send_commit_from_hook(bimo, r)
        return 0

    if args.send:
        if args.send == "commit":
            payload = {
                "type": "commit",
                "repo": args.repo_name or repos[0].name,
                "sha": args.sha,
                "msg": args.msg,
                "author": args.author,
            }
        elif args.send == "ci":
            payload = {
                "type": "ci",
                "repo": args.repo_name or repos[0].name,
                "branch": args.branch,
                "status": args.status,
                "name": args.name,
            }
        else:
            payload = {
                "type": "log",
                "source": args.source,
                "level": args.level,
                "text": args.text,
            }
        ok = post(bimo, payload)
        print("ok" if ok else "falhou")
        return 0 if ok else 1

    seen_shas: dict[str, str] = {}
    cursor_path = (repos[0] / CURSOR_EVENTS).resolve()
    cursor_off = 0
    print(f"Dev bridge -> {bimo}:{PORT}")
    print(f"Repos: {', '.join(str(r) for r in repos)}")
    print(f"Cursor events: {cursor_path}")
    print("Ctrl+C para sair\n")

    while True:
        events: list[dict] = []
        for repo in repos:
            if not (repo / ".git").is_dir():
                continue
            ev = git_latest(repo)
            if ev:
                key = f"{ev['repo']}:{ev['sha']}"
                if seen_shas.get(key) != ev["msg"]:
                    seen_shas[key] = ev["msg"]
                    events.append(ev)
            events.extend(gh_ci_runs(repo))
        cursor_ev, cursor_off = read_cursor_events(cursor_path, cursor_off)
        events.extend(cursor_ev)

        if events:
            stamp = time.strftime("%H:%M:%S")
            if post(bimo, {"type": "batch", "events": events}):
                print(f"[{stamp}] {len(events)} evento(s) enviado(s)")
            else:
                print(f"[{stamp}] falha ao enviar")

        if args.once:
            return 0
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ntchau!")
        raise SystemExit(0)
