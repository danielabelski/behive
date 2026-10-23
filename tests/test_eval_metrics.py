"""Worked examples: independent numeric constants, missing-label refusal and CIs."""
import importlib
from pathlib import Path
import sys
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def mod():
    assert (ROOT/'tools/eval/metrics.py').exists(), 'metrics toolkit missing'
    return importlib.import_module('tools.eval.metrics')


def test_precision_at_k_and_short_list_denominator():
    m=mod()
    assert m.precision_at_k([2,0,1,0],3) == pytest.approx(2/3)
    assert m.precision_at_k([2,0],3) == pytest.approx(1/3)
    assert m.precision_at_k([],3) == 0
    with pytest.raises(ValueError): m.precision_at_k([None],1)


def test_ndcg_worked_example():
    m=mod()
    assert m.ndcg_at_k([0,2,1],3) == pytest.approx(0.6590018048024133)
    assert m.ndcg_at_k([2,1,0],3) == 1
    assert m.ndcg_at_k([0,0],2) == 0
    assert m.ndcg_at_k([1,0],2,[2,1,0]) == pytest.approx(0.27541155237618664)


def test_kappa_worked_example():
    m=mod()
    assert m.cohens_kappa([1,1,0,0],[1,0,1,0]) == 0
    assert m.cohens_kappa([1,1,0,0],[1,1,1,0]) == pytest.approx(0.5)
    assert m.cohens_kappa([1,0],[0,1]) == -1
    assert m.cohens_kappa([1,1],[1,1]) is None
    with pytest.raises(ValueError): m.cohens_kappa([1],[])


def test_ci_degenerate_and_seeded_replay():
    m=mod()
    assert m.bootstrap_ci([1,1,1],sum,n_boot=100,seed=17) == [3,3]
    a=m.metric_report([2,1,0,0],k=3,n_boot=300,seed=17)
    assert a == m.metric_report([2,1,0,0],k=3,n_boot=300,seed=17)
    assert a['p_at_30'] == pytest.approx(2/3)
    assert 0 <= a['p_ci95'][0] <= a['p_ci95'][1] <= 1


def test_offline_scoring_uses_strict_admission_then_stable_ties():
    m=mod()
    pool=[{'url':'a'},{'url':'b'},{'url':'c'}]
    def scoring(row):
        return {'score_relevance':6 if row['url']!='a' else 4,'score_total':30}
    assert [r['url'] for r in m.rank_pool(pool,scoring)] == ['b','c']
    assert [r['url'] for r in m.rank_pool(pool,lambda r: {'score_relevance':0,'score_total':0})] == ['a','b','c']


def test_unjudged_ranking_returns_null_not_zero():
    m=mod()
    r=m.evaluate_ranking([{'url':'a'},{'url':'b'}],[{'url':'a','final':2}],k=2,n_boot=100)
    assert r['p_at_30'] is None
    assert r['unjudged_top_k']==1
