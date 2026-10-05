"""Unit tests: blob filter + empty-done guard."""
from behive.hygiene import is_structured_blob, is_empty_mission, SQL_CLAIM_NOT_BLOB


def test_blob_json_object():
    assert is_structured_blob('{"source_credibility":0.38,"facts":[]}')


def test_blob_json_array():
    assert is_structured_blob('[{"id":"H1","hypothesis":"x"}]')


def test_blob_leading_whitespace():
    assert is_structured_blob('  \n\t{"a":1}')


def test_plain_claim_is_not_blob():
    assert not is_structured_blob("Nvidia reported $39.3 billion Q4 FY2025 revenue, up 78% YoY")


def test_empty_and_none_not_blob():
    assert not is_structured_blob("")
    assert not is_structured_blob(None)
    assert not is_structured_blob("   ")


def test_empty_mission_without_claim_provenance():
    assert is_empty_mission(0, 10, sourced_claims=0) is True
    assert is_empty_mission(0, 10, sourced_claims=10) is False


def test_empty_mission_zero_claims():
    assert is_empty_mission(12, 0) is True


def test_empty_mission_both_zero():
    assert is_empty_mission(0, 0) is True


def test_nonempty_mission():
    assert is_empty_mission(3, 20) is False


def test_sql_fragment_mentions_ltrim():
    assert "ltrim(claim)" in SQL_CLAIM_NOT_BLOB
    assert "{" in SQL_CLAIM_NOT_BLOB
