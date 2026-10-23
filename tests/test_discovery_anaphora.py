"""'X i możliwości wykorzystania AI w ICH produkcji' is ONE subject, not two alternatives.

Holdout 2026-10-23 (aircraft engines + AI in their production): the conjunction split
made 'Silniki lotnicze' and 'możliwości wykorzystania sztucznej inteligencji w ich
produkcji' independent; claims split into engine history and generic AI.
"""
from behive.engine.orchestrator import QueenPlanner
from behive.engine.scout import _topic_subject_alternatives

H = "Silniki lotnicze i możliwości wykorzystania sztucznej inteligencji w ich produkcji"


def test_anaphoric_part_joins_previous_subject():
    alts = _topic_subject_alternatives(H)
    assert len(alts) == 1
    assert {"silniki", "lotnicze", "sztucznej", "inteligencji", "produkcji"} <= set(alts[0])


def test_english_anaphora_too():
    alts = _topic_subject_alternatives("Jet engines and the use of AI in their manufacturing")
    assert len(alts) == 1 and {"jet", "engines", "manufacturing"} <= set(alts[0])


def test_plain_coordination_still_gives_alternatives():
    assert len(_topic_subject_alternatives(
        "Dostawcy systemów WMS i telemetrii zbiorników w Polsce: oferta")) == 2


def test_fallback_queries_keep_both_halves_together():
    plan = QueenPlanner(H)._fallback_plan()
    assert plan
    for task in plan:
        q = task["query"].casefold()
        assert "silnik" in q or "lotnicz" in q, q
