# Changelog

All notable changes to BeHive are documented here.

## [0.6.0] — 2026-08-13

### Added
- **Entity Anchoring** — Queen task generation enforces 60%+ entity-specific queries (eliminates topic drift)
- **direct_url scout method** — fetch known API endpoints directly (KRS, VAT Biała Lista, company sites)
- **Context Providers subsystem** — pluggable context injection for domain-specific knowledge
- **AI Brand Visibility Checker** — free tool endpoint for brand SERP analysis
- **Federated Knowledge Network** — cross-instance knowledge sharing protocol
- **llms.txt** — AI discoverability metadata

### Fixed
- Graph engine single-instance PID lock prevents zombie process accumulation
- PostgreSQL schema compatibility (DuckDB syntax migration)

### Security
- All hardcoded database credentials removed from test files
- Production password rotated; credentials now read from environment variables only
- Git history scrubbed of leaked test credentials (BFG)

### Changed
- Synth module streamlined (491-line rewrite, faster report generation)
- API scout sources expanded (+152 entries, 70+ categories)

## [0.1.0] — 2026-07-28

### Added
- Initial public release
- V4 pipeline: dual-model extraction (Haiku bulk + Sonnet enrichment)
- Quality scoring system (5 dimensions, 0.55 gate, 0.82+ avg achieved)
- REST API with 27 endpoints + SSE streaming
- MCP server (Streamable HTTP, port 8090)
- Knowledge graph integration (Neo4j)
- 70+ API sources across 37 categories
- 8-layer stealth drone architecture
- Docker Compose self-hosted setup
- Agent integrations (Hermes, OpenClaw, Claude Desktop, Cursor, n8n)
- n8n community node (`n8n-nodes-behive` on npm)
- PyPI package (`pip install behive`)
- CLI with animated research visualization

### Benchmarks (v0.1.0)
| Topic | Claims | Quality | Duration |
|-------|--------|---------|----------|
| NVIDIA GPU market | 290 | 0.797 | 8 min |
| OpenAI GPT-5 | 574 | 0.789 | 12 min |
| EU AI Act | 267 | 0.759 | 6 min |
| Meta Llama 4 | 568 | 0.821 | 11 min |
