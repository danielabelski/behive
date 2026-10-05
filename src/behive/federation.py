"""Local claim pool — NOT a multi-instance network.

seed_from_hive() copies this host's hive_claims (quality>=0.85).
Contribute still needs an API key. Search is local FTS.
"""

import os
import time
import hashlib
import asyncio
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import JSONResponse


router = APIRouter(prefix="/federation", tags=["local_seed"])

_OFF_PRODUCT = {
    "ok": False,
    "product": False,
    "mode": "local_seed",
    "remote_peers": 0,
    "reason": "No peer network. Contribute/confirm are off. GET /federation/stats is the local hive_claims mirror.",
}


# ─── Models ───────────────────────────────────────────────────────────────────

class FederatedClaim(BaseModel):
    """Row in the local federated_claims pool. Not a remote network."""
    claim_hash: str = Field(..., description="SHA256 of normalized claim text")
    text: str = Field(..., min_length=10, max_length=2000)
    confidence: float = Field(..., ge=0, le=1)
    network_confidence: float = Field(0.0, ge=0, le=1)
    source_urls: list[str] = Field(default_factory=list, max_length=10)
    domain_tags: list[str] = Field(default_factory=list, max_length=5)
    entity_refs: list[str] = Field(default_factory=list, max_length=20)
    contributor_hash: str = ""
    contributed_at: Optional[str] = None
    confirmations: int = 0
    contradictions: int = 0


class ContributeRequest(BaseModel):
    """Unused: contribute is off the product (no peers)."""
    claims: list[FederatedClaim] = Field(..., min_length=1, max_length=100)


class ContributeResponse(BaseModel):
    accepted: int
    rejected: int
    reasons: list[str] = Field(default_factory=list)


class NetworkSearchResult(BaseModel):
    claims: list[FederatedClaim]
    total: int
    query: str
    mode: str = "local_seed"
    remote_peers: int = 0
    product: bool = False
    source: str = "local federated_claims (hive_claims copy)"


class ConfirmRequest(BaseModel):
    claim_hash: str
    confirmed: bool = True  # True = confirm, False = contradict


class NetworkStats(BaseModel):
    total_claims: int
    total_contributors: int
    total_confirmations: int
    avg_confidence: float
    top_domains: list[dict]
    last_contribution: Optional[str] = None
    mode: str = "local_seed"
    remote_peers: int = 0
    source: str = "local hive_claims (quality>=0.85 cap)"
    product: bool = False


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _hash_contributor(token: str) -> str:
    """Anonymize contributor identity."""
    return hashlib.sha256(f"behive-fkn-{token}".encode()).hexdigest()[:16]


def _hash_claim(text: str) -> str:
    """Normalize and hash claim text for dedup."""
    normalized = text.lower().strip()
    # Remove extra whitespace
    normalized = " ".join(normalized.split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def _get_db():
    """Get database connection for federation tables."""
    try:
        import psycopg2
        db_url = os.environ.get("BEHIVE_DB_URL") or os.environ.get("DATABASE_URL")
        if not db_url:
            user = os.environ.get("HIVE_PG_USER", "behive")
            password = os.environ.get("HIVE_PG_PASSWORD", "behive")
            host = os.environ.get("HIVE_PG_HOST", "localhost")
            port = os.environ.get("HIVE_PG_PORT", "5432")
            database = os.environ.get("HIVE_PG_DATABASE", "behive")
            db_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"
        return psycopg2.connect(db_url)
    except Exception:
        return None


def _ensure_tables():
    """Create federation tables if they don't exist."""
    conn = _get_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS federated_claims (
                    claim_hash TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    confidence FLOAT NOT NULL DEFAULT 0.0,
                    network_confidence FLOAT NOT NULL DEFAULT 0.0,
                    source_urls TEXT[] DEFAULT '{}',
                    domain_tags TEXT[] DEFAULT '{}',
                    entity_refs TEXT[] DEFAULT '{}',
                    contributor_hash TEXT NOT NULL,
                    contributed_at TIMESTAMPTZ DEFAULT NOW(),
                    confirmations INT DEFAULT 0,
                    contradictions INT DEFAULT 0
                );
                
                CREATE TABLE IF NOT EXISTS federated_contributors (
                    contributor_hash TEXT PRIMARY KEY,
                    reputation_score FLOAT DEFAULT 0.5,
                    claims_contributed INT DEFAULT 0,
                    claims_confirmed INT DEFAULT 0,
                    claims_flagged INT DEFAULT 0,
                    domain_expertise JSONB DEFAULT '{}',
                    joined_at TIMESTAMPTZ DEFAULT NOW(),
                    last_active TIMESTAMPTZ DEFAULT NOW()
                );
                
                CREATE TABLE IF NOT EXISTS federated_votes (
                    id SERIAL PRIMARY KEY,
                    claim_hash TEXT NOT NULL REFERENCES federated_claims(claim_hash),
                    voter_hash TEXT NOT NULL,
                    confirmed BOOLEAN NOT NULL,
                    voted_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(claim_hash, voter_hash)
                );
                
                CREATE INDEX IF NOT EXISTS idx_fed_claims_domain ON federated_claims USING GIN (domain_tags);
                CREATE INDEX IF NOT EXISTS idx_fed_claims_confidence ON federated_claims (network_confidence DESC);
                CREATE INDEX IF NOT EXISTS idx_fed_claims_contributor ON federated_claims (contributor_hash);
                CREATE INDEX IF NOT EXISTS idx_fed_claims_text ON federated_claims USING GIN (to_tsvector('english', text));
            """)
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        return False
    finally:
        conn.close()


# Initialize tables on import
_tables_ready = False
_LOCAL_CONTRIBUTOR = "local-hive-seed"


def _init_tables():
    global _tables_ready
    if not _tables_ready:
        _tables_ready = _ensure_tables()
    return _tables_ready


def seed_from_hive(limit: int = 3000, min_quality: float = 0.85) -> dict:
    """Copy local high-quality hive_claims into federated_claims. Not a remote network."""
    if not _init_tables():
        return {"ok": False, "error": "db"}
    conn = _get_db()
    if not conn:
        return {"ok": False, "error": "connect"}
    contributor = _hash_contributor(_LOCAL_CONTRIBUTOR)
    inserted = 0
    skipped = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO federated_contributors (contributor_hash)
                VALUES (%s)
                ON CONFLICT (contributor_hash) DO UPDATE SET last_active = NOW()
                """,
                (contributor,),
            )
            cur.execute(
                """
                SELECT claim, quality_score, source_url, claim_type
                FROM hive_claims
                WHERE (is_garbage = false OR is_garbage IS NULL)
                  AND length(claim) >= 10
                  AND coalesce(source_url, '') <> ''
                  AND coalesce(quality_score, 0) >= %s
                  AND left(ltrim(claim), 1) NOT IN ('{', '[')
                ORDER BY quality_score DESC
                LIMIT %s
                """,
                (float(min_quality), int(limit)),
            )
            rows = cur.fetchall()
            for text, quality, url, ctype in rows:
                h = _hash_claim(text)
                tags = [ctype] if ctype else []
                cur.execute("SELECT 1 FROM federated_claims WHERE claim_hash = %s", (h,))
                if cur.fetchone():
                    skipped += 1
                    continue
                cur.execute(
                    """
                    INSERT INTO federated_claims
                        (claim_hash, text, confidence, network_confidence, source_urls,
                         domain_tags, entity_refs, contributor_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (claim_hash) DO NOTHING
                    """,
                    (
                        h,
                        text[:2000],
                        float(quality or 0),
                        float(quality or 0),
                        [url],
                        tags,
                        [],
                        contributor,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    skipped += 1
            cur.execute(
                """
                UPDATE federated_contributors
                SET claims_contributed = claims_contributed + %s
                WHERE contributor_hash = %s
                """,
                (inserted, contributor),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)[:200], "inserted": inserted, "skipped": skipped}
    finally:
        conn.close()
    return {"ok": True, "inserted": inserted, "skipped": skipped, "limit": limit}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/contribute")
async def contribute_claims():
    """Off the product. No peer network to contribute to."""
    return JSONResponse(status_code=501, content=_OFF_PRODUCT)


@router.get("/search", response_model=NetworkSearchResult)
async def search_network(
    q: str = Query(..., min_length=2, max_length=500, description="Search query"),
    domain: Optional[str] = Query(None, description="Filter by domain tag"),
    min_conf: float = Query(0.6, ge=0, le=1, description="Minimum network confidence"),
    limit: int = Query(20, ge=1, le=100),
    x_api_key: str = Header(None, alias="X-API-Key"),
    authorization: str = Header(None),
):
    """
    Search the local federated claim pool.
    No remote BeHive network exists — auth not required to read.
    """
    if not _init_tables():
        raise HTTPException(503, "Federation database not available")

    conn = _get_db()
    if not conn:
        raise HTTPException(503, "Database connection failed")

    try:
        with conn.cursor() as cur:
            # Full-text search with optional domain filter
            if domain:
                cur.execute("""
                    SELECT claim_hash, text, confidence, network_confidence,
                           source_urls, domain_tags, entity_refs, contributor_hash,
                           contributed_at::text, confirmations, contradictions
                    FROM federated_claims
                    WHERE to_tsvector('english', text) @@ plainto_tsquery('english', %s)
                      AND %s = ANY(domain_tags)
                      AND network_confidence >= %s
                    ORDER BY network_confidence DESC, confirmations DESC
                    LIMIT %s
                """, (q, domain, min_conf, limit))
            else:
                cur.execute("""
                    SELECT claim_hash, text, confidence, network_confidence,
                           source_urls, domain_tags, entity_refs, contributor_hash,
                           contributed_at::text, confirmations, contradictions
                    FROM federated_claims
                    WHERE to_tsvector('english', text) @@ plainto_tsquery('english', %s)
                      AND network_confidence >= %s
                    ORDER BY network_confidence DESC, confirmations DESC
                    LIMIT %s
                """, (q, min_conf, limit))

            rows = cur.fetchall()

            # Get total count
            if domain:
                cur.execute("""
                    SELECT COUNT(*) FROM federated_claims
                    WHERE to_tsvector('english', text) @@ plainto_tsquery('english', %s)
                      AND %s = ANY(domain_tags) AND network_confidence >= %s
                """, (q, domain, min_conf))
            else:
                cur.execute("""
                    SELECT COUNT(*) FROM federated_claims
                    WHERE to_tsvector('english', text) @@ plainto_tsquery('english', %s)
                      AND network_confidence >= %s
                """, (q, min_conf))
            total = cur.fetchone()[0]

    except Exception as e:
        raise HTTPException(500, f"Search failed: {str(e)[:100]}")
    finally:
        conn.close()

    claims = []
    for row in rows:
        claims.append(FederatedClaim(
            claim_hash=row[0],
            text=row[1],
            confidence=row[2],
            network_confidence=row[3],
            source_urls=row[4] or [],
            domain_tags=row[5] or [],
            entity_refs=row[6] or [],
            contributor_hash=row[7],
            contributed_at=row[8],
            confirmations=row[9],
            contradictions=row[10],
        ))

    return NetworkSearchResult(claims=claims, total=total, query=q)


@router.post("/confirm")
async def confirm_or_contradict():
    """Off the product. No peer network to vote on."""
    return JSONResponse(status_code=501, content=_OFF_PRODUCT)


@router.get("/stats", response_model=NetworkStats)
async def network_stats():
    """
    Local federated_claims pool stats. Not a remote BeHive network.
    Public — no auth.
    """
    if not _init_tables():
        raise HTTPException(503, "Federation database not available")

    conn = _get_db()
    if not conn:
        raise HTTPException(503, "Database connection failed")

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM federated_claims")
            total_claims = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM federated_contributors")
            total_contributors = cur.fetchone()[0]

            cur.execute("SELECT COALESCE(SUM(confirmations), 0) FROM federated_claims")
            total_confirmations = cur.fetchone()[0]

            cur.execute("SELECT COALESCE(AVG(network_confidence), 0) FROM federated_claims")
            avg_confidence = cur.fetchone()[0]

            cur.execute("""
                SELECT unnest(domain_tags) as domain, COUNT(*) as cnt
                FROM federated_claims
                GROUP BY domain ORDER BY cnt DESC LIMIT 10
            """)
            top_domains = [{"domain": r[0], "count": r[1]} for r in cur.fetchall()]

            cur.execute("SELECT MAX(contributed_at::text) FROM federated_claims")
            last = cur.fetchone()[0]

    except Exception as e:
        raise HTTPException(500, f"Stats query failed: {str(e)[:100]}")
    finally:
        conn.close()

    return NetworkStats(
        total_claims=total_claims,
        total_contributors=total_contributors,
        total_confirmations=total_confirmations,
        avg_confidence=round(avg_confidence, 3),
        top_domains=top_domains,
        last_contribution=last,
        mode="local_seed",
        remote_peers=0,
        source="local hive_claims (quality>=0.85 cap)",
    )
