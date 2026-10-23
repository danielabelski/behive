# Labelled discovery pools (captured)

Every URL scouted by the live benchmark run `bench-final` (BeHive 51733ea,
2026-10-23, /root/outputs/behive-discovery-2026-10-23/bench-final), labelled once in
batches of 50 by the benchmark's strict model judge (gpt-6.1-sol via the Codex bridge,
same prompt as tools/discovery_benchmark.py; 29 calls; raw batches in
/root/outputs/behive-rank-2026-10-23/pools/). Labels are model judgments on
URL/title/snippet only, not human truth; snippets as stored in hive_sources (<=1024 chars).
`baseline_p30` = simulated harvest top-30 precision with scout scoring at eb38b5a.
