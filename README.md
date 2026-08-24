# Copilot Token Dashboard

A self-contained HTML dashboard for exploring GitHub Copilot Chat debug logs.

It parses Copilot debug / OTel session logs and renders a browser UI with:

- one row per chat/session
- source-server IP shown on each chat and searchable in the Chats tab
- expandable timelines showing user messages, tool calls, and model calls
- a `GenAI details` modal with full prompt/input/output context
- a context-window breakdown that separates:
  - system instructions
  - tool definitions
  - messages//
  - tool results
  - other prompt content
- cost per chat, session, model, and file — **exact** for GitHub Copilot CLI usage (taken from what GitHub charged each call), estimated from model pricing for VS Code chat
- analysis views for models, tools, files, insights, and telemetry
- per-file timeline graphs for estimated token / cost impact over time

## What the numbers mean

The dashboard intentionally shows **two different concepts**:

1. **Prompt / context size**
   - `Prompt now`
   - `Δ vs prev`
   - context window usage in the modal
   - these are meant to line up with what Copilot shows in its prompt/context-window view

2. **Billed usage / spend**
  - `Billed input tokens`
  - `Billed uncached input`
  - `Cached-read tokens`
   - `Billed output tokens`
   - `Billed cost`
   - these are per-call costs, summed over the chat/session. For CLI sessions they are GitHub's own recorded charges; for VS Code chat they are API-style estimates from the pricing table. The UI labels which, per row.

That distinction matters because a large prompt shown in Copilot is a **snapshot of the current request**, while billed cost is the **sum of many requests over time**.

The dashboard also infers **internal segments** inside a chat. A new segment starts when the model changes or when the prompt appears to have been rebuilt/reset (for example after compaction or a large context reset). Totals for the full chat remain the sum of all billed calls across all segments.

## Requirements

- Python 3 (Windows: the `python` command; Linux/Mac: `python3`)
- `zstd`
  - Linux (Debian/Ubuntu): `sudo apt install zstd`
  - Mac: `brew install zstd`
  - Windows: `winget install Meta.Zstandard` (or `choco install zstandard`)
- access to GitHub Copilot Chat debug logs

Remote import/sync (server → server over SSH) also requires:

- `paramiko` (`pip install paramiko`)
- SSH key or agent access to the remote host, and its host key already in `known_hosts` (no password auth — see [How remote sync behaves](#how-remote-sync-behaves-md5-based))

## Enable Copilot Chat debug logging (do this first)

The dashboard can only read data that VS Code has actually written. Nothing appears until this is enabled.

1. Open **User Settings (JSON)** — Command Palette → "Preferences: Open User Settings (JSON)", or edit the file directly:
   - Windows: `%APPDATA%\Code\User\settings.json`
   - Mac/Linux: `~/.config/Code/User/settings.json` (`~/Library/Application Support/Code/User/settings.json` on Mac)
2. Add:

```json
"github.copilot.chat.agentDebugLog.fileLogging.enabled": true,
"github.copilot.chat.otel.enabled": true,
"github.copilot.chat.otel.exporterType": "otlp-http",
"github.copilot.chat.otel.otlpEndpoint": "http://localhost:4318",
"github.copilot.chat.otel.captureContent": true
```

   If you're on a remote (SSH/WSL/Codespaces) window, add the same block to your **Remote** settings instead (Command Palette → "Preferences: Open Remote Settings (JSON)"), pointing `otlpEndpoint` at the host that runs the OTel collector (see below), e.g. `http://<dashboard-host-ip>:4318`.
3. **Reload/restart the VS Code window** for the settings to take effect.

> ⚠️ **Only chats that happen *after* this is enabled get logged.** VS Code does not retroactively log past conversations, and a session with 0 logged model calls is silently excluded from the dashboard (see Troubleshooting below). If the dashboard looks empty or incomplete right after setup, that's expected — start a new chat and check again.

### Optional: OTel collector (Aspire Dashboard)

The `otlpEndpoint` setting needs something listening on that port to receive OTel data. A quick local option is the .NET Aspire Dashboard container:

```bash
docker run --rm -d -p 18888:18888 -p 4318:4318 --name aspire-dashboard \
  mcr.microsoft.com/dotnet/aspire-dashboard:latest
```

This isn't required for the `agentDebugLog.fileLogging` output that `copilot-token-dashboard` parses — it's only useful if you separately want to inspect the raw OTel traces yourself (Aspire UI on `http://localhost:18888`).

## Default log discovery

If you do not pass any log directories explicitly, the dashboard auto-discovers logs in the common VS Code / VS Code Server locations under your home directory.

Typical discovered paths look like:

- `~/.vscode-server/data/User/workspaceStorage/*/GitHub.copilot-chat/debug-logs` (Linux/Mac, remote)
- `~/.vscode/data/User/workspaceStorage/*/GitHub.copilot-chat/debug-logs` (Linux/Mac, local)
- `%APPDATA%\Code\User\workspaceStorage\*\GitHub.copilot-chat\debug-logs` (Windows; also checks `Code - Insiders`)

Override discovery at any time with the `COPILOT_DEBUG_LOGS` environment variable, or by passing explicit directories on the command line.

## GitHub Copilot CLI usage

The **CLI** tab is fed by a completely different source from the Chats tab: the local session store that `copilot` writes at `~/.copilot/session-store.db`. Nothing needs enabling — if you have used the CLI, the data is already there. Override the location with `--cli-db /path/to/session-store.db` (or `$COPILOT_CLI_DB`); the file is only ever opened read-only.

That database matters because it records **what GitHub actually charged for each call**, in the `assistant_usage_events` table:

- `total_nano_aiu` — the exact charge for that call, in nano AI units (1 credit = 1 AIU = $0.01)
- `token_details_json` — the per-token-type counts *and the rates GitHub applied*

So CLI costs are not estimates. They are GitHub's own figures, summed per call, and they already include promotional pricing, long-context tiers, and the 10% auto-model-selection discount. Every CLI cost in the UI carries a provenance badge saying which of these it came from:

| Badge | Source | Meaning |
| --- | --- | --- |
| `exact` | `billed` | `total_nano_aiu`, GitHub's recorded charge |
| `exact` | `rates` | priced from the rates GitHub applied to that call |
| `partly exact` | `mixed` | some calls in this row fell back to an estimate |
| `estimated` | `estimate` | priced from `model_pricing.py` — no billed figure was recorded (older CLI build) |

The pricing table in **Reference → Model prices** is therefore only a *fallback* for CLI data, and the primary source for the Chats tab, where VS Code exposes no billing figure at all.

### Optional: capture the CLI's OpenTelemetry export

The CLI can also emit OTel spans (per-tool-call timing) and metrics (token and spend counters). This is optional and never changes a cost figure — it is used for per-tool insight and as an independent cross-check that reconciles GitHub's own counters against the database, surfacing any disagreement in the CLI tab.

Per [GitHub's CLI reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#opentelemetry-monitoring), OTel activates when any of `COPILOT_OTEL_ENABLED=true`, `OTEL_EXPORTER_OTLP_ENDPOINT`, or `COPILOT_OTEL_FILE_EXPORTER_PATH` is set. The dashboard reads the **file exporter** JSONL format, so set that path before running `copilot`:

```bash
export COPILOT_OTEL_FILE_EXPORTER_PATH="$HOME/.copilot/otel.jsonl"
copilot
```

```powershell
$env:COPILOT_OTEL_FILE_EXPORTER_PATH = "$HOME\.copilot\otel.jsonl"
copilot
```

Then point the dashboard at the file (repeatable; defaults to `$COPILOT_OTEL_FILE_EXPORTER_PATH` when set):

```bash
python3 generate_dashboard.py --cli-otel-log ~/.copilot/otel.jsonl
```

Setting only `COPILOT_OTEL_ENABLED=true` uses the default `otlp-http` exporter, which posts to `localhost:4318` and silently discards everything if nothing is listening there — so it produces no file for the dashboard to read.

## Generate a static HTML file

From the project directory:

```bash
python3 generate_dashboard.py
```

Write to a custom location:

```bash
python3 generate_dashboard.py -o /tmp/copilot-dashboard.html
```

Generate from explicit log directories instead of auto-discovery:

```bash
python3 generate_dashboard.py /path/to/debug-logs-a /path/to/debug-logs-b
```

## Run the live server

The server regenerates `dashboard.html` on each request.

Local-only:

```bash
python3 serve_dashboard.py --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765/dashboard.html
```

Bind on all interfaces so another machine can open it directly:

```bash
python3 serve_dashboard.py --host 0.0.0.0 --port 8765
```

Remote sync polling interval can be controlled via CLI:

```bash
python3 serve_dashboard.py --host 127.0.0.1 --port 8765 --remote-poll-seconds 300
```

To only refresh the compact/full cache files on a remote host and skip HTML generation, use cache-only mode:

```bash
python3 serve_dashboard.py --cache-only --cache-shard 10.26.33.35
```

Add `--cache-poll-seconds 300` to keep refreshing the cache in a loop instead of exiting after one pass.

The `remote_start.sh` helper wraps that mode for convenience and defaults to polling every 300 seconds.

You can also import a remote source directly from CLI (startup import + verify + download):

```bash
python3 serve_dashboard.py --remote "10.26.33.35,itayb,/home/itayb/.vscode-server/data/User/workspaceStorage/abc/GitHub.copilot-chat/debug-logs,22"
```

The spec is `IP,USERNAME,PATH[,PORT]` — **no password field.** Authentication is
SSH key/agent only, and the host key must already be known. Set that up once:

```bash
ssh-copy-id itayb@10.26.33.35     # if the key is not installed yet
ssh itayb@10.26.33.35             # accept + record the host key in known_hosts
```

Passwords were removed rather than made optional, for two reasons: anything in
`argv` shows up in shell history and in any process listing on the machine, and
a stored password had to be written to disk for the periodic re-sync to work.
Key auth needs neither. If you pass an old password-bearing spec, the server
rejects it with an explanation instead of misparsing it.

Host keys are verified against `known_hosts` (paramiko `RejectPolicy`). An
unknown host is a hard error, not a first-contact trust — so an impersonating
host fails loudly rather than silently serving you someone else's logs.

## How remote sync behaves (MD5-based)

Remote sources are configured with the `--remote` flag shown above. There is no
in-dashboard import UI — remote sync is CLI-configured only.

Once a source is registered, the server:

- connects over SSH
- verifies login and that the remote path exists and is a directory
- computes a recursive MD5 for the remote folder
- downloads to local cache on first import
- stores the MD5
- periodically recomputes the remote MD5 (see `--remote-poll-seconds`)
- downloads again only if the MD5 changed

Per-source status, last MD5, last check time, and last download time are tracked
in the metadata file described below.

### Where remote metadata/cache is stored

- metadata: `./.remote-sync/sources.json`
- downloaded remote caches: `./.remote-sync/cache/<source-id>/`

You can override this root directory:

```bash
python3 serve_dashboard.py --remote-cache-dir /srv/copilot-remote-sync
```

`sources.json` holds only non-secret connection metadata — host, port, username,
remote path, last MD5 and sync timestamps. No password or key material is
written there. If the file was created by an older build that did store a
password, re-adding the source (`--remote ...`) strips it.

## Share it from another machine

You have a few options.

### Simple LAN access

Run:

```bash
python3 serve_dashboard.py --host 0.0.0.0 --port 8765
```

Then browse to:

```text
http://<server-ip>:8765/dashboard.html
```

### SSH tunnel

If you prefer not to expose the port broadly, tunnel it:

```bash
ssh -L 8765:127.0.0.1:8765 user@server
```

Then browse locally to:

```text
http://127.0.0.1:8765/dashboard.html
```

## Install as a user-level systemd service

A starter unit file already exists in this repo:

- `copilot-token-dashboard.service`

Install it for the current user:

```bash
mkdir -p ~/.config/systemd/user
```

```bash
cp ~/copilot-token-dashboard/copilot-token-dashboard.service ~/.config/systemd/user/
```

```bash
systemctl --user daemon-reload
```

```bash
systemctl --user enable --now copilot-token-dashboard.service
```

Check status:

```bash
systemctl --user status copilot-token-dashboard.service
```

Stop it:

```bash
systemctl --user stop copilot-token-dashboard.service
```

Restart it:

```bash
systemctl --user restart copilot-token-dashboard.service
```

## Keep it running after reboot / logout

For a user service to survive reboots without an active login session, enable linger:

```bash
loginctl enable-linger "$USER"
```

That allows the user-level systemd instance to keep running after logout and start again after boot.

## Change the host / port for the service

The included unit starts:

```text
/usr/bin/python3 /home/itayb/copilot-token-dashboard/serve_dashboard.py --host 127.0.0.1 --port 8765
```

If you want a different host or port, either:

- edit `copilot-token-dashboard.service`, then reload + restart the service
- or create a systemd override with a custom `ExecStart`

After editing the unit:

```bash
systemctl --user daemon-reload
```

```bash
systemctl --user restart copilot-token-dashboard.service
```

## Aggregate logs from multiple servers onto one dashboard host

Yes — the server accepts multiple debug-log directories as positional arguments.

A practical pattern is:

1. copy each machine's Copilot `debug-logs` directory onto one central machine
2. keep them in separate folders
3. point the dashboard at all of them together

Example layout on the central dashboard host:

```text
/srv/copilot-logs/server-a/debug-logs
/srv/copilot-logs/server-b/debug-logs
```

Run the server against both:

```bash
python3 serve_dashboard.py --host 127.0.0.1 --port 8765 /srv/copilot-logs/server-a/debug-logs /srv/copilot-logs/server-b/debug-logs
```

Or generate one merged static HTML file:

```bash
python3 generate_dashboard.py /srv/copilot-logs/server-a/debug-logs /srv/copilot-logs/server-b/debug-logs -o /srv/copilot-dashboard/dashboard.html
```

The parser already de-duplicates sessions by session ID if the same session appears in more than one supplied directory.

## Collecting logs from other machines

Any copy mechanism is fine as long as you preserve the session subdirectories under each `debug-logs` folder.

Common approaches:

- `rsync`
- `scp`
- a shared NFS / SMB mount
- a periodic cron job that mirrors the directories to one server

## Useful files in this repo

- `dashboard_core.py` — parsing, cost estimation, aggregation, and HTML generation
- `cli_usage.py` — Copilot CLI `session-store.db` reader (exact billed costs) and OTel span/metric parsing
- `model_pricing.py` — the published per-model rate table used as the estimation fallback
- `diagnostics.py` — collects parse/cache failures and carries them to the UI, so a dropped session shows up as a warning instead of a quietly lower total
- `generate_dashboard.py` — CLI entrypoint for static HTML generation
- `serve_dashboard.py` — live HTTP server that regenerates the dashboard on request
- `remote_start.sh` — cache-only remote launcher that writes compact/full caches without serving HTML
- `copilot-token-dashboard.service` — starter user-level systemd unit
- `dashboard.html` — generated output

## Notes and limitations

- Tool and file attribution is estimated, because Copilot telemetry does **not** expose exact per-tool or per-file token counts.
- Prompt/context breakdowns are reconstructed from:
  - `inputMessages`
  - referenced system prompt files
  - referenced tool-definition files
- **VS Code chat** cost is estimated using API pricing tables and the observed token counters in the logs. Two things that estimate cannot see: the 10% auto-model-selection discount (nothing in the telemetry flags a call as auto-routed) and cache-write tokens (see below), so cache-heavy chats read as a lower bound.
- **Copilot CLI** cost is not estimated — it is read from what GitHub charged each call in `~/.copilot/session-store.db`, including cache-write tokens billed at their own rate. See "GitHub Copilot CLI usage" above.
- Current Copilot **chat** debug logs expose `inputTokens`, `outputTokens`, and cached-read counters, but they do **not** reliably expose explicit provider cache-write / cache-creation token counts. The CLI session store does record them (`cache_write_tokens`), so this limitation applies to the Chats tab only.
- Compaction is not emitted as a first-class event in the current debug logs. The dashboard therefore infers context resets from prompt shrinkage / prompt rebuild behavior and labels those as inferred segment boundaries.
- `inputTokens` is treated as billed input for each call, and is **all-inclusive**: the cached-read and cache-write counts are subsets of it, not additions to it. So uncached (billable-at-full-rate) input is `inputTokens - cachedTokens - cacheWriteTokens`, where the chat side has no cache-write counter and that term is 0.
- Some file rows may point to Copilot-generated resource files in VS Code workspace storage; that is expected when the model consumed those artifacts as part of the conversation context.

## Quick start

```bash
cd ~/copilot-token-dashboard
```

```bash
python3 serve_dashboard.py --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765/dashboard.html
```

## Troubleshooting

**Dashboard is empty, or shows far fewer sessions than expected.**

- Confirm the settings from [Enable Copilot Chat debug logging](#enable-copilot-chat-debug-logging-do-this-first) are in the right `settings.json` (User, and Remote if applicable) and that you **reloaded the VS Code window** after adding them.
- A workspace-storage folder having a `debug-logs` directory does not mean it has usable data: sessions with **zero completed model calls** (e.g. window opened but no chat sent, or logging enabled mid/after the chat) are parsed but intentionally dropped — they have nothing to show.
- Only chats sent **after** enabling the setting are captured; existing chat history is not retroactively logged.
- To check what's actually on disk for a given session dir, look for `main.jsonl` — a session with real content will contain multiple `llm_request` entries, not just a lone `session_start`.

**`Could not find Copilot debug logs` error.**

- No debug-logs folders were discovered. Set `COPILOT_DEBUG_LOGS` to an explicit path, or pass the directory as a positional argument to `generate_dashboard.py` / `serve_dashboard.py`.

**Remote import fails to connect.**

- Ensure `paramiko` is installed (`pip install paramiko`) and that the remote path exists and is a directory reachable over SSH on the given port.
- `Server ... not found in known_hosts` means the host key has never been recorded. Connect once interactively (`ssh USERNAME@IP`) and accept the key, then retry. This is deliberate: unknown hosts are rejected rather than trusted on first contact.
- `Authentication failed` with no password prompt is expected — remote sync is key/agent only. Confirm `ssh USERNAME@IP` succeeds without typing a password (`ssh-copy-id` installs the key), or that your agent holds the key (`ssh-add -l`).
- `Remote sources no longer take a PASSWORD field` means the `--remote` spec still has the old 4/5-field shape. Drop the password: `IP,USERNAME,PATH[,PORT]`.

**The dashboard shows "Totals on this page may be understated."**

- A cache entry or log file could not be read while building, so whatever it contained is missing from every figure. Open **Info → Telemetry → Data collection problems** for the specific files and reasons.
- `cache.corrupt` / `cache.checksum_mismatch` usually mean a cache file was truncated (interrupted write, full disk). Re-run with `--force-recalculate` to rebuild it from the raw logs.
- On the server, the same list is available as JSON at `/api/status` under `diagnostics` and `diagnosticsSummary`.
- Entries marked `none` (for example `otel.line_skipped`) never affect cost and do not raise the banner.