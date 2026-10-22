"""Private PG fixtures with live-shaped DDL captured read-only from hive.

The table and constraint statements below come from PG16 schema-only dumps in
/root/outputs/behive-repair-2026-10-22/A-schema. Only public qualification is
removed so every test owns a UUID schema. No production/default DSN fallback.
"""
import os
import uuid
from types import SimpleNamespace

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn, make_dsn
import pytest

LIVE_DDL = {
    'hive_claims': """CREATE TABLE hive_claims (
    id integer NOT NULL,
    mission_id text,
    claim text,
    evidence text,
    source_url text,
    claim_type text,
    confidence real,
    extracted_at timestamp with time zone,
    verified boolean,
    evidence_flags text,
    quality_score double precision,
    quality_details jsonb,
    source_operation text,
    source_tier integer,
    is_garbage boolean DEFAULT false
);
ALTER TABLE ONLY hive_claims
    ADD CONSTRAINT hive_claims_pkey PRIMARY KEY (id);""",
    'hive_content': """CREATE TABLE hive_content (
    id integer NOT NULL,
    mission_id text,
    url text,
    domain text,
    title text,
    raw_text text,
    word_count integer,
    harvest_method text,
    language text,
    quality_score double precision,
    author text,
    published_date text,
    keywords jsonb,
    harvested_at timestamp with time zone
);
ALTER TABLE ONLY hive_content
    ADD CONSTRAINT hive_content_pkey PRIMARY KEY (id);""",
    'hive_entities': """CREATE TABLE hive_entities (
    id integer NOT NULL,
    mission_id text,
    source_url text,
    entity_type text,
    value text,
    context text,
    confidence real,
    extracted_at timestamp with time zone
);
ALTER TABLE ONLY hive_entities
    ADD CONSTRAINT hive_entities_pkey PRIMARY KEY (id);""",
    'hive_gaps': """CREATE TABLE hive_gaps (
    id integer NOT NULL,
    mission_id text,
    gap_query text,
    gap_type text,
    priority integer,
    resolved boolean,
    created_at timestamp with time zone
);
ALTER TABLE ONLY hive_gaps
    ADD CONSTRAINT hive_gaps_pkey PRIMARY KEY (id);""",
    'hive_missions': """CREATE TABLE hive_missions (
    id text NOT NULL,
    topic text,
    started_at timestamp with time zone,
    phase text,
    sources_found integer,
    sources_scored integer,
    sources_harvested integer,
    total_words integer,
    total_files integer,
    synthesis text,
    status text,
    think_mode boolean,
    created_at timestamp with time zone,
    scout_done_at timestamp with time zone,
    harvest_done_at timestamp with time zone,
    process_done_at timestamp with time zone,
    synth_done_at timestamp with time zone,
    sources_processed integer,
    total_entities integer,
    total_facts integer,
    config jsonb,
    quality_coverage real,
    quality_depth real,
    quality_confidence real,
    specificity_score real,
    quality_metrics jsonb
);
ALTER TABLE ONLY hive_missions
    ADD CONSTRAINT hive_missions_pkey PRIMARY KEY (id);""",
    'hive_prescout_map': """CREATE TABLE hive_prescout_map (
    id integer DEFAULT nextval('hive_prescout_seq'::regclass) NOT NULL,
    mission_id text NOT NULL,
    url text NOT NULL,
    domain text,
    domain_tier text,
    http_status integer,
    content_type text,
    content_length integer,
    last_modified text,
    robots_tag text,
    head_latency_ms integer,
    snippet_density double precision,
    resource_type text,
    routing_decision text,
    flags jsonb,
    bm_decision text,
    bm_note text,
    prescout_at timestamp with time zone
);
ALTER TABLE ONLY hive_prescout_map
    ADD CONSTRAINT hive_prescout_map_pkey PRIMARY KEY (id);""",
    'hive_queen_primers': """CREATE TABLE hive_queen_primers (
    id text NOT NULL,
    mission_id text NOT NULL,
    topic text NOT NULL,
    topic_keywords jsonb,
    top_domains jsonb,
    recommended_queries jsonb,
    key_entities jsonb,
    depth_modifier real,
    primer_quality real,
    created_at timestamp with time zone
);
ALTER TABLE ONLY hive_queen_primers
    ADD CONSTRAINT hive_queen_primers_pkey PRIMARY KEY (id);""",
    'hive_sources': """CREATE TABLE hive_sources (
    id integer NOT NULL,
    mission_id text,
    url text,
    domain text,
    title text,
    snippet text,
    source_type text,
    discovered_at timestamp with time zone,
    score_relevance integer,
    score_freshness integer,
    score_density integer,
    score_authority integer,
    score_accessibility integer,
    score_uniqueness integer,
    score_depth integer,
    score_total integer,
    status text,
    harvest_method text
);
ALTER TABLE ONLY hive_sources
    ADD CONSTRAINT hive_sources_pkey PRIMARY KEY (id);""",
}


@pytest.fixture
def live_db(monkeypatch):
    from behive.engine import db as engine_db

    dsn = os.environ.get("CLAIM_TEST_PG_DSN")
    assert dsn, "Requires the private run_existing_pg_regressions.py harness"
    parsed = parse_dsn(dsn)
    assert parsed["host"].startswith("/tmp/behive-claim-pg-repair-")
    assert parsed["dbname"] == "postgres" and parsed["user"] == "postgres"
    name = "repair1022_" + uuid.uuid4().hex
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT current_setting('data_directory'), current_setting('listen_addresses')")
        data_dir, listen = cur.fetchone()
        assert data_dir == parsed["host"] + "/data" and listen == ""
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    scoped = make_dsn(dsn, options=f"-c search_path={name} -c client_encoding=UTF8")
    conn = psycopg2.connect(scoped)
    with conn.cursor() as cur:
        cur.execute("CREATE SEQUENCE hive_sources_id_seq START 500")
        cur.execute("CREATE SEQUENCE hive_prescout_seq START 1")
        for ddl in LIVE_DDL.values():
            cur.execute(ddl)
    conn.commit()
    monkeypatch.setenv("BEHIVE_DB_URL", scoped)
    monkeypatch.setenv("BEHIVE_BACKEND", "postgres")
    monkeypatch.setattr(engine_db, "DSN", scoped)
    monkeypatch.setattr(engine_db, "_pool", None)
    try:
        yield SimpleNamespace(conn=conn, dsn=scoped, name=name)
    finally:
        if engine_db._pool is not None:
            engine_db._pool.closeall()
        conn.close()
        with admin.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))
            cur.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (name,))
            assert cur.fetchone() is None
        admin.close()
