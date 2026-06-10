"""Dev Hub — feed de commits, CI/CD e logs vindos do PC (Cursor / git / webhooks).

O PC manda eventos via POST /dev no PairingServer (porta 8377):
    {"type": "commit", "repo": "BMO", "sha": "abc1234", "msg": "...", "author": "JP"}
    {"type": "ci", "repo": "BMO", "branch": "main", "status": "success", "name": "CI"}
    {"type": "log", "source": "cursor", "level": "error", "text": "..."}
    {"type": "batch", "events": [ ... ]}

O script scripts/bimo_dev_bridge.py no PC coleta git log, GitHub Actions (gh)
e um arquivo de eventos do Cursor (.bimo/dev_events.jsonl).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class DevCommit:
    repo: str
    sha: str
    msg: str
    author: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class DevCI:
    repo: str
    branch: str
    status: str      # success | failure | pending | unknown
    name: str = "CI"
    ts: float = field(default_factory=time.time)


@dataclass
class DevLog:
    source: str
    level: str       # info | warn | error
    text: str
    ts: float = field(default_factory=time.time)


class DevHubService:
    MAX_COMMITS = 40
    MAX_CI = 8
    MAX_LOGS = 20

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.commits: deque[DevCommit] = deque(maxlen=self.MAX_COMMITS)
        self.ci: deque[DevCI] = deque(maxlen=self.MAX_CI)
        self.logs: deque[DevLog] = deque(maxlen=self.MAX_LOGS)
        self.last_event_at = 0.0
        self.events_total = 0

    def ingest_http(self, payload: dict) -> dict:
        """Handler do POST /dev. Aceita um evento ou batch."""
        if not isinstance(payload, dict):
            return {"ok": False, "error": "payload invalido"}
        if payload.get("type") == "batch":
            events = payload.get("events") or []
            n = 0
            for ev in events:
                if isinstance(ev, dict) and self._ingest_one(ev):
                    n += 1
            return {"ok": True, "ingested": n}
        ok = self._ingest_one(payload)
        return {"ok": ok, "error": "" if ok else "tipo desconhecido"}

    def _ingest_one(self, ev: dict) -> bool:
        kind = str(ev.get("type", "")).strip().lower()
        if kind == "commit":
            sha = str(ev.get("sha", "")).strip()
            msg = str(ev.get("msg", ev.get("message", ""))).strip()
            if not sha and not msg:
                return False
            self.add_commit(DevCommit(
                repo=str(ev.get("repo", "?")).strip() or "?",
                sha=sha[:12],
                msg=msg[:120],
                author=str(ev.get("author", "")).strip()[:40],
            ))
            return True
        if kind == "ci":
            status = str(ev.get("status", "unknown")).strip().lower()
            if status in ("ok", "passed", "pass"):
                status = "success"
            elif status in ("fail", "failed", "error"):
                status = "failure"
            elif status in ("running", "in_progress", "queued"):
                status = "pending"
            self.add_ci(DevCI(
                repo=str(ev.get("repo", "?")).strip() or "?",
                branch=str(ev.get("branch", "main")).strip()[:24],
                status=status,
                name=str(ev.get("name", "CI")).strip()[:32],
            ))
            return True
        if kind == "log":
            text = str(ev.get("text", ev.get("message", ""))).strip()
            if not text:
                return False
            level = str(ev.get("level", "info")).strip().lower()
            if level not in ("info", "warn", "error"):
                level = "info"
            self.add_log(DevLog(
                source=str(ev.get("source", "pc")).strip()[:20] or "pc",
                level=level,
                text=text[:200],
            ))
            return True
        return False

    def add_commit(self, c: DevCommit) -> None:
        with self._lock:
            # dedup por sha+repo
            for old in self.commits:
                if old.sha == c.sha and old.repo == c.repo:
                    return
            self.commits.appendleft(c)
            self._touch()

    def add_ci(self, ci: DevCI) -> None:
        with self._lock:
            # atualiza CI do mesmo repo+branch se já existe
            for i, old in enumerate(self.ci):
                if old.repo == ci.repo and old.branch == ci.branch:
                    self.ci[i] = ci
                    self._touch()
                    return
            self.ci.appendleft(ci)
            self._touch()

    def add_log(self, log: DevLog) -> None:
        with self._lock:
            self.logs.appendleft(log)
            self._touch()

    def _touch(self) -> None:
        self.last_event_at = time.time()
        self.events_total += 1

    def snapshot(self) -> dict:
        """Cópia thread-safe pra UI."""
        with self._lock:
            return {
                "commits": list(self.commits),
                "ci": list(self.ci),
                "logs": list(self.logs),
                "last_event_at": self.last_event_at,
                "events_total": self.events_total,
            }

    def ci_summary(self) -> list[DevCI]:
        """Último status por repo (pra faixa do topo)."""
        with self._lock:
            seen: dict[str, DevCI] = {}
            for c in self.ci:
                if c.repo not in seen:
                    seen[c.repo] = c
            return list(seen.values())[:4]
