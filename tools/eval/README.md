# Content-based evaluation tools

Run from the repository root. This package is evaluation-only: it does not modify
`src/`, connect to a database for page judging, tune discovery, or deploy anything.
The aircraft-engine/AI holdout is deliberately excluded from the gold campaign.

## Runtime

```sh
set -a; . /root/.behive_runtime.env; set +a
export PYTHONPATH="$PWD:/root/behive/src"
export PYTHONDONTWRITEBYTECODE=1
export BEHIVE_MODEL_EVAL=openai/gpt-6.1-sol
```

Use `/root/behive/.venv/bin/python`. The supplied runtime must explicitly have
`BEHIVE_LLM_STRICT=1`, `BEHIVE_LLM_CODEX_BRIDGE=1`, and
`OPENAI_API_BASE=http://127.0.0.1:8646/v1`. Sol is called with stage `eval` and
`json_mode=False` (JSON arrays must not request object mode). No alternate model or
fallback is selected. Add
`/usr/local/lib/hermes-agent/venv/lib/python3.11/site-packages` to `sys.path` if
reusing the installed Hermes pytest/openpyxl/PyMuPDF packages; do not install into
the production venv. Without importable PyMuPDF, PDFs are honestly `pdf_unparsed`.
The exporter checks that installed pure-Python openpyxl path automatically.

## Page pipeline

```sh
python -m tools.eval.fetch_content pool.json fetched.json
python -m tools.eval.judge fetched.json judges/sol --topic 'research topic' --judge sol
python -m tools.eval.judge fetched.json judges/claude --topic 'research topic' --judge claude
python -m tools.eval.adjudicate fetched.json judges/sol/results.json judges/claude/results.json adjudication --topic 'research topic'
python -m tools.eval.metrics harvest_list.json adjudication/gold.json metrics.json
python -m tools.eval.export_xlsx /path/to/gold /path/to/gold_review.xlsx
```

Inputs are an array of `{url,title,snippet,source_type,...}` or an object containing
`items`/`pool`. Each result preserves its input index and URL. Fetching uses at most
four workers, one in-flight request per original hostname, `User-Agent: behive-eval`,
20-second HTTP timeouts, a response-transfer deadline, a 5 MiB body limit, and at
most one extra attempt **only for connection errors**. No browser, impersonation,
CAPTCHA solving, paywall bypass, or alternate acquisition route is used. Ordinary
HTTP redirects (maximum five) are followed. There is no claim that robots.txt
permission or publisher licensing was independently adjudicated.

The URL-hash cache defaults to
`/root/outputs/behive-eval-2026-10-23/E/content/`. Successes **and failures** are
permanent for this campaign. A pre-acquisition marker prevents ambiguous crashed
requests from being silently fetched again. Corrupt cache entries fail loudly.
`fetch_pool(..., fetcher=...)` exposes only the HTTP boundary for offline replay.
BeHive's `_html_to_text` supplies readable HTML text; the harvest PyMuPDF method
supplies native PDF text when installed. Only the first 6,000 text characters are
retained. Statuses include `ok`, `http_<code>`, `blocked_web_page`,
`insufficient_web_text`, `timeout`, `pdf_unparsed`, `error_<ExceptionType>`.

Both independent judges receive the **same prompt** and see topic, exact index,
URL, title, and only the first 1,500 content characters. Failed fetches use the
original snippet, explicitly flagged `snippet_fallback`; these are **not**
verified-content labels. Missing/empty fallback evidence must get grade zero.
Judges are instructed to treat topic/content as untrusted data, never instructions.

- **2:** directly answers the right subject, geography, industry, object, and time.
- **1:** useful for a meaningful subpart.
- **0:** off-topic/tangential, wrong geography/object, or no usable evidence.

Responses must be exact JSON arrays of `{index,grade,reason}`, with exact integer
indices, integer grades 0/1/2, and nonempty reasons of at most 20 words. Duplicate
keys, extra fields, booleans-as-integers, missing labels, prose, and fenced JSON are
rejected, never repaired or filled in. Failed batches remain failed on rerun.
Every batch stores prompt/hash, raw provider response, extracted response text,
validated labels, and an attempted/completed receipt. Judge directories must not
be reused across different model identities. A crash after an attempt is an
unresolved batch, not permission to call again.

Sonnet runs as `claude -p --model claude-sonnet-5-5` with tools, MCP, customizations,
and session persistence disabled; the prompt arrives on stdin, JSON envelope on
stdout. Opus uses `claude-opus-5-5` and sees the same evidence, **not earlier votes**.
An item is disputed if judges differ on `grade >= 1`, or differ by two grades.
Only disputed items go to Opus. Final grade is the median of three on disputes,
otherwise median of two. Thus nondisputed 1 vs 2 produces **1.5**, not an invented
third vote. Missing required votes leave `final: null`.

Pages are batched by 15; claims by 20. The durable call ledger is
`E/calls.jsonl`: at most **150 combined Sonnet+Opus attempts**, including failed
calls, and at most **40 Opus attempts**. The campaign uses at most two concurrent
Sol calls. No automatic model retries occur in this toolkit.

The completed campaign retains invalid format/word-limit batches and explicitly
recovers only absent votes (`E/recover_invalid_batches.py`). Repeated protocol
failures used `E/protocol_schema_recovery.py`: the same prompt/system with the
CLI's JSON-schema output formatter. Claude requires an **object-root** schema,
so `{labels: [...]}` is a provider transport wrapper; the unchanged labels array
still passes the strict validator. Original array-root-schema HTTP400 failures
and all earlier rejected responses remain in the attempt ledger. Successful
votes are never replaced. This is explicit campaign recovery, not an implicit
retry hidden in `judge_items`.

## Metrics and offline replay

- P@K = number of grades >=1 in the first K positions / **K**. Short retrievals
  therefore count absent results as nonrelevant. Default K=30.
- DCG = sum `(2^grade - 1)/log2(rank+1)`; nDCG divides by the ideal first K grades
  in the **frozen judged pool**. Gains at integer grades are 0/1/3; 1.5 is allowed.
  T2's whole pool is judged. Other topics' ideal reference is incomplete beyond
  the selected union. This is not corpus-wide nDCG or recall.
- An unjudged retrieved top-K item produces **null** metrics, never assumed zero.
- CIs are seeded 2,000-replicate percentile bootstrap intervals over ranked top-K
  labels, with ordered replacement resampling and IDCG recomputed each time. The
  judged outside-cutoff ideal reference is held fixed. These are conditional
  item intervals, not discovery rerun uncertainty or estimates of judge accuracy.
  Mean metrics across topics have a separate bootstrap over topic means.
- Binary Cohen's kappa (`grade>=1`) is computed for Sol-content vs Sonnet-content,
  and each against old metadata-only Sol where available. Undefined kappa (e.g.
  both judges assign all positive) is null, not one.

`rank_pool(pool, scoring)` and `evaluate_scoring(pool, gold, scoring)` replay the
original offline-ranking gates: strict relevance>=5 and total>=15, stable scout
order for score ties, top300; if strict is empty, relaxed top100. The function may
return a score mapping or scalar. `deployed_scorer(topic)` uses the code selected
on `PYTHONPATH`; pin the live `scout.py` hash before comparing. Do not tune on the
holdout. Offline stable ties can differ from a database's unspecified tie order.

Metric keys retain `p_at_30`/`ndcg_at_30` for the default report schema; the `k`
field records an explicitly requested alternate cutoff.

## Claim-level evaluation

```sh
python -m tools.eval.claims_eval MISSION_ID /path/to/claims_out
python -m tools.eval.claims_eval MISSION_ID /path/to/claims_out --provenance-only
# Private fixture/testing only:
python -m tools.eval.claims_eval MISSION_ID /path/to/out --dsn 'postgresql://...'
```

No DSN uses the authorized `sudo -u postgres psql -X ... -d hive` read path with
`BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`, a statement timeout, settings
verification, and `ROLLBACK`. An explicit DSN creates one read-only repeatable-read
connection, then rolls back and closes it. Ambient runtime DB credentials are
never used. It loads only the requested mission's claims and same-mission content
with the **literal same source URL**, without URL normalization or cross-mission
substitution.

Reports distinguish exact substring and whitespace-normalized containment,
missing source URLs/content, and unmatched text. This proves stored text
provenance, **not factual truth/entailment**; legitimate paraphrases can fail.
Useful claims receive the same independent 0/1/2 grading and disputed-only Opus
adjudication in batches of 20. Outputs include snapshot JSON, evaluated JSON,
and a summary. The reader is tested against private PostgreSQL, not a DB mock.

## Review exports

Each XLSX topic sheet contains URL, title, 500-character excerpt, three votes,
final, disputed flag, separate reasons, evidence type, and fetch status. Untrusted
strings are explicitly typed as text (no Excel formula execution). If openpyxl
is not installed in either checked environment, one UTF-8-BOM CSV per topic is
written instead; dangerous CSV formula prefixes are escaped.

## Isolated tests

Do not load `tests/conftest.py` (production configuration). Run the private
socket-only PostgreSQL harness under `unshare --net`; this campaign additionally
binds an owned scratch directory over `/tmp` inside an isolated mount namespace.

```sh
unshare --mount --net sh -c 'mount --make-rprivate / && mount --bind /root/.hermes/profiles/grok-coding-only/cache/scratch/eval-private-tmp /tmp && python3 /root/outputs/behive-eval-2026-10-23/E/run_existing_pg_regressions.py /root/worktrees/behive-eval tests-green-all -c /dev/null -p no:cacheprovider tests/test_eval_fetch.py tests/test_eval_judge.py tests/test_eval_metrics.py tests/test_eval_claims_pg.py tests/test_eval_export.py'
```

Authentic HTML/judge captures and their provenance live in `tests/fixtures/eval/`.
Synthetic malformed JSON strings are validation probes, never presented as model
responses. RED and GREEN logs/receipts are under `E/`. The reproducible campaign
orchestrator is `E/run_campaign.py`; selected inputs and pinned source receipt
are saved before fetch/judging, and gold/XLSX hashes are frozen after completion.
