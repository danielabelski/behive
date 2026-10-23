# Captured BeHive planner responses

These are **authentic configured-model completions**, not hand-authored planner responses.

- `captured_pl_wms_telemetry.txt`: Polish WMS/tank-telemetry supplier topic.
- `captured_en_heat_pumps.txt`: European heat-pump market topic with requested year 2025.
- Corresponding `.meta.json`: topic, model/stage, UTC capture time, prompt SHA-256, raw-response SHA-256 and attempt number. No credentials.

Captured through `behive.engine.llm.complete(stage='scout')`, with `/root/.behive_runtime.env` loaded and strict mode enabled. Two live calls total; no retries, missions, search requests or production writes. The complete capture script and call ledger are in `/root/outputs/behive-discovery-2026-10-23/W2/`.

Offline tests mock only the model boundary and pass these raw strings through the real `QueenPlanner.plan()` and validators. Synthetic mutations are labelled in test docstrings. The English capture contains model-proposed concrete EHPA/EU sites; the planner maps these to `site:` operators within the same eight-word cap. Mapping does not alter these captured source bytes.
