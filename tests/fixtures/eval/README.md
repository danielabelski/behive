# Authentic replay captures

- `flotlis.html`: direct anonymous GET with `User-Agent: behive-eval`; source,
  timestamp, content type, HTTP status, and original-byte SHA-256 are in
  `flotlis.receipt.json`. The same acquisition populates E/content; the campaign
  does not request this URL again.
- `sciencedirect-block.html`: anonymous direct GET returned HTTP403 and a real
  CAPTCHA challenge. The receipt identifies the exact public URL and byte hash.
  The classifier also replays these bytes under HTTP200 to prove challenge
  detection independent of the status code. No challenge was attempted/solved.
- `sol-content.raw.txt`: actual strict Sol bridge output for a single page-content
  prompt. Its batch prompt/response hashes are in `sol-content.receipt.json`;
  full prompt and response are under E/captures/sol. Model output is not edited.
- `claude-content.raw.txt` and `claude-content.envelope.json`: untouched Sonnet
  content-judging response and CLI envelope for T2 indices 0–14. The receipt pins
  its exact prompt/response hashes; modelUsage confirms claude-sonnet-5-5, one
  turn, and zero web-search requests.
- `claude-overlong-reason.raw.txt`: authentic rejected T2 batch (indices 225–239),
  retained unchanged because some reasons exceed the strict 20-word limit. It is
  a failure fixture, not a validated label set; the receipt records that failure.
- Any malformed JSON inside tests is a clearly synthetic validation probe, not a
  recorded model response. Test HTTP and model callbacks are only external
  boundaries; ranking, parsing, caching, provenance, and PG are real code.

These captures are frozen bytes, not assertions about current website contents.
