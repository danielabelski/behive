"""RED/GREEN for source-extraction diagnostics, no network or production DB.

Captured fixture: real configured openai/gpt-6.1-sol bridge completion on
2026-10-22, source 73354 in hive_1792672143_a6ba24. It returned exactly `[]`.
The source excerpt below is the complete captured harvested maintenance notice.
This tests correct refusal + missing diagnostics, NOT a fabricated positive claim.
Full capture and bridge receipt: outputs/behive-repair-2026-10-22/B/captured_responses.json
(prompt SHA-256 ac31e618bedeb65c5f434f41442c0912d61a5575518c1bbf2b68af8225d238c1).
"""
import asyncio
import logging
import socket

import pytest
from behive.engine.source_extraction import extract_source_claims

CAPTURED_RESPONSE = '[]'
CAPTURED_TOPIC = 'Dostawcy systemów WMS i telemetrii zbiorników w Polsce: oferta, cennik, wdrożenia'
CAPTURED_URL = 'https://pressto.amu.edu.pl/index.php/se/article/view/21232'
CAPTURED_SOURCE = (
    "Prace serwisowe - UAM body, html { height: 100%; margin: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f9f9f9; color: #333; display: flex; justify-content: center; align-items: center; text-align: center; } .container { padding: 20px; max-width: 600px; } .logo { max-width: 250px; height: auto; margin-bottom: 30px; animation: fadeIn 1.5s ease-in-out; } h1 { font-size: 1.8rem; font-weight: 400; margin-bottom: 15px; color: #000; } p { font-size: 1.1rem; color: #666; line-height: 1.6; } @keyframes fadeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } } .footer { position: absolute; bottom: 20px; font-size: 0.8rem; color: #aaa; } Informujemy, że w związku z informacjami o krytycznych podatnościach bezpieczeństwa w oprogramowaniu PHP, które mogą dotyczyć części udostępnianych przez nas usług internetowych, zdecydowaliśmy o czasowym, prewencyjnym ograniczeniu dostępu do usług WWW. Decyzja jest podyktowana koniecznością ograniczenia potencjalnego ryzyka do czasu wyjaśnienia charakteru zagrożeń, oceny ich wpływu na nasze systemy oraz ewentualnego wdrożenia odpowiednich aktualizacji bezpieczeństwa. Podkreślamy, że ograniczenie dostępu nie jest wynikiem stwierdzenia naruszenia bezpieczeństwa naszych systemów. Jest to działanie zapobiegawcze, mające na celu ochronę infrastruktury i danych użytkowników. &copy; 2026 Uniwersytet im. Adama Mickiewicza w Poznaniu"
)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Network forbidden in extraction regression')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr('behive.engine.llm.complete', blocked)


def summary(caplog):
    records = [r for r in caplog.records if hasattr(r, 'source_extraction_counts')]
    assert len(records) == 1, 'Every extraction must emit one payload-free filter-stage summary'
    return records[0]


def test_captured_empty_array_explains_no_candidates_not_validation_failure(monkeypatch, caplog):
    monkeypatch.setattr('behive.engine.llm.complete', lambda **kwargs: CAPTURED_RESPONSE)
    with caplog.at_level(logging.DEBUG):
        claims = asyncio.run(extract_source_claims(
            [{'url': CAPTURED_URL, 'raw_text': CAPTURED_SOURCE}], CAPTURED_TOPIC))
    assert claims == []
    record = summary(caplog)
    assert record.source_extraction_status == 'completed'
    assert record.levelno == logging.WARNING
    counts = record.source_extraction_counts
    assert counts['documents_input'] == counts['documents_considered'] == 1
    assert counts['model_calls'] == counts['responses'] == counts['empty_responses'] == 1
    assert counts['rows_returned'] == counts['accepted'] == 0
    assert all(value == 0 for key, value in counts.items() if key.startswith('rejected_'))
    assert CAPTURED_SOURCE not in caplog.text
    assert CAPTURED_TOPIC not in caplog.text
    assert CAPTURED_URL not in caplog.text


# Explicitly synthetic negative controls; never represented as model captures.
CLEAN_CLAIM = 'Acme supplied 42 warehouse monitoring systems in Poland during 2025.'


@pytest.mark.parametrize('row,rejected', [
    ({'claim': None, 'evidence': CLEAN_CLAIM, 'confidence': .9}, 'rejected_type'),
    # Digitless facts are allowed on the model path (user decision 2026-10-22);
    # hygiene still rejects markup/CSS fragments.
    ({'claim': 'Acme warehouse page { font-size: large; padding-left: auto } styles.', 'evidence': CLEAN_CLAIM, 'confidence': .9}, 'rejected_hygiene'),
    ({'claim': 'Acme ' + 'warehouse ' * 90 + '42.', 'evidence': CLEAN_CLAIM, 'confidence': .9}, 'rejected_hygiene'),
    ({'claim': CLEAN_CLAIM, 'evidence': '', 'confidence': .9}, 'rejected_evidence'),
    ({'claim': CLEAN_CLAIM, 'evidence': 'A' * 501, 'confidence': .9}, 'rejected_evidence'),
    ({'claim': CLEAN_CLAIM.replace('42', '99'), 'evidence': CLEAN_CLAIM, 'confidence': .9}, 'rejected_quote'),
    ({'claim': CLEAN_CLAIM, 'evidence': 'Quote invented by the model.', 'confidence': .9}, 'rejected_quote'),
    ({'claim': CLEAN_CLAIM, 'evidence': CLEAN_CLAIM, 'confidence': 'bad'}, 'rejected_confidence'),
    ({'claim': CLEAN_CLAIM, 'evidence': CLEAN_CLAIM, 'confidence': .69}, 'rejected_confidence'),
    ({'claim': CLEAN_CLAIM, 'evidence': CLEAN_CLAIM, 'confidence': 1.01}, 'rejected_confidence'),
    ({'claim': CLEAN_CLAIM, 'evidence': CLEAN_CLAIM, 'confidence': float('nan')}, 'rejected_confidence'),
    ({'claim': CLEAN_CLAIM, 'evidence': CLEAN_CLAIM, 'confidence': float('inf')}, 'rejected_confidence'),
])
def test_filter_summary_identifies_first_rejection_without_relaxing_validation(monkeypatch, caplog, row, rejected):
    import json
    monkeypatch.setattr('behive.engine.llm.complete', lambda **kwargs: json.dumps([row]))
    with caplog.at_level(logging.DEBUG):
        claims = asyncio.run(extract_source_claims(
            [{'url': CAPTURED_URL, 'raw_text': CLEAN_CLAIM}], CAPTURED_TOPIC))
    assert claims == []
    counts = summary(caplog).source_extraction_counts
    assert counts['rows_returned'] == counts['rows_considered'] == 1
    assert counts[rejected] == 1
    assert sum(v for k, v in counts.items() if k.startswith('rejected_')) == 1
    assert counts['accepted'] == 0
    assert CLEAN_CLAIM not in caplog.text


def test_success_summary_accounts_for_rows_and_document_caps(monkeypatch, caplog):
    import json
    from behive.engine import source_extraction as source
    row = {'claim': CLEAN_CLAIM, 'evidence': CLEAN_CLAIM, 'confidence': .9}
    monkeypatch.setattr('behive.engine.llm.complete', lambda **kwargs: json.dumps([row] * 6))
    doc = {'url': CAPTURED_URL, 'raw_text': CLEAN_CLAIM}
    with caplog.at_level(logging.DEBUG):
        claims = asyncio.run(extract_source_claims(
            [{'url': 'file:///not-a-source', 'raw_text': CLEAN_CLAIM},
             {'url': CAPTURED_URL, 'raw_text': ''}] + [doc] * source.MAX_DOCUMENTS, CAPTURED_TOPIC))
    assert len(claims) == 290
    record = summary(caplog)
    counts = record.source_extraction_counts
    assert record.levelno == logging.INFO
    assert counts['documents_input'] == 62
    assert counts['documents_considered'] == 60
    assert counts['documents_capped'] == counts['documents_skipped'] == 2
    assert counts['model_calls'] == counts['responses'] == 58
    assert counts['rows_returned'] == 348
    assert counts['rows_capped'] == 58
    assert counts['rows_considered'] == counts['accepted'] == 290
    assert all(c.claim == c.evidence == CLEAN_CLAIM and c.source_url == CAPTURED_URL for c in claims)


@pytest.mark.parametrize('error', [TimeoutError('PRIVATE_PROVIDER_TOKEN'), RuntimeError('PRIVATE_PROVIDER_TOKEN')])
def test_provider_failure_logs_safe_type_and_counts_without_swallowing(monkeypatch, caplog, error):
    def fail(**kwargs):
        raise error
    monkeypatch.setattr('behive.engine.llm.complete', fail)
    with caplog.at_level(logging.DEBUG), pytest.raises(type(error)) as caught:
        asyncio.run(extract_source_claims(
            [{'url': CAPTURED_URL, 'raw_text': CAPTURED_SOURCE}] * 2, CAPTURED_TOPIC))
    # asyncio.to_thread may translate the built-in TimeoutError instance.
    assert str(caught.value) == str(error)
    record = summary(caplog)
    assert record.levelno == logging.ERROR
    assert record.source_extraction_status == 'failed'
    assert record.source_extraction_error_type == type(error).__name__
    assert record.source_extraction_stage == 'completion'
    assert record.source_extraction_counts['model_calls'] == 1
    assert record.source_extraction_counts['responses'] == 0
    assert record.source_extraction_counts['documents_considered'] == 1
    assert record.exc_info is None
    assert 'PRIVATE_PROVIDER_TOKEN' not in caplog.text


@pytest.mark.parametrize('response,bucket,stage', [
    ('truncated [{PRIVATE_PROVIDER_TOKEN', 'invalid_json', 'json'),
    ('{}', 'invalid_shape', 'shape'),
    ('[3]', 'invalid_shape', 'shape'),
])
def test_invalid_response_logs_parsing_stage_not_provider_text(monkeypatch, caplog, response, bucket, stage):
    monkeypatch.setattr('behive.engine.llm.complete', lambda **kwargs: response)
    with caplog.at_level(logging.DEBUG), pytest.raises(ValueError):
        asyncio.run(extract_source_claims(
            [{'url': CAPTURED_URL, 'raw_text': CAPTURED_SOURCE}], CAPTURED_TOPIC))
    record = summary(caplog)
    assert record.source_extraction_status == 'failed'
    assert record.source_extraction_error_type == 'ValueError'
    assert record.source_extraction_stage == stage
    assert record.source_extraction_counts[bucket] == 1
    assert record.source_extraction_counts['responses'] == 1
    assert 'PRIVATE_PROVIDER_TOKEN' not in caplog.text
