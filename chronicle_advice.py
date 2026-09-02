#!/usr/bin/env python3
"""Capture the prose that `/chronicle` writes and put it on the dashboard.

    python chronicle_advice.py --dry-run       # print the command, send nothing, spend nothing
    python chronicle_advice.py                 # run the default subcommands, ingest the text
    python chronicle_advice.py --command tips  # just one

Ported from the `observability` repo's `scripts/chronicle-advice.py`. Only the
ingest path differs: rows go out through `openobserve_export.send_events` with this
repository's `OPENOBSERVE_USER` / `OPENOBSERVE_PASSWORD` pair.

WHY THIS IS A SEPARATE SCRIPT
-----------------------------
chronicle_export.py reads numbers out of a SQLite file: free, instant, and repeatable. This does
something different in kind -- it asks Copilot a question and stores the answer -- because four of
the six `/chronicle` subcommands produce no data at all. `standup`, `tips`, `cost-tips` and `improve`
are a model reading your history and writing about it, and there is no table behind them to query.
The only way to get that onto a dashboard is to run the command and keep what it says.

EVERY RUN COSTS CREDITS
-----------------------
Each subcommand is a billed model call, and by default each one is followed by a second, much smaller
call that summarises the answer -- see SUMMARISING, below. Both are charged to your account,
chronicle records them like any other call, and the next export therefore puts them on the very
panels this script feeds. So the spend numbers include the cost of measuring them. That is small at a
weekly cadence and it is not zero, and it is the reason this is opt-in and scheduled rather than
something the dashboard does on refresh. Four subcommands is eight calls, and one run of all four
took about five minutes of wall clock. `--no-summary` halves the calls and leaves the panels showing
the long form.

SUMMARISING, AND WHY IT CANNOT BE DONE IN SQL
---------------------------------------------
Chronicle answers at length: a few hundred words of markdown, several paragraphs per subcommand. A
dashboard table cell is one line. The query can shorten that mechanically -- lift the bold headline
out of each bullet, keep one sentence, cut at 200 characters -- and mechanical shortening is exactly
as good as the prose's own structure and no better. It cannot tell you what a paragraph *said*.

So the summary is asked for rather than computed: a second prompt in a fresh session, handing the
captured report back with an instruction to compress it to at most five one-line findings. That text
goes into `advice_summary` and the panels read it in preference to `advice_text`, which stays in the
row untouched and is what the fallback renders for any row captured before this existed.

The reply is trimmed in Python rather than trusted: bullets and numbering stripped, preamble and
anything under 15 characters dropped, five lines kept, each cut to 160 characters. A model asked for
five lines will sometimes write six and a sentence of introduction, and a panel is not the place to
find that out.

Handing the report back to the model is not a new disclosure -- the same model wrote it a minute
earlier in the same account -- but it is a second call over the same content, so `--no-summary` is
there for anyone who would rather it not happen at all.

WHICH SUBCOMMANDS, AND WHY NOT THE OTHER TWO
--------------------------------------------
The CLI registers six. Four of them answer a question in prose and are captured by default:

    standup     a report on recent work        -- takes an optional period, e.g. "standup last 7 days"
    tips        workflow tips from usage
    cost-tips   where the tokens are going
    improve     suggested edits to copilot-instructions.md

`improve` is included even though its subject is a file, because with no tool grant it cannot *write*
one: an edit raises a permission request, and this client cancels every one it receives. Reading is a
different matter and is not gated -- see TOOL PERMISSION below. So what comes back is the proposed
text, which is the useful part and the part a dashboard can show. Read a captured sample before
acting on it -- nothing here applies it for you.

Two are not captured:

* `search` needs a keyword to search *for*, and there is no standing one worth scheduling. Pass it
  explicitly when you want it: `--command "search openobserve"`.
* `reindex` rebuilds chronicle's own index. It is maintenance, not an answer, and it produces no
  prose to store. Run it by hand after a big import.

WHY THIS SPEAKS A PROTOCOL INSTEAD OF PASSING `--prompt`
--------------------------------------------------------
`-p/--prompt` is the obvious way to run one thing and read the answer, and it cannot run this. It
sends its argument to the model as text; it does not dispatch slash commands. Asking it for
`/chronicle tips` therefore bills a call and returns the model's reaction to the literal string --
the first attempt here stored "Which task? No req given. What u need - bug fix, feature design,
jira link, doc, review?", which is a chat reply, not chronicle output. Nothing failed, the exit
code was 0, and the row looked plausible until it was read.

`/chronicle` is a runtime command belonging to the session, not a prompt template that could be
copied out and sent as text: the handler ends at `session.commands.invoke({name, input})`, so it
needs a live session to invoke against. Two surfaces have one -- the interactive TUI, and the Agent
Client Protocol server behind `--acp`. ACP is the automatable one, so this script is a small ACP
client: it starts the CLI as a server, opens a session, and sends `/chronicle <request>` as a
prompt. ACP's prompt handler recognises the leading slash, resolves `chronicle` as a builtin, and
invokes it, streaming the answer back as `agent_message_chunk` notifications. Those are what gets
stored.

`--headless` is not the flag either, though it reads like it. It is a hidden alias for `--server`
("Enable headless JSON-RPC server mode") and it does not honour `--prompt` -- the same check rejects
`--attachment` as "not honored by --server, --headless, --acp". An earlier version of this script
passed it and would have sat there until the timeout.

TOOL PERMISSION, DELIBERATELY NARROW
------------------------------------
The CLI is invoked with no tool grant at all -- not `--allow-all-tools`. An unattended job with a
blanket grant can do anything the agent decides to do, and reading your own history should need
nothing.

Being the client rather than a bystander makes that enforceable rather than hopeful. Every
`session/request_permission` this client receives is answered "cancelled", and the file and terminal
methods an ACP client can offer are declined at the handshake and answered "not implemented" if
asked anyway. Anything refused is reported at the end of the run rather than swallowed, so a thin
answer names its cause. If some command genuinely needs one tool, add that one tool; do not reach
for the blanket flag.

That stops writes, not reads. The agent's own read-only tools need no confirmation, so nothing is
asked of this client before they run -- the first real `improve` capture opened a repository's
README without a single permission request, and said so in its answer. So `improve` cannot edit
copilot-instructions.md, because writing would raise a request and the request is cancelled, and it
can certainly read the working directory it was given. `--cwd` is therefore the control that matters
for reads: the session is opened in this repository, and pointing it somewhere with nothing to read
is what narrows that further.

WHAT ENDS UP IN THE STREAM, READ THIS ONCE
------------------------------------------
`advice_text` is prose written about your history, and the first real capture shows what that means
concretely: it named projects, quoted session ids, gave a session's title, counted how many times
raw logs were pasted into a prompt, and recommended things based on all of it. It is not a copy of
your prompts -- chronicle_export.py still never reads those -- but it is a description of them,
and a description can carry the part that mattered. On a shared OpenObserve instance that is a
disclosure decision and not a formatting one, so read a captured row before scheduling this.

WHAT LANDS IN THE STREAM
------------------------
One row per run per subcommand in `copilot_chronicle_advice`: the text, how long it took, the exit
code, and `service_user` so the Developer filter reaches it. Two columns name the command, because
they are not the same thing -- `chronicle_command` is the bare subcommand and is what the panel keys
on to show the latest of each, while `chronicle_request` is the whole thing that was asked,
arguments included. Without the split, "standup last 7 days" and "standup last month" would be two
unrelated rows and neither would ever supersede the other.

Unlike the insights events this repository's dashboard exports, these rows are **not** fingerprint
deduped: every run is a new observation about a moving history, and two runs a week apart are meant
to both be there. The panels show the latest row per `chronicle_command`, so an older capture is
superseded rather than removed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from chronicle_export import ADVICE_STREAM as STREAM
from chronicle_export import default_user, endpoint_for, stream_url_overrides
from openobserve_export import send_events

# The order a person would read them in: what happened, then how to work better, then what it costs,
# then what to change. Not the order they cost money in -- they are all one call each.
DEFAULT_COMMANDS = ("standup", "tips", "cost-tips", "improve")
TIMEOUT_SECONDS = 300
# Written at the model rather than at a person: no greeting, no markdown, no closing offer to help.
# "One line each" is said twice because the first phrasing alone produced paragraphs with newlines in
# them, which is indistinguishable from five findings once the panel splits on newline.
SUMMARY_INSTRUCTION = (
    "Summarise the report below for a dashboard table. Rules: at most five lines; one finding per "
    "line; each line a complete sentence under 160 characters, on one line, starting with the thing "
    "to change; no markdown, no bullets, no numbering, no heading, no preamble and no closing "
    "remark; keep the concrete figures and session ids that make a finding checkable; if the report "
    "says there is nothing to report, say that in one line."
)
MAX_SUMMARY_LINES = 5
MAX_SUMMARY_CHARS = 160
# Version the CLI's own ACP server announces and accepts. Sending a different number is not a
# negotiation this client can win, so it is pinned here and will fail loudly if a CLI update moves.
ACP_PROTOCOL = 1


def resolve_cli(explicit: str | None) -> list:
    """Work out how to start the CLI, preferring whatever the caller named.

    The npm-installed `copilot` shim is not reliable here: on Windows the PowerShell wrapper can
    fail with `Cannot bind argument to parameter 'Path'` before the CLI is ever reached. The real
    program is a plain Node entry point under ~/.copilot/pkg, and it self-updates into a new version
    directory without removing the old ones -- six of them on this machine -- so the right one has to
    be picked.

    Picked by version number, not by modification time. Sorting on mtime chose 0.0.419 over 1.0.82,
    because an old directory gets touched by whatever housekeeping the updater does. The `tmp`
    staging directory is skipped for the same reason: it holds a half-installed copy.
    """
    if explicit:
        return explicit.split() if " " in explicit else [explicit]
    if os.environ.get("COPILOT_CLI"):
        return os.environ["COPILOT_CLI"].split()

    def version_key(entry: Path) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", entry.parent.name))

    candidates = [p for p in (Path.home() / ".copilot" / "pkg").glob("*/*/index.js")
                  if p.parent.parent.name != "tmp"]
    if candidates:
        return ["node", str(max(candidates, key=version_key))]
    return ["copilot"]  # last resort: whatever is on PATH


def argv_for(cli: list) -> list:
    """The exact command line. Separate from run_prompt so --dry-run prints what would really run.

    `--stdio` is passed explicitly even though this is the transport ACP would most likely pick on
    its own. The alternative is TCP, chosen by `--port`, and the branch taken with neither flag set
    is not one worth discovering in an unattended job.
    """
    return cli + ["--acp", "--stdio", "--no-color", "--log-level", "error"]


class AcpError(RuntimeError):
    """The CLI's ACP server said no, stopped talking, or never got to an answer."""


class AcpClient:
    """Enough of the Agent Client Protocol to invoke one slash command and keep what it says.

    The protocol is JSON-RPC 2.0 over the process's stdin and stdout, one compact JSON object per
    line -- no Content-Length headers, unlike the `--server` mode next door in the same binary.
    Three kinds of message arrive on the same pipe and each needs different treatment:

        responses       matched to a request by id, and the only thing request() waits for
        requests        the agent asking *this* client for something; every one is refused
        notifications   `session/update`, which is where the answer actually arrives

    The answer being a notification stream rather than a return value is the whole reason this is a
    client and not a subprocess call. Chronicle's output is streamed as `agent_message_chunk`
    updates while the prompt is still outstanding, and `session/prompt` finally returns only a stop
    reason. Read the chunks or you get nothing.

    stdout is drained by one thread and stderr by another, because both are pipes with a fixed
    buffer: a run long enough to fill the log pipe would deadlock while this side waited on the
    other. Both are decoded as UTF-8 explicitly rather than by the platform default -- reading the
    CLI's em dashes through cp1252 is how the first captured row came out as mojibake.
    """

    def __init__(self, argv: list, cwd: str):
        self.process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.inbox: queue.Queue = queue.Queue()
        self.chunks: list = []
        self.after_notice = False
        self.refused: list = []
        self.log: list = []
        self.next_id = 0
        for target in (self._read_stdout, self._read_stderr):
            threading.Thread(target=target, daemon=True).start()

    def _note(self, line: str) -> None:
        self.log.append(line)
        del self.log[:-20]  # only the tail is ever quoted, and a long run can produce a lot

    def _read_stdout(self) -> None:
        for raw in self.process.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                self.inbox.put(json.loads(line))
            except ValueError:
                # Anything unparseable on this pipe is a log line written to the wrong stream.
                self._note("stdout: %s" % line[:200])
        self.inbox.put(None)  # end of stream, so a waiting request() stops waiting

    def _read_stderr(self) -> None:
        for raw in self.process.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self._note("stderr: %s" % line[:200])

    def _send(self, message: dict) -> None:
        self.process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def request(self, method: str, params: dict, deadline: float):
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        return self._pump(self.next_id, method, deadline)

    def _pump(self, wait_for: int, method: str, deadline: float):
        """Handle everything that arrives until the response to `wait_for` does."""
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise AcpError("timed out after %ds waiting for %s" % (TIMEOUT_SECONDS, method))
            try:
                message = self.inbox.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if message is None:
                raise AcpError("the CLI stopped talking during %s%s" % (method, self.tail()))
            if "method" not in message:
                if message.get("id") != wait_for:
                    continue  # a response to something abandoned by an earlier timeout
                if "error" in message:
                    error = message["error"] or {}
                    raise AcpError("%s failed: %s (code %s)"
                                   % (method, error.get("message"), error.get("code")))
                return message.get("result")
            if "id" in message:
                self._refuse(message)
            elif message["method"] == "session/update":
                self._collect(message.get("params") or {})

    def _refuse(self, message: dict) -> None:
        """Say no to everything the agent asks for, and remember that it asked.

        A permission request is answered rather than errored, because "cancelled" is a legitimate
        ACP outcome the agent knows how to carry on from -- it declines the one tool call instead of
        failing the whole turn, which is what should happen when `improve` reaches for a file. Every
        other method is refused as unimplemented, which is honest: this client told the agent at the
        handshake that it has no filesystem and no terminal.
        """
        method = message.get("method")
        self.refused.append(method)
        if method == "session/request_permission":
            self._send({"jsonrpc": "2.0", "id": message["id"],
                        "result": {"outcome": {"outcome": "cancelled"}}})
            return
        self._send({"jsonrpc": "2.0", "id": message["id"],
                    "error": {"code": -32601,
                              "message": "%s is not available to this agent" % method}})

    def _collect(self, params: dict) -> None:
        """Keep the assistant's prose. Not its thinking, and not its tool traffic.

        Chunks are deltas of one message and are joined with nothing between them, which is right
        until a message ends. Nothing in the stream says where that happened -- the update that
        would, `assistant.message_start`, is mapped to no notification at all. The one boundary that
        can be recognised is a status line: `session.info` and `session.error` are turned into single
        chunks prefixed "Info: " and "Error: ", so a chunk starting that way is a message of its own,
        and so is whatever follows it. Joined blind they run together, which is how a capture came
        back reading "...40 recent sessions**Ranked recommendations".
        """
        update = params.get("update") or {}
        if update.get("sessionUpdate") != "agent_message_chunk":
            return
        content = update.get("content") or {}
        if content.get("type") != "text" or not content.get("text"):
            return
        text = content["text"]
        notice = text.startswith(("Info: ", "Error: "))
        if self.chunks and (notice or self.after_notice):
            self.chunks.append("\n")
        self.after_notice = notice
        self.chunks.append(text)

    def tail(self) -> str:
        return ("\n  " + "\n  ".join(self.log)) if self.log else ""

    def close(self) -> None:
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                pipe.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()


def run_prompt(cli: list, prompt: str, cwd: str) -> tuple:
    """Send one prompt over ACP and keep the prose. Returns (text, exit_code, duration_ms, refused).

    A fresh session per prompt, deliberately. Reusing one would leave each answer in the context of
    the last, so `cost-tips` would be replying to `standup` as much as to the history -- and the
    summary pass would be answering with the whole conversation in view rather than the one report it
    was handed.
    """
    started = time.time()
    deadline = started + TIMEOUT_SECONDS
    client = None
    code, refused = 0, []
    try:
        client = AcpClient(argv_for(cli), cwd)
        client.request("initialize", {
            "protocolVersion": ACP_PROTOCOL,
            "clientInfo": {"name": "chronicle-advice", "version": "1"},
            # Declining these here is what makes the refusals in _refuse consistent rather than
            # surprising: the agent is told up front that there is no file access and no terminal.
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False},
                                   "terminal": False},
        }, deadline)
        session = client.request("session/new", {"cwd": cwd, "mcpServers": []}, deadline)
        result = client.request("session/prompt", {
            "sessionId": (session or {}).get("sessionId"),
            "prompt": [{"type": "text", "text": prompt}],
        }, deadline) or {}
        text = "".join(client.chunks).strip()
        stop = result.get("stopReason")
        refused = client.refused
        if not text:
            text, code = "no output (stop reason %s)%s" % (stop, client.tail()), 1
        elif stop not in (None, "end_turn"):
            code = 1  # kept, but flagged: a truncated answer is worth seeing on the panel
    except AcpError as err:
        text, code = str(err), 1
    except OSError as err:
        text, code = "could not start the CLI: %r" % (err,), 127
    finally:
        if client is not None:
            client.close()
    return text, code, int((time.time() - started) * 1000), refused


def tidy_summary(text: str) -> str:
    """Force a model's reply into at most five short lines, one finding each.

    Everything here is defence against a plausible reply rather than a broken one. The instruction
    asks for five lines and no preamble; replies arrive with six, or with "Here are the key points:"
    on top, or with `**bold**` inside a line, and each of those reaches the panel as a row that says
    nothing. Dropping short lines removes the leftover headings; dropping the trailing colon removes
    the preamble, since that is the shape it always takes.
    """
    lines = []
    for raw in (text or "").splitlines():
        line = re.sub(r"^([-*#>•]+|[0-9]+[.)])\s*", "", raw.strip())
        line = re.sub(r"\*+|`", "", line).strip()
        if len(line) < 15 or line.endswith(":"):
            continue
        lines.append(shorten(line))
        if len(lines) == MAX_SUMMARY_LINES:
            break
    return "\n".join(lines)


def shorten(line: str) -> str:
    """Cut an over-long line at a word boundary and say that it was cut.

    Asked for 160 characters the model will still write 190 now and then, and a hard slice ends a row
    mid-word -- "built to cut subagent cont" reads as a typo rather than as a truncation. An ellipsis
    at the last space before the limit reads as what it is.
    """
    if len(line) <= MAX_SUMMARY_CHARS:
        return line
    cut = line[:MAX_SUMMARY_CHARS - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > MAX_SUMMARY_CHARS // 2 else cut).rstrip(" ,;:-") + "…"


def summarise(cli: list, report: str, cwd: str) -> tuple:
    """Ask for a short version of one captured report. Returns (summary, duration_ms).

    An empty summary is not an error and is not filled in with a guess: the panels fall back to
    shortening `advice_text` themselves, which is what every row captured before this did.
    """
    prompt = SUMMARY_INSTRUCTION + "\n\n---\n" + report
    text, code, elapsed, _ = run_prompt(cli, prompt, cwd)
    return ("" if code else tidy_summary(text)), elapsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--command", action="append", default=[], metavar="REQUEST",
                        help="subcommand to run, with its arguments if it takes any, repeatable. "
                             "Quote anything with a space: --command \"standup last 7 days\". "
                             "Default: %s" % ", ".join(DEFAULT_COMMANDS))
    parser.add_argument("--copilot", help="how to start the CLI, if it is not found automatically")
    parser.add_argument("--cwd", default=str(Path(__file__).resolve().parent),
                        help="working directory the session is opened in. Chronicle reads the whole "
                             "history rather than this directory, but a session has to be opened "
                             "somewhere. Default: this repository")
    parser.add_argument("--user", default=None,
                        help="value written to service_user, which the Developer filter matches "
                             "on. Spell it exactly as the rest of the pipeline does. "
                             "Default: $COPILOT_USER, else the logged-in user.")
    parser.add_argument("--base-url", default=None,
                        help="OpenObserve base URL (default: $OPENOBSERVE_BASE_URL, else "
                             "http://localhost:5080)")
    parser.add_argument("--org", default=None,
                        help="OpenObserve org (default: $OPENOBSERVE_ORG, else 'default')")
    parser.add_argument("--stream-url", default=None, metavar="URL",
                        help="full ingest URL for %s, overriding the --base-url/--org form "
                             "(default: the entry for this stream in $CHRONICLE_STREAM_URLS)"
                             % STREAM)
    parser.add_argument("--insecure-tls", action="store_true", default=None,
                        help="accept a self-signed certificate on an HTTPS endpoint "
                             "(default: $OPENOBSERVE_INSECURE_TLS)")
    parser.add_argument("--no-summary", action="store_true",
                        help="skip the second call that shortens each report. Halves the credits and "
                             "the wall clock; the panels then shorten the long form themselves, "
                             "which is worse. See SUMMARISING above.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the command that would run, spend nothing, send nothing")
    args = parser.parse_args(argv)

    identity = args.user or default_user()
    commands = args.command or list(DEFAULT_COMMANDS)
    cli = resolve_cli(args.copilot)
    print("CLI: %s" % " ".join(cli))

    account = os.environ.get("OPENOBSERVE_USER") or ""
    secret = os.environ.get("OPENOBSERVE_PASSWORD") or ""
    if not args.dry_run and (not account or not secret):
        # Checked before the first model call rather than after: these calls cost credits, and
        # spending four of them only to fail on the POST wastes real money.
        print("Missing OpenObserve credentials. Set $OPENOBSERVE_USER and $OPENOBSERVE_PASSWORD.",
              file=sys.stderr)
        return 2
    allow_insecure = (args.insecure_tls if args.insecure_tls is not None
                      else os.environ.get("OPENOBSERVE_INSECURE_TLS", "").lower()
                      in {"1", "true", "yes"})

    rows = []
    for request in commands:
        request = request.strip()
        # The bare subcommand is the panel's key, the whole request is what was actually asked.
        subcommand = request.split()[0] if request else request
        if args.dry_run:
            print("would run: %s" % " ".join(argv_for(cli)))
            print("  then, over ACP: session/new in %s, then prompt \"/chronicle %s\""
                  % (args.cwd, request))
            if not args.no_summary:
                print("  then a second session with the answer and: %s" % SUMMARY_INSTRUCTION[:60])
            continue
        print("running /chronicle %s ..." % request, flush=True)
        text, code, elapsed, refused = run_prompt(cli, "/chronicle %s" % request, args.cwd)
        print("  exit %d, %d ms, %d characters" % (code, elapsed, len(text)))
        if refused:
            # Not a failure in itself -- see TOOL PERMISSION -- but it explains a thin answer.
            print("  refused %d agent request(s): %s"
                  % (len(refused), ", ".join(sorted(set(refused)))))
        if not text:
            print("  nothing came back -- see TOOL PERMISSION in this script's docstring")
            continue
        summary, summary_ms = "", 0
        if not args.no_summary and code == 0:
            print("  summarising ...", flush=True)
            summary, summary_ms = summarise(cli, text, args.cwd)
            print("  %s" % ("%d line(s), %d ms" % (len(summary.splitlines()), summary_ms)
                            if summary else "no summary came back -- the panels will shorten the "
                                            "long form instead"))
        rows.append({
            "_timestamp": int(time.time() * 1_000_000),
            "service_user": identity,
            "chronicle_command": subcommand,
            "chronicle_request": request,
            "advice_text": text,
            "advice_summary": summary,
            "exit_code": code,
            # Kept apart rather than added together: duration_ms has meant "how long the report took"
            # since the first row, and quietly widening it would make old and new rows incomparable.
            "duration_ms": elapsed,
            "summary_ms": summary_ms,
            "captured_at": dt.datetime.now().isoformat(timespec="seconds"),
        })

    if args.dry_run:
        print("\ndry run: no model call was made and nothing was ingested.")
        return 0
    if not rows:
        print("\nnothing captured, nothing sent.")
        return 1

    overrides = stream_url_overrides()
    if args.stream_url:
        overrides = {**overrides, STREAM: args.stream_url}
    endpoint = endpoint_for(STREAM, args.base_url, args.org, overrides)
    result = send_events(rows, endpoint, account, secret, timeout=60.0, insecure_tls=allow_insecure)
    ok = bool(result.get("ok"))
    print("\ningested %d row(s) into %s: %s"
          % (len(rows), STREAM, "ok" if ok else (result.get("error") or result.get("response"))))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
