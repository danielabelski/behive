# Landing verification

All commands run from `/root/behive-landing`. No deployment, commit, or push is part of this workflow.

```sh
npm ci
npm test
npm run build
npm run preview -- --host 127.0.0.1 --port 4330
# In another terminal (requires installed Python Playwright + Chromium):
BEHIVE_LANDING_URL=http://127.0.0.1:4330 npm run test:browser
# If HOME hides an existing browser cache, supply PLAYWRIGHT_BROWSERS_PATH.

# Optional read-only proof against a local engine checkout and its environment:
PYTHONDONTWRITEBYTECODE=1 /root/behive/.venv/bin/python tests/engine_contract_check.py
```

`content.test.mjs` gates version, unsupported marketing, setup contracts, and authentication caveats without dependencies. `browser_check.py` is explicitly opt-in: it exercises the **built static page** on desktop (1440×900), mobile (390×844), and narrow mobile (320×740). It checks rendered word spacing, hero bounds, real clipboard copy and feedback, navigation, mobile menu state/Escape/inert/background size, scroll-to-top, source-related copy, images, anchors, and page/console errors. Screenshots and machine-readable results are written to `artifacts/`. External resources are blocked with empty responses; remote Google Fonts use the system monospace/sans fallback. It does not call the engine or fake research output.

`engine_contract_check.py` reads package metadata, exercises actual CLI version/help, calls actual MCP initialize/tools/list through ASGI, inspects actual REST OpenAPI/request validation, and exercises implemented REST authentication. It avoids app startup, DB connections, research missions, and model/search-provider calls. Engine imports require its environment; set `BEHIVE_ENGINE_ROOT` to change the checkout path.

Red logs in `artifacts/red-*.log` record failures **before** their respective source fixes: stale version, unsupported marketing, missing setup, wrong auth variable, missing MCP auth caveat, absent mobile menu state, clipped mobile hero, undersized mobile menu backdrop, and collapsed inline word spacing.

## Scope limits

- No paid/live research, production DB, full PostgreSQL provisioning, Docker startup, fresh Python package installation, third-party desktop-client compatibility, or external link availability is claimed by this suite.
- The source supports CLI `--no-db`; this suite checks its real CLI contract, not successful full-pipeline DuckDB execution.
- Quality scores are heuristics, not verified truth. The terminal and comparison are explicitly schematic.
- API/MCP installation instructions match the 0.6.0 package source. The MCP bridge does not enforce or forward the REST API key; keep it private and use authenticated REST for protected research starts.
- Registered API adapters are not all runnable without provider credentials; the landing intentionally makes no fixed active-source count claim.
- `npm ci` and `npm run build` regenerate tracked `node_modules`/`dist` files. Do not stage those directories blindly. Source review scope is `src/pages/index.astro`, `package.json`, and `tests/`.
- The existing lockfile audit reports 7 vulnerable packages (6 high, 1 critical), including Astro's AVIF optimization advisory. No automatic dependency upgrade was applied. See `artifacts/npm-audit.json`; the page is built as static output, but that does not establish universal non-exploitability of the build dependencies.
