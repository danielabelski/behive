"""Name/source/rendering contracts. Offline; fake only the LLM/judge boundary.

Seams: synthesis validation + drop accounting; evaluator prompts/metrics; actual
Markdown and persisted citation-map roundtrip. Not semantic or live-model proof.
"""
import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def rows():
    return [
        {'id': 1, 'claim': 'Henkel produkuje blachy AH36 według EN10204 dla programu PA-NG. '
                          'Koszt wynosi 9 zł. Moc wynosi 11,6MW.',
         'source_url': 'https://voltterm.pl/oferta', 'confidence': .9},
        {'id': 2, 'claim': 'Firma Fantom oferuje produkt Ghost-Unit i program Miecznik.',
         'source_url': 'https://uncited.test/GAITER', 'confidence': .8},
    ]


def point(text='Opis obejmuje produkcję blach dla przemysłu.', cites=None):
    return {'text': text, 'cites': [1] if cites is None else cites}


def document(extra=()):
    return {'summary': [point(), point('Opis dotyczy kosztów wytwarzania blach.'),
                        point('Opis obejmuje wymagania jakościowe blach.'), *extra],
            'sections': [], 'gaps': []}


@pytest.mark.parametrize('text,missing', [
    ('Oferta firmy Fantom obejmuje blachy.', ['Fantom']),
    ('Oferta obejmuje produkt Ghost-Unit.', ['Ghost-Unit']),
    ('W programie Miecznik wykorzystano blachy.', ['Miecznik']),
    ('GAITER oferuje monitoring zbiorników.', ['GAITER']),
    ('Ghost-Unit oferuje monitoring zbiorników.', ['Ghost-Unit']),
    ('FX9 obejmuje produkcję blach.', ['FX9']),
    ('Opis jest poprawny. GAITER oferuje monitoring.', ['GAITER']),
    ('Opis dotyczy firmy Fantom i produktu Fantom.', ['Fantom']),
])
def test_unknown_names_drop_at_synthesis_boundary(monkeypatch, text, missing):
    from behive.engine import claim_synthesis as cs, llm
    bad = point(text)
    monkeypatch.setattr(llm, 'complete', lambda *a, **kw: json.dumps(document([bad])))
    result = cs.synthesize_claims('Produkcja blach', rows())
    assert result['metadata']['method'] == 'model'
    assert result['metadata']['points_valid'] == 3
    assert result['metadata']['points_dropped'] == 1
    assert result['metadata']['model_calls'] == 1
    assert bad not in result['document']['summary']
    checks = cs.point_checks(bad, {r['number']: r for r in result['claims']})
    assert checks['citation_valid'] and checks['number_grounded']
    assert checks.get('names_grounded') is False
    assert checks.get('unverified_names') == missing


@pytest.mark.parametrize('text', [
    'Według Voltterm opis dotyczy blach.',
    'Oferta Henkla obejmuje produkcję blach.',
    'Opis obejmuje AH36 i EN10204 dla PA-NG.',
    'AH36 stosuje się w produkcji blach.',
    'PA-NG obejmuje produkcję blach.',
    'Opis obejmuje moc 11,6 MW.',
    'Opis jest poprawny. Nowe wymagania opisano w źródle.',
])
def test_cited_names_domains_inflections_and_codes_kept(monkeypatch, text):
    from behive.engine import claim_synthesis as cs, llm
    monkeypatch.setattr(llm, 'complete', lambda *a, **kw: json.dumps(document([point(text)])))
    result = cs.synthesize_claims('Produkcja blach', rows())
    assert result['metadata']['method'] == 'model'
    assert result['metadata']['points_valid'] == 4
    assert result['metadata']['points_dropped'] == 0
    checks = cs.point_checks(point(text), {r['number']: r for r in result['claims']})
    assert checks.get('names_grounded') is True
    assert checks.get('unverified_names') == []


def test_topic_is_passed_to_validation_and_evaluation(monkeypatch):
    from behive.engine import claim_synthesis as cs, llm
    from tools.eval import report_eval as ev
    text = 'Opis dla programu ORION obejmuje produkcję blach.'
    monkeypatch.setattr(llm, 'complete', lambda *a, **kw: json.dumps(document([point(text)])))
    result = cs.synthesize_claims('Produkcja blach dla ORION', rows())
    assert result['metadata']['points_valid'] == 4
    metric = ev.automatic_metrics(result)
    assert metric.get('names_grounded') == 4
    assert metric.get('names_grounded_share') == 1.0
    no_topic = dict(result, topic='Produkcja blach')
    assert ev.automatic_metrics(no_topic).get('names_grounded') == 3


@pytest.mark.parametrize('evidence,text', [
    ('Henkel produkuje blachy.', 'Oferta Henkla obejmuje produkcję blach.'),
    ('Łódź oferuje instalacje.', 'Oferta Łodzi obejmuje instalacje.'),
    ('Huta Czestochowa produkuje blachy.', 'Oferta Częstochowy obejmuje blachy.'),
    ('Huta Cze\u0328stochowa produkuje blachy.', 'Oferta Częstochowy obejmuje blachy.'),
])
def test_diacritic_folded_four_character_stems(evidence, text):
    from behive.engine import claim_synthesis as cs
    numbered = {1: {'claim': evidence, 'source_url': 'https://source.test/a'}}
    checks = cs.point_checks(point(text), numbered)
    assert checks.get('names_grounded') is True
    assert checks.get('unverified_names') == []


def test_source_domains_derive_from_url_for_persisted_rows():
    from behive.engine import claim_synthesis as cs
    numbered = {1: {'claim': 'Opis dotyczy produkcji blach.', 'source_url': 'https://www.voltterm.pl/GAITER'}}
    good = cs.point_checks(point('Według Voltterm opis dotyczy blach.'), numbered)
    bad = cs.point_checks(point('Oferta GAITER dotyczy blach.'), numbered)
    assert good.get('names_grounded') is True
    assert bad.get('unverified_names') == ['GAITER']


@pytest.mark.parametrize('bad', [None, {}, point(cites=[]), point(cites=[True]),
                                 point(cites=[99]), point(cites='1'), point(None)])
def test_malformed_points_have_stable_failed_name_checks(bad):
    from behive.engine import claim_synthesis as cs
    checks = cs.point_checks(bad, {1: rows()[0]})
    assert checks.get('names_grounded') is False
    assert checks.get('unverified_names') == []
    assert not checks['valid']


@pytest.mark.parametrize('text,missing', [
    ('Fantom oferuje blachy.', []),  # Deliberately excluded ordinary sentence start.
    ('Opis. Fantom oferuje blachy.', []),
    ('Opis! „Fantom oferuje blachy.”', []),
    ('Opis obejmuje firmę Fantom.', ['Fantom']),
    ('Opis obejmuje firmę Henkel.', []),
])
def test_sentence_initial_rule_is_explicit(text, missing):
    from behive.engine import claim_synthesis as cs
    checks = cs.point_checks(point(text), {1: rows()[0]})
    assert checks.get('unverified_names') == missing
    assert checks.get('names_grounded') is (not missing)


@pytest.mark.parametrize('valid,bad,accepted', [(3, 2, True), (3, 3, False), (2, 1, False)])
def test_name_drops_preserve_minimum_and_forty_percent_rule(valid, bad, accepted):
    from behive.engine import claim_synthesis as cs
    doc = {'summary': [point()] * valid + [point('Oferta firmy Fantom dotyczy blach.')] * bad,
           'sections': [], 'gaps': []}
    claims = cs.number_claims(rows())
    if accepted:
        result = cs.validate_model_output(json.dumps(doc), claims)
        assert result['points_valid'] == valid and result['points_dropped'] == bad
    else:
        with pytest.raises(cs.InvalidSynthesis) as caught:
            cs.validate_model_output(json.dumps(doc), claims)
        assert caught.value.points_dropped == bad


def test_name_drop_counts_flow_through_unchanged_retry_and_fallback(monkeypatch):
    from behive.engine import claim_synthesis as cs, llm
    monkeypatch.setattr(llm, 'complete', lambda *a, **kw: json.dumps(
        {'summary': [point('Oferta firmy Fantom dotyczy blach.')] * 3, 'sections': [], 'gaps': []}))
    result = cs.synthesize_claims('Produkcja blach', rows())
    assert result['metadata']['method'] == 'deterministic'
    assert result['metadata']['model_calls'] == 2
    assert result['metadata']['points_dropped'] == 6
    assert result['metadata']['points_valid'] == 2  # Full fallback unchanged.


def test_system_prompt_has_name_preservation_and_narrow_false_drop_mitigations(monkeypatch):
    from behive.engine import claim_synthesis as cs, llm
    seen = []
    def complete(prompt, **kwargs):
        seen.append(kwargs['system'])
        return json.dumps(document())
    monkeypatch.setattr(llm, 'complete', complete)
    cs.synthesize_claims('Produkcja blach', rows())
    system = seen[0].lower()
    assert 'firms, products, programmes and places' in system
    assert 'as they appear in the cited claims' in system and 'no translation' in system
    assert 'domain owner' in system and 'as given in the input' in system
    assert 'domain label' in system
    assert 'abbreviations' in system and 'currency' in system and 'unit' in system
    assert 'inflection' in system and 'restructure' in system


def eval_payload():
    from behive.engine import claim_synthesis as cs
    return {'topic': 'Produkcja blach', 'claims': cs.number_claims(rows()),
            'document': document([point('Oferta firmy Fantom dotyczy blach.')]), 'report': '# Report\n'}


def test_support_prompts_include_each_cited_domain_url_and_publisher_rule(tmp_path):
    from tools.eval import report_eval as ev
    payload = eval_payload()
    # A persisted report's original rows need not have a domain field.
    payload['claims'][0].pop('domain')
    payload['document']['summary'][0]['cites'] = [1, 2]
    calls = []
    def complete(prompt, judge):
        data = json.loads(prompt.split('DATA_JSON:\n', 1)[1])
        if data['kind'] == 'support':
            calls.append((judge, prompt))
            assert 'attribution to the publisher of the cited source counts as supported' in prompt.lower()
            for item in data['items']:
                for claim in item['cited_claims']:
                    expected = payload['claims'][claim['number'] - 1]
                    assert claim['claim'] == expected['claim']
                    assert claim.get('source_url') == expected['source_url']
                    assert claim.get('domain') == ('voltterm.pl' if claim['number'] == 1 else 'uncited.test')
        return json.dumps([{'index': r['index'], 'grade': 2, 'reason': 'Offline prompt contract test'}
                           for r in data['items']])
    result = ev.evaluate_report(payload, tmp_path, complete=complete)
    assert {name for name, _ in calls} == {'sol', 'claude'}
    assert result['agreement']['compared'] == 4


def test_automatic_name_share_uses_shared_citation_scope_and_topic():
    from tools.eval import report_eval as ev
    payload = eval_payload()
    metric = ev.automatic_metrics(payload)
    assert metric.get('names_grounded') == 3
    assert metric.get('names_grounded_share') == .75
    assert metric['point_checks'][3].get('unverified_names') == ['Fantom']
    assert metric['points_valid'] == 3
    empty = copy.deepcopy(payload)
    empty['document']['summary'] = []
    assert ev.automatic_metrics(empty).get('names_grounded_share') == 0.0


@pytest.mark.parametrize('text,expected', [
    ('oil & gas', 'oil & gas'),
    ('oil &amp; gas', 'oil & gas'),
    ('oil &#38; gas', 'oil & gas'),
    ('<script>evil</script>', '&lt;script&gt;evil&lt;/script&gt;'),
    ('&lt;script&gt;evil&lt;/script&gt;', '&lt;script&gt;evil&lt;/script&gt;'),
    ('&#35; Heading [777] *bold* _italic_ `code` \\',
     r'\# Heading \[777\] \*bold\* \_italic\_ \`code\` \\'),
])
def test_ampersands_and_entities_render_once_and_controls_stay_escaped(text, expected):
    from behive.engine import claim_synthesis as cs
    evidence = [dict(rows()[0], number=1, claim=text, domain='voltterm.pl')]
    rendered = cs.render_model('Oil & gas', evidence, {'summary': [point(text)], 'sections': [], 'gaps': []})
    assert rendered.startswith('# Oil & gas\n')
    assert '- ' + expected + ' [1]' in rendered
    assert '- [1] ' + expected + ' — https://voltterm.pl/oferta' in rendered
    assert '&amp;' not in rendered and '<script>' not in rendered


def test_fallback_also_decodes_harvest_entities_without_html_injection(monkeypatch):
    from behive.engine import claim_synthesis as cs, llm
    evidence = [dict(rows()[0], claim='Firma oferuje oil &amp; gas oraz &lt;script&gt; jako tekst.')]
    def offline(*a, **kw):
        raise RuntimeError('offline')
    monkeypatch.setattr(llm, 'complete', offline)
    result = cs.synthesize_claims('Oil & gas', evidence)
    assert result['metadata']['method'] == 'deterministic'
    assert 'oil & gas' in result['report'] and '&amp;' not in result['report']
    assert '&lt;script&gt;' in result['report'] and '<script>' not in result['report']


@pytest.mark.parametrize('claim', ['Firma oferuje oil &amp; gas.', 'Firma oferuje oil & gas.',
                                   'Firma oferuje &lt;script&gt; jako tekst.'])
def test_rendered_source_map_roundtrips_original_entity_encoded_claims(claim):
    from behive.engine import claim_synthesis as cs
    from tools.eval import report_eval as ev
    evidence = [dict(rows()[0], number=1, claim=claim, domain='voltterm.pl')]
    doc = {'summary': [point('Opis dotyczy oferty oil &amp; gas.')], 'sections': [], 'gaps': []}
    report = cs.render_model('Oil & gas', evidence, doc)
    loaded = ev.parse_persisted_report('Oil & gas', report, evidence)
    assert loaded['claims'][0]['claim'] == claim
    assert loaded['document']['summary'][0]['text'] == 'Opis dotyczy oferty oil & gas.'
    with pytest.raises(ValueError, match='eligible claim'):
        ev.parse_persisted_report('Oil & gas', report.replace('Firma oferuje', 'Firma fałszuje'), evidence)
