"""Model source extraction must accept verbatim non-numeric facts (user decision 2026-10-22).

Supplier research needs sentences like "Firma X oferuje system WMS Y". The model
path is still bounded by verbatim-quote, hygiene and confidence checks; the
deterministic (no-model) fallback writers keep requiring a digit.
"""
import asyncio
import json
from unittest.mock import patch

from behive.engine import source_extraction
from behive.hygiene import sanitize_claim

URL = "https://example-wms.test/oferta"
FACT = "Firma Example Logistics oferuje system WMS Rewista zintegrowany z Comarch ERP XL."
SOURCE = (
    "Strona główna. " + FACT + " Skontaktuj się z naszym działem handlowym, "
    "aby umówić prezentację rozwiązania."
)
TOPIC = "Dostawcy systemów WMS w Polsce"


def _run(response_rows, captured=None):
    def fake_complete(prompt, **kwargs):
        if captured is not None:
            captured.append(prompt)
        return json.dumps(response_rows)

    with patch("behive.engine.llm.complete", side_effect=fake_complete):
        return asyncio.run(source_extraction.extract_source_claims(
            [{"url": URL, "raw_text": SOURCE}], TOPIC))


def test_verbatim_non_numeric_fact_is_accepted():
    claims = _run([{"claim": FACT, "evidence": FACT, "confidence": 0.9}])
    assert [(c.claim, c.source_url) for c in claims] == [(FACT, URL)]


def test_prompt_no_longer_demands_a_number_but_keeps_grounding_rules():
    captured = []
    _run([], captured)
    prompt = captured[0]
    assert "containing a number" not in prompt
    assert "verbatim" in prompt
    assert "Do not infer or invent facts" in prompt
    assert "Return [] if there is no relevant evidence" in prompt


def test_non_numeric_fact_not_in_source_is_still_rejected():
    invented = "Firma Example Logistics oferuje system WMS Galaxy dla branży chemicznej."
    assert _run([{"claim": invented, "evidence": invented, "confidence": 0.95}]) == []


def test_fragments_and_css_still_rejected_without_digit_requirement():
    assert sanitize_claim("Krótki fragment bez kropki", require_digit=False) is None
    assert sanitize_claim("Body { font-size: large; padding-left: auto } styl strony głównej", require_digit=False) is None
    assert sanitize_claim(FACT, require_digit=False) == FACT


def test_deterministic_fallback_hygiene_still_requires_digit():
    assert sanitize_claim(FACT) is None
    with_digit = "Firma Example Logistics wdrożyła system WMS Rewista w 120 magazynach w Polsce."
    assert sanitize_claim(with_digit) == with_digit
