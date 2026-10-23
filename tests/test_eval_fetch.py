"""Offline HTTP-boundary replay of captured public bytes (receipts in fixtures/eval)."""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = ROOT / 'tests/fixtures/eval'


def module():
    assert (ROOT / 'tools/eval/fetch_content.py').exists(), 'content fetch toolkit missing'
    return importlib.import_module('tools.eval.fetch_content')


def test_captured_html_extraction_and_block_classification():
    f = module()
    good = f.extract_response(200, 'text/html; charset=UTF-8', (FIX / 'flotlis.html').read_bytes())
    assert good['status'] == 'ok'
    assert 'telemetri' in good['text'].lower()
    blocked = f.extract_response(200, 'text/html', (FIX / 'sciencedirect-block.html').read_bytes())
    assert blocked['status'] == 'blocked_web_page'
    assert f.extract_response(429, 'text/html', b'busy')['status'] == 'http_429'
    assert f.extract_response(200, 'text/html', b'<html></html>')['status'] == 'insufficient_web_text'


def test_fetch_cache_resumes_success_and_failure_once(tmp_path):
    f = module()
    calls = []

    def http_boundary(url):
        calls.append(url)
        return {'url': url, 'status': 'timeout', 'text': '', 'attempts': 1}

    pool = [{'url': 'https://example.org/a'}, {'url': 'https://example.org/a'}]
    first = f.fetch_pool(pool, tmp_path, workers=2, fetcher=http_boundary)
    second = f.fetch_pool(pool, tmp_path, workers=2, fetcher=http_boundary)
    assert len(first) == len(second) == 2
    assert calls == ['https://example.org/a']
    assert first[0]['status'] == second[1]['status'] == 'timeout'
    assert len(list(tmp_path.glob('*.json'))) == 1


def test_bad_cache_never_silently_refetches(tmp_path):
    f = module()
    (tmp_path / (f.url_hash('https://example.org/a') + '.json')).write_text('{broken')
    with pytest.raises(ValueError, match='cache'):
        f.fetch_pool([{'url': 'https://example.org/a'}], tmp_path)


def test_fetch_worker_bound(tmp_path):
    with pytest.raises(ValueError):
        module().fetch_pool([], tmp_path, workers=5)
