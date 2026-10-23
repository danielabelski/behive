"""Scout ranking: subject coverage + non-supplier penalties (2026-10-23, T2 ranking repair).

Labelled pools in tests/fixtures/discovery_ranking/ are every URL scouted by the live
benchmark run bench-final (code 51733ea), each labelled once by the benchmark's strict
model judge (captured, not hand-written). The pool test simulates
HarvesterBee._load_pending_sources ordering and guards precision@30.
"""
import json
from pathlib import Path

import pytest

from behive.engine.scout import SwarmScout, _topic_subject_alternatives

FIX = Path(__file__).parent / "fixtures/discovery_ranking"
T1 = "Dostawcy systemów WMS i telemetrii zbiorników w Polsce: oferta, cennik, wdrożenia"
T2 = "Systemy telemetrii zbiorników paliw i chemikaliów w Polsce: dostawcy i wdrożenia"


def _scout(topic):
    s = SwarmScout.__new__(SwarmScout)
    s.topic, s.mission_id = topic, "offline"
    return s


@pytest.mark.parametrize("topic,expected", [
    (T2, [("telemetrii", "zbiorników", "paliw"), ("telemetrii", "zbiorników", "chemikaliów")]),
    (T1, [("wms",), ("telemetrii", "zbiorników")]),
    ("Wymogi KSeF 2026 dla małych firm: terminy, sankcje, wyjątki", [("wymogi", "ksef", "małych")]),
    ("European heat pump market 2025: installed base, leading manufacturers, subsidies",
     [("european", "heat", "pump", "market")]),
    ("Producenci okien PCV w Polsce: lista firm, zakłady produkcyjne", [("okien", "pcv")]),
])
def test_subject_alternatives(topic, expected):
    assert _topic_subject_alternatives(topic) == expected


def test_subject_coverage_beats_shared_generic_words():
    s = _scout(T2)
    telemetry = s._score_source("https://flotlis.pl/o-nas/telemetria-on-i-lpg",
                                "Telemetria ON i LPG - FLOTLIS", "zdalny system monitoringu zbiorników paliwa", "web")
    tank_seller = s._score_source("https://aseem.pl", "ASEEM – dostawy paliw, AdBlue, zbiorniki",
                                  "Sprzedaż zbiorników na paliwo i dystrybutorów", "web")
    assert telemetry["score_total"] > tank_seller["score_total"]


def test_monitoring_counts_as_telemetry_subject():
    s = _scout(T2)
    a = s._score_source("https://a.example.pl/", "Telemetria zbiorników paliwa", "", "web")
    b = s._score_source("https://b.example.pl/", "Monitoring zbiorników paliwa", "", "web")
    c = s._score_source("https://c.example.pl/", "Pojemność zbiorników paliwa", "", "web")
    assert a["score_relevance"] - b["score_relevance"] <= 3, "only breadth may differ"
    assert b["score_relevance"] > c["score_relevance"]


@pytest.mark.parametrize("url", [
    # No years/.pdf in paths: only the page-type penalty may differ (freshness/depth equal).
    "https://ted.europa.eu/pl/notice/-/detail/309862",
    "https://op.europa.eu/en/web/public-procurement/procurement-details/-/procurement/123",
    "https://bip-v1-files.idcom-jst.pl/sites/3083/wiadomosci/73232/files/oferta",
    "https://api.sejm.gov.pl/eli/acts/DU/1707/text",
    "https://bidsfactory.com/en/tenders/12345",
    "https://aplikuj.pl/pracodawca/17781",
    "https://pern.pl/en/author/jan-kowalski",
])
def test_non_supplier_pages_penalized_for_commercial_topic(url):
    title, snippet = "Telemetria zbiorników paliw", "system telemetrii zbiorników paliw dostawcy wdrożenia"
    supplier = _scout(T2)._score_source("https://example-supplier.pl/", title, snippet, "web")
    other = _scout(T2)._score_source(url, title, snippet, "web")
    assert other["score_total"] == supplier["score_total"] - 8


def test_procurement_pages_not_penalized_when_topic_asks_for_tenders():
    topic = "Przetargi na systemy telemetrii zbiorników paliw w Polsce: dostawcy, ceny ofert"
    title, snippet = "Telemetria zbiorników paliw", "przetarg system telemetrii zbiorników paliw dostawcy"
    a = _scout(topic)._score_source("https://example-supplier.pl/", title, snippet, "web")
    b = _scout(topic)._score_source("https://ted.europa.eu/pl/notice/-/detail/1", title, snippet, "web")
    assert a["score_total"] == b["score_total"]


def _p_at_30(tid, topic):
    pool = json.loads((FIX / f"{tid}.json").read_text())
    s = _scout(topic)
    rows = [(i, r, s._score_source(r["url"], r["title"] or "", r["snippet"] or "", r["source_type"] or "web"))
            for i, r in enumerate(pool)]
    strict = [x for x in rows if x[2]["score_relevance"] >= 5 and x[2]["score_total"] >= 15]
    order = sorted(strict or rows, key=lambda x: (-x[2]["score_total"], x[0]))[:300 if strict else 100]
    top = order[:30]
    return sum(1 for _, r, _ in top if r["on_topic"]) / len(top)


TOPICS = json.loads((FIX / "topics.json").read_text())
# Same labels, simulated top-30: baseline scoring (eb38b5a) T1 .767 T2 .500 T3 .833
# T4 .867 T5 .967 (topics.json); this change T1 .900 T2 .733 T3 .833 T4 .833 T5 .967.
# Floors sit one page (1/30) below the new values; harvest admission (relevance>=5)
# is unchanged because relevance never drops below the old breadth score.
FLOORS = {"T1": 0.866, "T2": 0.70, "T3": 0.80, "T4": 0.80, "T5": 0.933}


@pytest.mark.parametrize("tid", sorted(TOPICS))
def test_captured_pool_precision_at_30(tid):
    assert _p_at_30(tid, TOPICS[tid]["topic"]) >= FLOORS[tid]
