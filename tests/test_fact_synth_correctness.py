"""Offline regressions for conservative, evidence-preserving synthesis."""
import pytest

from behive.engine import fact_synth as fs


def rows_for(*claims):
    return [(claim, f"https://source{i}.example/article", 0.8) for i, claim in enumerate(claims)]


@pytest.mark.parametrize("other", [
    "Beta employs 20 million people across its worldwide offices.",
    "Alpha exported 20 million barrels during the previous year.",
    "Alpha employs 20 million people across its worldwide offices in 2025.",
    "Alpha does not employ 20 million people across its worldwide offices.",
    "Alpha employs 20 million people and operates 40 worldwide offices.",
])
def test_same_number_is_not_same_fact(other):
    claim = "Alpha employs 20 million people across its worldwide offices."
    assert fs.group_attested("", rows_for(claim, other)) == []


def test_sanitizer_must_not_erase_distinct_subject_prefixes():
    assert fs.group_attested("", rows_for(
        "eBay employs 20 million people across its worldwide offices.",
        "Bay employs 20 million people across its worldwide offices.",
    )) == []


def test_different_time_after_first_quantity_is_not_corroboration():
    assert fs.group_attested("", rows_for(
        "Alpha exported 20 million barrels during the calendar year 2024.",
        "Alpha exported 20 million barrels during the calendar year 2025.",
    )) == []


@pytest.mark.parametrize("left,right", [
    ("2,5 million", "2.5 million"),
    ("2,50 percent", "2.5%"),
    ("20 barrels", "20 barrel"),
    ("20 b/d", "20 bpd"),
    ("20 tonnes", "20 tonne"),
    ("1.234,50 tonnes", "1,234.50 tonnes"),
])
def test_safe_quantity_spellings_match_without_changing_evidence(left, right):
    template = "Alpha exported {} from its northern terminal last year."
    claims = [template.format(left), template.format(right)]
    assert fs.fact_key(claims[0]) == fs.fact_key(claims[1])
    groups = fs.group_attested("", rows_for(*claims))
    assert len(groups) == 1
    assert [value[0] for _, value in groups[0][2]] == claims


@pytest.mark.parametrize("left,right", [
    ("2,5 million", "25 million"),
    ("20 mb/d", "20 b/d"),
    ("20 barrels", "20 bpd"),
    ("20 tonnes", "20 tons"),
    ("2,500 tonnes", "2.500 tonnes"),  # ambiguous comma: no locale guessed
    ("20.04 tonnes", "20.03 tonnes"),
    ("1000.4 tonnes", "1000.3 tonnes"),
])
def test_distinct_quantities_or_units_do_not_match(left, right):
    template = "Alpha exported {} from its northern terminal last year."
    assert fs.fact_key(template.format(left)) != fs.fact_key(template.format(right))
    assert fs.group_attested("", rows_for(template.format(left), template.format(right))) == []


@pytest.mark.parametrize("quantity,prefix", [
    ("20 barrels", "20|barrel|"),
    ("20 mb/d", "20|mbpd|"),
    ("20.04 tonnes", "20.04|tonne|"),
    ("1000.4 tonnes", "1000.4|tonne|"),
])
def test_quantity_key_does_not_invent_rates_scales_or_rounding(quantity, prefix):
    key = fs.fact_key(f"Alpha exported {quantity} from its northern terminal.")
    assert key is not None and key.startswith(prefix)


def test_decimal_comma_is_not_multiplied_by_ten():
    key = fs.fact_key("Alpha exported 2,5 million barrels from its northern terminal.")
    assert key is not None and key.startswith("2.5|")


def test_all_original_evidence_is_preserved_in_groups_and_report():
    claims = [
        "Alpha exported 2,5 million barrels from its northern terminal last year.",
        "Alpha exported 2.5 million barrels from its northern terminal last year.",
        "<p>Alpha exported 2.50 million barrels from its northern terminal last year.</p>",
    ]
    rows = rows_for(*claims)
    rows[2] = (claims[2], rows[0][1], 0.8)
    groups = fs.group_attested("", rows)
    assert len(groups) == 1
    assert [value[0] for _, value in groups[0][2]] == claims
    report = fs.build_report("", rows)
    assert all(claim in report for claim in claims)
    assert "ta sama liczba" not in report


def test_domain_normalization_does_not_strip_hostname_characters():
    assert fs.domain_of("https://www.world.example/a") == "world.example"
    assert fs.domain_of("https://world.example:443/b") == "world.example"


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executions = []

    def execute(self, sql, params):
        self.executions.append((sql, params))

    def fetchone(self):
        return ("Alpha",)

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.cur = FakeCursor(rows)
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


@pytest.mark.parametrize("rows", [
    [],
    [("invalid", "https://source.example/a", 0.8)],
    [("Alpha exported 20 million barrels from its northern terminal last year.", "", 0.8)],
    [("Beta exported 20 million barrels from its northern terminal last year.", "https://source.example/a", 0.8)],
])
def test_no_usable_sourced_evidence_does_not_mark_mission_done(monkeypatch, rows):
    conn = FakeConnection(rows)
    monkeypatch.setattr(fs, "_connect", lambda: conn)
    result = fs.persist_fact_synthesis("mission-test")
    assert result == {"attested": 0, "claims": len(rows), "chars": 0}
    assert not any("UPDATE" in sql for sql, _ in conn.cur.executions)
    assert not conn.committed
    assert conn.closed


def test_sourced_single_claim_can_persist_without_false_attestation(monkeypatch):
    rows = rows_for("Alpha exported 20 million barrels from its northern terminal last year.")
    conn = FakeConnection(rows)
    monkeypatch.setattr(fs, "_connect", lambda: conn)
    result = fs.persist_fact_synthesis("mission-test")
    assert result["attested"] == 0
    assert result["claims"] == 1
    assert result["chars"] > 0
    update = [(sql, params) for sql, params in conn.cur.executions if "UPDATE" in sql]
    assert len(update) == 1
    assert rows[0][0] in update[0][1][0]
    assert "status=" not in update[0][0]
    assert "phase=" not in update[0][0]
    assert "status NOT IN" in update[0][0]
    assert conn.committed and conn.closed


def test_network_exposes_exact_source_evidence_and_matching_predicate(monkeypatch):
    claims = [
        "Alpha exported 2,5 million barrels from its northern terminal last year.",
        "Alpha exported 2.5 million barrels from its northern terminal last year.",
    ]
    rows = rows_for(*claims)
    conn = FakeConnection(rows)
    monkeypatch.setattr(fs, "_connect", lambda: conn)
    network = fs.attested_network("Alpha")
    assert network["attested"] == 1
    assert network["predicate"] == "same_normalized_claim_and_quantity_ge2_domains"
    fact_nodes = [node for node in network["nodes"] if node["type"] == "fact"]
    assert fact_nodes[0]["evidence"] == [
        {"claim": claim, "source_url": url, "domain": fs.domain_of(url)}
        for claim, url, _ in rows
    ]
    assert conn.closed and not conn.committed


def test_one_host_repeated_is_not_two_sources():
    claim = "Alpha exported 20 million barrels from its northern terminal last year."
    assert fs.group_attested("", [
        (claim, "https://www.world.example/a", 0.8),
        (claim, "https://world.example:443/b", 0.8),
    ]) == []


def test_report_does_not_truncate_long_evidence_or_later_groups():
    claims = [
        f"Alpha exported {number} million barrels from its northern terminal " + "during the year " * 20 + "2025."
        for number in range(3, 18)
    ]
    report = fs.build_report("Alpha", rows_for(*claims))
    assert all(claim in report for claim in claims)


def test_exact_claim_is_corroborated_and_original_evidence_is_kept():
    claim = "Alpha employs 20 million people across its worldwide offices."
    rows = rows_for(claim, claim)
    groups = fs.group_attested("", rows)
    assert len(groups) == 1
    assert groups[0][2] == [(url, (claim, fs.domain_of(url))) for claim, url, _ in rows]
