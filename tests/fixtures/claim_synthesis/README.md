# Steel synthesis fixture

`steel_claims.json` is a byte-identical, read-only-input copy of the real public-source claim export supplied for the synthesis repair:

- Source: `/root/outputs/behive-steel-2026-10-24/S1-claims/claims_snapshot.json`
- SHA-256: `418073d0c325d75e32a8d56979a9b1a73d41e7295bfcb93feb06336cc0b674b5`
- Claims: 87 (public claim text, URL, original IDs and provenance flags).

The copy makes the regression independent of an external artifact directory. It does not authorize a live mission or production database connection. Private-PG tests reinsert these claims into owned canonical tables. The completion in `tests/claim_synthesis_support.py` is explicitly hand-written fake JSON, not a live model capture.
