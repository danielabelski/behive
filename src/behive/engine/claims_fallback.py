"""Claims from harvested hive_content when the LLM process wrote zero.

No Queen. No Gemini. Sentences with a number, not CSS, not JSON blobs.
"""
from __future__ import annotations

import os
import re

from behive.hygiene import MIN_CLAIMS_FOR_DONE, is_structured_blob, sanitize_claim

_CSS = re.compile(
    r"[{}]|padding-|font-size|#dropdown|border:|width:\s*\d|margin-right|float:\s*left|"
    r"javascript:|cookie|lorem ipsum",
    re.I,
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_HAS_DIGIT = re.compile(r"\d")
_JUNK_START = (
    "click here", "read more", "subscribe", "sign in", "log in",
    "cookie", "privacy policy", "all rights reserved",
)


def sentences_from_text(text: str, limit: int = 8) -> list[str]:
    """Return claim-shaped sentences. Pure, no DB."""
    if limit <= 0:
        return []
    raw = re.sub(r"\s+", " ", (text or "")).strip()
    if len(raw) < 60:
        return []
    parts = _SENT_SPLIT.split(raw)
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        s = p.strip(" \t\"'«»")
        if len(s) < 60 or len(s) > 500:
            continue
        if is_structured_blob(s) or _CSS.search(s):
            continue
        s2 = sanitize_claim(s)
        if not s2:
            continue
        s = s2
        if not _HAS_DIGIT.search(s):
            continue
        if s.lower().startswith(_JUNK_START):
            continue
        if s.count(";") >= 5 or s.count("|") >= 4:
            continue
        key = s[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s[:1000])
        if len(out) >= limit:
            break
    return out


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


def salvage_claims_from_content(mission_id: str, per_doc: int = 5, cap: int = 24) -> int:
    """If mission has content and < MIN_CLAIMS_FOR_DONE claims, write regex claims.

    Returns number of rows inserted.
    """
    if not mission_id or cap <= 0 or per_doc <= 0:
        return 0
    conn = _connect()
    try:
        cur = conn.cursor()
        # Same transaction lock across claim writers: sequence IDs alone do not dedupe.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("behive_claims:" + mission_id,))
        cur.execute(
            "SELECT COUNT(*) FROM hive_claims WHERE mission_id = %s AND (is_garbage = false OR is_garbage IS NULL)",
            (mission_id,),
        )
        have = int((cur.fetchone() or [0])[0] or 0)
        if have >= MIN_CLAIMS_FOR_DONE:
            return 0
        target = min(MIN_CLAIMS_FOR_DONE - have, cap)
        cur.execute(
            """
            SELECT COALESCE(url, ''), COALESCE(raw_text, ''), COALESCE(title, '')
            FROM hive_content
            WHERE mission_id = %s AND length(COALESCE(raw_text, '')) > 80
            ORDER BY COALESCE(word_count, 0) DESC
            LIMIT 80
            """,
            (mission_id,),
        )
        docs = cur.fetchall()
        cur.execute(
            "SELECT LEFT(claim, 160) FROM hive_claims WHERE mission_id = %s",
            (mission_id,),
        )
        seen = {r[0] for r in cur.fetchall() if r[0]}
        from behive.engine.claim_ids import claim_id_expression
        id_sql = claim_id_expression(cur)
        n = 0
        for url, text, title in docs:
            for sent in sentences_from_text(text or "", limit=per_doc):
                key = sent[:160]
                if key in seen:
                    continue
                seen.add(key)
                cur.execute(
                    f"""
                    INSERT INTO hive_claims
                        (id, mission_id, claim, evidence, source_url, claim_type,
                         confidence, extracted_at, quality_score, source_operation, is_garbage)
                    VALUES
                        ({id_sql}, %s, %s, %s, %s, 'regex_fallback', 0.55, NOW(), 0.55, 'claims_fallback', false)
                    """,
                    (mission_id, sent, (title or "")[:500], (url or "")[:500]),
                )
                n += 1
                if n >= target:
                    break
            if n >= target:
                break
        conn.commit()
        return n
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
