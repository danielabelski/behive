import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const page = readFileSync(new URL('../src/pages/index.astro', import.meta.url), 'utf8');
test('landing identifies the actual 0.6.0 engine', () => {
  assert.match(page, /v0\.6\.0 — Open Source \(MIT\)/);
  assert.doesNotMatch(page, /v0\.4\.0/);
});

test('marketing avoids unsourced results and truth guarantees', () => {
  for (const unsupported of [/CountUp/, /53K|127K|64 APIs|64 API sources|60\+|1000\+/, /Benchmarks|No cherry-picking|Zero hallucination|verified claims/, /500K units|\$35\.1B|CoWoS-L/, /GPT-Researcher|\$29\/mo|\$20\/mo\+/]) {
    assert.equal(unsupported.test(page), false, `Unsupported claim remains: ${unsupported}`);
  }
  assert.match(page, /Schematic example — not a research result/);
  assert.match(page, /not a probability of truth/);
  assert.doesNotMatch(page, /src="\/images\/demo\.gif"/);
});

test('setup documents real CLI, REST, and MCP contracts with prerequisites', () => {
  for (const text of ['pip install behive==0.6.0', 'behive config --quick', 'behive db init', 'behive serve --host 127.0.0.1', 'behive research &quot;your research question&quot; --depth 3 --no-db', 'http://127.0.0.1:8090/mcp', 'http://127.0.0.1:8091/research', 'BEHIVE_DB_URL', 'OPENAI_API_KEY', 'research_topic', 'search_knowledge', 'mission_status', 'get_report', 'list_missions']) {
    assert.ok(page.includes(text), `Missing verified setup contract: ${text}`);
  }
  assert.doesNotMatch(page, /works everywhere|Any client works|Zero config|Three commands|Community Node|ClawHub-ready/);
  assert.match(page, /client-specific/);
  assert.match(page, /JSON-RPC/);
  assert.match(page, /curl[\s\S]*"query"[\s\S]*"depth": 3/);
});

test('REST authentication names the implemented variable, not the stale env example', () => {
  assert.ok(page.includes('BEHIVE_API_KEY'), 'REST auth is configured by BEHIVE_API_KEY');
  assert.ok(!page.includes('BEHIVE_AUTH_TOKEN'));
});

test('MCP setup discloses the API authentication forwarding limitation', () => {
  assert.ok(page.includes('does not forward API credentials'));
  assert.ok(page.includes('research_topic cannot start an authenticated API mission'));
});
