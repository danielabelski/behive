"""
HIVE API Scout — Structured Data Sources for Research Missions

Instead of scraping random web pages, the API Scout:
1. Takes a research query
2. Matches it to relevant APIs from the curated registry (70+ APIs, 125+ endpoints)
3. Selects the BEST endpoint per API based on use_when descriptions
4. Queries matching APIs for structured data
5. Returns clean, pre-parsed documents ready for BeeHive extraction

Integration point: called by hive2_process.py BEFORE web scraping.
If API Scout returns enough docs, web scraping is reduced/skipped.

QUEEN KNOWLEDGE: The registry at hive_api_sources.json contains:
- endpoints[].use_when → tells Queen WHEN data from this API is relevant
- endpoints[].returns → tells Queen WHAT data comes back (for claim extraction)
- notes → rate limits, auth requirements, data freshness
"""

import json
import asyncio
import aiohttp
import logging
import re
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from behive.engine.entity_resolver import (
    api_allowed,
    classify_domain,
    enrich_query,
    resolve_entity,
)

log = logging.getLogger("hive.api_scout")

_STOPWORDS = {
    "query", "data", "format", "api", "json", "the", "and", "for", "with", "from",
    "http", "www", "com", "org", "pl", "en", "v1", "v2", "v3", "to", "of", "in",
    "a", "an", "on", "by", "or", "at",
}


def _kw_in_query(kw: str, query_lower: str) -> bool:
    """Substring is how 'war' matched Warszawa. Require a token boundary."""
    if not kw:
        return False
    kw = kw.lower()
    if " " in kw:
        return kw in query_lower
    return re.search(r"(?<![a-z0-9ąćęłńóśźż])" + re.escape(kw) + r"(?![a-z0-9ąćęłńóśźż])", query_lower) is not None

# ── Registry ────────────────────────────────────────────────────────────────

REGISTRY_PATH = Path(__file__).parent / "hive_api_sources.json"

def load_registry() -> list[dict]:
    """Load the curated API registry."""
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    return []

# ── Query Matching ───────────────────────────────────────────────────────────

# Keywords that map to query_types
QUERY_TYPE_KEYWORDS = {
    "market_data": ["stock", "market", "price", "trading", "equity", "shares", "ticker",
                    "crypto", "bitcoin", "ethereum", "coin", "token", "defi",
                    "forex", "currency", "exchange rate", "FX", "commodity"],
    "papers": ["research", "paper", "study", "academic", "journal", "citation",
               "arxiv", "pubmed", "scholar", "scientific", "peer-reviewed", "literature"],
    "statistics": ["gdp", "population", "census", "demographic", "unemployment",
                   "inflation", "economic indicator", "oecd", "imf", "world bank"],
    "company_data": ["company", "startup", "funding", "incorporation", "corporate",
                     "business", "firm", "enterprise", "revenue", "registration"],
    "news": ["news", "headline", "breaking", "media", "press", "journalist", "coverage"],
    "datasets": ["dataset", "open data", "government data", "portal"],
    "tenders": ["tender", "procurement", "bid", "contract", "rfp", "rfq",
                "public tender", "government contract", "zamówienie"],
    "vulnerabilities": ["cve", "vulnerability", "exploit", "security flaw", "patch"],
    "threat_intel": ["malware", "threat", "apt", "attack", "mitre", "ioc", "phishing"],
    "patents": ["patent", "intellectual property", "invention", "USPTO"],
    "trade_data": ["import", "export", "trade", "tariff", "customs", "comtrade", "supply chain"],
    "regulations": ["regulation", "law", "federal register", "compliance", "rule", "directive"],
    "repositories": ["github", "repository", "open source", "library", "framework", "tool"],
    "packages": ["npm", "pypi", "package", "module", "dependency", "crate"],
    "events": ["geopolitical", "conflict", "war", "crisis", "gdelt", "unrest", "sanctions"],
    "sanctions": ["sanction", "blacklist", "embargo", "restricted entity", "ofac"],
    "economic_data": ["macroeconomic", "gdp growth", "interest rate", "central bank", "monetary"],
    "filings": ["sec", "filing", "10-k", "10-q", "annual report", "edgar"],
    "models": ["model", "llm", "machine learning", "neural", "transformer", "hugging face"],
    "benchmarks": ["benchmark", "leaderboard", "state of the art", "sota", "evaluation"],
    "discussions": ["opinion", "reddit", "forum", "community", "developers think"],
    "knowledge": ["what is", "definition", "explain", "overview", "background"],
    "country_data": ["country", "nation", "geography", "population density"],
    "conflict_data": ["conflict", "battle", "war", "violence", "casualties", "armed"],
    "persons": ["wanted", "fugitive", "criminal", "interpol"],
    "insider_trading": ["congress", "politician", "insider trading", "disclosure"],
    "fiscal_data": ["debt", "spending", "budget", "treasury", "fiscal"],
    "environmental_data": ["environment", "pollution", "emissions", "epa", "climate"],
    "weather_data": ["weather", "temperature", "climate", "forecast"],
    "containers": ["docker", "container", "kubernetes", "k8s"],
    "products": ["product hunt", "launch", "saas", "startup product"],
    "entities": ["entity", "wikidata", "disambiguation"],
    "science_data": ["space", "nasa", "astronomy", "asteroid"],
}

# Category keywords for direct matching
CATEGORY_KEYWORDS = {
    "crypto": ["crypto", "bitcoin", "ethereum", "blockchain", "defi", "nft", "token", "altcoin"],
    "stocks": ["stock", "equity", "share", "nasdaq", "nyse", "sp500", "dow", "wall street"],
    "academic": ["research paper", "academic", "arxiv", "scholar", "citation", "university"],
    "medical": ["medical", "health", "disease", "drug", "clinical", "biomedical", "pharma"],
    "security": ["cybersecurity", "vulnerability", "malware", "cve", "threat", "hack", "breach"],
    "government": ["government", "public sector", "federal", "state data", "municipal"],
    "procurement": ["procurement", "tender", "bid", "rfp", "government contract", "zamówienie publiczne"],
    "economics": ["economic", "gdp", "inflation", "monetary policy", "fiscal", "recession"],
    "macro": ["macroeconomic", "interest rate", "fed", "central bank", "quantitative"],
    "geopolitics": ["geopolitical", "international relations", "conflict", "diplomacy", "sanctions"],
    "development": ["developer", "programming", "software", "engineering", "devops", "infrastructure"],
    "ml": ["machine learning", "ai model", "deep learning", "neural network", "llm", "transformer"],
    "trade": ["trade", "export", "import", "tariff", "supply chain", "logistics"],
    "regulatory": ["regulation", "compliance", "rule", "law", "policy", "directive"],
    "business": ["company", "corporate", "incorporation", "registry", "due diligence"],
    "compliance": ["sanctions", "aml", "kyc", "pep", "restricted", "screening"],
    "law_enforcement": ["wanted", "criminal", "fugitive", "interpol", "fbi"],
    "tech_news": ["hacker news", "tech news", "startup", "vc", "y combinator"],
    "social": ["reddit", "social media", "community", "public opinion", "sentiment"],
    "news": ["news", "media", "press", "headline", "current events"],
    "forex": ["forex", "fx", "currency", "exchange rate", "eur", "usd"],
    "patents": ["patent", "ip", "invention", "intellectual property"],
    "knowledge_graph": ["entity", "knowledge graph", "wikidata", "ontology"],
    "demographics": ["census", "population", "demographics", "age distribution"],
    "government_finance": ["treasury", "national debt", "government spending", "fiscal"],
    "government_spending": ["spending", "budget", "appropriation", "federal spending"],
}


@dataclass
class APIMatch:
    """A matched API with relevance score."""
    api: dict
    score: float
    matched_keywords: list[str] = field(default_factory=list)
    best_endpoint: dict = field(default_factory=dict)


def _select_best_endpoint(api: dict, query: str) -> dict:
    """Select the best endpoint from an API based on query relevance.
    
    Prefers endpoints with generic placeholders ({topic}, {query}, {name})
    over endpoints with specific ID placeholders ({cve_id}, {paper_id}, {number})
    because the query is a natural language search, not a specific ID lookup.
    """
    endpoints = api.get("endpoints", [])
    if not endpoints:
        return {}
    
    query_lower = query.lower()
    query_words = set(re.findall(r'\w+', query_lower))
    
    # Placeholders that indicate "search by topic" (good for NL queries)
    SEARCH_PLACEHOLDERS = {"{topic}", "{query}", "{name}", "{company}", "{entity}", "{ticker}"}
    # Placeholders that indicate "lookup by ID" (bad for NL queries)
    ID_PLACEHOLDERS = {"{cve_id}", "{paper_id}", "{number}", "{doi}", "{id}", "{ip}"}
    
    best = endpoints[0]  # default to first
    best_score = -1
    
    for ep in endpoints:
        score = 0
        path = ep.get("path", "")
        use_when = ep.get("use_when", "").lower()
        returns = ep.get("returns", "").lower()
        
        # Strongly prefer search endpoints over ID-lookup endpoints
        path_placeholders = set(re.findall(r'\{[^}]+\}', path))
        if path_placeholders & SEARCH_PLACEHOLDERS:
            score += 10  # bonus for search-type endpoint
        if path_placeholders & ID_PLACEHOLDERS:
            score -= 5   # penalty for ID-lookup endpoint
        
        # Score based on use_when overlap with query
        use_words = set(re.findall(r'\w+', use_when))
        score += len(query_words & use_words) * 3
        
        # Score based on returns overlap  
        ret_words = set(re.findall(r'\w+', returns))
        score += len(query_words & ret_words) * 1
        
        # Exact phrase matches in use_when
        for phrase_len in [3, 2]:
            words = query_lower.split()
            for i in range(len(words) - phrase_len + 1):
                phrase = " ".join(words[i:i+phrase_len])
                if phrase in use_when:
                    score += phrase_len * 5
        
        if score > best_score:
            best_score = score
            best = ep
    
    return best


def match_apis(query: str, registry: list[dict], top_k: int = 8,
               domain: Optional[str] = None) -> list[APIMatch]:
    """Match a research query to relevant APIs from registry.

    Domain gate first (company_pl / judgment / tariff / tender / crypto / general).
    Keywords use token boundaries — substring 'war' must not match Warszawa.
    """
    query_lower = query.lower()
    query_words = set(re.findall(r'\w+', query_lower)) - _STOPWORDS
    domain = domain or classify_domain(query)

    matches = []

    for api in registry:
        if not api_allowed(api, domain):
            continue

        score = 0.0
        matched_kw = []

        api_qtype = api.get("query_type", "")
        if api_qtype in QUERY_TYPE_KEYWORDS:
            for kw in QUERY_TYPE_KEYWORDS[api_qtype]:
                if _kw_in_query(kw, query_lower):
                    score += 5.0
                    matched_kw.append(kw)

        api_cat = api.get("category", "")
        if api_cat in CATEGORY_KEYWORDS:
            for kw in CATEGORY_KEYWORDS[api_cat]:
                if _kw_in_query(kw, query_lower):
                    score += 3.0
                    matched_kw.append(kw)

        api_name_lower = api.get("name", "").lower()
        if api_name_lower and api_name_lower in query_lower:
            score += 10.0
            matched_kw.append(api_name_lower)
        else:
            for tok in api_name_lower.split():
                if len(tok) >= 4 and tok in query_words:
                    score += 8.0
                    matched_kw.append(tok)
                    break

        api_context = f"{api_name_lower} {api_cat} {api_qtype} {api.get('notes', '')}"
        api_words = set(re.findall(r'\w+', api_context.lower())) - _STOPWORDS
        overlap = query_words & api_words
        score += len(overlap) * 1.5

        for ep in api.get("endpoints", []):
            use_when = ep.get("use_when", "").lower()
            use_words = set(re.findall(r'\w+', use_when)) - _STOPWORDS
            ep_overlap = query_words & use_words
            if len(ep_overlap) >= 2:
                score += len(ep_overlap) * 2.0
                matched_kw.extend(list(ep_overlap)[:3])

        if api.get("auth") == "apiKey":
            score *= 0.7
        elif api.get("auth") == "OAuth":
            score *= 0.3

        # Domain-forced APIs (KRS on company_pl) get a floor so they survive threshold
        if domain in ("company_pl", "tender", "tariff", "judgment", "eu_law") and score < 4.1:
            allow_names = {
                "company_pl": {
                    "KRS API (Polish Court Registry)",
                    "Biala Lista VAT (Polish Tax Registry)",
                    "Orbis (Moody's BvD)",
                    "Bisnode D&B",
                },
                "tender": {
                    "TED EU Tenders",
                    "e-Zamowienia (Polish Public Procurement)",
                },
                "tariff": {"UN Comtrade", "Eurostat Data API"},
                "judgment": {
                    "SAOS (Polish Court Judgments)",
                    "LEX Wolters Kluwer",
                },
                "eu_law": {
                    "EUR-Lex Cellar",
                    "BOE Spain Official Gazette",
                    "CURIA CJEU",
                    "HUDOC ECHR",
                    "Dziennik Ustaw ELI",
                },
            }.get(domain, set())
            if api.get("name") in allow_names:
                score = 4.5
                matched_kw.append("domain:" + domain)

        if score > 4.0:
            best_ep = _select_best_endpoint(api, query)
            matches.append(APIMatch(
                api=api, score=score,
                matched_keywords=list(set(matched_kw))[:5],
                best_endpoint=best_ep,
            ))

    matches.sort(key=lambda m: -m.score)
    return matches[:top_k]


# ── API Querying ─────────────────────────────────────────────────────────────

# Country name → ISO 2-letter code mapping
_COUNTRY_CODES = {
    "united states": "US", "usa": "US", "us": "US", "america": "US",
    "united kingdom": "GB", "uk": "GB", "britain": "GB", "england": "GB",
    "germany": "DE", "france": "FR", "italy": "IT", "spain": "ES",
    "poland": "PL", "netherlands": "NL", "belgium": "BE", "austria": "AT",
    "switzerland": "CH", "sweden": "SE", "norway": "NO", "denmark": "DK",
    "finland": "FI", "ireland": "IE", "portugal": "PT", "greece": "GR",
    "czech": "CZ", "romania": "RO", "hungary": "HU", "slovakia": "SK",
    "croatia": "HR", "bulgaria": "BG", "slovenia": "SI", "estonia": "EE",
    "latvia": "LV", "lithuania": "LT", "luxembourg": "LU", "malta": "MT",
    "china": "CN", "japan": "JP", "korea": "KR", "south korea": "KR",
    "india": "IN", "australia": "AU", "canada": "CA", "brazil": "BR",
    "mexico": "MX", "russia": "RU", "turkey": "TR", "israel": "IL",
    "saudi": "SA", "uae": "AE", "singapore": "SG", "taiwan": "TW",
    "indonesia": "ID", "malaysia": "MY", "thailand": "TH", "vietnam": "VN",
    "philippines": "PH", "nigeria": "NG", "south africa": "ZA", "egypt": "EG",
    "argentina": "AR", "colombia": "CO", "chile": "CL", "peru": "PE",
    "ukraine": "UA", "georgia": "GE", "new zealand": "NZ",
}

def _detect_country_code(text: str) -> str:
    """Extract a 2-letter country code from text, default 'US'."""
    text_lower = text.lower()
    for name, code in _COUNTRY_CODES.items():
        if name in text_lower:
            return code
    return "US"  # default


def _build_url(api: dict, endpoint: dict, topic: str) -> Optional[str]:
    """Build the full URL for an API endpoint with variable substitution."""
    base_url = api["url"]
    if api.get("name") == "LEX Wolters Kluwer":
        base_url = os.environ.get("LEX_API_BASE") or base_url
    path = endpoint.get("path", "")
    
    if not path:
        return None
    
    # Substitute variables
    from urllib.parse import quote_plus
    topic_encoded = quote_plus(topic)
    
    # Detect country code from query
    country_code = _detect_country_code(topic)
    
    # ── TRADE DATA QUERY BUILDER ──────────────────────────────────
    # For APIs with trade-specific parameters, extract from topic context
    topic_lower = topic.lower()
    
    # UN M49 country codes for trade APIs
    M49_CODES = {
        'poland': '616', 'polish': '616', 'polska': '616',
        'south africa': '710', 'brazil': '076', 'argentina': '032',
        'chile': '152', 'paraguay': '600', 'uruguay': '858',
        'kenya': '404', 'nigeria': '566', 'ethiopia': '231',
        'tanzania': '834', 'morocco': '504', 'egypt': '818',
        'ukraine': '804', 'ukrainian': '804', 'ukraina': '804',
        'kazakhstan': '398', 'uzbekistan': '860',
        'vietnam': '704', 'philippines': '608', 'indonesia': '360',
        'germany': '276', 'france': '250', 'uk': '826', 'united kingdom': '826',
        'usa': '842', 'united states': '842',
        'turkey': '792', 'india': '356', 'china': '156', 'japan': '392',
        'canada': '124', 'australia': '036', 'mexico': '484',
    }
    
    # HS codes for agricultural machinery
    HS_CODES = {
        'tractor': '8701', 'tractors': '8701', 'ciągnik': '8701',
        'plow': '8432', 'plough': '8432', 'cultivat': '8432', 'soil': '8432',
        'maszyn': '8432', 'machin': '8432', 'implement': '8432',
        'harvester': '8433', 'mower': '8433', 'combine': '8433', 'kosiark': '8433',
        'milking': '8434', 'dairy equipment': '8434',
        'seeder': '8436', 'other ag': '8436',
    }
    
    # Detect reporter/partner from topic
    detected_reporter = '616'  # Default: Poland
    detected_partner = '0'    # Default: World
    detected_hs = '8432'      # Default: soil prep machinery
    detected_flow = 'X'       # Default: exports
    
    # Sort by length descending to avoid "uk" matching "ukraine"
    sorted_countries = sorted(M49_CODES.items(), key=lambda x: -len(x[0]))
    
    # First pass: identify all mentioned countries
    mentioned_countries = []
    for country, code in sorted_countries:
        if re.search(r'\b' + re.escape(country) + r'\b', topic_lower):
            mentioned_countries.append((country, code))
    
    # Determine flow direction from explicit verbs near Poland
    poland_export = bool(re.search(r'pol(?:and|ish|ska).*(?:export|eksport)', topic_lower))
    poland_import = bool(re.search(r'pol(?:and|ish|ska).*import', topic_lower))
    
    if poland_export:
        detected_flow = 'X'
        detected_reporter = '616'
    elif poland_import:
        detected_flow = 'M'
        detected_reporter = '616'
    
    # Assign partner: first non-Poland country mentioned
    for country, code in mentioned_countries:
        if code != '616':
            # Check explicit patterns
            from_pattern = re.search(r'from\s+' + re.escape(country) + r'\b', topic_lower)
            to_pattern = re.search(r'to\s+' + re.escape(country) + r'\b', topic_lower)
            
            if from_pattern:
                detected_partner = code
            elif to_pattern:
                detected_partner = code
            else:
                # Default: non-Poland country is the partner
                detected_partner = code
            break  # Take first non-Poland country as primary partner
    
    # Collect ALL non-Poland partners for multi-URL queries (used by Comtrade)
    _all_partners = [code for _, code in mentioned_countries if code != '616']
    if not _all_partners:
        _all_partners = ['0']  # World
    
    for keyword, hs in HS_CODES.items():
        if keyword in topic_lower:
            detected_hs = hs
            break
    
    from behive.engine.entity_resolver import extract_pl_ids
    _ids = extract_pl_ids(topic)
    detected_nip = _ids.get("nip") or ""
    detected_krs = _ids.get("krs") or ""
    
    # Standard substitutions
    from datetime import date
    today = date.today().isoformat()
    
    subs = {
        "{topic}": topic_encoded,
        "{query}": topic_encoded,
        "{name}": topic_encoded,
        "{company}": topic_encoded,
        "{ticker}": topic_encoded,
        "{entity}": topic_encoded,
        "{country}": country_code,
        "{country_code}": country_code,
        "{package}": topic_encoded,
        "{domain}": topic_encoded,
        "{ip}": topic_encoded,
        "{tag}": topic_encoded,
        "{base}": "USD",
        "{date}": today,
        "{from}": "2024-01-01",
        "{to}": "2025-01-01",
        "{year}": "2023",
        "{year_start}": "2020",
        "{year_end}": "2024",
        "{start}": "2020",
        "{end}": "2024",
        "{fips}": "06",
        "{subreddit}": "technology",
        "{cat}": "technology",
        "{cve_id}": topic_encoded,
        "{code}": country_code,
        # Trade-specific
        "{reporter}": detected_reporter,
        "{partner}": detected_partner,
        "{hs_code}": detected_hs,
        "{flow}": detected_flow,
        "{product}": detected_hs,
        # Polish APIs
        "{nip}": detected_nip,
        "{krs_number}": detected_krs,
        "{keyword}": topic_encoded,
        "{var_id}": "217230",  # Default: CPI
    }
    
    for var, val in subs.items():
        if var in ("{nip}", "{krs_number}", "{regon}") and not val:
            continue
        path = path.replace(var, val)
    
    # Skip if has {key} and no key available (or other unresolved vars)
    if "{key}" in path or "{email}" in path:
        # Check env for common API key patterns
        api_name_upper = api["name"].upper().replace(" ", "_").replace(".", "_")
        env_key = os.environ.get(f"{api_name_upper}_API_KEY") or os.environ.get(f"{api_name_upper}_KEY")
        if env_key:
            path = path.replace("{key}", env_key)
            path = path.replace("{email}", "hive@research.ai")
        else:
            return None  # Skip — no key available
    
    # Never stuff a company name into KRS/NIP/REGON placeholders
    if re.search(r'\{(krs_number|nip|regon)\}', path):
        return None

    # Any remaining unresolved vars?
    if re.search(r'\{[^}]+\}', path):
        # Try to fill with topic-derived best guess
        path = re.sub(r'\{[^}]+\}', topic_encoded, path)
    
    # Build full URL
    if path.startswith("http"):
        return path
    elif path.startswith("/"):
        return base_url.rstrip("/") + path
    elif path.startswith("?"):
        return base_url.rstrip("/") + path
    else:
        return base_url.rstrip("/") + "/" + path


def _vendor_api_key(api: dict) -> str:
    """BYOK lookup. Empty → caller must skip, never scrape a login wall."""
    env_map = {
        "Orbis (Moody's BvD)": ("ORBIS_API_KEY", "BVD_API_KEY"),
        "LEX Wolters Kluwer": ("LEX_API_KEY", "WOLTERS_KLUWER_API_KEY"),
        "Bisnode D&B": ("BISNODE_API_KEY", "DNB_API_KEY", "DNB_DIRECT_KEY"),
        "WTO Timeseries API": ("WTO_API_KEY", "WTO_TIMESERIES_KEY"),
        "OpenCorporates": ("OPENCORPORATES_API_KEY",),
    }
    for k in env_map.get(api.get("name") or "", ()):
        v = os.environ.get(k)
        if v:
            return v
    name_upper = (api.get("name") or "").upper().replace(" ", "_").replace(".", "_").replace("'", "")
    return os.environ.get(f"{name_upper}_API_KEY") or ""


async def query_api(match: 'APIMatch', topic: str, session: aiohttp.ClientSession,
                    timeout: int = 15) -> Optional[dict]:
    """Query a single API and return structured document."""
    api = match.api
    endpoint = match.best_endpoint
    
    if not endpoint:
        return None

    missing_endpoint = api.get("name") == "LEX Wolters Kluwer" and not os.environ.get("LEX_API_BASE")
    if api.get("auth") == "apiKey" and (not _vendor_api_key(api) or missing_endpoint):
        from behive.engine.byok import gap_doc
        log.info(f"  API {api['name']}: BYOK gap (no API key)")
        return gap_doc(api, topic)

    if (api.get("name") or "").startswith("EUR-Lex"):
        try:
            from behive.engine.cellar import hits_to_doc, search_cellar
            hits = await asyncio.to_thread(search_cellar, topic)
            return hits_to_doc(topic, hits)
        except Exception as e:
            log.debug(f"  API {api['name']}: cellar error {e}")
            return None

    if (api.get("name") or "").startswith("SAOS"):
        try:
            from behive.engine.cellar import saos_search
            return await asyncio.to_thread(saos_search, topic)
        except Exception as e:
            log.debug(f"  API {api['name']}: saos error {e}")
            return None

    if (api.get("name") or "").startswith("HUDOC"):
        try:
            from behive.engine.cellar import hudoc_search
            return await asyncio.to_thread(hudoc_search, topic)
        except Exception as e:
            log.debug(f"  API {api['name']}: hudoc error {e}")
            return None

    if (api.get("name") or "").startswith("Dziennik Ustaw"):
        try:
            from behive.engine.cellar import eli_search
            return await asyncio.to_thread(eli_search, topic)
        except Exception as e:
            log.debug(f"  API {api['name']}: eli error {e}")
            return None

    if (api.get("name") or "").startswith("CURIA"):
        try:
            from behive.engine.cellar import curia_search
            return await asyncio.to_thread(curia_search, topic)
        except Exception as e:
            log.debug(f"  API {api['name']}: curia error {e}")
            return None

    if (api.get("name") or "").startswith("WTO Documents"):
        try:
            from behive.engine.wto import wto_search
            return await asyncio.to_thread(wto_search, topic)
        except Exception as e:
            log.debug(f"  API {api['name']}: wto error {e}")
            return None
    
    url = _build_url(api, endpoint, topic)
    if not url:
        return None
    
    try:
        headers = {"User-Agent": "HIVE-Research/2.0 (research-engine; +https://behive.ai)"}
        if api.get("auth") == "apiKey":
            key = _vendor_api_key(api)
            if not key:
                from behive.engine.byok import gap_doc
                log.info(f"  API {api['name']}: BYOK gap (no API key)")
                return gap_doc(api, topic)
            header = api.get("auth_header") or "X-API-Key"
            scheme = (api.get("auth_scheme") or "").strip()
            if scheme.lower() == "bearer" or header == "Authorization":
                headers["Authorization"] = f"Bearer {key}"
            else:
                headers[header] = key
        
        # Some APIs need Accept header
        if "arxiv" in api["name"].lower():
            headers["Accept"] = "application/atom+xml"
        else:
            headers["Accept"] = "application/json"
        
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout),
                               headers=headers) as resp:
            if resp.status == 429:
                # Rate limited — wait and retry once
                log.debug(f"  API {api['name']}: HTTP 429 (rate limited), retrying...")
                await asyncio.sleep(2.0)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout),
                                       headers=headers) as retry_resp:
                    if retry_resp.status != 200:
                        log.debug(f"  API {api['name']}: retry HTTP {retry_resp.status}")
                        return None
                    resp = retry_resp
            elif resp.status != 200:
                log.debug(f"  API {api['name']}: HTTP {resp.status}")
                return None
            
            content_type = resp.headers.get("Content-Type", "")
            
            if "json" in content_type or "javascript" in content_type:
                data = await resp.json(content_type=None)
                # Check for error responses
                if isinstance(data, dict):
                    err_keys = {"error", "Error Message", "error_message", "fault", "errors"}
                    if err_keys & set(data.keys()):
                        log.debug(f"  API {api['name']}: returned error response")
                        return None
            elif "xml" in content_type or "atom" in content_type:
                text = await resp.text()
                data = {"_raw_xml": text[:8000]}
            else:
                text = await resp.text()
                if len(text.strip()) < 50:
                    return None
                data = {"_raw_text": text[:8000]}
            
            raw_text = _extract_text_from_response(data, api)
            if not raw_text or len(raw_text.strip()) < 30:
                return None
            
            return {
                "source": f"api:{api['name']}",
                "url": url,
                "api_name": api["name"],
                "category": api.get("category", ""),
                "query_type": api.get("query_type", ""),
                "endpoint_returns": endpoint.get("returns", ""),
                "data": data,
                "raw_text": raw_text,
            }
    except asyncio.TimeoutError:
        log.debug(f"  API {api['name']}: timeout")
        return None
    except Exception as e:
        log.debug(f"  API {api['name']}: error {e}")
        return None


def _extract_text_from_response(data: dict, api: dict) -> str:
    """Convert API JSON response into readable text for bee extraction."""
    if not data:
        return ""
    
    # Handle XML (arXiv, PubMed)
    if "_raw_xml" in data:
        return _parse_xml_text(data["_raw_xml"], api)
    
    if "_raw_text" in data:
        return data["_raw_text"][:5000]
    
    texts = []
    
    if isinstance(data, list):
        for item in data[:25]:
            if isinstance(item, dict):
                texts.append(_dict_to_text(item))
    elif isinstance(data, dict):
        # Look for common data containers
        containers = ["results", "data", "items", "articles", "works", 
                     "documents", "hits", "records", "entries", "notices",
                     "esearchresult", "response", "message", "assets",
                     "models", "packages", "repositories", "total_count",
                     "search-results", "result", "output", "collection",
                     "feed", "observations", "rates", "people", "features",
                     "abilities", "stats", "types", "moves", "forms"]
        for key in containers:
            if key in data:
                inner = data[key]
                # Skip if value is a short primitive (e.g. "result": "success")
                if isinstance(inner, (str, int, float, bool)):
                    continue
                if isinstance(inner, list):
                    for item in inner[:25]:
                        if isinstance(item, dict):
                            texts.append(_dict_to_text(item))
                        elif isinstance(item, str):
                            texts.append(item)
                elif isinstance(inner, dict):
                    # Check for nested list inside
                    for subkey in ["items", "works", "results", "idlist"]:
                        if subkey in inner and isinstance(inner[subkey], list):
                            for item in inner[subkey][:25]:
                                if isinstance(item, dict):
                                    texts.append(_dict_to_text(item))
                                elif isinstance(item, str):
                                    texts.append(item)
                            break
                    else:
                        texts.append(_dict_to_text(inner))
                break
        else:
            # No standard container found — dump top-level
            texts.append(_dict_to_text(data))
    
    return "\n---\n".join(texts)[:12000]


def _parse_xml_text(xml_text: str, api: dict) -> str:
    """Extract readable text from XML responses (arXiv, PubMed)."""
    texts = []
    
    # arXiv-style entries
    entries = re.findall(r'<entry>(.*?)</entry>', xml_text, re.DOTALL)
    for entry in entries[:20]:
        title = re.search(r'<title[^>]*>(.*?)</title>', entry, re.DOTALL)
        summary = re.search(r'<summary[^>]*>(.*?)</summary>', entry, re.DOTALL)
        authors = re.findall(r'<name>(.*?)</name>', entry)
        published = re.search(r'<published>(.*?)</published>', entry)
        
        parts = []
        if title:
            parts.append(f"title: {title.group(1).strip()}")
        if authors:
            parts.append(f"authors: {', '.join(authors[:5])}")
        if published:
            parts.append(f"published: {published.group(1)[:10]}")
        if summary:
            parts.append(f"abstract: {summary.group(1).strip()[:500]}")
        
        if parts:
            texts.append(" | ".join(parts))
    
    if texts:
        return "\n---\n".join(texts)
    
    # Fallback: strip all XML tags
    clean = re.sub(r'<[^>]+>', ' ', xml_text)
    clean = re.sub(r'\s+', ' ', clean)
    return clean[:5000]


def _dict_to_text(d: dict, max_depth: int = 2) -> str:
    """Convert a dict to readable key: value text."""
    lines = []
    # Prioritize informative keys
    priority_keys = ["title", "name", "display_name", "full_name", "description",
                     "abstract", "summary", "content", "body", "text",
                     "author", "authors", "creator", "owner",
                     "date", "published", "created_at", "year", "publication_date",
                     "score", "stars", "stargazers_count", "citations", "citationCount",
                     "price", "market_cap", "volume", "value", "amount",
                     "url", "link", "doi", "venue"]
    
    # Process priority keys first
    seen = set()
    for k in priority_keys:
        if k in d:
            seen.add(k)
            v = d[k]
            lines.append(_format_value(k, v, max_depth))
    
    # Then remaining keys
    for k, v in d.items():
        if k in seen or k.startswith("_") or k in ("id", "href", "links", "self", "type"):
            continue
        if len(lines) > 12:  # don't overflow
            break
        formatted = _format_value(k, v, max_depth)
        if formatted:
            lines.append(formatted)
    
    return " | ".join(filter(None, lines))


def _format_value(k: str, v, max_depth: int) -> str:
    """Format a key-value pair as text."""
    if isinstance(v, str) and len(v) > 0:
        return f"{k}: {v[:500]}"
    elif isinstance(v, (int, float)):
        return f"{k}: {v}"
    elif isinstance(v, bool):
        return f"{k}: {v}"
    elif isinstance(v, list) and len(v) > 0 and max_depth > 0:
        if isinstance(v[0], str):
            return f"{k}: {', '.join(str(x) for x in v[:10])}"
        elif isinstance(v[0], dict) and max_depth > 1:
            sub = [_dict_to_text(item, max_depth-1)[:150] for item in v[:3]]
            return f"{k}: [{'; '.join(sub)}]"
    elif isinstance(v, dict) and max_depth > 0:
        nested = _dict_to_text(v, max_depth - 1)
        if nested:
            return f"{k}: {nested[:300]}"
    return ""


# ── Main Scout Interface ─────────────────────────────────────────────────────

async def scout_apis(query: str, max_results: int = 12, 
                     timeout_per_api: int = 15) -> list[dict]:
    """
    Scout structured APIs for a research query.
    
    Returns list of documents (same format as web-scraped docs) ready for
    BeeHive processing.
    
    Args:
        query: Research topic/question
        max_results: Max documents to return
        timeout_per_api: Timeout per API call in seconds
    
    Returns:
        List of doc dicts with keys: title, url, raw_text, source, domain
    """
    registry = load_registry()
    if not registry:
        log.warning("API registry empty — skipping API scout")
        return []

    ent = resolve_entity(query, fetch=True)
    query = enrich_query(query, ent)
    log.info(
        f"  API Scout entity: domain={ent.domain} krs={ent.krs or '-'} "
        f"nip={ent.nip or '-'} src={ent.source}"
    )

    # Match query to APIs
    matches = match_apis(query, registry, top_k=10, domain=ent.domain)
    
    if not matches:
        log.info(f"  API Scout: no matching APIs for '{query[:50]}'")
        return []
    
    log.info(f"  API Scout: {len(matches)} APIs matched for '{query[:50]}'")
    for m in matches[:5]:
        ep_info = m.best_endpoint.get("use_when", "?")
        log.info(f"    [{m.score:.1f}] {m.api['name']} → {ep_info}")
    
    # Query matched APIs in parallel
    docs = []
    async with aiohttp.ClientSession() as session:
        tasks = []
        _comtrade_extra_queries = []  # Sequential to avoid rate limiting
        for m in matches:
            tasks.append(query_api(m, query, session, timeout_per_api))
            # For trade APIs with multiple target countries — collect for sequential execution
            if m.api.get('name', '') == 'UN Comtrade':
                # Detect all mentioned partners from query
                _q_lower = query.lower()
                _m49 = {
                    'south africa': '710', 'brazil': '076', 'argentina': '032',
                    'chile': '152', 'ukraine': '804', 'kenya': '404',
                    'nigeria': '566', 'ethiopia': '231', 'tanzania': '834',
                    'kazakhstan': '398', 'turkey': '792', 'egypt': '818',
                    'morocco': '504', 'vietnam': '704', 'indonesia': '360',
                    'canada': '124', 'australia': '036', 'india': '356',
                }
                _partners_found = []
                for cname, ccode in sorted(_m49.items(), key=lambda x: -len(x[0])):
                    if re.search(r'\b' + re.escape(cname) + r'\b', _q_lower):
                        _partners_found.append((cname, ccode))
                # If >1 partner mentioned, queue additional queries
                if len(_partners_found) > 1:
                    for cname, ccode in _partners_found[1:]:  # Skip first (already in default)
                        _comtrade_extra_queries.append((m, f"Poland export {cname} HS 8432 agricultural machinery"))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Run Comtrade fan-out queries sequentially with delay to avoid rate limiting
        for _ct_match, _ct_query in _comtrade_extra_queries:
            await asyncio.sleep(1.5)  # 1.5s between requests (Comtrade rate limit ~1req/s)
            for _retry in range(2):
                try:
                    _ct_result = await query_api(_ct_match, _ct_query, session, timeout_per_api)
                    if _ct_result:
                        results.append(_ct_result)
                        break
                    elif _retry == 0:
                        await asyncio.sleep(2.0)  # Extra wait on None (might be soft 429)
                except Exception as _ct_err:
                    if _retry == 0:
                        await asyncio.sleep(2.0)
                    results.append(_ct_err)
        
        for i, result in enumerate(results):
            if not isinstance(result, dict):
                continue
            if result and isinstance(result.get("data"), dict) and result["data"].get("skipped"):
                # Configuration gaps are diagnostics, not harvested evidence.
                continue
            if result and result.get("raw_text"):
                # Convert to standard doc format for BeeHive
                doc = {
                    "title": f"[API: {result['api_name']}] {query}",
                    "url": result["url"],
                    "raw_text": result["raw_text"],
                    "source": result["source"],
                    "domain": result["api_name"].lower().replace(" ", "_"),
                    "_api_data": result["data"],
                    "_api_category": result["category"],
                    "_api_query_type": result["query_type"],
                    "_api_endpoint_returns": result.get("endpoint_returns", ""),
                }
                docs.append(doc)
    
    log.info(f"  API Scout: {len(docs)}/{len(matches)} APIs returned data")
    return docs[:max_results]


# ── Queen Knowledge Export ────────────────────────────────────────────────────

def get_api_knowledge_for_queen() -> str:
    """
    Generate a concise knowledge summary for the Queen (synthesis agent).
    
    The Queen uses this to:
    - Know what structured data sources were consulted
    - Cite API sources properly
    - Understand data recency and reliability
    """
    registry = load_registry()
    
    lines = ["## Available Structured Data Sources (API Scout)\n"]
    lines.append(f"Total: {len(registry)} APIs across {len(set(a['category'] for a in registry))} categories\n")
    
    by_cat = {}
    for api in registry:
        cat = api.get("category", "other")
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(api)
    
    for cat, apis in sorted(by_cat.items()):
        lines.append(f"\n### {cat.upper()} ({len(apis)} sources)")
        for api in apis:
            auth_icon = "🔓" if api["auth"] == "none" else "🔑"
            ep_count = len(api.get("endpoints", []))
            lines.append(f"  {auth_icon} **{api['name']}** ({ep_count} endpoints)")
            # What it provides
            for ep in api.get("endpoints", [])[:2]:
                lines.append(f"    → {ep.get('returns', '?')} [when: {ep.get('use_when', '?')}]")
            if api.get("notes"):
                lines.append(f"    ⚠️ {api['notes'][:100]}")
    
    return "\n".join(lines)


# ── CLI Test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--queen-knowledge":
        print(get_api_knowledge_for_queen())
        sys.exit(0)
    
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "cryptocurrency market trends 2025"
    
    print(f"🔍 API Scout query: '{query}'")
    print("=" * 60)
    
    docs = asyncio.run(scout_apis(query))
    
    print(f"\n📊 Results: {len(docs)} documents from APIs")
    for i, doc in enumerate(docs, 1):
        print(f"\n{'─'*60}")
        print(f"  [{i}] {doc['title']}")
        print(f"      URL: {doc['url']}")
        print(f"      Source: {doc['source']}")
        text_preview = doc['raw_text'][:200].replace('\n', ' ')
        print(f"      Text: {text_preview}...")
