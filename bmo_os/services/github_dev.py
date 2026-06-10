"""GitHub -> Dev Hub: puxa commits, CI, stats e atividade direto da API.

Configura no .env da rasp (ou PC em dev):
    GITHUB_USER=seu_login
    GITHUB_TOKEN=ghp_...          (recomendado — mais rate limit + repos privados)
    GITHUB_REPOS=BMO,Games          (opcional; vazio = top repos por push recente)

Roda em thread de background e alimenta o DevHubService.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .dev_hub import DevCI, DevCommit, DevHubService

API = "https://api.github.com"
POLL_S = 150.0   # ~2.5 min — gentil com o rate limit


@dataclass
class DevHubStats:
    github_user: str = ""
    display_name: str = ""
    commits_today: int = 0
    commits_week: int = 0
    streak_days: int = 0
    repos_total: int = 0
    repos_active: int = 0
    stars_total: int = 0
    ci_pass_pct: int = 0          # 0-100
    top_language: str = ""
    week_bars: list = field(default_factory=lambda: [0] * 7)   # últimos 7 dias
    last_sync: float = 0.0
    sync_error: str = ""


def _parse_github_ts(ts: str) -> float:
    try:
        return datetime.fromisoformat(
            ts.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except Exception:
        return 0.0


def _day_key(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


class GitHubPoller:
    def __init__(self, hub: DevHubService) -> None:
        self.hub = hub
        self.user = os.environ.get("GITHUB_USER", "").strip()
        self.token = os.environ.get("GITHUB_TOKEN", "").strip()
        raw = os.environ.get("GITHUB_REPOS", "").strip()
        self.repos_override = [r.strip() for r in raw.split(",") if r.strip()]
        self.stats = DevHubStats()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return bool(self.user or self.token)

    def start(self) -> None:
        if not self.available:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def get_stats(self) -> DevHubStats:
        with self._lock:
            return DevHubStats(**vars(self.stats))

    def _set_stats(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self.stats, k, v)

    def _api(self, path: str, params: dict | None = None) -> object | None:
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "BMO-OS/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode()).get("message", str(e))
            except Exception:
                err = str(e)
            self._set_stats(sync_error=str(err)[:60])
            return None
        except Exception as e:
            self._set_stats(sync_error=str(e)[:60])
            return None

    def _resolve_user(self) -> str:
        if self.user:
            return self.user
        if self.token:
            me = self._api("/user")
            if isinstance(me, dict) and me.get("login"):
                return me["login"]
        return ""

    def _loop(self) -> None:
        self._poll()
        while not self._stop.is_set():
            self._stop.wait(POLL_S)
            if not self._stop.is_set():
                self._poll()

    def _poll(self) -> None:
        user = self._resolve_user()
        if not user:
            self._set_stats(sync_error="GITHUB_USER ou TOKEN invalido")
            return

        profile = self._api(f"/users/{user}") or {}
        display = profile.get("name") or user
        repos_total = int(profile.get("public_repos") or 0)

        # repos monitorados
        repo_names = self._repo_list(user)
        if not repo_names:
            self._set_stats(github_user=user, display_name=display,
                            repos_total=repos_total, sync_error="sem repos")
            return

        # eventos públicos (feed rápido de pushes)
        events = self._api(f"/users/{user}/events/public", {"per_page": "100"})
        if not isinstance(events, list):
            events = []

        day_counts: dict[str, int] = {}
        stars = 0
        languages: dict[str, int] = {}
        repos_active = 0
        now = time.time()
        week_ago = now - 7 * 86400

        for full in repo_names:
            info = self._api(f"/repos/{full}")
            if isinstance(info, dict):
                stars += int(info.get("stargazers_count") or 0)
                lang = info.get("language") or ""
                if lang:
                    languages[lang] = languages.get(lang, 0) + 1
                pushed = _parse_github_ts(info.get("pushed_at", ""))
                if pushed >= week_ago:
                    repos_active += 1

        for ev in events:
            if ev.get("type") != "PushEvent":
                continue
            ts = _parse_github_ts(ev.get("created_at", ""))
            dk = _day_key(ts)
            n = len((ev.get("payload") or {}).get("commits") or [])
            if n < 1:
                n = 1
            day_counts[dk] = day_counts.get(dk, 0) + n
            repo_short = (ev.get("repo") or {}).get("name", "").split("/")[-1]
            for c in reversed((ev.get("payload") or {}).get("commits") or []):
                sha = str(c.get("sha", ""))[:12]
                msg = str(c.get("message", "")).split("\n")[0]
                author = ""
                commit_obj = c.get("author") or {}
                if isinstance(commit_obj, dict):
                    author = commit_obj.get("name", "") or ""
                self.hub.add_commit(DevCommit(
                    repo=repo_short or "?",
                    sha=sha,
                    msg=msg[:120],
                    author=author[:40],
                    ts=ts,
                ))

        # commits profundos por repo (pega o que events não cobre)
        for full in repo_names[:5]:
            short = full.split("/")[-1]
            page = self._api(f"/repos/{full}/commits", {"per_page": "15"})
            if not isinstance(page, list):
                continue
            for c in page:
                commit = c.get("commit") or {}
                ts = _parse_github_ts((commit.get("author") or {}).get("date", ""))
                if ts < week_ago:
                    break
                dk = _day_key(ts)
                day_counts[dk] = day_counts.get(dk, 0) + 1
                sha = str(c.get("sha", ""))[:12]
                msg = str(commit.get("message", "")).split("\n")[0]
                author = (commit.get("author") or {}).get("name", "")
                self.hub.add_commit(DevCommit(
                    repo=short, sha=sha, msg=msg[:120],
                    author=author[:40], ts=ts,
                ))

        # CI / Actions
        ci_ok = ci_total = 0
        for full in repo_names[:4]:
            short = full.split("/")[-1]
            runs = self._api(f"/repos/{full}/actions/runs", {"per_page": "5"})
            if not isinstance(runs, dict):
                continue
            for run in (runs.get("workflow_runs") or [])[:5]:
                conc = (run.get("conclusion") or "").lower()
                status = (run.get("status") or "").lower()
                if status != "completed":
                    st = "pending"
                elif conc == "success":
                    st = "success"
                    ci_ok += 1
                    ci_total += 1
                elif conc in ("failure", "cancelled", "timed_out"):
                    st = "failure"
                    ci_total += 1
                else:
                    st = "unknown"
                    continue
                self.hub.add_ci(DevCI(
                    repo=short,
                    branch=(run.get("head_branch") or "main")[:24],
                    status=st,
                    name=(run.get("name") or "CI")[:32],
                    ts=_parse_github_ts(run.get("updated_at", "")),
                ))

        today = _day_key(now)
        commits_today = day_counts.get(today, 0)
        commits_week = sum(day_counts.values())

        # barras dos últimos 7 dias (domingo..sábado visual = últimos 7 dias)
        week_bars = []
        for i in range(6, -1, -1):
            dk = _day_key(now - i * 86400)
            week_bars.append(day_counts.get(dk, 0))

        # streak: dias consecutivos com commit até hoje
        streak = 0
        for i in range(0, 366):
            dk = _day_key(now - i * 86400)
            if day_counts.get(dk, 0) > 0:
                streak += 1
            elif i == 0:
                continue   # hoje sem commit ainda não quebra
            else:
                break

        top_lang = max(languages, key=languages.get) if languages else ""
        ci_pct = int(100 * ci_ok / ci_total) if ci_total else 0

        self._set_stats(
            github_user=user,
            display_name=display[:20],
            commits_today=commits_today,
            commits_week=commits_week,
            streak_days=streak,
            repos_total=repos_total,
            repos_active=repos_active,
            stars_total=stars,
            ci_pass_pct=ci_pct,
            top_language=top_lang,
            week_bars=week_bars,
            last_sync=time.time(),
            sync_error="",
        )

    def _repo_list(self, user: str) -> list[str]:
        if self.repos_override:
            out = []
            for r in self.repos_override:
                if "/" in r:
                    out.append(r)
                else:
                    out.append(f"{user}/{r}")
            return out
        page = self._api(f"/users/{user}/repos", {
            "sort": "pushed", "direction": "desc", "per_page": "8",
            "type": "owner",
        })
        if not isinstance(page, list):
            return []
        return [r.get("full_name", "") for r in page if r.get("full_name")]
