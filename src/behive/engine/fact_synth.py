"""Deterministic synthesis from hive_claims. No LLM. No new numbers."""
from __future__ import annotations

import os
import re
from collections import defaultdict
from decimal import Decimal
from urllib.parse import urlparse

from behive.hygiene import sanitize_claim

_NUM = re.compile(
    r"(?<!\w)(?P<n>[+-]?\d+(?:[.,]\d+)*)"
    r"(?:\s*(?P<u>%|(?:percent|million|billion|thousand|barrels?|mb/?d|b/?d|bpd|tonnes?|tons?)\b))?",
    re.I,
)
_GENERIC = frozenset(
    "strait oil share transit global world market report crisis war "
    "the and for with from about through between under over into "
    "million billion percent barrels crude energy".split()
)


def clean_claim(text: str) -> str | None:
    return sanitize_claim(text)


def _number_key(raw: str) -> str:
    """Normalize explicit decimals without guessing ambiguous locale separators."""
    value = raw
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        grouping = "." if decimal == "," else ","
        integer, fraction = raw.rsplit(decimal, 1)
        if not re.fullmatch(r"[+-]?\d{1,3}(?:" + re.escape(grouping) + r"\d{3})+", integer):
            return raw
        value = integer.replace(grouping, "") + "." + fraction
    elif "," in raw:
        if raw.count(",") > 1:
            if not re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+", raw):
                return raw
            value = raw.replace(",", "")
        elif len(raw.rsplit(",", 1)[1]) == 3:
            # 2,500 may mean 2500 or 2.5. Preserve rather than invent a value.
            return raw
        else:
            value = raw.replace(",", ".")
    elif raw.count(".") > 1:
        return raw
    value = format(Decimal(value), "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def _quantity_key(match: re.Match) -> tuple[str, str]:
    unit = (match.group("u") or "").lower()
    aliases = {
        "%": "pct", "percent": "pct", "barrels": "barrel",
        "mb/d": "mbpd", "mbd": "mbpd", "b/d": "bpd", "bd": "bpd",
        "tonnes": "tonne", "tons": "ton",
    }
    return _number_key(match.group("n")), aliases.get(unit, unit)


def fact_key(text: str) -> str | None:
    m = _NUM.search(text or "")
    if not m:
        return None
    number, unit = _quantity_key(m)
    if not unit and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", number):
        n = Decimal(number)
        if 1900 <= n <= 2100 or n < 2:
            return None
    # A shared quantity is not a shared fact. Keep the entire assertion,
    # including subject, negation, other quantities and temporal qualifiers.
    # Deterministic matching intentionally does not infer paraphrase equivalence.
    def normalized_quantity(match):
        value, measure = _quantity_key(match)
        return value + (" " + measure if measure else "")

    context = _NUM.sub(normalized_quantity, text)
    context = re.sub(r"\s+", " ", context).strip().casefold()
    return f"{number}|{unit}|{context}"


def topic_needles(topic: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", topic or "")
    dist = [w.lower() for w in words if w.lower() not in _GENERIC]
    return dist[:6]


def on_topic(claim: str, needles: list[str]) -> bool:
    if not needles:
        return True
    low = (claim or "").lower()
    return any(n in low for n in needles)


def domain_of(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower().removeprefix("www.")
    return host or "unknown"


def _split_groups(topic: str, rows: list[tuple]):
    needles = topic_needles(topic)
    groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for claim, url, _conf in rows:
        cl = clean_claim(claim)
        if not cl:
            continue
        # The sanitizer can discard a lowercase prefix before its first
        # capital letter (eBay -> Bay). Admit through it, but never use that
        # shortened assertion as the fact identity.
        match_text = re.sub(r"<[^>]+>", " ", claim)
        key = fact_key(match_text)
        if not key:
            continue
        if not on_topic(match_text, needles):
            continue
        # Cleaning is only an admission/matching step, never a replacement for
        # the source's actual assertion in the evidence record.
        groups[key].append((claim, url or "", domain_of(url or "")))

    attested = []
    single = []
    for key, items in groups.items():
        domains = sorted({d for _, _, d in items if d != "unknown"})
        evidence = []
        seen = set()
        for cl, url, dom in items:
            if (url, cl) not in seen:
                evidence.append((url, (cl, dom)))
                seen.add((url, cl))
        if len(domains) >= 2:
            attested.append((key, domains, evidence))
        else:
            single.append((key, domains, evidence))
    attested.sort(key=lambda x: (-len(x[1]), x[0]))
    return attested, single


def group_attested(topic: str, rows: list[tuple]) -> list:
    attested, _ = _split_groups(topic, rows)
    return attested


def build_report(topic: str, rows: list[tuple]) -> str:
    attested, single = _split_groups(topic, rows)
    lines = [
        f"# {topic}",
        "",
        "Raport z claimów. Bez modelu. Ta sama znormalizowana treść i ilość w ≥2 domenach; nie niezależna weryfikacja prawdziwości.",
        "",
        f"## Potwierdzone (≥2 domeny) — {len(attested)}",
        "",
    ]
    if not attested:
        lines.append("*Brak tej samej treści i ilości powtórzonych w dwóch domenach.*")
        lines.append("")
    for key, domains, urls in attested:
        quantity = "|".join(key.split("|", 2)[:2])
        lines.append(f"- **{quantity}** · {len(domains)} domen")
        for u, (claim, _) in urls:
            lines.append(f"  {claim}")
            if u:
                lines.append(f"  - {u}")
        lines.append("")
    lines.append(f"## Jedno źródło — {len(single)} (nie wniosek)")
    lines.append("")
    for key, domains, urls in single:
        for u, (claim, _) in urls:
            lines.append(f"- {claim}")
            if u:
                lines.append(f"  - {u}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def attested_network(name: str) -> dict:
    """Graph of attested facts for a name. Not co-occurrence, not PageRank."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT claim, source_url, confidence
            FROM hive_claims
            WHERE (is_garbage = false OR is_garbage IS NULL)
              AND claim ILIKE %s
            ORDER BY confidence DESC NULLS LAST
            LIMIT 2000
            """,
            (f"%{name}%",),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    attested = group_attested(name, rows)
    nodes = {name: {"name": name, "type": "center", "weight": len(attested)}}
    edges = []
    for key, domains, urls in attested[:20]:
        nodes[key] = {
            "name": key, "type": "fact", "weight": len(domains),
            "evidence": [
                {"claim": claim, "source_url": url, "domain": domain}
                for url, (claim, domain) in urls
            ],
        }
        edges.append({
            "source": name,
            "target": key,
            "weight": len(domains),
            "relation": "attested_value",
        })
        for dom in domains:
            nodes[dom] = {"name": dom, "type": "domain", "weight": 1}
            edges.append({
                "source": key,
                "target": dom,
                "weight": 1,
                "relation": "attested_in",
            })
    node_list = list(nodes.values())
    return {
        "center": name,
        "depth": 2,
        "nodes": node_list,
        "edges": edges,
        "node_count": len(node_list),
        "edge_count": len(edges),
        "source": "fact_synth_attested",
        "predicate": "same_normalized_claim_and_quantity_ge2_domains",
        "attested": len(attested),
        "claims_scanned": len(rows),
        "knowledge_graph": False,
    }


def _connect():
    import psycopg2

    db_url = os.environ.get("BEHIVE_DB_URL") or os.environ.get("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)
    return psycopg2.connect(
        host=os.environ.get("HIVE_PG_HOST", "127.0.0.1"),
        port=os.environ.get("HIVE_PG_PORT", "5432"),
        user=os.environ.get("HIVE_PG_USER", "hive_app"),
        password=os.environ.get("HIVE_PG_PASSWORD", ""),
        dbname=os.environ.get("HIVE_PG_DATABASE", "hive"),
    )


def persist_fact_synthesis(mission_id: str) -> dict:
    """Write synthesis from claims. Returns {attested, claims, chars}."""
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute("SELECT topic FROM hive_missions WHERE id=%s", (mission_id,))
        row = cur.fetchone()
        if not row:
            return {"attested": 0, "claims": 0, "chars": 0}
        topic = row[0] or mission_id
        cur.execute(
            """
            SELECT claim, source_url, confidence
            FROM hive_claims
            WHERE mission_id=%s AND (is_garbage=false OR is_garbage IS NULL)
            ORDER BY confidence DESC NULLS LAST
            """,
            (mission_id,),
        )
        rows = cur.fetchall()
        attested, single = _split_groups(topic, rows)
        if not any(domains for _, domains, _ in attested + single):
            # No evidence-backed product: do not overwrite prior synthesis or
            # promote an empty/filtered/unsourced harvest to done.
            return {"attested": 0, "claims": len(rows), "chars": 0}
        report = build_report(topic, rows)
        cur.execute(
            """
            UPDATE hive_missions
            SET synthesis=%s, synth_done_at=NOW()
            WHERE id=%s AND status NOT IN ('cancelled', 'error')
            """,
            (report, mission_id),
        )
        conn.commit()
        return {"attested": len(attested), "claims": len(rows), "chars": len(report)}
    finally:
        conn.close()
