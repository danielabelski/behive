"""Planner must be able to search in the language of a country the topic targets (2026-10-23).

Live T7 ("Rynek domowych magazynów energii w Niemczech 2025: ..."): the planner may only
use the topic language (pl) and English, so Polish queries returned Polish pages about
the Polish market (metadata judge: 7/30 on topic). German-language queries were rejected
by validation as language='de' not in {pl, en}.
"""
import json

import pytest

from behive.engine import orchestrator

T7 = "Rynek domowych magazynów energii w Niemczech 2025: producenci, ceny, dotacje"


@pytest.mark.parametrize("topic,expected", [
    (T7, {"de"}),
    ("Heat pump subsidies in France and Spain 2025", {"fr", "es"}),
    ("Dostawcy systemów MES dla przemysłu spożywczego w Polsce: wdrożenia", {"pl"}),
    ("Rynek fotowoltaiki w Czechach i na Słowacji", {"cs", "sk"}),
    ("European heat pump market 2025: installed base", set()),
])
def test_geo_languages(topic, expected):
    assert orchestrator.QueenPlanner(topic)._topic_geo_languages() == expected


def _items(language):
    return [{"query": f"Heimspeicher Hersteller Vergleich {i}", "language": language,
             "intent": "vendors_list", "rationale": "German-language supplier pages."} for i in range(10)]


def test_validator_accepts_target_country_language(monkeypatch):
    planner = orchestrator.QueenPlanner(T7)
    monkeypatch.setattr("behive.engine.llm.complete", lambda *a, **k: json.dumps(_items("de"), ensure_ascii=False))
    plan = planner.plan()
    assert {t["language"] for t in plan} == {"de"}
    assert {t["region"] for t in plan} == {"de-de"}


def test_validator_still_rejects_unrelated_language(monkeypatch):
    planner = orchestrator.QueenPlanner(T7)
    monkeypatch.setattr("behive.engine.llm.complete", lambda *a, **k: json.dumps(_items("fr"), ensure_ascii=False))
    plan = planner.plan()
    assert all(t["language"] != "fr" for t in plan), "invalid plan must fall back"


def test_prompt_names_allowed_languages():
    system, prompt = orchestrator.QueenPlanner(T7)._query_prompt()
    data = json.loads(prompt.split("\n", 1)[1])
    assert set(data["allowed_languages"]) == {"pl", "en", "de"}
    assert "country" in system.casefold()
