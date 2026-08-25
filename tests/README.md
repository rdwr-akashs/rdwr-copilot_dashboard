# Copilot Token Dashboard — test suite

## Install dev dependencies

```powershell
python -m pip install -r requirements-dev.txt
```

## Run the tests

```powershell
python -m pytest -q
```

Run a single module, e.g.:

```powershell
python -m pytest tests\test_cli_usage.py -q
```

## Regenerate the golden baseline

`tests/test_golden.py` renders a full dashboard from the synthetic fixtures
and checks it against `tests/golden/app_data.json` (a strict, byte-for-byte
comparison of the underlying data/arithmetic) plus a structural contract on
the rendered HTML (see the module docstring for why there is no full-HTML
byte hash any more). After an intentional change to `app_data`'s shape or
values, regenerate the golden instead of hand-editing it:

```powershell
$env:COPILOT_DASHBOARD_UPDATE_GOLDEN = "1"
python -m pytest tests\test_golden.py -q
Remove-Item Env:COPILOT_DASHBOARD_UPDATE_GOLDEN
```

Always diff the resulting `tests/golden/app_data.json` change to confirm it
only reflects the intended change before committing it.

## What each fixture simulates (`tests/conftest.py`)

- **`tmp_cache_dir`** — an isolated dashboard cache root. Monkeypatches
  `COPILOT_DASHBOARD_CACHE_DIR` (and pins `COPILOT_DASHBOARD_CACHE_SHARD` to a
  constant) so tests never read/write the real shared cache at
  `~/.copilot-dashboard/cache` or `/mnt/radware/...`, and so session identity
  hashes are deterministic across machines.
- **`fake_cli_db`** — a small SQLite `session-store.db` built with the exact
  schema `cli_usage.py` queries (`sessions`, `assistant_usage_events`,
  `turns`, `session_files`), populated with 3 sessions, usage events across
  2 models, several turns, and several file-touch rows.
- **`fake_otel_jsonl`** — a JSONL OpenTelemetry file-exporter export with a
  handful of `execute_tool` spans (plus a non-span line and a malformed line
  to exercise graceful skipping), joined onto `fake_cli_db` sessions via the
  `gen_ai.conversation.id` attribute.
- **`fake_debug_logs`** — a directory tree mimicking a VS Code Copilot Chat
  debug-log root, with two session directories each containing a
  `main.jsonl` with `user_message` / `llm_request` / `agent_response`
  entries — enough for `build_dashboard_data()` to return sessions with real
  model calls (across two different models).

## Test modules

- `test_model_pricing.py` — `get_pricing()` exact/prefix/substring/fallback
  lookups; `calculate_cost()` maths (cached-vs-uncached split, zero and
  negative edge cases); the all-inclusive prompt partition
  (`split_prompt_tokens()` never returns a negative component, clamps cache
  counts that exceed the prompt instead of billing them on top, and always
  sums back to the prompt) and the cost-impacting diagnostic that clamp
  raises; long-context tier selection from the per-call prompt size.
- `test_chat_cost_attribution.py` — how a chat turn's cost is attributed,
  end to end from a debug log through `compact_cache.parse_session_payload`:
  prompt-growth attribution keeps the long-context tier of the whole call,
  attributed cost never exceeds the same call's billed cost (and never goes
  negative when the prompt shrinks), and ordinary short prompts stay on the
  default tier.
- `test_cli_usage.py` — `build_cli_dashboard_data()` summary counts,
  per-model breakdown, file list, and graceful degradation for a missing DB.
- `test_cli_otel.py` — `parse_cli_otel_files()` tool aggregation and
  per-session join behavior.
- `test_portability.py` — `default_output_path()` / `default_dashboard_cache_root()`
  honour their env-var overrides and never fall back to a hardcoded
  `/tmp/...` or `/mnt/radware/...` path on non-POSIX hosts.
- `test_cli_periods.py` — the `cli["periods"]` block: `monthly` only
  contains calls made in the current calendar month, `allTime` contains all
  sessions, both have coherent `summary`/`byModel`, and monthly totals never
  exceed all-time totals. Also covers a session spanning a month boundary
  (its spend splits across both months, while the session itself counts once
  in each) and the invariant that the per-call `callBuckets` rollups
  re-partition a session's totals without re-pricing them. Uses its own
  SQLite fixture built relative to `datetime.now()` at test time (there is no
  `now` injection point in `cli_usage.py`'s period logic).
- `test_usage_model.py` — `records_from_chat_sessions()` /
  `records_from_cli()` adapters (including the compacted-session fallback
  path, the CLI `attributed == billed` no-op invariant, one unified record
  per `callBuckets` row so a straddling session lands in both months, the
  legacy `modelBreakdown` fallback for payloads without buckets, and
  `uncached` following `inputBillable` so cache-write tokens are not
  double-counted), full
  `build_unified()` aggregation maths (daily/monthly/byModel/byRepo/
  bySource/byHost/totals) against hand-computed expected sums,
  `month_key_ms`/`day_key_ms` format parity with
  `global_calculations.month_key_from_timestamp`, `filter_records()`
  inclusive-boundary behavior, and a dedicated invariant test that
  `unified.totals.billed.cost` equals the independently-summed chat-side +
  CLI-side billed costs (guards against future double-counting).
- `test_premium_requests.py` — `get_multiplier()` resolution tiers,
  `load_config()`'s explicit-arg > JSON-file > env-var > default precedence
  chain, and `build_budget()` maths with a frozen `now_ms` (deterministic
  `daysElapsed`/`burnRatePerDay`/`projectedMonthEnd`), including exact
  `ok`/`warn`/`critical` threshold boundaries and unlimited/`None` allowance
  handling (no division by `None`). Also pins which block the budget spends
  from: a `billed` block worth `$0.00` is a real answer and must not fall
  through to the attributed figure, the attributed block is used only when no
  billed block exists, and the credit unit is the same constant the cost
  layer bills through (`model_pricing.AIU_USD`).
- `test_structural_contract.py` — pins `app_data["unified"]`/`["premium"]`
  top-level key sets and `app_data["insights"]`'s list-of-records shape, and
  — critically — asserts all three survive
  `compact_files.compact_app_data_for_html()` unchanged (that function
  builds an explicit dict literal and silently drops anything not listed;
  this is a regression test for exactly that class of bug).
- `test_insights_engine.py` — lightweight contract coverage for
  `insights_engine.build_insights()` (shape, determinism, sort order,
  never-raises-on-empty-input), plus one cost-correctness rule test: a
  model-substitution hypothetical is priced at the tier implied by the
  average prompt *per call*, so a period's summed tokens cannot promote it to
  long-context rates and halve the saving it reports. Not exhaustive per-rule
  coverage.
- `test_generate_html.py` — `generate_html()` produces a well-formed
  document with no unreplaced `__APP_JSON__`/`__PRICING_JSON__` placeholders
  and no leftover `{{`/`}}` escaping artifacts. Tolerant of the `web/`
  bundling refactor's `var`/`let`/`const` variable declarations.
- `test_golden.py` — end-to-end golden-file baseline: a strict `app_data`
  data/arithmetic comparison plus a churn-tolerant structural contract on
  the rendered HTML (no raw HTML byte-hash any more; see below).
- `test_server_integration.py` — starts the real `serve_dashboard.py`
  `DashboardHandler`/`DashboardCache` on a real `ThreadingHTTPServer` bound
  to an OS-assigned ephemeral port (never a hardcoded port, never 8765).
  Covers `/dashboard.html` (200, `ETag`/`Last-Modified`, `If-None-Match` /
  `If-Modified-Since` → 304), cache hit/miss behavior via `/api/status`
  counters (not timing), `?refresh=1` / `Cache-Control: no-cache` forcing a
  rebuild, `/api/data.json`'s and the embedded `/dashboard.html` `APP_DATA`'s
  documented top-level keys (including `unified`/`premium`/`insights`/
  `anonymized`), `/api/status`'s documented fields (including `appDataKeys`/
  `anonymized`), `/api/session?id=...` (known id → 200, bogus id → 404,
  missing id → 400), `POST` to any route → 404, and unknown paths → 404.
  Also contains `test_live_and_batch_app_data_have_same_top_level_keys`, a
  parity test asserting the live server's `app_data` and
  `dashboard_core.compose_app_data()`'s batch-path output (the shared
  composition seam both paths now call) expose the same top-level key set
  against the same fixtures -- this is what stops the two paths drifting
  apart again the way they briefly did before `compose_app_data()` existed.
- `test_web_assembly.py` — guards the `web/` thin-assembler contract:
  `web/index.html`/`bundle.css`/`bundle.js` exist and are non-empty, both
  bundles are actually inlined with no leftover injection markers, no
  `undefined`/`NaN`/`[object Object]` literals leak into the *static*
  skeleton markup, `web/dist/bundle.js` passes `node --check` when Node is
  available (skipped gracefully otherwise — the Python path never requires
  Node), and — the highest-value test in the suite — every inline
  `onclick`/`onchange`/`oninput`/`onsubmit` handler referenced anywhere in
  the rendered document is either a native/DOM construct or exposed via one
  of the `Object.assign(window, {...})` blocks in the bundled JS (a missing
  entry is a silent dead-button-at-runtime bug with no build error; see
  `web/README.md`).

## Notes

- The suite is hermetic: no network access, and no dependency on a
  developer's real `~/.copilot/session-store.db` or real VS Code debug logs.
  Time-dependent results (`build_budget`, golden `generatedAt`) are computed
  against a frozen/injected `now_ms`, not the live clock.
- `fake_debug_logs` is a hand-written, minimal-but-realistic reproduction of
  the real debug-log JSONL shape (derived by reading
  `per_chat_calculations.parse_session()`), not a captured real log. It
  covers `user_message` / `llm_request` / `agent_response` entries only —
  enough to exercise the full `build_dashboard_data()` pipeline (parsing,
  caching, monthly trends, HTML rendering) — but does not cover every entry
  type the real parser understands (e.g. `tool_call`, sub-agent streams,
  system-prompt/tools-file references). Extending it to cover those is
  straightforward if a future test needs it.
- `insights_engine.py` landed mid-suite (added concurrently by another
  agent). `test_structural_contract.py` tolerates its absence anywhere else
  in the suite; `test_insights_engine.py` provides direct coverage now that
  it exists, but does not exercise every individual `_rule_*` heuristic.
- The `web/` CSS/JS extraction refactor (an esbuild bundle assembled by
  `html_generation.generate_html()` at render time) changed the exact bytes
  of the rendered dashboard HTML without changing `app_data` itself.
  `tests/golden/dashboard.sha256` (a raw full-HTML byte hash) has been
  retired for this reason: three UI agents are now actively and legitimately
  rewriting `web/js/**`/`web/styles/**`, which would make a raw hash churn
  constantly for reasons unrelated to a data regression. `test_golden.py`
  now asserts a structural contract on the HTML instead (see that module's
  docstring), while keeping `tests/golden/app_data.json`'s strict comparison
  as the thing that actually matters for regression protection.
- `test_server_integration.py`'s `dashboard_server` fixture previously issued
  two throwaway warm-up requests before yielding, to settle an intermittent
  (~1-in-3 observed) filesystem-timing race in
  `DashboardCache.compute_fingerprint()`: a fingerprint computed immediately
  after the very first build of a just-created log directory could briefly
  disagree with one computed a moment later on this filesystem, causing an
  unwanted extra rebuild on the *second* real request. `compute_fingerprint()`
  now quantizes all mtimes to whole seconds before hashing, which absorbs
  that sub-second jitter; the warm-up requests were removed after 12
  consecutive full-suite runs showed no recurrence, so this is no longer
  needed.
- `serve_dashboard.py`'s live `/api/data.json` / `/dashboard.html` path used
  to skip `app_data["unified"]` / `app_data["premium"]`, unlike
  `dashboard_core.write_dashboard()`'s static/batch path. This has since
  been fixed via a shared composition seam, `dashboard_core.compose_app_data()`,
  called by both `write_dashboard()` and `serve_dashboard.py`'s
  `_compose_dashboard()`, guaranteeing the two paths produce the same
  top-level `app_data` keys by construction.
  `test_server_integration.py::test_api_data_json_has_documented_top_level_keys`
  now asserts `unified`/`premium`/`insights`/`anonymized` are present
  directly (no more xfail), and
  `test_server_integration.py::test_live_and_batch_app_data_have_same_top_level_keys`
  guards against the two paths drifting apart again in the future.
