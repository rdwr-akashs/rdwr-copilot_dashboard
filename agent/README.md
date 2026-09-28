# AI Coding Usage Dashboard — Setup Guide

Sends your **GitHub Copilot** and **Claude Code** usage to the team's shared OpenObserve dashboard,
so you can see what your sessions cost, which models you use, and how you compare with the team.

Setup takes about **10 minutes** and you only do it once.

---

## Before you start

Tick these off first — most setup problems come from one of them.

| # | You need | How to check |
|---|----------|--------------|
| 1 | Windows 10/11 with PowerShell | Open *PowerShell* from the Start menu |
| 2 | Python 3 on your PATH | `python --version` prints `Python 3.x` |
| 3 | Git | `git --version` |
| 4 | Copilot and/or Claude Code already installed and working | You can open a chat |
| 5 | The **`ca.crt`** file | Attached to the setup email |
| 6 | The **OpenObserve password** | Sent to you separately (never in the email) |
| 7 | Your **team name** and **department name** | Ask your lead if unsure; spelling must match your teammates' |

> On macOS or Linux? Skip to [macOS / Linux](#macos--linux).

---

## Setup (Windows)

### Step 1 — Save the certificate

Save the `ca.crt` from the email to a permanent location, for example:

```
C:\Users\<you>\observability\ca.crt
```

Don't leave it in *Downloads* — if it's moved or deleted later, telemetry silently stops.

### Step 2 — Get the code

```powershell
cd C:\
git clone https://github.com/rdwr-akashs/rdwr-copilot_dashboard.git
cd rdwr-copilot_dashboard\agent
```

Keep this folder. The background job that uploads your history runs from it.

### Step 3 — Run the setup script

In a **normal** PowerShell window (not "Run as administrator"):

```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 -Mode REMOTE
```

It asks three questions:

**1. `OTEL resource attributes`** — who you are. Type one line in exactly this shape:

```
team.name=<team>,department.name=<department>,user=<YourName>,org=RDWR
```

Example:

```
team.name=washim_scrum,department.name=AMS,user=AkashS,org=RDWR
```

- No spaces anywhere.
- Use the **same spelling as your teammates** — the dashboard's Team and Department filters list
  whatever they find, so `AMS` and `ams` become two different departments.
- `user` is the name you'll pick in the dashboard's *Developer* filter.

**2. `Path to OTEL exporter certificate (ca.crt)`** — the full path from Step 1, e.g.
`C:\Users\<you>\observability\ca.crt`

**3. `OpenObserve password`** — the password you were sent. Nothing is shown as you type; that's
expected.

When it finishes you'll see messages confirming the environment variables, the Claude Code settings,
and the scheduled task.

### Step 4 — Restart your tools

The new settings are only picked up by programs started **after** setup:

1. Close **every** PowerShell / terminal window.
2. Fully quit and reopen **VS Code** (File → Exit, not just closing the window).
3. Quit and restart **Claude Code**.
4. **IntelliJ users:** IntelliJ's Copilot plugin is not configured by the script. Go to
   *Settings → GitHub Copilot → Chat*, turn on **OpenTelemetry support**, and set the endpoint to
   `https://34.14.177.44:8080`.

That's it. Use Copilot / Claude Code normally from now on.

---

## Check that it worked

1. Open a new chat in Copilot or Claude Code and send one prompt.
2. Wait about 5 minutes.
3. Open **https://34.14.177.44/web/** and log in with the username `admin@localhost.dev` and the
   password you were sent. Your browser will warn about the certificate; that's expected for this
   server.
4. Open **Dashboards** and choose:
   - **Claude Code Productivity (CLI)** — Claude Code usage
   - **Copilot Code Team Productivity** — Copilot usage
5. In the **Developer** filter at the top, pick **your** `user` name. The default shows everyone.

Don't see yourself after 10 minutes? Go to [Troubleshooting](#troubleshooting).

---

## What gets collected

| Collected | Details |
|-----------|---------|
| Usage | Session start/end, number of prompts, model calls, tool calls, errors |
| Cost and tokens | Tokens per call and estimated cost (list-price estimate, not a bill) |
| Environment | Tool version, VS Code / terminal, model used |
| Identity | The `team.name`, `department.name` and `user` you typed in Step 3 |
| **Prompt and reply text** | **Yes** — this setup turns on content capture for both Copilot and Claude Code |

Everyone with dashboard access can see this data. Don't paste secrets, customer data or credentials
into Copilot or Claude Code prompts.

On Windows, a background scheduled task named `CopilotDashboardOpenObserve` runs at logon and every
6 hours. It uploads your local Copilot CLI history and Claude Code usage summaries so the dashboard
also covers sessions from before the live telemetry started.

---

## Troubleshooting

**Nothing shows up in the dashboard**

1. Check the Developer filter is set to your name, and the time range (top right) covers today.
2. Make sure you restarted your tools **after** setup (Step 4). This is the most common cause.
3. In a **new** PowerShell window, check the environment variables are set:
   ```powershell
   Get-ChildItem Env: | Where-Object Name -match 'OTEL|COPILOT'
   ```
   You should see about 10 variables, including
   `OTEL_EXPORTER_OTLP_ENDPOINT = https://34.14.177.44:8080`.
4. For Claude Code, confirm the settings were written:
   ```powershell
   Select-String -Path "$env:USERPROFILE\.claude\settings.json" -Pattern '34.14.177.44'
   ```
5. Check the certificate still exists at the path you gave:
   ```powershell
   Test-Path $env:OTEL_EXPORTER_OTLP_CERTIFICATE
   ```
   `False` means it was moved or deleted — put it back, or re-run Step 3 with the new path.

**`python was not found on PATH`**

Install Python 3 from python.org and tick **"Add python.exe to PATH"** during install, then re-run
Step 3.

**`running scripts is disabled on this system`**

Run the command exactly as written in Step 3, including `-ExecutionPolicy Bypass`. It only affects
that one run; your system policy isn't changed.

**Wrong team, name or password**

Re-run Step 3 with the right values. Running it again is safe: it overwrites its own settings and
keeps everything else in `~/.claude/settings.json`.

**Check that the background job ran**

```powershell
Get-ScheduledTaskInfo -TaskName CopilotDashboardOpenObserve
Start-ScheduledTask   -TaskName CopilotDashboardOpenObserve   # run it now
```

A `LastTaskResult` of `0` means it succeeded.

**Still stuck?** Contact AkashS and include the output of the commands above.

---

## macOS / Linux

You need `python3` and Git. Save `ca.crt` somewhere permanent (e.g. `~/observability/ca.crt`), then:

```bash
git clone https://github.com/rdwr-akashs/rdwr-copilot_dashboard.git
cd rdwr-copilot_dashboard/agent
chmod +x setup-copilot-otel-env.sh
./setup-copilot-otel-env.sh remote
```

It asks the same three questions as Windows [Step 3](#step-3--run-the-setup-script) and sets up both
Copilot (in `~/.zshrc` or `~/.bash_profile`) and Claude Code (in `~/.claude/settings.json`).

Then open a new terminal, restart VS Code and Claude Code, and follow
[Check that it worked](#check-that-it-worked).

The background history upload is Windows-only; live usage is still sent from macOS/Linux.

---

## Uninstall

From the `agent` folder:

```powershell
# Remove the background task
.\install-openobserve-agent.ps1 -Uninstall

# Remove the environment variables
'OPENOBSERVE_INSECURE_TLS','OTEL_RESOURCE_ATTRIBUTES','OTEL_SERVICE_NAME',
'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT','OTEL_EXPORTER_OTLP_PROTOCOL',
'OTEL_EXPORTER_OTLP_ENDPOINT','OTEL_EXPORTER_OTLP_CERTIFICATE','COPILOT_OTEL_EXPORTER_TYPES',
'COPILOT_OTEL_ENABLED','COPILOT_OTEL_CAPTURE_CONTENT' |
  ForEach-Object { [Environment]::SetEnvironmentVariable($_, $null, 'User') }
```

For Claude Code, delete the `OTEL_*`, `CLAUDE_CODE_ENABLE_TELEMETRY`,
`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA` and `NODE_EXTRA_CA_CERTS` keys from the `"env"` object in
`~/.claude/settings.json`. Then restart your tools.

---

## Advanced options

You don't need anything in this section for a normal setup.

### Run against a local Docker stack instead of the shared server

For people developing the dashboards. Start the stack from the `observability` repo
(`docker compose up -d`), then run the script without `-Mode` (it defaults to `LOCAL`):

```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1
```

LOCAL mode skips the certificate question. The password is `OpenObserve1!` and the UI is at
http://localhost:5080. To switch back, re-run with `-Mode REMOTE`.

| | LOCAL | REMOTE |
|---|---|---|
| Dashboard UI | http://localhost:5080 | https://34.14.177.44/web/ |
| Copilot telemetry | http://localhost:4318 | https://34.14.177.44:8080 |
| Claude Code telemetry | http://localhost:4418 | https://34.14.177.44:8080 |
| Certificate | not needed | `ca.crt` required |

### Chronicle advice (opt-in, costs money)

Adds `-ChronicleAdvice` so the background task also asks Copilot for periodic standup notes and
tips and stores them on the dashboard. **Each capture makes billed model calls**, so it's off by
default.

```powershell
powershell -ExecutionPolicy Bypass -File .\Setup-CopilotOtelAgent.ps1 -Mode REMOTE `
  -ChronicleAdvice -ChronicleAdviceIntervalDays 7 -ChronicleAdviceCommands standup
```

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `-ChronicleAdvice` | off | Turn advice capture on |
| `-ChronicleAdviceIntervalDays` | `7` | Days between captures |
| `-ChronicleAdviceCommands` | all | Any of `standup`, `tips`, `cost-tips`, `improve` |
| `-ChronicleAdviceNoSummary` | off | Skip the summary step (fewer model calls) |

### What the script changes

1. **User environment variables** for Copilot (the list in [Uninstall](#uninstall)).
2. **`~/.claude/settings.json`** for Claude Code: adds telemetry keys under `"env"`, including an
   auth header built from your password. Other settings are kept.
3. **Scheduled task** `CopilotDashboardOpenObserve` (Windows only): runs at logon and every 6 hours.

Re-running the script is always safe. It overwrites its own values and nothing else.
