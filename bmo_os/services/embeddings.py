"""Cliente de embeddings do BMO (RAG vetorial).

Fala com um endpoint OpenAI-compatível de embeddings (`/v1/embeddings`) —
**Ollama** (porta 11434, `ollama pull bge-m3`) ou llama.cpp em modo embedding.
Sem dependência pesada: urllib puro.

MECÂNICA: o embedding (caro) é gerado NO PC. O builder (scripts/build_rag_index.py)
embeda todos os chunks de uma vez e manda o índice pronto pra Rasp. Em runtime, a
Rasp só embeda a QUERY (1 texto curto) chamando o MESMO endpoint do PC pela LAN —
o resto (cosseno) é local e leve.

Endpoint: config `embed_url` (UI) > .env EMBED_URL > padrão 127.0.0.1:11434.
Na Rasp, aponte pro PC (ex.: EMBED_URL=jp-predator.local:11434 no .env).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..core import config

DEFAULT_EMBED_URL = "http://127.0.0.1:11434/v1/embeddings"


def _normalize(value: str, default_port: int = 11434) -> str:
    """Aceita URL completa, 'host' ou 'host:porta' e devolve a URL de
    /v1/embeddings. '' -> ''."""
    v = (value or "").strip()
    if not v:
        return ""
    if "://" in v:
        v = v.rstrip("/")
        if v.endswith("/embeddings"):
            return v
        if v.endswith("/v1"):
            return v + "/embeddings"
        return v + "/v1/embeddings"
    if ":" not in v:
        v += f":{default_port}"
    return f"http://{v}/v1/embeddings"


def embed_url() -> str:
    """URL do /v1/embeddings: config `embed_url` > EMBED_URL (.env) > padrão
    Ollama no 127.0.0.1:11434. Nunca volta ''."""
    cfg = (config.get("embed_url") or "").strip()
    if cfg:
        return _normalize(cfg)
    env = os.environ.get("EMBED_URL", "").strip()
    if env:
        return _normalize(env)
    return DEFAULT_EMBED_URL


def model() -> str:
    return (config.get("embed_model") or "bge-m3").strip()


def embed(texts: list[str], *, timeout: int = 60, batch: int = 32) -> list[list[float]] | None:
    """Embeda uma lista de textos -> lista de vetores (float). None em falha
    (rede/endpoint fora) — o chamador cai pro léxico. Vetores NÃO normalizados
    (quem usa normaliza)."""
    if not texts:
        return []
    url = embed_url()
    mdl = model()
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        chunk = texts[i:i + batch]
        payload = json.dumps({"model": mdl, "input": chunk}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer ollama")  # placeholder (Ollama ignora)
        req.add_header("User-Agent", "BMO-OS/1.0")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return None
        rows = data.get("data") or []
        if len(rows) != len(chunk):
            return None
        for r in rows:
            vec = r.get("embedding")
            if not isinstance(vec, list) or not vec:
                return None
            out.append([float(x) for x in vec])
    return out


def embed_one(text: str, *, timeout: int = 20) -> list[float] | None:
    """Embeda 1 texto (a query, em runtime na Rasp). None em falha."""
    res = embed([text], timeout=timeout)
    return res[0] if res else None


def available() -> bool:
    """True se o endpoint de embeddings responde (faz um embed de teste curto)."""
    return embed_one("ping") is not None
