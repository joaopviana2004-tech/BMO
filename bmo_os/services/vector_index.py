"""Índice vetorial leve do RAG do BMO — só cosseno, roda tranquilo na Rasp.

Os vetores (embeddings) são gerados NO PC (caro) e o índice pronto é entregue à
Rasp, que apenas faz a busca por cosseno (barato). O índice é um JSON compacto:

    {"model","dim","count",
     "keys":   [[note_id, section], ...],   # paralelo aos vetores
     "hashes": [hash_do_texto_do_chunk, ...],
     "vectors": "<base64 de float32 N*dim, JÁ NORMALIZADOS>"}

Não guarda o TEXTO do chunk: a Rasp re-deriva o texto das próprias notas pela
chave (note_id, section) com o mesmo chunk_markdown — economiza tamanho e garante
que o texto bate. `hash` deixa detectar chunk que mudou desde o build (vetor velho).

numpy é usado se disponível (rápido); senão cai num cosseno em Python puro
(suficiente pra alguns milhares de chunks).
"""
from __future__ import annotations

import base64
import math
from array import array

try:
    import numpy as _np
    HAS_NUMPY = True
except Exception:  # noqa: BLE001
    _np = None
    HAS_NUMPY = False


def _normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def pack_index(model: str, dim: int, items: list[dict]) -> dict:
    """Monta o dict do índice (pro builder no PC mandar pra Rasp).
    items = [{note_id, section, hash, vector}]. Normaliza os vetores."""
    flat: list[float] = []
    keys: list[list[str]] = []
    hashes: list[str] = []
    for it in items:
        vec = it.get("vector") or []
        if len(vec) != dim:
            continue
        flat.extend(_normalize([float(x) for x in vec]))
        keys.append([it["note_id"], it.get("section", "")])
        hashes.append(it.get("hash", ""))
    blob = array("f", flat).tobytes()
    return {
        "model": model, "dim": dim, "count": len(keys),
        "keys": keys, "hashes": hashes,
        "vectors": base64.b64encode(blob).decode("ascii"),
    }


class VectorIndex:
    def __init__(self) -> None:
        self.model = ""
        self.dim = 0
        self.keys: list[tuple[str, str]] = []
        self.hashes: list[str] = []
        self._mat = None          # numpy (N,dim) OU list[list[float]]
        self.ready = False

    @property
    def count(self) -> int:
        return len(self.keys)

    @classmethod
    def from_dict(cls, d: dict) -> "VectorIndex":
        idx = cls()
        try:
            idx.model = str(d.get("model", ""))
            idx.dim = int(d.get("dim", 0))
            idx.keys = [(str(k[0]), str(k[1]) if len(k) > 1 else "") for k in d.get("keys", [])]
            idx.hashes = list(d.get("hashes", []))
            raw = base64.b64decode(d.get("vectors", "") or "")
            n = len(idx.keys)
            if not n or not idx.dim:
                idx.ready = False
                return idx
            if HAS_NUMPY:
                idx._mat = _np.frombuffer(raw, dtype=_np.float32).reshape(n, idx.dim)
            else:
                a = array("f")
                a.frombytes(raw)
                idx._mat = [list(a[i * idx.dim:(i + 1) * idx.dim]) for i in range(n)]
            idx.ready = True
        except Exception:  # noqa: BLE001 — índice corrompido: degrada (sem denso)
            idx.ready = False
        return idx

    def search(self, qvec: list[float], k: int = 6) -> list[dict]:
        """Top-k por cosseno. qvec cru (normaliza aqui). Retorna
        [{note_id, section, hash, score}] em ordem decrescente."""
        if not self.ready or not qvec or len(qvec) != self.dim:
            return []
        q = _normalize([float(x) for x in qvec])
        if HAS_NUMPY:
            scores = self._mat @ _np.asarray(q, dtype=_np.float32)
            k = min(k, scores.shape[0])
            top = _np.argpartition(-scores, k - 1)[:k] if k > 0 else []
            order = sorted(top, key=lambda i: -float(scores[i]))
            idxs = [(int(i), float(scores[i])) for i in order]
        else:
            scored = []
            for i, row in enumerate(self._mat):
                scored.append((i, sum(a * b for a, b in zip(row, q))))
            scored.sort(key=lambda t: -t[1])
            idxs = scored[:k]
        out = []
        for i, sc in idxs:
            note_id, section = self.keys[i]
            out.append({"note_id": note_id, "section": section,
                        "hash": self.hashes[i] if i < len(self.hashes) else "",
                        "score": round(float(sc), 4)})
        return out
