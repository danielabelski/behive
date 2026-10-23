"""Ranking metrics, conditional item-bootstrap intervals, agreement and offline scoring."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import random
from statistics import mean

from .fetch_content import load_pool, save_json


def _grades(values):
    values = list(values)
    if any(type(g) not in (int, float) or not math.isfinite(g) or not 0 <= g <= 2 for g in values):
        raise ValueError('all grades must be observed finite numbers in [0,2]')
    return values


def precision_at_k(grades, k=30):
    if type(k) is not int or k < 1:
        raise ValueError('positive integer k required')
    return sum(g >= 1 for g in _grades(grades)[:k]) / k


def dcg(grades, k=30):
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(_grades(grades)[:k]))


def ndcg_at_k(grades, k=30, ideal_grades=None):
    grades = _grades(grades)
    ideal = _grades(ideal_grades) if ideal_grades is not None else grades
    denominator = dcg(sorted(ideal, reverse=True), k)
    return dcg(grades, k) / denominator if denominator else 0.0


def _quantile(values, q):
    a = sorted(values)
    pos = (len(a) - 1) * q
    lower = math.floor(pos)
    fraction = pos - lower
    return a[lower] * (1 - fraction) + a[min(lower + 1, len(a) - 1)] * fraction


def bootstrap_ci(items, statistic=mean, n_boot=2000, seed=20261023):
    items = list(items)
    if not items:
        return [None, None]
    if n_boot < 1:
        raise ValueError('positive bootstrap replicate count required')
    rng = random.Random(seed)
    samples = [statistic(rng.choices(items, k=len(items))) for _ in range(n_boot)]
    return [_quantile(samples, .025), _quantile(samples, .975)]


def metric_report(grades, k=30, ideal_grades=None, n_boot=2000, seed=20261023):
    grades = _grades(grades)
    top = grades[:k]
    ideal = _grades(ideal_grades) if ideal_grades is not None else grades
    # Hold the labelled reference documents outside the evaluated cutoff fixed.
    remaining = Counter(ideal)
    for grade in top:
        if remaining[grade] < 1:
            raise ValueError('ideal reference must contain every evaluated item')
        remaining[grade] -= 1
    outside = list(remaining.elements())
    p_ci = bootstrap_ci(top, lambda sample: precision_at_k(sample, k), n_boot, seed)
    n_ci = bootstrap_ci(top, lambda sample: ndcg_at_k(sample, k, sample + outside), n_boot, seed)
    if not top:
        p_ci = n_ci = [0.0, 0.0]
    return {'k': k, 'retrieved_top_k': len(top), 'p_at_30': precision_at_k(top, k),
            'ndcg_at_30': ndcg_at_k(top, k, ideal), 'p_ci95': p_ci, 'ndcg_ci95': n_ci,
            'bootstrap_replicates': n_boot, 'bootstrap_seed': seed,
            'gain': '2^grade - 1 (0,1,3; grade 1.5 from median of two is allowed)',
            'ci_method': 'Percentile item bootstrap of ranked top-K labels, ordered resample; outside-cutoff judged ideal reference fixed; conditional, not discovery-run uncertainty.'}


def cohens_kappa(a, b):
    a, b = list(a), list(b)
    if len(a) != len(b):
        raise ValueError('paired label lengths differ')
    if not a:
        return None
    if any(v not in (0, 1, False, True) for v in a + b):
        raise ValueError('binary labels required')
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    p_a, p_b = sum(a) / n, sum(b) / n
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    return (observed - expected) / (1 - expected) if expected < 1 else None


def agreement(items):
    out = {}
    for a, b in [('sol', 'claude'), ('sol', 'old_sol'), ('claude', 'old_sol')]:
        pairs = [(r[a] >= 1, r[b] >= 1) for r in items if r.get(a) is not None and r.get(b) is not None]
        out[f'{a}_vs_{b}'] = {'n': len(pairs), 'binary_kappa': cohens_kappa([p[0] for p in pairs], [p[1] for p in pairs]),
                              'agreement': mean(x == y for x, y in pairs) if pairs else None}
    return out


def rank_pool(pool, scoring):
    """Replay original strict>=5/15 top300; relaxed top100 if strict empty. Stable input ties."""
    rows = []
    for i, row in enumerate(pool):
        score = scoring(row)
        if not isinstance(score, dict):
            score = {'score_relevance': 5, 'score_total': score}
        rows.append((i, row, score))
    strict = [r for r in rows if r[2]['score_relevance'] >= 5 and r[2]['score_total'] >= 15]
    selected = sorted(strict or rows, key=lambda r: (-r[2]['score_total'], r[0]))[:300 if strict else 100]
    return [dict(r, eval_score=sc) for _, r, sc in selected]


def deployed_scorer(topic):
    """Import source path is selected explicitly via PYTHONPATH by the operator."""
    from behive.engine.scout import SwarmScout
    scout = SwarmScout.__new__(SwarmScout)
    scout.topic = topic
    scout.mission_id = 'offline-content-eval'
    return lambda r: scout._score_source(r['url'], r.get('title') or '', r.get('snippet') or '', r.get('source_type') or 'web')


def evaluate_ranking(ranked, gold, k=30, n_boot=2000, seed=20261023):
    labels = {r['url']: r['final'] for r in gold if r.get('final') is not None}
    top = ranked[:k]
    unjudged = [r['url'] for r in top if r['url'] not in labels]
    if unjudged:
        return {'k': k, 'p_at_30': None, 'ndcg_at_30': None, 'p_ci95': [None, None], 'ndcg_ci95': [None, None],
                'unjudged_top_k': len(unjudged), 'unjudged_urls': unjudged}
    result = metric_report([labels[r['url']] for r in top], k, list(labels.values()), n_boot, seed)
    result.update(unjudged_top_k=0, labelled_ideal_pool=len(labels), ndcg_scope='IDCG over frozen judged pool, not unknown unjudged documents')
    return result


def evaluate_scoring(pool, gold, scoring, **kwargs):
    return evaluate_ranking(rank_pool(pool, scoring), gold, **kwargs)


def mean_across_topics(reports, n_boot=2000, seed=20261023):
    out = {}
    for metric in ('p_at_30', 'ndcg_at_30'):
        values = [r[metric] for r in reports if r.get(metric) is not None]
        out[metric] = {'n_topics': len(values), 'mean': mean(values) if values else None,
                       'ci95_over_topics': bootstrap_ci(values, mean, n_boot, seed)}
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ranked')
    p.add_argument('gold')
    p.add_argument('out')
    p.add_argument('--k', type=int, default=30)
    a = p.parse_args()
    gold = load_pool(a.gold)
    report = {'metrics': evaluate_ranking(load_pool(a.ranked), gold, k=a.k), 'agreement': agreement(gold)}
    save_json(a.out, report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
