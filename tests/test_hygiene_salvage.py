from behive.hygiene import has_salvageable_claims, is_empty_mission


def test_empty_requires_claim_provenance_not_scout_row_counts():
    assert is_empty_mission(0, 0, sourced_claims=0) is True
    assert is_empty_mission(100, 0, sourced_claims=0) is True
    assert is_empty_mission(0, 12, sourced_claims=12) is False
    assert is_empty_mission(0, 12, sourced_claims=0) is True
    assert is_empty_mission(100, 12, sourced_claims=0) is True


def test_salvage_threshold():
    assert has_salvageable_claims(0) is False
    assert has_salvageable_claims(2) is False
    assert has_salvageable_claims(3) is True
    assert has_salvageable_claims(244) is True
