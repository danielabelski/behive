"""Read-only mission claim provenance and independent usefulness evaluation."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

from .adjudicate import adjudicate
from .fetch_content import save_json
from .judge import judge_items


def provenance_check(claim, texts):
    texts = [t for t in texts if isinstance(t, str)]
    present = isinstance(claim, str) and bool(claim.strip())
    normalized = ' '.join(claim.split()) if present else ''
    return {'exact': bool(present and any(claim in t for t in texts)),
            'whitespace_normalized': bool(present and any(normalized in ' '.join(t.split()) for t in texts)),
            'same_url_content_present': bool(texts)}


def _assemble(mission_id, topic, claims, contents, isolation):
    by_url = defaultdict(list)
    for row in contents:
        by_url[row['url']].append(row.get('raw_text') or '')
    items = []
    for n, row in enumerate(claims):
        row = dict(row)
        row.update(index=n, url=row.get('source_url') or '', title=row.get('claim_type') or '',
                   provenance=provenance_check(row.get('claim'), by_url[row.get('source_url')]))
        items.append(row)
    summary = {'claims': len(items), 'source_url_present': sum(bool(r.get('source_url')) for r in items),
               'same_url_content_present': sum(r['provenance']['same_url_content_present'] for r in items),
               'exact_text_present': sum(r['provenance']['exact'] for r in items),
               'whitespace_text_present': sum(r['provenance']['whitespace_normalized'] for r in items),
               'unmatched': sum(not r['provenance']['whitespace_normalized'] for r in items)}
    return {'mission_id': mission_id, 'topic': topic, 'items': items, 'provenance_summary': summary,
            'read_only_verified': True, 'isolation': isolation,
            'limitation': 'Literal or whitespace-normalized same-mission same-URL containment, not factual entailment. Paraphrases can fail containment.'}


def load_mission(mission_id, dsn=None):
    """One owned REPEATABLE READ, READ ONLY snapshot; rollback and close on all paths.

    No DSN means the explicitly authorized local sudo/psql hive reader, never an
    ambient production connection string. Explicit DSNs are useful for private PG.
    """
    if dsn is None:
        query = '''BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10s';
SELECT json_build_object(
 'read_only',current_setting('transaction_read_only'),
 'isolation',current_setting('transaction_isolation'),
 'topic',(SELECT topic FROM hive_missions WHERE id=:'mission_id'),
 'claims',COALESCE((SELECT json_agg(t) FROM (SELECT id,claim,source_url,claim_type FROM hive_claims WHERE mission_id=:'mission_id' ORDER BY id) t),'[]'::json),
 'contents',COALESCE((SELECT json_agg(t) FROM (SELECT url,raw_text FROM hive_content WHERE mission_id=:'mission_id' AND url IN (SELECT source_url FROM hive_claims WHERE mission_id=:'mission_id')) t),'[]'::json));
ROLLBACK;'''
        run = subprocess.run(['sudo', '-u', 'postgres', 'psql', '-X', '-q', '-t', '-A', '-v', 'ON_ERROR_STOP=1',
                              '-v', 'mission_id=' + mission_id, '-d', 'hive'], input=query,
                             text=True, capture_output=True, timeout=30)
        if run.returncode:
            raise RuntimeError(f'readonly psql exit {run.returncode}')
        result = json.loads(run.stdout)
        if result['read_only'] != 'on' or result['isolation'] != 'repeatable read':
            raise RuntimeError('read-only snapshot not established')
        if result['topic'] is None:
            raise ValueError('mission not found')
        return _assemble(mission_id, result['topic'], result['claims'], result['contents'], result['isolation'])
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(dsn, connect_timeout=5)
    try:
        conn.set_session(isolation_level='REPEATABLE READ', readonly=True, autocommit=False)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '10s'")
            cur.execute("SELECT current_setting('transaction_read_only') AS ro, current_setting('transaction_isolation') AS isolation")
            settings = cur.fetchone()
            if settings['ro'] != 'on' or settings['isolation'] != 'repeatable read':
                raise RuntimeError('read-only snapshot not established')
            cur.execute('SELECT topic FROM hive_missions WHERE id=%s', (mission_id,))
            mission = cur.fetchone()
            if mission is None:
                raise ValueError('mission not found')
            cur.execute('SELECT id,claim,source_url,claim_type FROM hive_claims WHERE mission_id=%s ORDER BY id', (mission_id,))
            claims = cur.fetchall()
            cur.execute('SELECT url,raw_text FROM hive_content WHERE mission_id=%s AND url IN (SELECT source_url FROM hive_claims WHERE mission_id=%s)', (mission_id, mission_id))
            contents = cur.fetchall()
        return _assemble(mission_id, mission['topic'], claims, contents, settings['isolation'])
    finally:
        conn.rollback()
        conn.close()


def evaluate_mission(mission_id, out, dsn=None, provenance_only=False):
    out = Path(out)
    snapshot = load_mission(mission_id, dsn)
    save_json(out / 'claims_snapshot.json', snapshot)
    if provenance_only:
        save_json(out / 'claims_eval.json', snapshot)
        return snapshot
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda judge: judge_items(snapshot['topic'], snapshot['items'], judge, out / judge,
                                                              batch_size=20, kind='claim'), ['sol', 'claude']))
    result = adjudicate(snapshot['topic'], snapshot['items'], *results, out, batch_size=20, kind='claim')
    result.update(mission_id=mission_id, provenance_summary=snapshot['provenance_summary'],
                  read_only_verified=True, isolation=snapshot['isolation'])
    finalized = [r['final'] for r in result['items'] if r['final'] is not None]
    result['usefulness_summary'] = {'graded': len(finalized), 'relevant': sum(g >= 1 for g in finalized),
                                  'mean_grade': sum(finalized) / len(finalized) if finalized else None}
    save_json(out / 'claims_eval.json', result)
    (out / 'summary.md').write_text('# Claim evaluation\n\n```json\n' + json.dumps({k: result[k] for k in ('mission_id', 'counts', 'provenance_summary', 'usefulness_summary')}, indent=2) + '\n```\n\n' + snapshot['limitation'] + '\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mission_id')
    p.add_argument('out')
    p.add_argument('--dsn', help='Explicit private/test DSN; omit for authorized read-only sudo psql hive reader')
    p.add_argument('--provenance-only', action='store_true')
    a = p.parse_args()
    r = evaluate_mission(a.mission_id, a.out, a.dsn, a.provenance_only)
    print(json.dumps({'mission_id': a.mission_id, 'provenance': r['provenance_summary'], 'usefulness': r.get('usefulness_summary')}))


if __name__ == '__main__':
    main()
