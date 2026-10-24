"""E2E finding 2026-10-23 (mission hive_1792742515_a6ba24): one Codex-bridge 502
(litellm BadGatewayError) on document 9 of 20 discarded 32 already-validated
claims, because any provider error aborted the whole A3 batch.

Contract: a 5xx-class gateway error gets one retry; a document that still fails
is skipped and counted, other documents' claims are kept, status=partial.
The whole batch still fails when no document got a response, after 3
consecutive failed documents, or on any non-transient error (auth, timeout,
rate limit, invalid output).
"""
import asyncio
import json
import logging

import pytest

from behive.engine import source_extraction

TOPIC = "Dostawcy systemów WMS w Polsce"


class BadGatewayError(Exception):
    """Same class name as litellm.BadGatewayError; no provider text."""


class AuthenticationError(Exception):
    pass


def _doc(i):
    fact = f"Firma Example {chr(65 + i)} oferuje system WMS Rewista dla magazynów chemicznych."
    return {"url": f"https://seed{i}.example.test/wms", "raw_text": "Oferta. " + fact + " Kontakt."}, fact


def _summary(caplog):
    records = [r for r in caplog.records if hasattr(r, "source_extraction_counts")]
    assert records
    return records[-1]


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(source_extraction, "TRANSIENT_RETRY_DELAY_S", 0, raising=False)


def _plan_for(docs_facts, failures):
    plan = {}
    for i, (doc, fact) in enumerate(docs_facts):
        plan[fact] = list(failures.get(i, [])) + [fact]
    return plan


def _run(monkeypatch, docs_facts, failures):
    plan = _plan_for(docs_facts, failures)
    calls = []

    def complete(prompt, **kwargs):
        fact = next(f for f in plan if f in prompt)
        calls.append(fact)
        outcome = plan[fact].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return json.dumps([{"claim": outcome, "evidence": outcome, "confidence": 0.9}])

    monkeypatch.setattr("behive.engine.llm.complete", complete)
    claims = asyncio.run(source_extraction.extract_source_claims([d for d, _ in docs_facts], TOPIC))
    return claims, calls


def test_document_failing_twice_is_skipped_and_others_kept(monkeypatch, caplog):
    docs = [_doc(i) for i in range(3)]
    with caplog.at_level(logging.DEBUG):
        claims, calls = _run(monkeypatch, docs, {1: [BadGatewayError(), BadGatewayError()]})
    assert [c.claim for c in claims] == [docs[0][1], docs[2][1]]
    record = _summary(caplog)
    assert record.source_extraction_status == "partial"
    assert record.levelno == logging.WARNING
    counts = record.source_extraction_counts
    assert counts["documents_failed"] == 1
    assert counts["transient_errors"] == 2
    assert counts["model_calls"] == 4 and counts["responses"] == 2


def test_single_transient_error_is_retried_once(monkeypatch, caplog):
    docs = [_doc(0)]
    with caplog.at_level(logging.DEBUG):
        claims, calls = _run(monkeypatch, docs, {0: [BadGatewayError()]})
    assert [c.claim for c in claims] == [docs[0][1]]
    record = _summary(caplog)
    assert record.source_extraction_status == "completed"
    assert record.source_extraction_counts["transient_errors"] == 1
    assert record.source_extraction_counts["documents_failed"] == 0


def test_all_documents_failing_still_fails_the_batch(monkeypatch, caplog):
    docs = [_doc(i) for i in range(2)]
    failures = {i: [BadGatewayError(), BadGatewayError()] for i in range(2)}
    with caplog.at_level(logging.DEBUG), pytest.raises(BadGatewayError):
        _run(monkeypatch, docs, failures)
    assert _summary(caplog).source_extraction_status == "failed"


def test_three_consecutive_failures_stop_admission_with_one_inflight_sibling(monkeypatch, caplog):
    docs = [_doc(i) for i in range(5)]
    failures = {i: [BadGatewayError(), BadGatewayError()] for i in (1, 2, 3)}
    with caplog.at_level(logging.DEBUG), pytest.raises(BadGatewayError):
        _, calls = _run(monkeypatch, docs, failures)
    counts = _summary(caplog).source_extraction_counts
    assert 7 <= counts["model_calls"] <= 8, "1 ok + 3 failed pages x 2 attempts, plus at most one admitted sibling"
    assert counts["documents_failed"] == 3


def test_non_transient_error_drains_admitted_sibling_without_retry(monkeypatch, caplog):
    docs = [_doc(i) for i in range(2)]
    with caplog.at_level(logging.DEBUG), pytest.raises(AuthenticationError):
        _run(monkeypatch, docs, {0: [AuthenticationError()]})
    counts = _summary(caplog).source_extraction_counts
    assert counts["model_calls"] == 2 and counts["responses"] == 1
