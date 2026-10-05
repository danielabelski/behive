from behive.engine.byok import gap_doc, status_list, has_key


def test_lex_gap_mentions_handel():
    doc = gap_doc({"name": "LEX Wolters Kluwer", "url": "https://sip.lex.pl"}, "kodeks")
    assert doc is not None
    assert doc["data"]["skipped"] is True
    assert "LEX_API_KEY" in doc["data"]["needed"]
    assert "pl-handel@wolterskluwer.com" in doc["raw_text"]
    assert doc["raw_text"][0] not in "{["


def test_orbis_gap_mentions_env():
    doc = gap_doc({"name": "Orbis (Moody's BvD)", "url": "https://api.bvdinfo.com"}, "QA10")
    assert doc is not None
    assert "ORBIS_API_KEY" in doc["raw_text"]
    assert "chmod 600" in doc["raw_text"]


def test_status_list_no_secret_values():
    rows = status_list()
    names = {r["api"] for r in rows}
    assert "LEX Wolters Kluwer" in names
    for r in rows:
        assert "how" in r
        assert r["present"] is False or r["present"] is True
        assert not any(len(v) > 12 and v not in r["needed"] for v in r.get("present_vars") or [])
