-- ═══════════════════════════════════════════════════════════════════
-- BeHive PostgreSQL Schema — Full Production
-- Runs automatically on first docker compose up
-- ═══════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── Core Tables ─────────────────────────────────────────────────

-- Missions (research sessions)
CREATE TABLE IF NOT EXISTS hive_missions (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    phase TEXT DEFAULT 'scout',
    depth INTEGER DEFAULT 3,
    sources_found INTEGER DEFAULT 0,
    sources_scored INTEGER DEFAULT 0,
    sources_harvested INTEGER DEFAULT 0,
    sources_processed INTEGER DEFAULT 0,
    total_words INTEGER DEFAULT 0,
    total_files INTEGER DEFAULT 0,
    total_entities INTEGER DEFAULT 0,
    total_facts INTEGER DEFAULT 0,
    synthesis TEXT,
    think_mode BOOLEAN DEFAULT FALSE,
    config JSONB DEFAULT '{}'::jsonb,
    quality_coverage REAL,
    quality_depth REAL,
    quality_confidence REAL,
    specificity_score REAL,
    quality_metrics JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    scout_done_at TIMESTAMPTZ,
    harvest_done_at TIMESTAMPTZ,
    process_done_at TIMESTAMPTZ,
    synth_done_at TIMESTAMPTZ
);

-- Sources (discovered URLs)
CREATE TABLE IF NOT EXISTS hive_sources (
    id SERIAL PRIMARY KEY,
    mission_id TEXT REFERENCES hive_missions(id),
    url TEXT NOT NULL,
    domain TEXT,
    title TEXT,
    snippet TEXT,
    source_type TEXT,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    score_relevance INTEGER DEFAULT 0,
    score_freshness INTEGER DEFAULT 0,
    score_density INTEGER DEFAULT 0,
    score_authority INTEGER DEFAULT 0,
    score_accessibility INTEGER DEFAULT 0,
    score_uniqueness INTEGER DEFAULT 0,
    score_depth INTEGER DEFAULT 0,
    score_total INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    harvest_method TEXT
);

CREATE INDEX IF NOT EXISTS idx_sources_mission ON hive_sources(mission_id);
CREATE INDEX IF NOT EXISTS idx_sources_domain ON hive_sources(domain);

-- Content (harvested page content)
CREATE TABLE IF NOT EXISTS hive_content (
    id SERIAL PRIMARY KEY,
    mission_id TEXT REFERENCES hive_missions(id),
    url TEXT NOT NULL,
    domain TEXT,
    title TEXT,
    raw_text TEXT,
    word_count INTEGER DEFAULT 0,
    harvest_method TEXT,
    language TEXT,
    quality_score DOUBLE PRECISION DEFAULT 0.0,
    author TEXT,
    published_date TEXT,
    keywords JSONB,
    harvested_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_mission ON hive_content(mission_id);
CREATE INDEX IF NOT EXISTS idx_content_quality ON hive_content(quality_score DESC);

-- Claims (extracted facts with scores)
CREATE TABLE IF NOT EXISTS hive_claims (
    id SERIAL PRIMARY KEY,
    mission_id TEXT REFERENCES hive_missions(id),
    claim TEXT NOT NULL,
    evidence TEXT,
    source_url TEXT,
    claim_type TEXT DEFAULT 'fact',
    confidence REAL DEFAULT 0.5,
    quality_score DOUBLE PRECISION DEFAULT 0.0,
    quality_details JSONB,
    source_operation TEXT,
    source_tier INTEGER DEFAULT 3,
    extracted_at TIMESTAMPTZ DEFAULT NOW(),
    verified BOOLEAN DEFAULT FALSE,
    evidence_flags TEXT,
    is_garbage BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_claims_mission ON hive_claims(mission_id);
CREATE INDEX IF NOT EXISTS idx_claims_quality ON hive_claims(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_claims_text_trgm ON hive_claims USING gin(claim gin_trgm_ops);

-- Entities (extracted named entities)
CREATE TABLE IF NOT EXISTS hive_entities (
    id SERIAL PRIMARY KEY,
    mission_id TEXT REFERENCES hive_missions(id),
    source_url TEXT,
    entity_type TEXT,
    value TEXT NOT NULL,
    context TEXT,
    confidence REAL DEFAULT 0.5,
    extracted_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entities_mission ON hive_entities(mission_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON hive_entities(entity_type);

-- Triples (subject-predicate-object relationships)
CREATE TABLE IF NOT EXISTS hive_triples (
    id SERIAL PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES hive_missions(id),
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence DOUBLE PRECISION DEFAULT 0.5,
    source_count INTEGER DEFAULT 1,
    sources JSONB
);

CREATE INDEX IF NOT EXISTS idx_triples_mission ON hive_triples(mission_id);

-- Gaps (identified knowledge gaps for follow-up research)
CREATE TABLE IF NOT EXISTS hive_gaps (
    id SERIAL PRIMARY KEY,
    mission_id TEXT REFERENCES hive_missions(id),
    gap_query TEXT NOT NULL,
    gap_type TEXT,
    priority INTEGER DEFAULT 5,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Intelligence Tables ─────────────────────────────────────────

-- Events (real-time progress / SSE streaming)
CREATE SEQUENCE IF NOT EXISTS hive_events_seq;
CREATE TABLE IF NOT EXISTS hive_events (
    id INTEGER PRIMARY KEY DEFAULT nextval('hive_events_seq'),
    mission_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    event_type TEXT NOT NULL,
    data JSONB,
    quality_coverage REAL,
    quality_depth REAL,
    quality_confidence REAL,
    ts TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_mission ON hive_events(mission_id, ts);

-- Domain reputation (track which domains yield high-quality content)
CREATE TABLE IF NOT EXISTS hive_domain_reputation (
    domain TEXT PRIMARY KEY,
    avg_quality REAL DEFAULT 0.0,
    harvest_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    last_harvest_at TIMESTAMPTZ,
    last_bad_at TIMESTAMPTZ,
    consecutive_bad INTEGER DEFAULT 0,
    blacklisted BOOLEAN DEFAULT FALSE,
    blacklist_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Drone map (stealth strategy per domain)
CREATE TABLE IF NOT EXISTS drone_map (
    mission_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    strategy TEXT,
    block_type TEXT,
    working_ua TEXT,
    cffi_target TEXT,
    primp_target TEXT,
    robots_json TEXT,
    delay_ms INTEGER,
    via_jina BOOLEAN DEFAULT FALSE,
    via_wayback BOOLEAN DEFAULT FALSE,
    via_archive_ph BOOLEAN DEFAULT FALSE,
    via_nodriver BOOLEAN DEFAULT FALSE,
    via_patchright BOOLEAN DEFAULT FALSE,
    probe_status INTEGER,
    probe_ms INTEGER,
    notes_json TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (mission_id, domain)
);

-- Clusters (topic clustering of content)
CREATE TABLE IF NOT EXISTS hive_clusters (
    id SERIAL PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES hive_missions(id),
    cluster_id INTEGER,
    topic_label TEXT,
    keywords JSONB,
    document_count INTEGER DEFAULT 0,
    urls JSONB,
    representative_text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    centroid_score DOUBLE PRECISION DEFAULT 0.0
);

-- ─── Queen / Planning Tables ─────────────────────────────────────

-- Queen primers (research strategy plans)
CREATE TABLE IF NOT EXISTS hive_queen_primers (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES hive_missions(id),
    topic TEXT NOT NULL,
    topic_keywords JSONB,
    top_domains JSONB,
    recommended_queries JSONB,
    key_entities JSONB,
    depth_modifier REAL DEFAULT 1.0,
    primer_quality REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Queen facts (persistent knowledge across missions)
CREATE TABLE IF NOT EXISTS hive_queen_facts (
    id TEXT PRIMARY KEY,
    fact_text TEXT NOT NULL,
    source_type TEXT,
    mission_id TEXT,
    agent_id TEXT,
    run_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    linked_ids TEXT
);

-- Numerical facts (verified data points)
CREATE TABLE IF NOT EXISTS hive_facts (
    id SERIAL PRIMARY KEY,
    mission_id TEXT REFERENCES hive_missions(id),
    value DOUBLE PRECISION,
    unit TEXT,
    context TEXT,
    source_count INTEGER DEFAULT 1,
    sources JSONB,
    domains JSONB,
    confidence TEXT,
    is_outlier BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Feedback / Learning Tables ──────────────────────────────────

-- Claim feedback (user ratings for quality calibration)
CREATE TABLE IF NOT EXISTS hive_claim_feedback (
    id SERIAL PRIMARY KEY,
    claim_id TEXT NOT NULL,
    mission_id TEXT,
    rating SMALLINT NOT NULL,
    context TEXT,
    source_operation TEXT,
    source_tier INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ─── Indexes for Performance ─────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_sources_status ON hive_sources(status);
CREATE INDEX IF NOT EXISTS idx_content_url ON hive_content(url);
CREATE INDEX IF NOT EXISTS idx_entities_value ON hive_entities(value);
CREATE INDEX IF NOT EXISTS idx_facts_mission ON hive_facts(mission_id);
CREATE INDEX IF NOT EXISTS idx_clusters_mission ON hive_clusters(mission_id);

-- ─── Bee Results ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hive_bee_results (
    id              TEXT PRIMARY KEY,
    mission_id      TEXT REFERENCES hive_missions(id),
    doc_id          TEXT,
    operation_id    TEXT,
    operation_name  TEXT,
    tier            INTEGER,
    relevance_score REAL,
    output_json     TEXT,
    confidence      REAL,
    processing_ms   INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bee_results_mission ON hive_bee_results(mission_id);

-- ─── Citations ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hive_citations (
    id                  SERIAL PRIMARY KEY,
    mission_id          TEXT REFERENCES hive_missions(id),
    claim               TEXT,
    source_url          TEXT,
    source_domain       TEXT,
    source_title        TEXT,
    author              TEXT,
    published_date      TEXT,
    confidence          DOUBLE PRECISION,
    cross_validated     BOOLEAN DEFAULT FALSE,
    supporting_sources  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_citations_mission ON hive_citations(mission_id);

-- ─── Queen Assessments ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hive_queen_assessments (
    id                      TEXT PRIMARY KEY,
    mission_id              TEXT REFERENCES hive_missions(id),
    query                   TEXT,
    queen_json              TEXT,
    must_know_insight       TEXT,
    hausdorff_score         REAL,
    confidence_raw          REAL,
    confidence_calibrated   REAL,
    bee_ops_count           INTEGER,
    rag_chunks_count        INTEGER,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_queen_assessments_mission ON hive_queen_assessments(mission_id);

-- ─── Compatibility Functions ──────────────────────────────────────────────
-- Replaces DuckDB's built-in array_cosine_similarity for vector search
CREATE OR REPLACE FUNCTION array_cosine_similarity(a DOUBLE PRECISION[], b DOUBLE PRECISION[]) 
RETURNS DOUBLE PRECISION AS $$
DECLARE
    dot_product DOUBLE PRECISION := 0;
    norm_a DOUBLE PRECISION := 0;
    norm_b DOUBLE PRECISION := 0;
    i INTEGER;
BEGIN
    IF a IS NULL OR b IS NULL OR array_length(a, 1) IS NULL OR array_length(b, 1) IS NULL THEN
        RETURN NULL;
    END IF;
    IF array_length(a, 1) != array_length(b, 1) THEN
        RETURN NULL;
    END IF;
    FOR i IN 1..array_length(a, 1) LOOP
        dot_product := dot_product + a[i] * b[i];
        norm_a := norm_a + a[i] * a[i];
        norm_b := norm_b + b[i] * b[i];
    END LOOP;
    IF norm_a = 0 OR norm_b = 0 THEN
        RETURN 0;
    END IF;
    RETURN dot_product / (sqrt(norm_a) * sqrt(norm_b));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Overload for REAL[] arrays (FLOAT[] in schema)
CREATE OR REPLACE FUNCTION array_cosine_similarity(a REAL[], b REAL[]) 
RETURNS DOUBLE PRECISION AS $$
    SELECT array_cosine_similarity(a::DOUBLE PRECISION[], b::DOUBLE PRECISION[]);
$$ LANGUAGE sql IMMUTABLE;

-- ─── Feedback / Intelligence Closure Tables ──────────────────────────────

-- Calibration log (predictions extracted from syntheses)
CREATE TABLE IF NOT EXISTS hive3_calibration_log (
    id SERIAL PRIMARY KEY,
    mission_id TEXT,
    prediction TEXT NOT NULL,
    confidence_stated REAL DEFAULT 0.5,
    outcome TEXT,
    outcome_evidence TEXT,
    time_to_outcome_hours REAL,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_calibration_mission ON hive3_calibration_log(mission_id);
CREATE INDEX IF NOT EXISTS idx_calibration_outcome ON hive3_calibration_log(outcome);

-- Priors (cross-mission confirmed facts)
CREATE TABLE IF NOT EXISTS hive3_priors (
    id TEXT PRIMARY KEY,
    fact TEXT NOT NULL,
    domain TEXT DEFAULT 'general',
    confidence REAL DEFAULT 0.5,
    source_mission TEXT,
    cited_by_missions TEXT DEFAULT '[]',
    times_confirmed INTEGER DEFAULT 0,
    times_contradicted INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_confirmed TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_priors_domain ON hive3_priors(domain);
CREATE INDEX IF NOT EXISTS idx_priors_confidence ON hive3_priors(confidence DESC);

-- Graveyard (refuted hypotheses)
CREATE TABLE IF NOT EXISTS hive3_graveyard (
    id TEXT PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    topic_domain TEXT DEFAULT 'general',
    failure_reason TEXT,
    mission_id TEXT,
    confidence_at_death REAL DEFAULT 0.0,
    buried_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_graveyard_domain ON hive3_graveyard(topic_domain);

-- Lessons (operational lessons from past missions)
CREATE TABLE IF NOT EXISTS hive3_lessons (
    id SERIAL PRIMARY KEY,
    mission_id TEXT,
    lesson_type TEXT DEFAULT 'INSIGHT',
    lesson TEXT NOT NULL,
    recommendation TEXT,
    applies_to TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lessons_mission ON hive3_lessons(mission_id);
CREATE INDEX IF NOT EXISTS idx_lessons_type ON hive3_lessons(lesson_type);

-- Falsification evidence
CREATE TABLE IF NOT EXISTS hive3_falsification_evidence (
    id VARCHAR PRIMARY KEY,
    mission_id VARCHAR,
    doc_url VARCHAR,
    target_claim VARCHAR,
    contra_evidence VARCHAR,
    evidence_quality VARCHAR,
    contradiction_type VARCHAR,
    impact VARCHAR,
    confidence FLOAT DEFAULT 0.0,
    overall_challenge_score FLOAT DEFAULT 0.0,
    falsification_status VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Numerical conflicts
CREATE TABLE IF NOT EXISTS hive3_numerical_conflicts (
    id VARCHAR PRIMARY KEY,
    mission_id VARCHAR,
    entity_category VARCHAR,
    year_context VARCHAR,
    claim_a_id VARCHAR,
    claim_a_text VARCHAR,
    value_a DOUBLE PRECISION,
    unit_a VARCHAR,
    claim_b_id VARCHAR,
    claim_b_text VARCHAR,
    value_b DOUBLE PRECISION,
    unit_b VARCHAR,
    divergence_pct DOUBLE PRECISION,
    resolution VARCHAR,
    resolver_notes VARCHAR,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─── RAG Chunks ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hive_rag_chunks (
    id VARCHAR PRIMARY KEY,
    mission_id VARCHAR,
    doc_id VARCHAR,
    url VARCHAR,
    domain VARCHAR,
    language VARCHAR,
    chunk_index INTEGER,
    chunk_text VARCHAR,
    context_header VARCHAR,
    word_count INTEGER,
    embedding FLOAT[512],
    confidence FLOAT DEFAULT 0.7,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_mission ON hive_rag_chunks(mission_id);

-- ─── Additional Intelligence Tables ──────────────────────────────────────

-- Tier tuning (per-domain bee tier weight calibration)
CREATE TABLE IF NOT EXISTS hive3_tier_tuning (
    id SERIAL PRIMARY KEY,
    tier INTEGER NOT NULL,
    topic_domain TEXT DEFAULT 'general',
    activation_weight REAL DEFAULT 1.0,
    avg_confidence REAL DEFAULT 0.5,
    mission_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tier_tuning_domain ON hive3_tier_tuning(topic_domain);

-- Ecosystem state (key-value store for calibrator state)
CREATE TABLE IF NOT EXISTS hive3_ecosystem_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Pattern library (discovered research patterns)
CREATE TABLE IF NOT EXISTS hive3_pattern_library (
    id SERIAL PRIMARY KEY,
    pattern_name TEXT NOT NULL,
    pattern_type TEXT DEFAULT 'general',
    description TEXT,
    confidence REAL DEFAULT 0.5,
    observation_count INTEGER DEFAULT 1,
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_patterns_type ON hive3_pattern_library(pattern_type);

-- Cluster atlas (cross-mission topic clustering)
CREATE TABLE IF NOT EXISTS hive3_cluster_atlas (
    id SERIAL PRIMARY KEY,
    cluster_theme TEXT NOT NULL,
    theme_keywords JSONB DEFAULT '[]'::jsonb,
    mission_ids JSONB DEFAULT '[]'::jsonb,
    mission_count INTEGER DEFAULT 0,
    centroid FLOAT[512],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cluster_atlas_theme ON hive3_cluster_atlas(cluster_theme);

-- Mission memory (key findings persistence across missions)
CREATE TABLE IF NOT EXISTS hive3_mission_memory (
    id SERIAL PRIMARY KEY,
    mission_id TEXT NOT NULL,
    mission_topic TEXT,
    completed_at TIMESTAMPTZ,
    key_findings JSONB DEFAULT '[]'::jsonb,
    confidence REAL DEFAULT 0.5,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mission_memory_mission ON hive3_mission_memory(mission_id);
