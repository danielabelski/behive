#!/usr/bin/env python3
"""
BeHive → Singularity Room Bridge
=================================
Hook that runs after BeHive mission completes.
Extracts claims from hive_claims and POSTs them to SR /ingest endpoint.

Features:
- Filters garbage claims (is_garbage = false)
- Maps confidence + quality_score → SR confidence
- Tags source as "behive:{mission_id}" for traceability
- Deduplication: checks if mission was already bridged (idempotent)
- Batches claims in groups of 50 for API efficiency

Usage:
  Called from _run_pipeline() after subprocess.run completes.
  bridge_mission("hive_1234567_topic_name")
"""

import os
import sys
import json
import time
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Optional

import psycopg2
import requests

log = logging.getLogger("behive-sr-bridge")
log.setLevel(logging.INFO)
if not log.handlers:
    log.addHandler(logging.StreamHandler())

# ─── Configuration ──────────────────────────────────────────────────────────

SR_INGEST_URL = os.environ.get("SR_INGEST_URL", "http://localhost:8092/ingest")
SR_TIMEOUT = int(os.environ.get("SR_BRIDGE_TIMEOUT", "30"))
BATCH_SIZE = 50
MIN_QUALITY = 0.4  # Skip claims below this quality threshold
MIN_CONFIDENCE = 0.3  # Skip claims below this confidence

# DB config — reads from env (same as SR server.py)
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'dbname': 'hive',
    'user': 'hive_app',
    'password': os.environ.get('HIVE_PG_PASSWORD', ''),
}


# ─── Bridge State (dedup) ──────────────────────────────────────────────────

def _get_db():
    return psycopg2.connect(**DB_CONFIG)


def _ensure_bridge_table():
    """Create tracking table if not exists (idempotent)."""
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sr_bridge_log (
            mission_id TEXT PRIMARY KEY,
            claims_sent INTEGER NOT NULL DEFAULT 0,
            bridged_at TIMESTAMP DEFAULT NOW(),
            sr_response JSONB
        )
    """)
    conn.commit()
    conn.close()


def _was_already_bridged(mission_id: str) -> bool:
    """Check if mission was already sent to SR."""
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sr_bridge_log WHERE mission_id = %s", (mission_id,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def _mark_bridged(mission_id: str, claims_sent: int, sr_response: dict):
    """Record that mission was bridged."""
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sr_bridge_log (mission_id, claims_sent, sr_response)
        VALUES (%s, %s, %s)
        ON CONFLICT (mission_id) DO UPDATE SET
            claims_sent = EXCLUDED.claims_sent,
            sr_response = EXCLUDED.sr_response,
            bridged_at = NOW()
    """, (mission_id, claims_sent, json.dumps(sr_response)))
    conn.commit()
    conn.close()


def _sync_encoder(mission_id: str) -> None:
    """Re-encode snapshot and hot-reload SR vectors. Must not fail the bridge."""
    encode = "/root/math-workspace/singularity-room/scripts/encode_claims.py"
    py = "/root/stealth-research-env/bin/python3"
    try:
        r = subprocess.run([py, "-u", encode], timeout=180, capture_output=True, text=True)
        log.info("[BRIDGE] encode exit=%s tail=%s", r.returncode, (r.stdout or "")[-200:].replace("\n", " "))
        if r.returncode != 0:
            log.warning("[BRIDGE] encode stderr=%s", (r.stderr or "")[-400:])
            return
        rr = requests.post("http://127.0.0.1:8092/internal/reload-encoder", timeout=30)
        log.info("[BRIDGE] encoder reload %s %s", rr.status_code, rr.text[:200])
        Path("/tmp/sr_encoder_synced.json").write_text(
            json.dumps({"mission_id": mission_id, "reload": rr.text[:300], "ts": time.time()}),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("[BRIDGE] encoder sync failed: %s", e)


# ─── Core Logic ────────────────────────────────────────────────────────────

def _fetch_mission_claims(mission_id: str) -> List[Dict]:
    """Fetch non-garbage claims for a mission from hive_claims."""
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT claim, confidence, quality_score, source_url, claim_type
        FROM hive_claims
        WHERE mission_id = %s
          AND (is_garbage = false OR is_garbage IS NULL)
          AND claim IS NOT NULL
          AND LENGTH(claim) > 20
        ORDER BY quality_score DESC NULLS LAST
    """, (mission_id,))
    
    rows = cur.fetchall()
    conn.close()
    
    claims = []
    for claim_text, confidence, quality, source_url, claim_type in rows:
        # Combined confidence: average of BeHive confidence and quality_score
        conf = confidence or 0.7
        qual = quality or 0.5
        combined_confidence = (conf + qual) / 2.0
        
        # Apply thresholds
        if combined_confidence < MIN_CONFIDENCE:
            continue
        if qual is not None and qual < MIN_QUALITY:
            continue
        s = (claim_text or "").lstrip()
        if not s or s[0] in "{[":
            continue
        claims.append({
            "claim": claim_text[:500],  # SR has 500 char limit
            "confidence": round(min(combined_confidence, 0.99), 3),
            "source": f"behive:{mission_id}",
        })
    
    return claims


def _send_to_sr(claims: List[Dict]) -> Dict:
    """POST claims to SR /ingest in batches with rate limiting."""
    total_ingested = 0
    last_response = {}
    max_retries = 2
    
    for i in range(0, len(claims), BATCH_SIZE):
        batch = claims[i:i + BATCH_SIZE]
        
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(
                    SR_INGEST_URL,
                    json={"claims": batch},
                    timeout=SR_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    total_ingested += data.get("ingested", 0)
                    last_response = data
                    break  # Success
                else:
                    log.warning(f"SR ingest returned {resp.status_code}: {resp.text[:200]}")
                    break  # Don't retry on 4xx
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt < max_retries:
                    wait = 10 * (attempt + 1)
                    log.warning(f"SR ingest attempt {attempt+1} failed ({e.__class__.__name__}), retry in {wait}s")
                    time.sleep(wait)
                else:
                    log.error(f"SR ingest failed after {max_retries+1} attempts for batch {i//BATCH_SIZE + 1}")
            except Exception as e:
                log.error(f"SR ingest unexpected error: {e}")
                break
        
        # Rate limit: 2s between batches to avoid overloading SR event loop
        if i + BATCH_SIZE < len(claims):
            time.sleep(2)
    
    last_response["total_ingested"] = total_ingested
    return last_response


# ─── Public API ────────────────────────────────────────────────────────────

def bridge_mission(mission_id: str) -> Optional[Dict]:
    """
    Bridge a completed BeHive mission's claims into Singularity Room.
    
    Returns:
        dict with {claims_fetched, claims_sent, sr_response} on success
        None if already bridged or no claims found
    """
    _ensure_bridge_table()
    
    # Idempotency check
    if _was_already_bridged(mission_id):
        log.info(f"[BRIDGE] Mission {mission_id} already bridged — skipping")
        return None
    
    # Fetch claims
    claims = _fetch_mission_claims(mission_id)
    if not claims:
        log.info(f"[BRIDGE] Mission {mission_id} has no eligible claims — skipping")
        _mark_bridged(mission_id, 0, {"skipped": "no_claims"})
        return None
    
    log.info(f"[BRIDGE] Mission {mission_id}: {len(claims)} claims → SR")
    
    # Send to SR
    sr_response = _send_to_sr(claims)
    total_sent = sr_response.get("total_ingested", 0)
    
    # Record
    _mark_bridged(mission_id, total_sent, sr_response)
    
    log.info(f"[BRIDGE] Mission {mission_id}: {total_sent}/{len(claims)} claims ingested into SR")
    _sync_encoder(mission_id)
    return {
        "mission_id": mission_id,
        "claims_fetched": len(claims),
        "claims_sent": total_sent,
        "sr_response": sr_response,
    }


def bridge_all_pending() -> List[Dict]:
    """Bridge all completed missions that haven't been bridged yet."""
    _ensure_bridge_table()
    
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id 
        FROM hive_missions m
        LEFT JOIN sr_bridge_log b ON m.id = b.mission_id
        WHERE m.status = 'done'
          AND b.mission_id IS NULL
        ORDER BY m.created_at DESC
        LIMIT 50
    """)
    pending = [row[0] for row in cur.fetchall()]
    conn.close()
    
    results = []
    for mid in pending:
        result = bridge_mission(mid)
        if result:
            results.append(result)
    
    return results


# ─── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        # Bridge all pending missions
        results = bridge_all_pending()
        print(f"Bridged {len(results)} missions")
        for r in results:
            print(f"  {r['mission_id']}: {r['claims_sent']}/{r['claims_fetched']} claims")
    elif len(sys.argv) > 1:
        # Bridge specific mission
        result = bridge_mission(sys.argv[1])
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("Already bridged or no claims")
    else:
        print("Usage: sr_bridge.py <mission_id> | --all")
