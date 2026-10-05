"""Mission/claim hygiene.

Empty-done is a lie: status=done requires clean claims with mission provenance.
JSON/list envelopes from v4 extraction are not claims.
"""
import re


def is_structured_blob(text) -> bool:
    if text is None:
        return False
    s = str(text).lstrip()
    return bool(s) and s[0] in "{["


# PostgreSQL predicate on hive_claims.claim
SQL_CLAIM_NOT_BLOB = "left(ltrim(claim), 1) NOT IN ('{', '[')"


# Pipeline exit code is not a product. Claims are.
MIN_CLAIMS_FOR_DONE = 3


# Completion queries use alias c. URL provenance is mission-scoped: API scouts
# legitimately write hive_content without inserting any hive_sources rows.
SQL_COMPLETION_CLAIM = """
    (c.is_garbage = false OR c.is_garbage IS NULL)
    AND length(ltrim(COALESCE(c.claim, ''), chr(32) || chr(9) || chr(10) || chr(13) || chr(11) || chr(12))) > 0
    AND substr(ltrim(c.claim, chr(32) || chr(9) || chr(10) || chr(13) || chr(11) || chr(12)), 1, 1) NOT IN ('{', '[')
    AND length(trim(COALESCE(c.source_url, ''))) > 0
    AND (
        EXISTS (SELECT 1 FROM hive_sources s
                WHERE s.mission_id = c.mission_id AND s.url = c.source_url)
        OR EXISTS (SELECT 1 FROM hive_content d
                   WHERE d.mission_id = c.mission_id AND d.url = c.source_url)
    )
"""


def is_empty_mission(sources: int, claims: int, *, sourced_claims: int | None = None) -> bool:
    """Require clean claims with provenance, including API-only content.

    Callers with actual evidence supply sourced_claims. Legacy count-only callers
    retain the conservative source+claim guard; counts cannot prove API provenance.
    """
    if sourced_claims is not None:
        return int(claims or 0) <= 0 or int(sourced_claims or 0) <= 0
    return int(sources or 0) <= 0 or int(claims or 0) <= 0


def has_salvageable_claims(claims: int) -> bool:
    """A nonzero exit produced enough eligible claims (not raw row counts)."""
    return int(claims or 0) >= MIN_CLAIMS_FOR_DONE


_CSS = re.compile(
    r"[{}]|padding-|font-size|#dropdown|border:|width:\s*\d|margin-right|float:\s*left|"
    r"/\*|javascript:|lorem ipsum",
    re.I,
)
_HTML = re.compile(r"<[^>]+>")
_SENT_START = re.compile(r"[A-ZĄĆĘŁŃÓŚŹŻ]")


def sanitize_claim(text: str) -> str | None:
    """Drop CSS/HTML/truncated fragments. Keep a full sentence with a digit."""
    s = _HTML.sub(" ", text or "")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) < 40:
        return None
    if is_structured_blob(s) or _CSS.search(s):
        return None
    if s.count(";") >= 5:
        return None
    m = _SENT_START.search(s)
    if not m:
        return None
    s = s[m.start():].strip()
    if len(s) < 40 or len(s) > 800:
        return None
    if s[0].islower() or s[0] in ")]},.;:":
        return None
    if not re.search(r"\d", s):
        return None
    return s
