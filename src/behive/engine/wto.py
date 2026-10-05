"""WTO Documents Online — FE_S_S006 Query, not the old timeout URL."""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import Optional

WTO_SEARCH = "https://docs.wto.org/dol2fe/Pages/FE_Search/FE_S_S006.aspx"
WTO_PREVIEW = "https://docs.wto.org/dol2fe/Pages/FE_Search/FE_S_S009-DP.aspx"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HIT_RE = re.compile(
    r'<a name="(\d+)"></a>.*?>\s*([^<]+)</a>.*?title="Document title">([^<]+)',
    re.S,
)
SYM_RE = re.compile(
    r"\b((?:WT|G|TN|S|IP)/[A-Z0-9][A-Z0-9/_\-\.]{2,50})",
    re.I,
)
_DROP = {"wto", "world", "trade", "organization", "document", "docs", "online"}


def _kw(topic: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9 \\-]", " ", topic or "")
    s = re.sub(r"\s+", " ", s).strip().lower()
    words = [w for w in s.split() if w not in _DROP and len(w) > 2]
    return " ".join(words[:6])


def _query(topic: str) -> str:
    m = SYM_RE.search(topic or "")
    if m:
        return f"(@Symbol = {m.group(1)}*)"
    kw = _kw(topic)
    if len(kw) < 3:
        return ""
    return f"(@Title = {kw})"


def wto_search(topic: str, timeout: float = 30.0, limit: int = 10) -> Optional[dict]:
    q = _query(topic)
    if not q:
        return None
    url = WTO_SEARCH + "?" + urllib.parse.urlencode(
        {
            "Query": q,
            "Language": "ENGLISH",
            "Context": "FoEScriptedSearched",
            "languageUIChanged": "true",
        }
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    hits = HIT_RE.findall(html)
    if not hits:
        return None
    lines = [f"WTO Documents Online hits for: {topic} (n={len(hits)})", ""]
    rows = []
    for cid, sym, title in hits[:limit]:
        sym, title = sym.strip(), title.strip()
        rows.append({"catalogue_id": cid, "symbol": sym, "title": title})
        lines.append(f"{sym} | {title[:200]}")
        lines.append(f"  {WTO_PREVIEW}?language=E&CatalogueIdList={cid}")
    text = "\n".join(lines)
    return {
        "source": "api:WTO Documents Online",
        "url": url,
        "api_name": "WTO Documents Online",
        "category": "trade",
        "query_type": "trade_data",
        "endpoint_returns": "WTO document symbol + title + catalogue id",
        "data": {"count": len(rows), "hits": rows},
        "raw_text": text[:20000],
    }
