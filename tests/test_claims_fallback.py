from behive.engine.claims_fallback import sentences_from_text
from behive.hygiene import is_structured_blob


def test_sentences_keep_numeric_prose():
    text = (
        "The Strait of Hormuz handles about 21 million barrels per day of crude. "
        "Click here to subscribe. "
        "padding-left: 12px; font-size: 14px; width: 100. "
        '{"claim": "json blob is not a claim"}. '
        "EU in-quota duty on beef remains 7.5 percent under the agreement."
    )
    sents = sentences_from_text(text, limit=8)
    joined = " ".join(sents).lower()
    assert any("21 million" in x.lower() or "barrels" in x.lower() for x in sents)
    assert any("7.5" in x for x in sents)
    assert not any("click here" in x.lower() for x in sents)
    assert not any(is_structured_blob(x) for x in sents)
    assert "padding-left" not in joined


def test_short_text_empty():
    assert sentences_from_text("too short", limit=8) == []
