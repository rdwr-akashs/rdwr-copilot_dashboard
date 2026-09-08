#!/usr/bin/env python3
"""Ship Claude Code's own `/insights` cache into OpenObserve, as a companion to chronicle_export.py.

    python claude_insights_export.py --dry-run       # print what it would send
    python claude_insights_export.py                 # send anything new or changed
    python claude_insights_export.py --reset          # forget the watermark, resend every session

WHY THIS EXISTS
---------------
Copilot's chronicle (`chronicle_export.py`) has no equivalent on the Claude Code side -- there is no
local `session-store.db` it writes as it goes. What Claude Code has instead is a *command*: running
`/insights` in a session scans every local transcript under `~/.claude/projects/`, asks the model to
judge each one -- what the user was trying to do, whether it worked, what went wrong -- and writes the
result to two on-disk caches:

    ~/.claude/usage-data/session-meta/<session_id>.json   mechanical facts, computed locally, free --
                                                           duration, message counts, tool counts, git
                                                           commits, token counts
    ~/.claude/usage-data/facets/<session_id>.json          the model's judgement, one billed call per
                                                           session the first time it is analysed --
                                                           outcome, friction, satisfaction, a one-line
                                                           summary of what the session was for

That is the same split chronicle draws between its numeric streams and `chronicle_advice.py`'s prose,
just produced by one command instead of two scripts. This script is the numbers-and-judgement half --
it only ever reads files `/insights` already wrote. It never runs `/insights` and never makes a model
call of its own. Refreshing the cache means running `/insights` yourself in a Claude Code session; this
script's job starts after that, the same way `chronicle_export.py` starts after `copilot` has already
written to its store.

`facets` is a *subset* of `session-meta`: `/insights` scans up to 200 sessions per run but only sends
the ~50 most meaningful of them (long enough, more than one exchange) to the model, and skips a session
already cached with a facets file at least as new as its transcript. So most session-meta rows will
carry no facets columns at all -- that is normal, not a partial load.

ONE STREAM, NOT FIVE
---------------------
Chronicle needs five streams because its source SQLite store has five tables of different grain.
`/insights`'s two caches share exactly one grain -- one row per session -- so they are merged into a
single row per `session_id` in one stream, `claude_insights_sessions`, rather than kept apart and
joined later.

WHY A CHANGED ROW IS A NEW ROW, AND HOW PANELS MUST READ IT
--------------------------------------------------------------
Chronicle rows are immutable once GitHub bills a call, which is why its panels dedupe with
`SELECT DISTINCT ... chronicle_row_id`. A `/insights` session-meta or facets file is not immutable: the
*same* session_id can be re-analysed later with a fresher transcript, and every column is carried on
every row, so a re-run of this script sends a full replacement row rather than a delta. OpenObserve has
no upsert, so both versions end up in the stream.

`DISTINCT session_id` would be wrong here -- it collapses to the right *count* of sessions but not the
right *values*, because the two versions differ in their other columns. What every panel on
`openobserve/claude_insights.dashboard.json` does instead is keep the newest version by `captured_at`,
the wall-clock time this script sent the row (not `_timestamp`, which is the session's own `start_time`
and is identical across every resend of the same session):

    WITH latest AS (
      SELECT session_id, MAX(captured_at) AS cap FROM claude_insights_sessions GROUP BY session_id
    )
    SELECT s.* FROM claude_insights_sessions s
    JOIN latest l ON l.session_id = s.session_id AND l.cap = s.captured_at

not `ROW_NUMBER() OVER (PARTITION BY session_id ...)` -- a partitioned window is rejected by this
OpenObserve build with "Expects PARTITION BY expression to be ordered", the same limitation
`chronicle.dashboard.json`'s `top_model` CTE works around with max-then-rejoin.

A session-meta/facets pair is only resent when its own file mtime moves past what
`claude_insights_state.json` last recorded for that `session_id`, so a re-run with nothing new sends
nothing.

THIS DATA IS PER MACHINE, LIKE CHRONICLE
------------------------------------------
`/insights` reads local transcripts. There is no server-side aggregation across developers -- every
teammate who wants their own rows on this tab has to run `/insights` at least once on their own machine
and then run this script there, pointed at the same OpenObserve instance. Same shape as chronicle,
same limitation.

WHAT IT DELIBERATELY SENDS, GIVEN THE CHOICE
-----------------------------------------------
`first_prompt` is already truncated by `/insights` itself to roughly 200 characters before it ever
reaches this script -- nothing here adds that truncation. `underlying_goal`, `brief_summary` and
`friction_detail` are the model's own prose about a session, the same kind of thing
`copilot_chronicle_advice` stores and the README's chronicle section already carries a privacy note
about: read a captured row before putting this stream on a shared instance, because it names what a
person was working on.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from openobserve_export import send_events

DEFAULT_BASE_URL = "http://localhost"
DEFAULT_ORG = "default"
DEFAULT_DIR = Path.home() / ".claude" / "usage-data"
STREAM = "claude_insights_sessions"
ENV_STATE = "CLAUDE_INSIGHTS_STATE"
ENV_USER = "CLAUDE_USER"
BATCH = 200

# Every row carries these whatever the two caches hold, and none come from either cache.
# openobserve/seed_schema.py reads this tuple so the column list cannot drift from what is sent.
ROW_IDENTITY = ("session_id", "service_user", "captured_at")

# session-meta columns copied straight through: already scalars, already free.
META_COLUMNS = (
    "project_path", "duration_minutes", "user_message_count", "assistant_message_count",
    "git_commits", "git_pushes", "input_tokens", "output_tokens", "user_interruptions",
    "tool_errors", "lines_added", "lines_removed", "files_modified",
    "uses_task_agent", "uses_mcp", "uses_web_search", "uses_web_fetch", "first_prompt",
)

# session-meta sends these as JSON booleans. Sent on as 0/1 instead: openobserve/seed_schema.py has
# no boolean-column machinery (nothing Copilot's chronicle writes is ever a JSON bool -- its one
# true/false-shaped field, content_filter_triggered, is an INTEGER in SQLite), and adding a second
# type path there for four columns is a bigger change than avoiding the type entirely here.
BOOL_AS_INT_COLUMNS = ("uses_task_agent", "uses_mcp", "uses_web_search", "uses_web_fetch")

# facets columns copied straight through: the model's own judgement, already computed and cached.
FACETS_COLUMNS = (
    "outcome", "session_type", "claude_helpfulness", "primary_success",
    "underlying_goal", "brief_summary", "friction_detail",
)

# Computed here from the nested maps in session-meta/facets -- see derive_row().
DERIVED_COLUMNS = (
    "total_tool_calls", "primary_language", "primary_goal_category", "primary_friction",
    "satisfaction_positive", "satisfaction_negative",
)


def default_state_path() -> str:
    """Where the watermark lives when none is configured.

    Alongside chronicle_export.py's own state, under `~/.copilot-dashboard/` -- the repository's
    existing convention for this app's own state, not a Claude-specific directory of its own -- so a
    checkout can be replaced without losing the record of what was ingested.
    """
    configured = os.environ.get(ENV_STATE)
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(os.path.expanduser("~"), ".copilot-dashboard", "claude_insights_state.json")


def default_user() -> str:
    """The login written to `service_user`, which the Developer filter matches on."""
    return (
      os.environ.get(ENV_USER)
      or os.environ.get("USERNAME")
      or os.environ.get("USER")
      or _login_name()
    )


def _login_name() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "unattributed"


def micros(value: Any) -> int | None:
    """`/insights` stores ISO-8601 with a trailing Z; OpenObserve wants microseconds."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        stamp = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return int(stamp.timestamp() * 1_000_000)


def load_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def top_key(counts: dict | None) -> str | None:
    """The key with the largest count, or None for an empty or missing map."""
    if not counts:
        return None
    return max(counts.items(), key=lambda pair: pair[1])[0]


def derive_row(meta: dict, facets: dict) -> dict:
    """The columns computed from a nested map in either cache -- see DERIVED_COLUMNS.

    `user_satisfaction_counts` has no fixed key set, so "negative" is decided by substring rather
    than an enum: any key containing "dissatisf", "frustrat" or "unsatisf" counts against
    `satisfaction_negative`, everything else counts toward `satisfaction_positive`. That is a
    heuristic, not a schema Anthropic has published, and it is worth re-checking a captured row
    against this list if a new key shows up that the split gets wrong.
    """
    row: dict[str, Any] = {}
    tool_counts = meta.get("tool_counts") or {}
    row["total_tool_calls"] = sum(tool_counts.values())
    language = top_key(meta.get("languages"))
    if language is not None:
        row["primary_language"] = language
    goal_category = top_key(facets.get("goal_categories"))
    if goal_category is not None:
        row["primary_goal_category"] = goal_category
    friction = top_key(facets.get("friction_counts"))
    if friction is not None:
        row["primary_friction"] = friction
    satisfaction = facets.get("user_satisfaction_counts") or {}
    negative_markers = ("dissatisf", "frustrat", "unsatisf")
    positive = negative = 0
    for key, count in satisfaction.items():
        if any(marker in key for marker in negative_markers):
            negative += count
        else:
            positive += count
    row["satisfaction_positive"] = positive
    row["satisfaction_negative"] = negative
    return row


def build_session_row(meta_path: Path, facets_path: Path, user: str, captured_at: int) -> dict | None:
    """One row for one session, or None if session-meta carries no readable start time."""
    meta = load_json(meta_path)
    session_id = meta.get("session_id") or meta_path.stem
    timestamp = micros(meta.get("start_time"))
    if timestamp is None:
        return None
    facets = load_json(facets_path) if facets_path.exists() else {}
    row: dict[str, Any] = {
      "_timestamp": timestamp,
      "session_id": session_id,
      "service_user": user,
      "captured_at": captured_at,
    }
    for column in META_COLUMNS:
        value = meta.get(column)
        if value is not None:
            row[column] = int(bool(value)) if column in BOOL_AS_INT_COLUMNS else value
    for column in FACETS_COLUMNS:
        value = facets.get(column)
        if value is not None:
            row[column] = value
    row.update(derive_row(meta, facets))
    return row


def scan_cache(cache_dir: Path, user: str, captured_at: int, state: dict) -> tuple[list, dict]:
    """Every session-meta file whose own (or its facets sibling's) mtime is newer than the watermark.

    Returns (rows to send, the state entries to record if the send succeeds). The caller decides
    whether it succeeded -- this function never writes state itself, the same division
    chronicle_export.py keeps between reading rows and recording a watermark.
    """
    meta_dir = cache_dir / "session-meta"
    facets_dir = cache_dir / "facets"
    rows: list[dict] = []
    to_record: dict[str, float] = {}
    for meta_path in sorted(meta_dir.glob("*.json")):
        session_id = meta_path.stem
        facets_path = facets_dir / meta_path.name
        mtime = meta_path.stat().st_mtime
        if facets_path.exists():
            mtime = max(mtime, facets_path.stat().st_mtime)
        if state.get(session_id) == mtime:
            continue
        row = build_session_row(meta_path, facets_path, user, captured_at)
        if row is None:
            continue
        rows.append(row)
        to_record[session_id] = mtime
    return rows, to_record


def load_state(state_path: str, reset: bool = False) -> dict:
    if reset:
        return {}
    try:
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(state_path: str, state: dict) -> None:
    directory = os.path.dirname(state_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_path = f"{state_path}.{os.getpid()}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1)
    os.replace(temp_path, state_path)


def endpoint_for(base_url: str | None = None, org: str | None = None,
                 endpoint: str | None = None) -> str:
    """The `_json` ingest URL for the one stream this script writes.

    `endpoint` overrides the whole URL, for a server that does not follow the
    `{base}/api/{org}/{stream}/_json` shape -- a proxy in front of OpenObserve. Not read from
    `$OPENOBSERVE_URL`, for the same reason `chronicle_export.py`'s `endpoint_for` ignores it: that
    variable names the single-event insights stream, and honouring it here would misfile every row
    into `insights` instead.
    """
    if endpoint:
        return endpoint
    base = (base_url or os.environ.get("OPENOBSERVE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    org_name = org or os.environ.get("OPENOBSERVE_ORG") or DEFAULT_ORG
    return f"{base}/api/{org_name}/{STREAM}/_json"


def ingest_rows(rows: list[dict], endpoint: str, username: str, password: str,
                insecure_tls: bool = False, timeout: float = 120.0) -> tuple[int, int, str]:
    """POST one batch. Returns (accepted, rejected, first error) -- never raises on HTTP."""
    result = send_events(rows, endpoint, username, password, timeout=timeout,
                         insecure_tls=insecure_tls)
    if not result.get("ok"):
        return 0, len(rows), str(result.get("error") or result.get("response") or "")[:300]
    try:
        body = json.loads(result.get("response") or "{}")
    except ValueError:
        return len(rows), 0, ""
    accepted = rejected = 0
    error = ""
    for entry in body.get("status", []) or []:
        accepted += entry.get("successful") or 0
        rejected += entry.get("failed") or 0
        if entry.get("error") and not error:
            error = str(entry["error"])[:300]
    if accepted == 0 and rejected == 0:
        return len(rows), 0, ""
    return accepted, rejected, error


def export_claude_insights(
  cache_dir: str | None = None,
  base_url: str | None = None,
  org: str | None = None,
  endpoint: str | None = None,
  username: str | None = None,
  password: str | None = None,
  user: str | None = None,
  state_path: str | None = None,
  reset: bool = False,
  dry_run: bool = False,
  insecure_tls: bool | None = None,
  log=None,
) -> dict[str, Any]:
    """Read the /insights cache and ship whatever has not been shipped. Never raises on HTTP.

    Returns `{"ok": bool, "sent": int, "failed": int, "rows": int}`.
    """
    def say(message: str) -> None:
        if log is not None:
            log(message)

    identity = user or default_user()
    resolved_state = state_path or default_state_path()
    resolved_dir = Path(cache_dir).expanduser() if cache_dir else DEFAULT_DIR
    meta_dir = resolved_dir / "session-meta"

    account = username or os.environ.get("OPENOBSERVE_USER") or ""
    secret = password or os.environ.get("OPENOBSERVE_PASSWORD") or ""
    allow_insecure = (
      insecure_tls
      if insecure_tls is not None
      else os.environ.get("OPENOBSERVE_INSECURE_TLS", "").lower() in {"1", "true", "yes"}
    )
    if not dry_run and (not account or not secret):
        return {"ok": False, "sent": 0, "failed": 0, "rows": 0,
                "error": "Missing OpenObserve credentials. Set $OPENOBSERVE_USER and "
                         "$OPENOBSERVE_PASSWORD."}

    if not meta_dir.is_dir():
        # Not an error: this machine may simply never have run /insights. Said out loud so an empty
        # panel has an explanation in the log, the same courtesy chronicle_export.py extends to a
        # missing session-store.db.
        say(f"no {meta_dir} -- has /insights ever been run on this machine? nothing to send.")
        return {"ok": True, "sent": 0, "failed": 0, "rows": 0}

    state = load_state(resolved_state, reset=reset)
    captured_at = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1_000_000)
    rows, to_record = scan_cache(resolved_dir, identity, captured_at, state)

    report: dict[str, Any] = {"ok": True, "sent": 0, "failed": 0, "rows": len(rows)}
    label = f"{STREAM} <- {meta_dir}"
    if not rows:
        say(f"{label:<58} nothing new")
        if not dry_run:
            save_state(resolved_state, state)
        return report

    say("%-58s %5d row(s)" % (label, len(rows)))
    resolved_endpoint = endpoint_for(base_url, org, endpoint)
    report["endpoint"] = resolved_endpoint
    if dry_run:
        report["sample"] = rows[0]
        say(f"      would post to {resolved_endpoint}")
        say("      sample: %s" % json.dumps(rows[0])[:280])
        say("\ndry run: nothing was sent, no state written.")
        report["dryRun"] = True
        return report

    sent = failed = 0
    for start in range(0, len(rows), BATCH):
        accepted, rejected, error = ingest_rows(rows[start:start + BATCH], resolved_endpoint,
                                                account, secret, insecure_tls=allow_insecure)
        sent += accepted
        failed += rejected
        if error:
            report.setdefault("error", error)
            say(f"      {error}")
    report["sent"], report["failed"] = sent, failed
    say(f"      sent {sent}, failed {failed} -> {resolved_endpoint}")

    if failed == 0:
        # Only the sessions actually sent advance -- a partial batch failure must not mark a
        # session done, or the rows it rejected are lost silently on the next run too.
        state.update(to_record)
    save_state(resolved_state, state)
    report["ok"] = failed == 0
    report["statePath"] = resolved_state
    say(f"\nsent {sent} row(s), {failed} failed. Watermark in {resolved_state}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
      description=__doc__.splitlines()[0],
      formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dir", default=None,
                        help="the /insights cache (default %s)" % DEFAULT_DIR)
    parser.add_argument("--base-url", default=None,
                        help="OpenObserve base URL (default: $OPENOBSERVE_BASE_URL, else %s)"
                             % DEFAULT_BASE_URL)
    parser.add_argument("--org", default=None,
                        help="OpenObserve org (default: $OPENOBSERVE_ORG, else 'default').")
    parser.add_argument("--endpoint", default=None,
                        help="full ingest URL, overriding --base-url/--org -- for a server that "
                             "does not follow the {base}/api/{org}/claude_insights_sessions/_json "
                             "shape.")
    parser.add_argument("--user", default=None,
                        help="value written to service_user, which the dashboard's Developer "
                             "filter matches on. Default: $CLAUDE_USER, else the logged-in user.")
    parser.add_argument("--state", default=None,
                        help="watermark file (default: $CLAUDE_INSIGHTS_STATE, else "
                             "~/.copilot-dashboard/claude_insights_state.json).")
    parser.add_argument("--reset", action="store_true",
                        help="ignore the watermark and resend every session-meta file found")
    parser.add_argument("--dry-run", action="store_true", help="print what would be sent, send nothing")
    parser.add_argument("--insecure-tls", action="store_true", default=None,
                        help="accept a self-signed certificate on an HTTPS endpoint "
                             "(default: $OPENOBSERVE_INSECURE_TLS).")
    args = parser.parse_args(argv)

    report = export_claude_insights(
      cache_dir=args.dir,
      base_url=args.base_url,
      org=args.org,
      endpoint=args.endpoint,
      user=args.user,
      state_path=args.state,
      reset=bool(args.reset),
      dry_run=bool(args.dry_run),
      insecure_tls=args.insecure_tls,
      log=lambda message: print(message, flush=True),
    )
    if report.get("error"):
        print(report["error"], file=sys.stderr)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
