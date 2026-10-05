"""Correct LLM NER when PERSON is actually geo/org/junk. Shared by process.py and bulk UPDATE."""
from __future__ import annotations

import re

GEO = frozenset(
    {
        "united states", "united kingdom", "south america",
        "latin america", "north america", "middle east", "southeast asia",
        "western europe", "eastern europe", "south africa", "saudi arabia",
        "south korea", "north korea", "black sea", "red sea", "caspian",
        "china", "india", "brazil", "argentina", "paraguay", "uruguay",
        "bolivia", "chile", "peru", "mexico", "canada", "russia", "ukraine",
        "poland", "germany", "france", "italy", "spain", "portugal",
        "netherlands", "belgium", "austria", "sweden", "norway", "denmark",
        "finland", "ireland", "greece", "hungary", "romania", "czechia",
        "czech republic", "slovakia", "croatia", "bulgaria", "slovenia",
        "estonia", "latvia", "lithuania", "luxembourg", "malta", "cyprus",
        "japan", "taiwan", "vietnam", "thailand", "indonesia", "malaysia",
        "singapore", "philippines", "australia", "new zealand", "egypt",
        "nigeria", "kenya", "ethiopia", "morocco", "algeria", "tunisia",
        "israel", "iran", "iraq", "turkey", "türkiye", "qatar", "uae",
        "united arab emirates", "pakistan", "bangladesh", "switzerland",
        "polska", "niemcy", "francja", "włochy", "hiszpania", "brazylia",
        "chiny", "indie", "argentyna", "paragwaj", "urugwaj", "boliwia",
        "stany zjednoczone", "wielka brytania",
        "south american", "north american", "latin american",
        "member states", "asia", "africa", "europe", "antarctica",
        "pacific", "atlantic", "caribbean", "scandinavia", "balkans",
        "horn of africa", "sub-saharan africa", "central america",
        "far east", "near east", "maghreb", "sahel", "asia pacific", "asia-pacific",
    }
)

ORG = frozenset(
    {
        "european commission", "european parliament", "european council",
        "european union", "unii europejskiej",
        "european central bank", "european court of justice",
        "world trade organization", "world bank", "international monetary fund",
        "united nations", "oecd", "nato", "who", "fao", "unhcr",
        "openai", "anthropic", "google", "microsoft", "meta", "nvidia",
        "amazon", "apple", "tesla", "byd", "columbus energy",
        "mercosur partnership agreement", "wto", "imf", "ecb", "cj eu",
        "court of justice", "general court",
    }
)

NOISE = frozenset(
    {
        "frequently asked questions", "in statista", "helvetica neue",
        "lorem ipsum", "click here", "read more", "home page",
        "privacy policy", "cookie policy", "terms of service",
        "javascript", "undefined", "null", "n/a", "unknown",
        "key takeaways", "executive summary", "table of contents",
        "noto sans", "noto color emoji", "apple color emoji", "segoe ui",
        "times new roman", "arial", "roboto", "open sans",
    }
)

_MONTH_LEAD = re.compile(
    r"^in (january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.I,
)

_ORG_SUFFIX = re.compile(
    r"\b(commission|parliament|agency|ministry|corporation|inc\.?|ltd\.?|"
    r"gmbh|s\.a\.|sp\.?\s*z\s*o\.?\s*o\.?|agreement|organization|"
    r"organisation|authority|institute|university|bank)\b",
    re.I,
)
_GEO_SUFFIX = re.compile(
    r"\b(states|kingdom|republic|federation|islands|peninsula|gulf|sea|"
    r"ocean|continent|region|union)\b",
    re.I,
)


def remap_entity_type(etype: str, value: str) -> str:
    """If NER said person/unknown but value is geo/org/junk, override."""
    t = (etype or "").strip().lower()
    if t in ("org", "orgs", "company"):
        t = "organization"
    if t in ("loc", "geo", "country", "city", "region"):
        t = "location"
    v = " ".join((value or "").strip().lower().split())
    if not v:
        return t or "unknown"
    if v in NOISE or v.startswith("frequently asked") or _MONTH_LEAD.match(v):
        return "noise"
    if "emoji" in v or v.startswith("noto "):
        return "noise"
    if v in GEO:
        return "location"
    if v in ORG:
        return "organization"
    if t in ("person", "people", "individual", "unknown", "entity", "entitie"):
        if _ORG_SUFFIX.search(v) and v not in GEO:
            return "organization"
        if _GEO_SUFFIX.search(v):
            return "location"
    return t or "unknown"
