"""Disputed-only blind Opus adjudication; preserve absent votes as null."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median

from .fetch_content import load_pool, save_json
from .judge import judge_items


def is_disputed(sol, claude):
    if sol is None or claude is None:
        return False
    return (sol >= 1) != (claude >= 1) or abs(sol - claude) == 2


def final_grade(sol, claude, opus=None):
    if sol is None or claude is None:
        return None
    if is_disputed(sol, claude):
        return median([sol, claude, opus]) if opus is not None else None
    return median([sol, claude])


def adjudicate(topic, items, sol_result, claude_result, out_dir, batch_size=15, kind='page', complete=None, ledger=None):
    sol = {r['index']: r for r in sol_result['labels']}
    claude = {r['index']: r for r in claude_result['labels']}
    rows = [dict(row, index=row.get('index', n)) for n, row in enumerate(items)]
    disputed = [r for r in rows if is_disputed(sol.get(r['index'], {}).get('grade'), claude.get(r['index'], {}).get('grade'))]
    kwargs = {'ledger': ledger} if ledger is not None else {}
    vote = judge_items(topic, disputed, 'opus', Path(out_dir) / 'opus', batch_size=batch_size, kind=kind, complete=complete, **kwargs)
    opus = {r['index']: r for r in vote['labels']}
    gold = []
    for row in rows:
        i = row['index']
        votes = {'sol': sol.get(i), 'claude': claude.get(i), 'opus': opus.get(i)}
        grades = {name: label['grade'] if label else None for name, label in votes.items()}
        row.update(**grades, final=final_grade(**grades), disputed=is_disputed(grades['sol'], grades['claude']),
                   reasons={name: label['reason'] if label else None for name, label in votes.items()})
        row['evidence_type'] = 'claim' if kind == 'claim' else ('page_content' if row.get('content', {}).get('status') == 'ok' else 'snippet_fallback')
        gold.append(row)
    result = {'topic': topic, 'kind': kind, 'items': gold,
              'counts': {'items': len(gold), 'disputed': len(disputed), 'finalized': sum(r['final'] is not None for r in gold),
                         'unresolved': sum(r['final'] is None for r in gold)},
              'provenance': {'sol': str(sol_result.get('model')), 'claude': str(claude_result.get('model')),
                             'opus': vote['model'], 'failures': {'sol': sol_result['failures'], 'claude': claude_result['failures'], 'opus': vote['failures']},
                             'median_rule': 'Median of 3 on disputes; median of 2 otherwise (1 vs 2 = 1.5).'}}
    save_json(Path(out_dir) / 'gold.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pool')
    p.add_argument('sol')
    p.add_argument('claude')
    p.add_argument('out')
    p.add_argument('--topic', required=True)
    a = p.parse_args()
    r = adjudicate(a.topic, load_pool(a.pool), json.loads(Path(a.sol).read_text()), json.loads(Path(a.claude).read_text()), a.out)
    print(json.dumps(r['counts']))


if __name__ == '__main__':
    main()
