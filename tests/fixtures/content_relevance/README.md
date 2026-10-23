# Real content relevance captures

These fixtures are **real page texts and unmodified configured-model responses**, not generated provider stubs.

- `pages.json`: Benin TRACKFUEL PDF (read-only `hive_content`, mission `hive_1792749685_27c999`), six pages from mission `hive_1792754507_37a6d0`, and a direct public HTTP capture of the ATK GPS vehicle-probe page.
- `response.json`: one strict bridge `behive.engine.llm.complete` call on those eight cleaned 2,000-character excerpts, with title and URL. Model `openai/gpt-6.1-sol`; stage `process`; `json_mode=False`. Raw return value, exact prompt, and call options retained.
- `pages_secondary.json` / `response_secondary.json`: ten additional read-only page texts from `hive_1792754507_37a6d0`, and one real bridge call. Includes a grade-1 Baltchem implementation and grade-2 Polish suppliers, so tests distinguish partial from direct relevance.

Each page records provenance and the SHA-256 of its captured raw text. Database reads used `BEGIN READ ONLY ... ROLLBACK`. No mission, production write, or service action occurred.

The capture calls judged all 18 supplied pages. The real filter first applies its existing keyword threshold; consequently the secondary capture's zero-overlap Endress page is not submitted by `filter()`. Tests replay only the relevant captured rows, preserving grades/reasons and explicitly reindexing them when repeating/subsetting pages for batch controls. Fault injections (exceptions, malformed JSON, wrong indices/types, duplicate keys) are explicitly labelled controls, not real provider output.

These fixtures test gate behavior. They are not independent frozen evaluation gold, and no precision/recall quality claim should be inferred from same-judge replay.
