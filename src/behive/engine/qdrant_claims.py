"""Qdrant hive_intelligence via REST. Embed may use BEHIVE_EMBED_PYTHON."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Optional

QDRANT = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
COLLECTION = os.environ.get("HIVE_QDRANT_COLLECTION", "hive_intelligence")
UA = "BeHiveQdrant/1.0"


def _http(path: str, payload: Optional[dict] = None, timeout: float = 15.0) -> dict:
    url = f"{QDRANT}{path}"
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": UA, "Accept": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def collection_stats() -> dict:
    try:
        d = _http(f"/collections/{COLLECTION}", timeout=8.0)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "collection": COLLECTION}
    res = d.get("result") or {}
    return {
        "ok": True,
        "collection": COLLECTION,
        "points": int(res.get("points_count") or 0),
        "indexed_vectors": int(res.get("indexed_vectors_count") or 0),
        "status": res.get("status"),
        "vector_size": ((res.get("config") or {}).get("params") or {}).get("vectors", {}).get("size"),
    }


def _embed_local(text: str) -> list[float]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")
    vec = model.encode(text, normalize_embeddings=True)
    return [float(x) for x in vec.tolist()]


def _embed_python() -> str:
    env = os.environ.get("BEHIVE_EMBED_PYTHON") or ""
    candidates = [
        env,
        "/root/mercosur-eu-docs/.venv/bin/python",
        "/root/math-workspace/singularity-room/.venv/bin/python",
    ]
    for p in candidates:
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return ""


def embed_query(text: str) -> list[float]:
    try:
        return _embed_local(text)
    except Exception:
        pass
    py = _embed_python()
    if not py:
        raise RuntimeError("sentence_transformers missing and BEHIVE_EMBED_PYTHON unset")
    code = (
        "import json,sys;"
        "from sentence_transformers import SentenceTransformer;"
        "t=sys.stdin.read();"
        "m=SentenceTransformer('all-MiniLM-L6-v2');"
        "v=m.encode(t, normalize_embeddings=True);"
        "print(json.dumps([float(x) for x in v.tolist()]))"
    )
    proc = subprocess.run(
        [py, "-c", code],
        input=text.encode("utf-8"),
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", "replace")[-300:])
    vec = json.loads(proc.stdout.decode("utf-8"))
    if not isinstance(vec, list) or len(vec) < 32:
        raise RuntimeError("embed returned empty vector")
    return vec


def semantic_search(query: str, top_k: int = 8) -> dict:
    stats = collection_stats()
    if not stats.get("ok"):
        return {"ok": False, "error": stats.get("error"), "hits": []}
    try:
        vec = embed_query(query)
    except Exception as e:
        return {"ok": False, "error": f"embed: {e}", "hits": [], "stats": stats}
    try:
        d = _http(
            f"/collections/{COLLECTION}/points/search",
            {"vector": vec, "limit": int(top_k), "with_payload": True},
            timeout=20.0,
        )
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"qdrant {e.code}", "hits": [], "stats": stats}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "error": f"qdrant transport: {type(e).__name__}", "hits": [], "stats": stats}
    raw = d.get("result") or []
    hits = []
    for h in raw:
        pl = h.get("payload") or {}
        hits.append(
            {
                "score": round(float(h.get("score") or 0), 4),
                "claim": pl.get("claim_text") or "",
                "mission_id": pl.get("mission_id") or "",
                "confidence": pl.get("confidence"),
                "community_c0": pl.get("community_c0"),
                "community_id": pl.get("community_id"),
            }
        )
    return {"ok": True, "query": query, "hits": hits, "count": len(hits), "stats": stats}
