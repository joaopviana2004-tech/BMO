"""Builder do índice vetorial do RAG — RODA NO PC (onde está o Ollama).

Mecânica: o embedding é caro, então é gerado AQUI no PC; a Rasp recebe o índice
pronto e só faz cosseno (leve). Fluxo:

  1. GET  http://<rasp>:8000/api/brain/export   -> baixa as notas da Rasp
  2. chunka com o MESMO chunk_markdown do BMO (paridade de chaves)
  3. embeda cada chunk no Ollama local (/v1/embeddings, bge-m3) — com cache
  4. POST http://<rasp>:8000/api/brain/index     -> manda o índice pronto

Pré-requisito: Ollama rodando no PC e o modelo baixado (`ollama pull bge-m3`).

Uso:
    python scripts/build_rag_index.py --pi 192.168.0.109:8000
    python scripts/build_rag_index.py --pi raspberrypi:8000 --model bge-m3

Re-rode quando mudar/criar notas (o cache evita re-embedar o que não mudou).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bmo_os.core import config                         # noqa: E402
from bmo_os.services import embeddings                 # noqa: E402
from bmo_os.services.knowledge import chunk_markdown, chunk_hash  # noqa: E402
from bmo_os.services.vector_index import pack_index    # noqa: E402

CACHE = Path(__file__).resolve().parent / ".rag_cache.json"   # hash->vetor (gitignored)


def _get(url: str, timeout: int = 60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url: str, payload: dict, timeout: int = 180):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Builder do índice vetorial do RAG (no PC).")
    ap.add_argument("--pi", default="192.168.0.109:8000", help="host:porta do painel da Rasp")
    ap.add_argument("--embed-url", default="", help="endpoint /v1/embeddings (senão config/.env/127.0.0.1:11434)")
    ap.add_argument("--model", default="", help="modelo de embedding (senão config: bge-m3)")
    args = ap.parse_args()
    if args.embed_url:
        config.set_value("embed_url", args.embed_url)
    if args.model:
        config.set_value("embed_model", args.model)

    base = f"http://{args.pi}"
    print(f"[1/4] baixando notas de {base}/api/brain/export ...")
    exp = _get(f"{base}/api/brain/export")
    notes = exp.get("notes", [])
    level = int(exp.get("chunk_level", 2))
    print(f"      {len(notes)} notas (chunk_level={level})")

    chunks: list[dict] = []
    for n in notes:
        for ch in chunk_markdown(n.get("body", ""), level):
            txt = ch.get("text", "")
            if not txt.strip() and not ch.get("section"):
                continue
            chunks.append({"note_id": n["id"], "section": ch["section"],
                           "text": txt, "hash": chunk_hash(txt)})
    print(f"[2/4] {len(chunks)} chunks")

    model = embeddings.model()
    cache: dict = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    def ckey(h: str) -> str:
        return f"{model}:{h}"

    todo = [c for c in chunks if ckey(c["hash"]) not in cache]
    print(f"[3/4] embedando {len(todo)} novos (reuso do cache: {len(chunks) - len(todo)}) "
          f"via {embeddings.embed_url()} [{model}] ...")
    if todo:
        vecs = embeddings.embed([c["text"] for c in todo], timeout=600)
        if not vecs:
            print("ERRO: embedding falhou. Ollama no ar? `ollama pull bge-m3` feito?")
            sys.exit(1)
        for c, v in zip(todo, vecs):
            cache[ckey(c["hash"])] = v
        CACHE.write_text(json.dumps(cache), encoding="utf-8")

    items, dim = [], 0
    for c in chunks:
        v = cache.get(ckey(c["hash"]))
        if not v:
            continue
        dim = dim or len(v)
        items.append({"note_id": c["note_id"], "section": c["section"],
                      "hash": c["hash"], "vector": v})
    if not items:
        print("ERRO: nenhum vetor gerado.")
        sys.exit(1)

    index = pack_index(model, dim, items)
    print(f"[4/4] enviando índice ({index['count']} chunks, dim={dim}) "
          f"pra {base}/api/brain/index ...")
    res = _post(f"{base}/api/brain/index", index)
    print("      resposta:", res)
    print("OK." if res.get("ok") else "FALHOU.")


if __name__ == "__main__":
    main()
