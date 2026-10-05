"""Turn hive_facts into hive_claims without Queen/LLM.

Process already extracts numbers+context. Queen/Gemini is only required for
narrative synthesis. The warehouse path must not wait on a free-tier 429.
"""
from __future__ import annotations

import math
import os
import re
from typing import Optional

_CSS = re.compile(
    r"[{}]|padding-|font-size|#dropdown|border:|width:\s*\d|margin-right|float:\s*left",
    re.I,
)
_STOP = frozenset(
    "about after before being between during following global through which whose "
    "their there these those other would could should using based".split()
)


def _topic_keys(topic: str) -> list[str]:
    keys = []
    for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", topic or ""):
        lw = w.lower()
        if lw in _STOP or len(lw) < 5:
            continue
        keys.append(lw)
    keys = sorted(set(keys), key=len, reverse=True)
    return keys[:6]


from behive.hygiene import sanitize_claim


def _clean_ctx(context: str) -> Optional[str]:
    return sanitize_claim(context)


def persist_facts_as_claims(mission_id: str, topic: Optional[str] = None) -> int:
    import psycopg2

    url = os.environ.get("BEHIVE_DB_URL")
    if not url:
        raise RuntimeError("BEHIVE_DB_URL missing")
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        if not topic:
            cur.execute("SELECT topic FROM hive_missions WHERE id = %s", (mission_id,))
            row = cur.fetchone()
            topic = (row[0] if row else "") or ""
        keys = _topic_keys(topic or "")
        cur.execute(
            """
            SELECT value, unit, context, sources, confidence
            FROM hive_facts
            WHERE mission_id = %s AND context IS NOT NULL
            """,
            (mission_id,),
        )
        facts = cur.fetchall()
        cur.execute(
            "SELECT LEFT(claim, 180) FROM hive_claims WHERE mission_id = %s",
            (mission_id,),
        )
        seen = {r[0] for r in cur.fetchall() if r[0]}
        n = 0
        for _value, _unit, context, sources, conf in facts:
            ctx = _clean_ctx(context)
            if not ctx:
                continue
            low = ctx.lower()
            if keys and not any(k in low for k in keys[:3]):
                continue
            key = ctx[:180]
            if key in seen:
                continue
            seen.add(key)
            src = ""
            if isinstance(sources, list) and sources:
                src = str(sources[0])[:500]
            elif isinstance(sources, str):
                src = sources[:500]
            conf_f = 0.62
            if str(conf).upper() == "LOW":
                conf_f = 0.55
            else:
                try:
                    conf_f = float(conf)
                    if not math.isfinite(conf_f) or not 0 <= conf_f <= 1:
                        conf_f = 0.62
                except (TypeError, ValueError):
                    conf_f = 0.62
            cur.execute(
                """
                INSERT INTO hive_claims
                    (mission_id, claim, evidence, source_url, claim_type,
                     confidence, extracted_at, quality_score, source_operation, is_garbage)
                VALUES
                    (%s, %s, %s, %s, 'fact_persist', %s, NOW(), %s, 'facts_to_claims', false)
                """,
                (mission_id, ctx[:1000], ctx[:500], src or None, conf_f, conf_f),
            )
            n += 1
        conn.commit()
        return n
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
