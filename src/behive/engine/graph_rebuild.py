"""Rebuild NetworkX graph.json from live Qdrant payloads. No HDBSCAN."""
from __future__ import annotations

import json
import re
import urllib.request
from collections import defaultdict
from typing import Any

from behive.engine.graph_engine import save_graph
from behive.engine.qdrant_claims import COLLECTION, QDRANT, UA

_YEAR = re.compile(r"^(19|20)\d{2}$")
_DROP = {"core", "entity", "unknown", "null", "none", "n/a"}


def _ok_entity(name: str) -> bool:
    n = (name or "").strip().lower()
    if len(n) < 3 or n in _DROP or n.isdigit() or _YEAR.match(n):
        return False
    return True


def _scroll(offset: Any = None, limit: int = 256) -> tuple[list[dict], Any]:
    payload: dict[str, Any] = {
        "limit": int(limit),
        "with_payload": True,
        "with_vector": False,
    }
    if offset is not None:
        payload["offset"] = offset
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{QDRANT}/collections/{COLLECTION}/points/scroll",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": UA, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read().decode("utf-8", "replace"))
    res = body.get("result") or {}
    return res.get("points") or [], res.get("next_page_offset")


def rebuild_from_qdrant(max_points: int = 100_000) -> dict:
    import networkx as nx

    G = nx.DiGraph()
    c0_size: dict[int, int] = defaultdict(int)
    c1_size: dict[int, int] = defaultdict(int)
    offset = None
    n_points = 0
    while n_points < max_points:
        points, offset = _scroll(offset=offset, limit=256)
        if not points:
            break
        for p in points:
            pl = p.get("payload") or {}
            nid = pl.get("node_id") or f"claim:{p.get('id')}"
            text = (pl.get("claim_text") or "")[:240]
            mid = pl.get("mission_id") or ""
            c0 = pl.get("community_c0")
            c1 = pl.get("community_id")
            G.add_node(
                nid,
                node_type="claim",
                text=text,
                mission_id=mid,
                confidence=float(pl.get("confidence") or 0),
                community_c0=c0 if c0 is not None else -1,
                community_id=c1 if c1 is not None else -1,
            )
            if isinstance(c0, int) and c0 >= 0:
                c0_size[c0] += 1
            if isinstance(c1, int) and c1 >= 0:
                c1_size[c1] += 1
            if mid:
                mn = f"mission:{mid}"
                if mn not in G:
                    G.add_node(mn, node_type="mission", mission_id=mid)
                G.add_edge(nid, mn, relation="from_mission")
            for eid in pl.get("entity_ids") or []:
                if not eid:
                    continue
                en = eid if str(eid).startswith("entity:") else f"entity:{eid}"
                name = str(en).replace("entity:", "", 1)
                if not _ok_entity(name):
                    continue
                if en not in G:
                    G.add_node(en, node_type="entity", canonical_name=name)
                G.add_edge(en, nid, relation="mentions", weight=1.0)
        n_points += len(points)
        if offset is None:
            break

    # cheap centrality for graph_stats
    deg = dict(G.degree())
    n = max(len(G), 1)
    for node, d in list(G.nodes(data=True)):
        if d.get("node_type") == "entity":
            G.nodes[node]["pagerank"] = round((deg.get(node) or 0) / n, 8)

    c0_summ = {
        str(cid): {"claim_count": sz, "level": "C0"}
        for cid, sz in sorted(c0_size.items(), key=lambda x: -x[1])[:200]
    }
    c1_summ = {
        str(cid): {"claim_count": sz, "level": "C1"}
        for cid, sz in sorted(c1_size.items(), key=lambda x: -x[1])[:500]
    }
    save_graph(G, community_summaries=c1_summ, c0_summaries=c0_summ)
    return {
        "points_scrolled": n_points,
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "claims": sum(1 for _, d in G.nodes(data=True) if d.get("node_type") == "claim"),
        "entities": sum(1 for _, d in G.nodes(data=True) if d.get("node_type") == "entity"),
        "missions": sum(1 for _, d in G.nodes(data=True) if d.get("node_type") == "mission"),
        "c0_clusters": len(c0_size),
        "c1_clusters": len(c1_size),
    }
