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
  - messages
  - tool results
  - other prompt content
- API-style cost estimation using model pricing
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
   - these are API-style cost estimates per call, summed over the chat/session

That distinction matters because a large prompt shown in Copilot is a **snapshot of the current request**, while billed cost is the **sum of many requests over time**.

The dashboard also infers **internal segments** inside a chat. A new segment starts when the model changes or when the prompt appears to have been rebuilt/reset (for example after compaction or a large context reset). Totals for the full chat remain the sum of all billed calls across all segments.

## Requirements

- Python 3
- zstd
- access to GitHub Copilot Chat debug logs

Remote import/sync (server → server over SSH) also requires:

- `paramiko` (`pip install paramiko`)

## Default log discovery

If you do not pass any log directories explicitly, the dashboard auto-discovers logs in the common VS Code / VS Code Server locations under your home directory.

Typical discovered paths look like:

- `~/.vscode-server/data/User/workspaceStorage/*/GitHub.copilot-chat/debug-logs`
- `~/.vscode/data/User/workspaceStorage/*/GitHub.copilot-chat/debug-logs`

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
python3 serve_dashboard.py --remote "10.26.33.35,itayb,myPassword,/home/itayb/.vscode-server/data/User/workspaceStorage/abc/GitHub.copilot-chat/debug-logs,22"
```

> ⚠️ CLI password warning: values passed in command arguments can appear in shell history and process listings.

## Import remote logs from the dashboard UI (MD5-based sync)

When running `serve_dashboard.py`, the dashboard header now includes **Import remote logs**.

1. Click **Import remote logs**.
2. Enter:
  - IP/host
  - username
  - password
  - remote debug-log path
  - optional SSH port (default `22`)
3. Submit.

Server behavior:

- connects over SSH
- verifies login and that the remote path exists and is a directory
- computes a recursive MD5 for the remote folder
- downloads to local cache on first import
- stores the MD5
- periodically recomputes remote MD5
- downloads again only if MD5 changed

The modal also shows per-source status, last MD5, last check time, and last download time.

### Where remote metadata/cache is stored

- metadata: `./.remote-sync/sources.json`
- downloaded remote caches: `./.remote-sync/cache/<source-id>/`

You can override this root directory:

```bash
python3 serve_dashboard.py --remote-cache-dir /srv/copilot-remote-sync
```

> ⚠️ Security note: remote credentials are stored locally in `sources.json` so periodic sync can reconnect.
> Restrict file access to trusted operators and host accounts.

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
- Cost is estimated using API pricing tables and the observed token counters in the logs.
- Current Copilot debug logs expose `inputTokens`, `outputTokens`, and cached-read counters, but they do **not** reliably expose explicit provider cache-write / cache-creation token counts.
- Compaction is not emitted as a first-class event in the current debug logs. The dashboard therefore infers context resets from prompt shrinkage / prompt rebuild behavior and labels those as inferred segment boundaries.
- `inputTokens` is treated as billed input for each call. `cachedTokens` is treated as the cached-read subset of that billed input, and `uncached input = inputTokens - cachedTokens`.
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

to install:
docker run --rm -d -p 18888:18888 -p 4318:18890 --name aspire-dashboard \
  mcr.microsoft.com/dotnet/aspire-dashboard:latest


in the settings -> users
open the settings as json and add this:
    "github.copilot.chat.agentDebugLog.fileLogging.enabled": true,
    "github.copilot.chat.otel.enabled": true,
    "github.copilot.chat.otel.exporterType": "otlp-http",
    "github.copilot.chat.otel.otlpEndpoint": "http://RDE_IP:4318",
    "github.copilot.chat.otel.captureContent": true
 
in settings -> Remote add the settings in json and add this:
{
    "github.copilot.chat.otel.enabled": true,
    "github.copilot.chat.otel.exporterType": "otlp-http",
    "github.copilot.chat.otel.otlpEndpoint": "http://localhost:4318",
    "github.copilot.chat.otel.captureContent": true
}
 
in the source folder of the project run:
python3 serve_dashboard.py --host 127.0.0.1 --port 8765

in windows browser run this url:
http://localhost:8765/dashboard.html