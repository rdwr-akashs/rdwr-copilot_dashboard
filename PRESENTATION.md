# Copilot Token Dashboard

## Where is your Copilot spend actually going?

GitHub bills Copilot in AI credits, and your billing page gives you one number per
month. That number is accurate and completely unactionable. It doesn't tell you which
conversation burned 400 credits, which model you drifted onto, which repository is
expensive, which tool definition you pay to ship on every single request and never
call, or which file got re-read eleven times in one session. You get a total, and no
way to make it smaller.

This dashboard is the missing breakdown. It reads data that is *already on your
disk* — the Copilot CLI's own session store and, optionally, VS Code's Copilot Chat
debug logs — and renders a single self-contained HTML file: cost per chat, per
session, per model, per repository, per tool, per file, plus a set of deterministic
findings telling you what to change. Nothing is uploaded anywhere, and nothing needs
to be enabled to get the CLI half working.

---

## The part that matters: the CLI numbers are not estimates

Most tools in this space multiply a token count by a published rate and call the
result your cost. That is an estimate, and it is wrong in at least four ways at once —
promotional pricing, long-context tiers, cache-write tokens billed at their own rate,
and the 10% auto-model-selection discount are all invisible to it.

This dashboard doesn't do that for CLI usage. When you run `copilot`, the CLI writes
to a local SQLite store at `~/.copilot/session-store.db`, and its
`assistant_usage_events` table records two things that change everything:

- **`total_nano_aiu`** — the exact amount GitHub charged for that individual call,
  in nano AI units. One credit is one AIU is $0.01, so one nano AIU is $1e-11.
- **`token_details_json`** — the per-token-type counts *and the rates GitHub actually
  applied to that call.*

So CLI cost in this dashboard is not computed. It is read, per call, from what GitHub
charged, and summed. Every distortion listed above is already baked into that figure
because GitHub baked it in when they billed you.

**How close is it?** Against a real store of 3,925 model calls, the dashboard totals

```
dashboard:  $183.06943527999996
GitHub:     $183.06943528000002
delta:      -0.000000000000057   (-5.7e-14)
```

That delta is IEEE-754 float noise, not disagreement. It stays that tight because of
one deliberate rule: **costs are always summed per call, never re-derived from
aggregated token counts.** Aggregate first and you lose the per-call rate — which tier
applied, which discount applied — and you can never get it back. Every row in the UI,
from a single session to the all-time total, is a sum of individual charges.

### Every cost figure tells you where it came from

The dashboard resolves cost in strict precedence — `billed`, then `rates`, then
`estimate` — and shows you which one it landed on:

| Badge | Source | Meaning |
| --- | --- | --- |
| `exact` | `billed` | `total_nano_aiu`, GitHub's recorded charge |
| `exact` | `rates` | priced from the rates GitHub applied to that call |
| `partly exact` | `mixed` | some calls in this row fell back to an estimate |
| `estimated` | `estimate` | priced from `model_pricing.py` — no billed figure was recorded (older CLI build) |

`mixed` is the honest case that most tools hide: if you have sessions from an older
CLI build sitting next to current ones, that row is part-exact and says so, with a
count of how many calls came from each source.

### Where it is still an estimate — and why

**VS Code chat is estimated.** Not by choice: VS Code's telemetry exposes no billing
figure at all, so chat has to be priced from the published rate table in
`model_pricing.py` (40 models across 7 providers, including cache-write rates and the
272K/200K long-context tiers). Two things that estimate structurally cannot see are
the 10% auto-model-selection discount — nothing in the telemetry flags a call as
auto-routed — and cache-write tokens, which chat telemetry simply doesn't count. Both
push the same direction, so **chat cost reads as a lower bound.**

That is exactly why the badges exist. You are never left guessing which kind of number
you're looking at, and a rollup that mixes both says `partly exact` rather than
quietly averaging a fact together with a guess.

---

## What you get, tab by tab

### Overview — *am I going to blow the monthly allowance?*

Opens on an AI-credit budget gauge: allowance for your plan, credits used, remaining,
current burn rate, and the projected end-of-month figure, flagged `ok` / `warn` /
`critical` with alerts when the projection overshoots. Below that, a stacked trend
chart splitting Chat from CLI spend over time, a Chat-vs-CLI summary, top-five rollups
by model, by repository, and by developer/host, and a preview of the three
highest-severity recommendations. It is the one screen to look at if you look at
nothing else.

### Chats — *what did that conversation cost, and why was the prompt so big?*

One card per chat session, paginated and searchable by title, model, or ID. Each card
carries its models, the source host, call and tool counts, the full token split
(total / uncached / cached / output) and cost. Expand it and you get a sixteen-cell
session grid — duration, segments, cache-hit rate, peak prompt size, inferred context
boundaries — plus a token-breakdown chart showing how much of the prompt was chat
history versus tool results versus files versus overhead.

Drilling further, `GenAI details` on any model call opens the real thing: the system
prompt, the input messages, the assistant output, the tool definitions that were
shipped, and a context-window breakdown that separates system instructions, tool
definitions, messages, tool results, and reserved space — with each section's share of
the window. This is where "why is this chat expensive" stops being a mystery.

### Analysis — *which model, tool, or file is the expensive one?*

Five subtabs, each exportable to CSV:

**Model usage** — calls, sessions, token split, cache share, average time-to-first-token
and cost per model, listed separately for chat and CLI.

**Tool impact** — two views. *Usage attribution* ranks tools by calls, errors, average
and total duration, tokens and cost. *Unused tool waste* is the one people don't expect:
it measures the tool definitions that were shipped in a prompt and never invoked, with
a waste percentage and the total input tokens you paid to send them. Tool definitions
are pure overhead on every request in a session, so this is often the cheapest win on
the whole dashboard.

**File activity** — reads, edits, token and cost impact per file, with a per-file modal
breaking down which tools touched it. Click-through from any row.

**Monthly trends** — cost, tokens, sessions, or cache-hit rate over months, as a chart
and a table, with CLI columns when CLI data is present.

**Insights** — the recommendation feed (see the next section).

### CLI — *what did GitHub charge me, exactly?*

The exact-cost tab. Summary cards for sessions, model calls, the full token split
*including cache-write* (which the chat side can't see), billed cost with its
provenance badge, AI credits, files touched, and tool calls. Then per-session cards,
a per-model table, usage trends at monthly or daily granularity, per-tool impact, and
a breakdown by repository and branch.

The efficiency section is where the money is: a cache-hit gauge, your most expensive
sessions, the sessions with the *worst* cache-hit rate, and the worst cost per 1K
output tokens — which is a much better "was this worth it?" signal than raw spend.
Finally, an OpenTelemetry status panel that, when you've enabled the export,
reconciles GitHub's own token and spend counters against the database and shows the
delta per token type. If those two ever disagree, you see it rather than trusting one
of them blindly.

### Info — *what are the rates, and where do these numbers come from?*

The full model price table (input, cached, cache-write, output, and long-context tier),
sorted cheapest first; a searchable tool catalog with each tool's description-token
cost and waste percentage; ten concrete tips on model switching, chat length, tool
overhead, cache warming and context files; and a telemetry page stating plainly which
fields are measured directly and which are derived.

---

## What it tells you to fix

The dashboard doesn't stop at showing you numbers. `insights_engine.py` runs ten
deterministic rules over the aggregated data and emits ranked findings — each with a
severity, a confidence level, an estimated saving in dollars and AI credits, an
expandable evidence table, and a specific recommended action:

- **Low cache-hit rate on a high-input session** — you're re-paying full price for
  context that could have been cached.
- **Expensive model used for a small, short session** — a two-turn question answered
  by your priciest model.
- **Same file re-read many times in one session** — billed once per read.
- **Frequent context resets / model switches re-billing the full prompt** — every
  switch rebuilds and re-charges the whole context.
- **Session prompt has grown very large** — every subsequent call in that session pays
  for the bloat.
- **Spend with negligible output and no file edits** — sessions that cost money and
  produced nothing.
- **Standardizing on a cheaper model would cost less this period** — with the actual
  delta for your data, not a generic suggestion.
- **Chat vs CLI cost profile** — where your spend concentrates and what that implies.
- **AI-credit usage projected to exceed the monthly allowance** — with the overshoot.
- **Data-health warnings** — chat logging looks stale or disabled, CLI OTel export is
  off. These matter because a missing data source silently *understates* your usage.

Every finding is deterministic: same data in, same findings out. There is no model in
the loop deciding what to tell you, so nothing here is a hallucination and nothing
changes between two runs on the same input. You can also copy the whole feed as
Markdown, which makes it easy to paste into a team channel or a ticket.

---

## Two numbers, not one: Attributed vs Billed

There's a toggle in the filter bar labelled **Attributed / Billed**, and it's worth
thirty seconds of your attention because it switches what every token figure in the
app means.

**Billed** is the money. Per-call token counters, summed. For CLI sessions these are
GitHub's own recorded figures; for chat they're the observed counters priced from the
rate table. If you want to know what something cost, this is the mode.

**Attributed** answers a different question: *what is filling my context?* It tracks
how the prompt grows between consecutive calls and apportions each increment across
the system prompt, tool definitions, user messages, assistant context, tool results,
and files. That apportionment is a heuristic — it's reconstructed from parsing the
messages, not reported by the API — and its job is diagnosis, not accounting.

So: **Attributed explains, Billed bills.** The dashboard labels which one you're
looking at everywhere it matters, and cost provenance badges are unaffected by the
toggle.

One related caveat, stated up front: Copilot doesn't emit context compaction as a
first-class event, so the dashboard infers context resets from prompt shrinkage and
labels those boundaries as inferred. Totals for a chat remain the sum of all billed
calls across all inferred segments, so the inference never affects a cost figure.

---

## Getting it running

Requirements are Python 3 and `zstd`. Node is only needed to *rebuild* the front end —
`web/dist/` is committed and the Python side never invokes Node, so generating a
dashboard needs no JavaScript toolchain at all.

**CLI data needs nothing enabled.** If you've used `copilot`, `~/.copilot/session-store.db`
already exists and the dashboard opens it read-only. Override the path with `--cli-db`
if yours lives elsewhere.

**Chat data needs logging turned on first**, and VS Code does not backfill — only
chats sent *after* you enable it are captured. See
[Enable Copilot Chat debug logging](README.md#enable-copilot-chat-debug-logging-do-this-first)
in the README; it's one block in `settings.json` plus a window reload.

Then either generate a static file:

```bash
python3 generate_dashboard.py -o dashboard.html
```

That's one self-contained HTML file — no assets, no server, no network calls. You can
email it or drop it in a share.

Or run the live server, which regenerates on each request:

```bash
python3 serve_dashboard.py --host 127.0.0.1 --port 8765
# then open http://127.0.0.1:8765/dashboard.html
```

**Optional, and worth it:** point the CLI's OpenTelemetry file exporter somewhere and
pass it in. This never changes a cost figure — it adds per-tool-call timing and the
independent reconciliation cross-check described above.

```bash
export COPILOT_OTEL_FILE_EXPORTER_PATH="$HOME/.copilot/otel.jsonl"
copilot
# later:
python3 generate_dashboard.py --cli-otel-log ~/.copilot/otel.jsonl
```

Note that setting only `COPILOT_OTEL_ENABLED=true` uses the default OTLP-HTTP
exporter, which posts to `localhost:4318` and silently discards everything if nothing
is listening — so it produces no file to read. Set the file exporter path explicitly.

---

## Things worth knowing

**Nothing leaves your machine.** There is no telemetry, no phone-home, and no analytics
in this tool. The CLI database is opened read-only. The only outbound network code in
the repo is `remote_sync.py`, which uses SSH to *pull* logs from a host you explicitly
configure — opt-in, and inert unless you use it. (The `socket` calls in
`compact_cache.py` look alarming in a grep and aren't: they read the local interface
address and hostname to name cache shards and label which host a session came from.)

**It's safe to share a team dashboard.** `--anonymize` replaces hosts, IPs, usernames
and home-directory paths with stable pseudonyms (`dev-a3f1`) derived via HMAC from a
local-only salt, applied as a final pass before the data reaches the HTML. The rollups
stay meaningful — the same developer is the same pseudonym across the whole
dashboard — while the identities don't ship. The UI shows an `anonymized` badge so
nobody mistakes a pseudonymised view for a real one.

**Multi-host aggregation works.** Point it at several `debug-logs` directories at once
and it merges them, de-duplicating sessions by ID. A per-session parse cache
(fingerprinted on file list, mtimes and sizes) plus a worker pool keeps regeneration
fast as the log volume grows, so a big shared dashboard doesn't get slower to open.

**Some things are honestly estimated, and labelled.** Per-tool and per-file token
attribution is estimated, because Copilot telemetry doesn't expose exact per-tool or
per-file token counts — nobody's does. Sessions with zero completed model calls are
parsed and then intentionally dropped, since they have nothing to show; if the
dashboard looks emptier than you expected, that's usually why (the README's
troubleshooting section covers the rest).

---

## By the numbers

| | |
| --- | --- |
| Python | 9,660 lines across 20 modules |
| Front end | 5,847 lines across 14 ES modules, bundled by esbuild; zero runtime dependencies |
| Charts | hand-rolled SVG — no charting library |
| Pricing table | 40 models across 7 providers, with cache-write rates and long-context tiers |
| Insight rules | 10, fully deterministic |
| Tests | 13 modules, 176 test functions, 187 tests collected |
| Regression safety | golden-output snapshot test, structural-contract test on the data payload, and `npm run audit:ui` — jsdom walks all 18 views and fails on misaligned columns, dead CSS classes, or unbound inline handlers |
| Output | one self-contained HTML file |

For setup detail, remote sync, deployment and troubleshooting, see
[README.md](README.md). For the front-end build and contribution rules, see
[web/README.md](web/README.md).
