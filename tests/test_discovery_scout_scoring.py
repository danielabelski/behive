"""Captured fuel-supplier relevance, persisted scores, and real harvest gate."""
import json
import unicodedata

import pytest

from behive.engine.harvest import HarvesterBee
from behive.engine import scout as scout_module

from test_discovery_scout_execution import FIXTURES, TOPIC, private_scout


def labelled_sources():
    rows = (json.loads((FIXTURES / 'exa_suppliers.json').read_text())
            + json.loads((FIXTURES / 'negative_sources.json').read_text()))
    # The two real missions share URLs; scout's dedupe is mission-wide.
    return list({row['url']: row for row in rows}.values())


def test_captured_suppliers_pass_harvest_ahead_of_irrelevant_authorities(private_scout):
    scout = private_scout()
    rows = labelled_sources()
    positive_urls = {r['url'] for r in rows if r['label'] == 'on_topic'}
    negative_urls = {r['url'] for r in rows if r['label'] != 'on_topic'}
    for row in rows:
        assert scout._save_source(row['url'], row['title'], row['snippet'], row['source_type'], 'captured-replay')
    persisted = scout.db.execute('SELECT url, score_relevance, score_total FROM hive_sources').fetchall()
    positive = {url: (relevance, total) for url, relevance, total in persisted if url in positive_urls}
    negative = {url: (relevance, total) for url, relevance, total in persisted if url in negative_urls}
    assert len(positive) == 10
    assert all(relevance >= 5 and total >= 15 for relevance, total in positive.values()), positive
    assert min(total for _, total in positive.values()) > max(total for _, total in negative.values()), (positive, negative)
    assert all(0 <= relevance <= 25 and 0 <= total <= 100 for _, relevance, total in persisted)
    columns = ['url', 'score_relevance', 'score_total', 'score_authority', 'score_freshness', 'score_depth']
    receipt = scout.db.execute('SELECT url, score_relevance, score_total, score_authority, score_freshness, score_depth FROM hive_sources ORDER BY score_total DESC, url').fetchall()
    print('SCOUT_SCORE_RECEIPT ' + json.dumps([dict(zip(columns, row)) for row in receipt], ensure_ascii=False))

    harvester = HarvesterBee(scout.mission_id)
    try:
        selected = harvester._load_pending_sources()
    finally:
        harvester.con.close()
    selected_urls = [r['url'] for r in selected]
    assert positive_urls <= set(selected_urls)
    assert not (negative_urls & set(selected_urls)), selected
    # Check the actual public harvester DB reader honors descending stored rank.
    assert [r['score_total'] for r in selected] == sorted([r['score_total'] for r in selected], reverse=True)


@pytest.mark.parametrize('domain', ['example.com', 'gov.pl', 'example.gov', 'itu.int', 'example.org', 'arxiv.org', 'imf.org', 'www.eulisa.europa.eu'])
def test_commercial_topic_has_no_prestige_domain_bonus(private_scout, domain):
    scout = private_scout()
    score = scout._score_source(f'https://{domain}/telemetria/', 'Telemetria zbiorników paliw', '', 'web')
    assert score['score_authority'] == 6


@pytest.mark.parametrize('topic, domain, expected', [
    ('Rozporządzenie i ustawa dotycząca zbiorników paliwa', 'gov.pl', 9),
    ('Tank telemetry regulation and directive', 'europa.eu', 9),
    ('Tank telemetry regulation and directive', 'example.com', 6),
    ('Tank telemetry regulation and directive', 'europa.eu.example.com', 6),
    ('Tank telemetry study paper', 'arxiv.org', 9),
    ('Tank telemetry study paper', 'example.edu', 9),
    ('Tank telemetry study paper', 'imf.org', 6),
    ('Tank telemetry study paper', 'example.com', 6),
])
def test_authority_is_modest_and_specific_to_topic_intent(private_scout, topic, domain, expected):
    scout = private_scout(topic)
    score = scout._score_source(f'https://{domain}/content/', topic, '', 'web')
    assert score['score_authority'] == expected


@pytest.mark.parametrize('topic, entities', [
    (TOPIC, []),
    ('Dostawcy systemów WMS i telemetrii zbiorników w Polsce', []),
    ('Acme Logistics dostawcy telemetrii', []),  # sentence-initial title case is not an entity declaration
    ('Systemy. Acme Logistics oferta', []),
    ('Analiza oferty Lech-Pol Gniezno i wdrożeń', ['Lech-Pol Gniezno']),
    ('Compare vendors Acme Logistics and Beta Systems suppliers', ['Acme Logistics', 'Beta Systems']),
    ('"FuelPrime" dostawcy systemów monitorowania', ['FuelPrime']),
    ('Oferta „Łódź Systems” dla dostawców', ['Łódź Systems']),
    ("Oferta 'Acme Logistics' dla klientów", ['Acme Logistics']),
])
def test_only_explicit_names_are_entity_anchors(topic, entities):
    assert scout_module._explicit_topic_entities(topic) == entities


def test_only_explicit_entity_can_boost_its_domain(private_scout):
    topic = 'Dostawcy "Acme Logistics" telemetrii zbiorników paliwa oraz chemikaliów'
    scout = private_scout(topic)
    score = scout._score_source('https://acme-logistics.pl/', 'Kontakt', '', 'web')
    assert score['score_relevance'] == 25
    scout.topic = 'Dostawcy acme logistics telemetrii zbiorników paliwa oraz chemikaliów'
    unquoted = scout._score_source('https://acme-logistics.pl/', 'Kontakt', '', 'web')
    assert unquoted['score_relevance'] == 0


def test_missing_explicit_entity_penalty_never_applies_to_generic_first_word(private_scout):
    scout = private_scout('Dostawcy acme logistics telemetrii zbiorników paliwa oraz chemikaliów')
    plain = scout._score_source('https://example.pl/', 'Telemetria zbiorników', '', 'web')
    scout.topic = 'Dostawcy "Acme Logistics" telemetrii zbiorników paliwa oraz chemikaliów'
    explicit = scout._score_source('https://example.pl/', 'Telemetria zbiorników', '', 'web')
    assert plain['score_relevance'] == 10
    assert explicit['score_relevance'] == 5


@pytest.mark.parametrize('url', [
    'https://sjp.pwn.pl/definicja/', 'https://wsjp.pl/haslo/', 'https://www.olx.pl/oferty/',
    'https://supplier.example/login', 'https://supplier.example/user/sign-in/',
    'https://supplier.example/login.php', 'https://supplier.example/wp-login.php',
    'https://supplier.example/cart/', 'https://supplier.example/koszyk/',
    'https://supplier.example/checkout.aspx',
])
def test_commercial_noncontent_penalty_is_soft_and_rows_are_saved(private_scout, url):
    scout = private_scout()
    title = 'Telemetria zbiorników paliw chemikaliów dostawcy wdrożenia'
    content = scout._score_source('https://supplier.example/offer/', title, '', 'web')
    noncontent = scout._score_source(url, title, '', 'web')
    assert content['score_total'] - noncontent['score_total'] == 8
    assert noncontent['score_relevance'] == content['score_relevance']
    assert noncontent['score_total'] >= 15  # penalty, not a hard-drop or zero score
    assert scout._save_source(url, title, '', 'web', 'controlled-noncontent-edge')
    assert scout.db.execute('SELECT url FROM hive_sources').fetchone() == (url,)


def test_dictionary_penalty_does_not_apply_to_noncommercial_definition_topic(private_scout):
    scout = private_scout('telemetria definicja')
    first = scout._score_source('https://sjp.pwn.pl/haslo/', 'Telemetria definicja', '', 'web')
    second = scout._score_source('https://supplier.example/haslo/', 'Telemetria definicja', '', 'web')
    assert first == second


@pytest.mark.parametrize('topic, title, expected', [
    ('telemetrii', 'Telemetria', 25),
    ('zbiorników', 'Zbiornikami', 25),
    ('oil', 'Spoilers for cars', 0),
    ('ERP', 'Enterprise tables', 0),
])
def test_shared_unicode_inflection_matcher_not_substring_scoring(private_scout, topic, title, expected):
    scout = private_scout(topic)
    assert scout._score_source('https://supplier.example/', title, '', 'web')['score_relevance'] == expected


def test_polish_stopwords_and_canonical_unicode_do_not_change_relevance(private_scout):
    scout = private_scout('telemetrii zbiorników')
    clean = scout._score_source('https://supplier.example/', 'TELEMETRIA ZBIORNIKAMI', '', 'web')
    scout.topic = 'oraz telemetrii dla zbiorników w Polsce'
    decomposed = scout._score_source('https://supplier.example/', unicodedata.normalize('NFD', 'TELEMETRIA ZBIORNIKAMI'), '', 'web')
    assert clean['score_relevance'] == 25
    assert decomposed['score_relevance'] == clean['score_relevance']


@pytest.mark.parametrize('url, title, snippet, expected', [
    ('https://supplier.example/', 'Telemetria', '', True),
    ('https://supplier.example/', '', 'Telemetria', True),
    ('https://supplier.example/telemetri%C4%85/', '', '', True),
    ('https://telemetria.example/', '', '', False),
    ('https://supplier.example/?q=telemetria', '', '', False),
    ('https://dostawcy.example/', '', '', False),
])
def test_relevance_counts_title_snippet_decoded_path_not_host_or_query(private_scout, url, title, snippet, expected):
    scout = private_scout()
    score = scout._score_source(url, title, snippet, 'web')
    assert (score['score_relevance'] >= 5) is expected


def test_one_document_word_cannot_count_as_multiple_inflections(private_scout):
    scout = private_scout('telemetria telemetrii telemetrią')
    one = scout._score_source('https://supplier.example/', 'Telemetria', '', 'web')
    three = scout._score_source('https://supplier.example/', 'Telemetria telemetrii telemetrią', '', 'web')
    # One result token satisfies one topic keyword (breadth); since 2026-10-23 the
    # subject-coverage lift applies equally to both, so compare instead of a band.
    assert 5 <= one['score_relevance'] < three['score_relevance']


@pytest.mark.parametrize('mission_id', ['hive_1792744015_96a356', 'hive_1792743366_a6ba24'])
def test_all_captured_production_rows_replay_into_private_pg(private_scout, mission_id):
    captured = json.loads((FIXTURES / 'production_sources.json').read_text())
    topic = next(row['topic'] for row in captured['missions'] if row['id'] == mission_id)
    scout = private_scout(topic)
    rows = [row for row in captured['rows'] if row['mission_id'] == mission_id]
    unique_rows = {row['url']: row for row in rows}
    for row in unique_rows.values():
        assert scout._save_source(row['url'], row['title'], row['snippet'], row['source_type'], 'captured-production-replay')
    persisted = scout.db.execute('SELECT url, score_relevance, score_total FROM hive_sources WHERE mission_id=?', [scout.mission_id]).fetchall()
    assert len(persisted) == len(unique_rows)
    assert all(0 <= relevance <= 25 and 0 <= total <= 100 for _, relevance, total in persisted)
