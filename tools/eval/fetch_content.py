"""Single-acquisition public-page cache for content relevance evaluation (no DB)."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

DEFAULT_CACHE = Path('/root/outputs/behive-eval-2026-10-23/E/content')
MAX_BYTES = 5 * 1024 * 1024


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


url_hash = digest


def save_json(path, value):
    """Atomic local publication; unique temp names also tolerate concurrent writers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import os
    import tempfile
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_pool(path):
    obj = json.loads(Path(path).read_text())
    rows = obj if isinstance(obj, list) else obj.get('items', obj.get('pool'))
    if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('url'), str) for r in rows):
        raise ValueError('pool must contain objects with string url fields')
    return rows


def extract_response(code: int, content_type: str, body: bytes) -> dict:
    """Classify honest HTTP errors before page interpretation; never solve challenges."""
    if code < 200 or code >= 300:
        return {'status': f'http_{code}', 'text': ''}
    from behive.engine.harvest import _html_to_text, _get_fitz
    if 'pdf' in content_type.lower() or body.startswith(b'%PDF'):
        fitz = _get_fitz()
        if fitz is None:
            return {'status': 'pdf_unparsed', 'text': ''}
        try:
            with fitz.open(stream=body, filetype='pdf') as doc:
                text = ''
                for page in doc:
                    text += page.get_text() + '\n'
                    if len(text) >= 6000:
                        break
        except Exception as exc:
            return {'status': 'pdf_unparsed', 'text': '', 'error_type': type(exc).__name__}
    else:
        match = re.search(r'charset=([\w-]+)', content_type, re.I)
        charset = match.group(1) if match else 'utf-8'
        try:
            html = body.decode(charset, errors='replace')
        except LookupError:
            html = body.decode('utf-8', errors='replace')
        text = _html_to_text(html)
    text = text.strip()
    # Short challenge pages, not long articles discussing CAPTCHA/blocked access.
    blocked = re.search(r'just a moment|attention required|access denied|enable javascript|verify (?:you are|that you)|unusual traffic|please (?:complete|enable).*captcha|checking your browser|are you a (?:robot|human)|verify your humanity|request (?:has been )?blocked', text, re.I)
    challenge_header = re.search(r'are you a robot\?|please confirm you are a human|verify your humanity', text[:700], re.I)
    if challenge_header or (len(text.split()) < 500 and blocked):
        return {'status': 'blocked_web_page', 'text': text[:6000]}
    if len(text.split()) < 20:
        return {'status': 'insufficient_web_text', 'text': text[:6000]}
    return {'status': 'ok', 'text': text[:6000]}


_HOSTS = {}
_HOSTS_LOCK = threading.Lock()


def fetch_url(url: str) -> dict:
    import httpx
    host = urlsplit(url).hostname
    if urlsplit(url).scheme not in ('http', 'https') or not host:
        return {'url': url, 'status': 'error_InvalidURL', 'text': '', 'attempts': 0}
    with _HOSTS_LOCK:
        lock = _HOSTS.setdefault(host, threading.Lock())
    with lock:
        # One in-flight request per hostname, at least a small courtesy delay.
        time.sleep(0.15)
        result = {'url': url, 'text': '', 'attempts': 0, 'fetched_at': time.time()}
        for attempt in range(2):
            result['attempts'] += 1
            started = time.monotonic()
            try:
                with httpx.Client(timeout=20, follow_redirects=True, max_redirects=5,
                                  headers={'User-Agent': 'behive-eval'}) as client:
                    with client.stream('GET', url) as response:
                        chunks, length = [], 0
                        for chunk in response.iter_bytes():
                            if time.monotonic() - started > 20:
                                raise httpx.ReadTimeout('20 second response deadline')
                            length += len(chunk)
                            if length > MAX_BYTES:
                                raise ValueError('response exceeds 5MiB limit')
                            chunks.append(chunk)
                        body = b''.join(chunks)
                        result.update(http_status=response.status_code, final_url=str(response.url),
                                      content_type=response.headers.get('content-type', ''),
                                      body_sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
                        result.update(extract_response(response.status_code, result['content_type'], body))
                break
            except httpx.TimeoutException:
                result['status'] = 'timeout'
                break
            except httpx.ConnectError as exc:
                result['status'] = 'error_' + type(exc).__name__
                if attempt == 0:
                    time.sleep(0.5)
                    continue
            except Exception as exc:
                result['status'] = 'error_' + type(exc).__name__
                break
        return result


def fetch_pool(pool, cache_dir=DEFAULT_CACHE, workers=4, fetcher=None):
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('workers must be 1..4')
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    fetcher = fetcher or fetch_url

    def cached(url):
        key = url_hash(url)
        target = cache_dir / (key + '.json')
        with (cache_dir / (key + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if target.exists():
                try:
                    value = json.loads(target.read_text())
                    if value['url'] != url or not isinstance(value['status'], str) or not isinstance(value['text'], str):
                        raise ValueError('bad fields')
                    return value
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f'corrupt content cache: {target}') from exc
            marker = cache_dir / (key + '.attempt')
            if marker.exists():
                value = {'url': url, 'status': 'error_InterruptedAcquisition', 'text': '', 'attempts': None}
            else:
                marker.write_text(str(time.time()))
                value = fetcher(url)
            save_json(target, value)
            return value

    urls = list(dict.fromkeys(row['url'] for row in pool))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        values = dict(zip(urls, executor.map(cached, urls)))
    return [dict(row, status=values[row['url']]['status'], content=values[row['url']]) for row in pool]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pool')
    parser.add_argument('out')
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    rows = fetch_pool(load_pool(args.pool), args.cache, args.workers)
    save_json(args.out, rows)
    print(json.dumps({'items': len(rows), 'statuses': Counter(r['content']['status'] for r in rows)}))


if __name__ == '__main__':
    main()
