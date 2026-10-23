"""Deterministic fallback plan must match the topic kind (parent review 2026-10-23).

The W2 fallback attached commercial suffixes to every topic, producing queries such as
"CRISPR gene editing research papers 2024 pricing" and "Wymogi KSeF 2026 ... cennik".
The fallback only runs when the model planner fails, but it must still search sensibly.
"""
import pytest

from behive.engine.orchestrator import QueenPlanner

COMMERCIAL_WORDS = {"vendors", "suppliers", "pricing", "cost", "manufacturers", "products",
                    "cennik", "dostawcy", "producenci", "oferta", "produkty", "case", "wdrożenia"}


def _queries(topic):
    plan = QueenPlanner(topic)._fallback_plan()
    assert 8 <= len(plan) <= 14
    for task in plan:
        assert 2 <= len(task["query"].split()) <= 8
        assert task["method"] in {"web", "ddg_news"}
    return [t["query"].casefold() for t in plan]


def _words(queries):
    return {w for q in queries for w in q.split()}


@pytest.mark.parametrize("topic,kind", [
    ("CRISPR gene editing research papers 2024", "academic"),
    ("Wymogi KSeF 2026 dla małych firm: terminy, sankcje, wyjątki", "regulatory"),
    ("sanctions Russia energy exports 2024", "general"),
    ("European heat pump market 2025: installed base, leading manufacturers, subsidies", "market"),
    ("Producenci okien PCV w Polsce: lista firm, zakłady produkcyjne", "commercial"),
    ("Dostawcy systemów WMS i telemetrii zbiorników w Polsce: oferta, cennik, wdrożenia", "commercial"),
])
def test_topic_kind(topic, kind):
    assert QueenPlanner(topic)._topic_kind() == kind


def test_academic_fallback_has_no_commercial_intents():
    queries = _queries("CRISPR gene editing research papers 2024")
    assert not (_words(queries) & COMMERCIAL_WORDS), queries
    assert _words(queries) & {"review", "study", "studies", "paper", "papers", "trial", "results"}


def test_regulatory_fallback_targets_rules_not_vendors():
    queries = _queries("Wymogi KSeF 2026 dla małych firm: terminy, sankcje, wyjątki")
    assert not (_words(queries) & COMMERCIAL_WORDS), queries
    assert _words(queries) & {"przepisy", "ustawa", "rozporządzenie", "obowiązki", "interpretacje"}
    assert any("sankcje" in q for q in queries) and any("wyjątki" in q for q in queries)


def test_general_fallback_has_no_commercial_intents():
    queries = _queries("sanctions Russia energy exports 2024")
    assert not (_words(queries) & COMMERCIAL_WORDS), queries


def test_market_fallback_keeps_requested_facets_and_market_intents():
    queries = _queries("European heat pump market 2025: installed base, leading manufacturers, subsidies")
    assert any("installed base" in q for q in queries)
    assert any("leading manufacturers" in q for q in queries)
    assert _words(queries) & {"share", "size", "statistics", "forecast"}


def test_commercial_fallback_still_searches_suppliers():
    queries = _queries("Producenci okien PCV w Polsce: lista firm, zakłady produkcyjne")
    assert _words(queries) & {"producenci", "dostawcy", "firmy"}
    assert any("zakłady produkcyjne" in q for q in queries)
