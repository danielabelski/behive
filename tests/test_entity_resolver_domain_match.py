"""Domain matcher + PL ID resolver — no TLS drones."""
from behive.engine.api_scout import load_registry, match_apis, _kw_in_query, _build_url
from behive.engine.entity_resolver import (
    classify_domain,
    extract_pl_ids,
    enrich_query,
    resolve_entity,
    api_allowed,
)


def test_war_is_not_warszawa():
    assert not _kw_in_query("war", "ceidg jan kowalski warszawa")
    assert _kw_in_query("war", "war in ukraine")


def test_domain_ceidg_is_company_pl():
    assert classify_domain("CEIDG Jan Kowalski Warszawa") == "company_pl"


def test_domain_orzeczenie():
    assert classify_domain("orzeczenie SN 2025 kradzież danych") == "judgment"


def test_domain_isap_pl_law():
    assert classify_domain("ISAP dziennik ustaw kodeks cywilny") == "pl_law"


def test_domain_mercosur_tariff():
    assert classify_domain("EU Mercosur staging category 4 Annex 2-A") == "tariff"


def test_domain_nvidia_not_crypto():
    assert classify_domain("NVIDIA GPU market 2026") == "general"


def test_domain_bitcoin_crypto():
    assert classify_domain("bitcoin defi market 2026") == "crypto"


def test_extract_krs_and_nip():
    ids = extract_pl_ids("QA10 sp. z o.o. KRS 0001232199 NIP 9542906279")
    assert ids["krs"] == "0001232199"
    assert ids["nip"] == "9542906279"


def test_extract_bare_krs_leading_zeros():
    ids = extract_pl_ids("spółka 0001232199 Katowice")
    assert ids["krs"] == "0001232199"


def test_usgs_denied_on_ceidg():
    usgs = {"name": "USGS Earthquake", "category": "science_data"}
    assert api_allowed(usgs, "company_pl") is False
    assert api_allowed(usgs, "general") is False


def test_krs_allowed_on_company_pl():
    krs = {"name": "KRS API (Polish Court Registry)", "category": "company_data"}
    assert api_allowed(krs, "company_pl") is True


def test_match_ceidg_not_usgs():
    reg = load_registry()
    names = [m.api["name"] for m in match_apis("CEIDG Jan Kowalski Warszawa", reg)]
    assert "USGS Earthquake" not in names
    assert any("KRS" in n or "Biala" in n for n in names)


def test_match_nvidia_not_coingecko():
    reg = load_registry()
    names = [m.api["name"] for m in match_apis("NVIDIA GPU market 2026", reg)]
    assert "CoinGecko" not in names
    assert "CoinPaprika" not in names


def test_match_orzeczenie_hits_saos_not_usgs():
    reg = load_registry()
    names = [m.api["name"] for m in match_apis("orzeczenie SN 2025 kradzież danych", reg)]
    assert "SAOS (Polish Court Judgments)" in names
    assert "USGS Earthquake" not in names
    assert "Federal Register" not in names


def test_match_company_pl_includes_orbis_bisnode():
    reg = load_registry()
    names = [m.api["name"] for m in match_apis("QA10 sp. z o.o. Katowice", reg)]
    assert "Orbis (Moody's BvD)" in names
    assert "Bisnode D&B" in names


def test_vendor_key_empty_without_env():
    from behive.engine.api_scout import _vendor_api_key
    assert _vendor_api_key({"name": "Orbis (Moody's BvD)"}) == ""
    assert _vendor_api_key({"name": "LEX Wolters Kluwer"}) == ""
    assert _vendor_api_key({"name": "Bisnode D&B"}) == ""


def test_match_qa10_hits_krs():
    reg = load_registry()
    q = "QA10 sp. z o.o. Katowice KRS 0001232199 NIP 9542906279"
    names = [m.api["name"] for m in match_apis(q, reg)]
    assert "KRS API (Polish Court Registry)" in names
    assert "USGS Earthquake" not in names


def test_build_url_skips_krs_without_id():
    api = {"name": "KRS API (Polish Court Registry)", "url": "https://api-krs.ms.gov.pl"}
    ep = {"path": "/api/krs/OdpisAktualny/{krs_number}?rejestr=P&format=json"}
    assert _build_url(api, ep, "QA10 sp z o o Katowice") is None


def test_build_url_krs_with_id():
    api = {"name": "KRS API (Polish Court Registry)", "url": "https://api-krs.ms.gov.pl"}
    ep = {"path": "/api/krs/OdpisAktualny/{krs_number}?rejestr=P&format=json"}
    url = _build_url(api, ep, "QA10 KRS 0001232199")
    assert url and "0001232199" in url


def test_enrich_query_appends_ids():
    from behive.engine.entity_resolver import ResolvedEntity
    ent = ResolvedEntity(krs="0001232199", nip="9542906279", domain="company_pl")
    q = enrich_query("QA10 sp. z o.o.", ent)
    assert "0001232199" in q
    assert "9542906279" in q


def test_domain_eurolaw():
    assert classify_domain("Eurolaw") == "eu_law"
    assert classify_domain("EUR-Lex CELEX 32016R0679") == "eu_law"


def test_extract_celex():
    from behive.engine.cellar import extract_celex, case_to_celex
    assert extract_celex("GDPR 32016R0679 text") == "32016R0679"
    assert extract_celex("62021CJ0128") == "62021CJ0128"
    assert case_to_celex("CURIA C-128/21 TSUE") == "62021CJ0128"


def test_match_eurlex_not_federal_register():
    reg = load_registry()
    names = [m.api["name"] for m in match_apis("EUR-Lex CELEX regulation directive", reg)]
    assert "EUR-Lex Cellar" in names
    assert "Federal Register" not in names
    assert "CoinGecko" not in names
    assert "PubMed" not in names
