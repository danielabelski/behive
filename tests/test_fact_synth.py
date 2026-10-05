from behive.engine.fact_synth import build_report, clean_claim, fact_key, on_topic, topic_needles


def test_css_dropped():
    assert clean_claim("x { padding-left: 12px; 20 million barrels of oil }") is None
    assert clean_claim("/* Scoped st 20 million barrels of oil transit") is None
    assert clean_claim("le) strait handles 20 million barrels per day of crude oil exports") is None


def test_sanitize_keeps_sentence():
    s = clean_claim("The strait handles 20 million barrels of oil per day according to EIA.")
    assert s is not None
    assert s.startswith("The strait")


def test_fact_key_barrels():
    k = fact_key("EIA: about 20 million barrels of oil per day transit Hormuz")
    assert k is not None
    assert k.startswith("20")


def test_hormuz_not_malacca():
    needles = topic_needles("Strait of Hormuz oil transit share 2026 EIA")
    assert "hormuz" in needles
    assert on_topic("EIA: 20 million barrels through Hormuz", needles)
    assert not on_topic("94,000 vessels transited the Strait of Malacca in 2024", needles)


def test_attested_two_domains():
    rows = [
        ("About 20 million barrels of oil transit Hormuz each day according to EIA.", "https://www.aljazeera.com/a", 0.8),
        ("Hormuz handles 20 million barrels per day of crude.", "https://en.wikipedia.org/wiki/Hormuz", 0.8),
        ("94,000 vessels transited the Strait of Malacca in 2024 hauling cargo.", "https://oilprice.com/x", 0.8),
    ]
    report = build_report("Strait of Hormuz oil transit 2026 EIA", rows)
    assert "Potwierdzone" in report
    assert "aljazeera.com" in report
    assert "wikipedia.org" in report
    assert "Malacca" not in report
    assert "20" in report
