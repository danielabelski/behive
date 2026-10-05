"""Polish entity IDs + research-domain classification.

Name→KRS public search does not exist on api-krs (number only).
Resolver: extract NIP/KRS/REGON, enrich via KRS odpis / Biała Lista.
Matcher uses classify_domain() so CEIDG cannot hit USGS.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

KRS_ODPIS = "https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json"
BIALA_NIP = "https://wl-api.mf.gov.pl/api/search/nip/{nip}?date={day}"
BIALA_REGON = "https://wl-api.mf.gov.pl/api/search/regon/{regon}?date={day}"
UA = "BeHiveResolver/1.0 (+https://github.com/qa10devteam/behive)"

_NIP_RE = re.compile(r"\b(?:NIP[:\s]*)?(\d{3}-?\d{3}-?\d{2}-?\d{2}|\d{10})\b", re.I)
_KRS_RE = re.compile(r"\b(?:KRS[:\s]*)?(\d{7,10})\b", re.I)
_REGON_RE = re.compile(r"\b(?:REGON[:\s]*)?(\d{9}(?:\d{5})?)\b", re.I)

# Longer phrases first. Word-boundary applied at match time.
DOMAIN_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("company_pl", (
        r"sp\.?\s*z\s*o\.?\s*o", r"\bs\.a\b", r"\bkrs\b", r"\bnip\b", r"\bregon\b",
        r"\bceidg\b", r"sp[oó]łka", r"\bfirma\b", r"przedsi[eę]biorst",
        r"sądow[ey](?:m)? rejestr", r"odpis aktualny",
        r"\borbis\b", r"\bbisnode\b", r"\bduns\b", r"bureau van dijk",
    )),
    ("eu_law", (
        r"eur-?lex", r"\beurolaw\b", r"\bcelex\b", r"\bcellar\b",
        r"\btsue\b", r"\bcjeu\b", r"\becj\b", r"\bcuria\b", r"\bhudoc\b", r"\bechr\b",
        r"dziennik urz[eę]dowy", r"official journal",
        r"dyrektyw", r"rozporz[aą]dzen", r"\beu regulation\b", r"\beu directive\b",
        r"\bcelex\b", r"\bboe\b", r"bolet[ií]n oficial", r"legislation\.gov\.uk",
    )),
    ("judgment", (
        r"\borzeczenie\b", r"\bwyrok\b", r"\bsaos\b", r"\bkio\b",
        r"\bnsa\b", r"\bwsa\b", r"sąd(?:u)? najwyższ", r"\bsn\b",
        r"portal orzecze", r"teza orzec",
    )),
    ("pl_law", (
        r"\bisap\b", r"dziennik ustaw", r"\bdz\.?\s*u\b", r"\beli\.gov\b",
        r"api\.sejm\.gov", r"ustaw[ay] z dnia", r"\bn-?lex\b",
    )),
    ("tender", (
        r"przetarg", r"zam[oó]wie[nń]", r"\bswz\b", r"\bpzp\b", r"\bbzp\b",
        r"\bted\b", r"\btender\b", r"procurement", r"e-zamowienia",
    )),
    ("tariff", (
        r"\btariff\b", r"\bc[lł]o\b", r"\bhs\s*code\b", r"\bncm\b",
        r"\bannex\b", r"\bita\b", r"mercosur", r"\bcustoms\b", r"\bduty\b",
        r"\bisc\b", r"\biva\b", r"aduan", r"stawka cel",
        r"\bwto\b", r"world trade organization", r"\bsafeguard measure\b",
    )),
    ("crypto", (
        r"\bcrypto\b", r"\bbitcoin\b", r"\bethereum\b", r"\bdefi\b",
        r"\bnft\b", r"\baltcoin\b", r"\bblockchain\b",
    )),
]

# category allowlists; empty = match nothing (honest gap, not earthquake)
DOMAIN_ALLOW_CATEGORIES = {
    "company_pl": {"company_data", "business", "compliance"},
    "eu_law": set(),
    "judgment": set(),
    "pl_law": set(),
    "tender": {"tenders", "procurement"},
    "tariff": {"trade", "statistics"},
    "crypto": {"crypto"},
    "general": None,  # no allowlist — use deny only
}

DOMAIN_DENY_CATEGORIES = {
    "company_pl": {"crypto", "stocks", "forex", "science_data", "weather", "ml", "development", "containers"},
    "eu_law": {"science_data", "weather", "crypto", "ml", "forex", "stocks", "development"},
    "judgment": {"crypto", "stocks", "forex", "science_data", "weather", "ml", "development"},
    "pl_law": {"crypto", "stocks", "forex", "science_data", "weather", "ml", "development"},
    "tender": {"crypto", "science_data", "weather", "ml", "forex"},
    "tariff": {"crypto", "science_data", "weather", "ml", "development", "forex"},
    "crypto": {"science_data", "weather", "company_data", "tenders"},
    "general": {"science_data", "weather", "containers", "crypto", "forex"},
}

DOMAIN_ALLOW_NAMES = {
    "company_pl": {
        "KRS API (Polish Court Registry)",
        "Biala Lista VAT (Polish Tax Registry)",
        "UK Companies House",
        "OpenCorporates",
        "Open Sanctions",
        "Orbis (Moody's BvD)",
        "Bisnode D&B",
    },
    "eu_law": {
        "EUR-Lex Cellar",
        "BOE Spain Official Gazette",
        "HUDOC ECHR",
        "CURIA CJEU",
    },
    "judgment": {
        "SAOS (Polish Court Judgments)",
        "LEX Wolters Kluwer",
    },
    "pl_law": {
        "Dziennik Ustaw ELI",
    },
    "tariff": {"UN Comtrade", "Eurostat Data API", "OECD Trade Data", "FAOSTAT", "WTO Documents Online"},
    "tender": {"TED EU Tenders", "TED (EU Tenders)", "e-Zamowienia (Polish Public Procurement)", "SAM.gov"},
}


@dataclass
class ResolvedEntity:
    nip: str = ""
    krs: str = ""
    regon: str = ""
    name: str = ""
    domain: str = "general"
    source: str = ""
    extras: dict = field(default_factory=dict)

    def has_pl_id(self) -> bool:
        return bool(self.nip or self.krs or self.regon)


def _norm_nip(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) == 10 else ""


def _norm_krs(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if 7 <= len(digits) <= 10:
        return digits.zfill(10)
    return ""


def _norm_regon(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) in (9, 14):
        return digits
    return ""


def classify_domain(query: str) -> str:
    q = query or ""
    for domain, pats in DOMAIN_SIGNALS:
        for pat in pats:
            if re.search(pat, q, re.I):
                return domain
    return "general"


def extract_pl_ids(query: str) -> dict:
    q = query or ""
    nip = krs = regon = ""
    m = re.search(r"\bNIP[:\s]*(\d{3}-?\d{3}-?\d{2}-?\d{2}|\d{10})\b", q, re.I)
    if m:
        nip = _norm_nip(m.group(1))
    m = re.search(r"\bKRS[:\s]*(\d{7,10})\b", q, re.I)
    if m:
        krs = _norm_krs(m.group(1))
    m = re.search(r"\bREGON[:\s]*(\d{9,14})\b", q, re.I)
    if m:
        regon = _norm_regon(m.group(1))
    if not krs:
        for b in re.findall(r"\b(000\d{7})\b", q):
            krs = _norm_krs(b)
            break
    if not nip:
        for b in re.findall(r"\b(\d{10})\b", q):
            if b.startswith("000"):
                continue
            nip = _norm_nip(b)
            break
    return {"nip": nip, "krs": krs, "regon": regon}


def _http_json(url: str, timeout: float = 8.0) -> Optional[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None


def _from_krs_odpis(data: dict) -> dict:
    out = {"nip": "", "krs": "", "regon": "", "name": ""}
    odpis = (data or {}).get("odpis") or data or {}
    nag = odpis.get("naglowekA") or odpis.get("naglowek") or {}
    out["krs"] = _norm_krs(str(nag.get("numerKRS") or ""))
    dane = odpis.get("dane") or {}
    dzial1 = dane.get("dzial1") or dane.get("dział1") or {}
    dane_pod = dzial1.get("danePodmiotu") or {}
    out["name"] = str(dane_pod.get("nazwa") or dane_pod.get("nazwaSpolki") or "")[:200]
    ident = dane_pod.get("identyfikatory") or {}
    out["nip"] = _norm_nip(str(ident.get("nip") or ident.get("NIP") or ""))
    out["regon"] = _norm_regon(str(ident.get("regon") or ident.get("REGON") or ""))
    return out


def _from_biala(data: dict) -> dict:
    out = {"nip": "", "krs": "", "regon": "", "name": ""}
    subj = ((data or {}).get("result") or {}).get("subject") or {}
    if not subj:
        return out
    out["nip"] = _norm_nip(str(subj.get("nip") or ""))
    out["krs"] = _norm_krs(str(subj.get("krs") or ""))
    out["regon"] = _norm_regon(str(subj.get("regon") or ""))
    out["name"] = str(subj.get("name") or "")[:200]
    return out


def enrich_from_registries(ent: ResolvedEntity) -> ResolvedEntity:
    """Fill missing IDs via official public APIs. Number lookup only."""
    day = date.today().isoformat()
    if ent.krs and not (ent.nip and ent.name):
        data = _http_json(KRS_ODPIS.format(krs=ent.krs))
        if data:
            got = _from_krs_odpis(data)
            ent.nip = ent.nip or got["nip"]
            ent.regon = ent.regon or got["regon"]
            ent.name = ent.name or got["name"]
            ent.krs = ent.krs or got["krs"]
            ent.source = (ent.source + "+krs_odpis").strip("+")
    if ent.nip and not ent.krs:
        data = _http_json(BIALA_NIP.format(nip=ent.nip, day=day))
        if data:
            got = _from_biala(data)
            if got["nip"] or got["krs"]:
                ent.krs = ent.krs or got["krs"]
                ent.regon = ent.regon or got["regon"]
                ent.name = ent.name or got["name"]
                ent.source = (ent.source + "+biala_nip").strip("+")
    if ent.regon and not (ent.nip or ent.krs):
        data = _http_json(BIALA_REGON.format(regon=ent.regon, day=day))
        if data:
            got = _from_biala(data)
            ent.nip = ent.nip or got["nip"]
            ent.krs = ent.krs or got["krs"]
            ent.name = ent.name or got["name"]
            ent.source = (ent.source + "+biala_regon").strip("+")
    return ent


def resolve_entity(query: str, fetch: bool = True) -> ResolvedEntity:
    domain = classify_domain(query)
    ids = extract_pl_ids(query)
    ent = ResolvedEntity(
        nip=ids["nip"], krs=ids["krs"], regon=ids["regon"],
        domain=domain, source="extract",
    )
    if fetch and ent.has_pl_id():
        enrich_from_registries(ent)
    return ent


def enrich_query(query: str, ent: ResolvedEntity) -> str:
    """Append canonical IDs so api_scout _build_url regexes see them."""
    parts = [query.rstrip()]
    if ent.krs and ent.krs not in query:
        parts.append(f"KRS {ent.krs}")
    if ent.nip and ent.nip not in query.replace("-", ""):
        parts.append(f"NIP {ent.nip}")
    if ent.regon and ent.regon not in query:
        parts.append(f"REGON {ent.regon}")
    return " ".join(parts)


def api_allowed(api: dict, domain: str) -> bool:
    cat = api.get("category") or ""
    name = api.get("name") or ""
    deny = DOMAIN_DENY_CATEGORIES.get(domain) or set()
    if cat in deny:
        return False
    allow = DOMAIN_ALLOW_CATEGORIES.get(domain)
    allow_names = DOMAIN_ALLOW_NAMES.get(domain) or set()
    if allow is None:
        return True
    if name in allow_names:
        return True
    if not allow:
        return False
    return cat in allow
