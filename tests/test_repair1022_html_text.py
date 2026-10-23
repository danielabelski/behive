"""B2 web extraction through the real fetch seam, with an offline HTTP boundary.

HTML controls are explicitly synthetic, realistic pages (the mission capture
contains already-stripped text, not the original HTML). No network/DB/model.
"""
import asyncio
from types import SimpleNamespace

import pytest

from behive.engine import harvest


def fetch_html(monkeypatch, html, extractor=None):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            assert url == 'https://offline.example.test/page'
            return SimpleNamespace(text=html)

    monkeypatch.setattr(harvest, '_get_curl_cffi_session_cls', lambda: None)
    monkeypatch.setattr(harvest, '_get_httpx', lambda: SimpleNamespace(
        AsyncClient=Client, Timeout=lambda *a, **k: None))
    monkeypatch.setattr(harvest, '_get_trafilatura', lambda: extractor)
    bee = object.__new__(harvest.HarvesterBee)
    return asyncio.run(bee._harvest_web('https://offline.example.test/page'))


def test_html_fallback_keeps_only_visible_prose_and_decodes_entities(monkeypatch):
    html = '''<!doctype html><html><head><title>Supplier</title>
    <style>body {font-family:system-ui} .secret {color:rgba(0,0,0,1)}</style>
    <script>window.state = {fake: "<p>FAKE MODEL CLAIM</p>"};</script></head>
    <body><!-- hidden price: 999999 -->
    <main><h1>WMS &amp; telemetry</h1><p>Wdrożenie&nbsp;w Polsce kosztuje
    1200 &#122;&#322; &lt; 1500 zł.</p><p>Oferta obejmuje pomiar zbiorników.</p></main>
    <noscript>Enable JavaScript to continue</noscript>
    <svg><title>FAKE SVG CLAIM</title><text>999 sensors</text></svg>
    <template><div>FAKE TEMPLATE CLAIM</div></template></body></html>'''
    result = fetch_html(monkeypatch, html)
    assert result['success'] is True
    assert result['text'] == (
        'Supplier WMS & telemetry Wdrożenie w Polsce kosztuje 1200 zł < 1500 zł. '
        'Oferta obejmuje pomiar zbiorników.')
    assert result['word_count'] == 17
    assert result['method'] == 'web_httpx'


@pytest.mark.parametrize('message', [
    'Just a moment... Enable JavaScript and cookies to continue',
    'Attention Required! Cloudflare Ray ID: offline-challenge',
    'Access denied. You do not have permission to access this resource.',
    'Please enable JavaScript to continue browsing this website.',
])
def test_short_block_pages_are_unsuccessful_with_reason(monkeypatch, message):
    html = ('<html><head><title>Security check</title><style>body{font-family:system-ui}</style>'
            '<script>window._cf_chl_opt = {token:"synthetic-not-a-real-token"};</script>'
            '</head><body><main>' + message + '</main></body></html>')
    result = fetch_html(monkeypatch, html)
    assert result['success'] is False
    assert result['error'] == 'blocked_web_page'
    assert 'window' not in result['text']


@pytest.mark.parametrize('body', [
    '<style>body{font-family:system-ui}</style><script>window.fake=42;</script>',
    '<main> &nbsp; ... &#160; </main>',
    '<main>OK</main>',
    '<!-- only a comment --><svg><text>Invisible supplier</text></svg>',
])
def test_essentially_empty_web_text_is_unsuccessful_with_reason(monkeypatch, body):
    result = fetch_html(monkeypatch, '<html><body>' + body + '</body></html>')
    assert result['success'] is False
    assert result['error'] == 'insufficient_web_text'


def test_short_block_text_is_rejected_even_with_optional_extractor(monkeypatch):
    result = fetch_html(monkeypatch, '<p>Access denied to this resource</p>',
                        SimpleNamespace(extract=lambda *a, **k: 'Access denied to this resource'))
    assert result['success'] is False
    assert result['error'] == 'blocked_web_page'


def test_security_article_mentioning_block_phrases_is_not_a_challenge(monkeypatch):
    html = ('<article><h1>How access denied errors work</h1><p>' +
            ('This security article explains Cloudflare configuration and legitimate supplier access. ' * 20) +
            'The enable JavaScript message is one example discussed in the article.</p></article>')
    result = fetch_html(monkeypatch, html)
    assert result['success'] is True
    assert 'error' not in result


def test_fallback_handles_nested_hidden_and_inline_elements(monkeypatch):
    html = ('<article><h1>Telemet<em>ria</em> zbiorników</h1>'
            '<template><template>Fake nested claim</template>Still hidden</template>'
            '<svg><g><text>Fake diagram</text></g></svg><svg/>'
            '<p>Oferta<br/>obejmuje 20 czujników &#38; wdrożenie.</p></article>')
    result = fetch_html(monkeypatch, html)
    assert result['success'] is True
    assert result['text'] == 'Telemetria zbiorników Oferta obejmuje 20 czujników & wdrożenie.'
