"""Persist hive_triples from entity co-occurrence. No LLM. PERSON types are polluted."""
from __future__ import annotations

import json
import os
from typing import Any, Optional

CLEAN_TYPES = (
    "org",
    "organization",
    "location",
    "country",
    "regulation",
    "technology",
    "threat_actor",
)
PREDICATE = "co_occurs_in_research"
DROP_VALUES = (
    "exa", "tavily", "searx", "searxng", "duckduckgo", "brave", "serpapi",
    "firecrawl", "jina", "wikipedia",
)


def _connect():
    import psycopg2

    db_url = os.environ.get("BEHIVE_DB_URL") or os.environ.get("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)
    user = os.environ.get("HIVE_PG_USER", "hive_app")
    password = os.environ.get("HIVE_PG_PASSWORD", "")
    host = os.environ.get("HIVE_PG_HOST", "127.0.0.1")
    port = os.environ.get("HIVE_PG_PORT", "5432")
    database = os.environ.get("HIVE_PG_DATABASE", "hive")
    return psycopg2.connect(
        host=host, port=port, user=user, password=password, dbname=database
    )


def ensure_schema(cur) -> None:
    try:
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS hive_triples_spo
            ON hive_triples (subject, predicate, object)
            """
        )
    except Exception as e:
        if "InsufficientPrivilege" not in type(e).__name__ and "must be owner" not in str(e):
            raise
        try:
            cur.connection.rollback()
        except Exception:
            pass


def rebuild_cooccurrence_triples(
    min_sources: int = 2,
    limit: int = 20000,
    conn: Optional[Any] = None,
) -> dict:
    """Same-URL pairs of clean-typed entities → hive_triples. PERSON excluded on purpose."""
    own = conn is None
    if own:
        conn = _connect()
    cur = conn.cursor()
    ensure_schema(cur)
    types = list(CLEAN_TYPES)
    cur.execute(
        """
        WITH clean AS (
          SELECT mission_id, source_url, lower(trim(value)) AS val
          FROM hive_entities
          WHERE lower(entity_type) = ANY(%s)
            AND length(trim(value)) BETWEEN 3 AND 80
            AND lower(trim(value)) <> ALL(%s)
        ),
        pairs AS (
          SELECT LEAST(a.val, b.val) AS s,
                 GREATEST(a.val, b.val) AS o,
                 a.source_url,
                 a.mission_id
          FROM clean a
          JOIN clean b ON a.source_url = b.source_url AND a.val < b.val
        ),
        agg AS (
          SELECT s, o,
                 count(DISTINCT source_url)::int AS sc,
                 min(mission_id) AS mid,
                 (array_agg(DISTINCT source_url))[1:8] AS urls
          FROM pairs
          GROUP BY s, o
          HAVING count(DISTINCT source_url) >= %s
          ORDER BY count(DISTINCT source_url) DESC
          LIMIT %s
        )
        INSERT INTO hive_triples (mission_id, subject, predicate, object, confidence, source_count, sources)
        SELECT mid, left(s, 200), %s, left(o, 200),
               LEAST(0.95, 0.40 + 0.05 * sc),
               sc,
               to_jsonb(urls)
        FROM agg
        ON CONFLICT (subject, predicate, object) DO UPDATE SET
          source_count = EXCLUDED.source_count,
          confidence = EXCLUDED.confidence,
          sources = EXCLUDED.sources
        """,
        (types, list(DROP_VALUES), int(min_sources), int(limit), PREDICATE),
    )
    written = cur.rowcount
    cur.execute("SELECT COUNT(*) FROM hive_triples")
    total = int(cur.fetchone()[0])
    conn.commit()
    if own:
        conn.close()
    return {"written": written, "total": total, "predicate": PREDICATE}


def triples_for_entity(name: str, limit: int = 40, conn: Optional[Any] = None) -> list[dict]:
    own = conn is None
    if own:
        conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT subject, object, source_count, confidence
        FROM hive_triples
        WHERE predicate = %s
          AND (subject ILIKE %s OR object ILIKE %s)
        ORDER BY source_count DESC
        LIMIT %s
        """,
        (PREDICATE, f"%{name}%", f"%{name}%", int(limit)),
    )
    rows = [
        {
            "subject": r[0],
            "object": r[1],
            "source_count": int(r[2] or 1),
            "confidence": float(r[3] or 0),
        }
        for r in cur.fetchall()
    ]
    if own:
        conn.close()
    return rows
