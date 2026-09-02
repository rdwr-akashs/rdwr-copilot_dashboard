#!/usr/bin/env python3
"""Replay the Copilot CLI's chronicle history into OpenObserve.

    python chronicle_export.py --dry-run                 # print what it would send
    python chronicle_export.py                           # send anything not sent before
    python chronicle_export.py --since 2026-07-09        # ...but nothing older than this
    python chronicle_export.py --reset --stream copilot_chronicle_sessions

Ported from the `observability` repo's `scripts/backfill-chronicle.py`, with the
endpoint, credentials and state-file conventions of this repository: the base URL
and the `OPENOBSERVE_USER` / `OPENOBSERVE_PASSWORD` pair that `openobserve_export.py`
already reads, and a state file next to the exporter's own under
`~/.copilot-dashboard/`.

WHY THIS EXISTS
---------------
The dashboard reads `~/.copilot/session-store.db` directly and renders it as HTML.
This sends the same store's *history* to OpenObserve instead, so the chronicle
panels can show months of billed spend rather than one page load, and so a team
can look at it without anyone generating an HTML file.

`assistant_usage_events.total_nano_aiu` is what GitHub charged for a call, not an
estimate, which is the whole reason this is worth ingesting.

WHY IT DOES NOT USE THE INSIGHTS DEDUPE STATE
---------------------------------------------
`openobserve_export.py` fingerprints every event it sends and skips anything an
endpoint accepted before. That is right for a few dozen findings whose numbers
drift between runs, and wrong here: chronicle rows are immutable and there are
thousands of them, so a fingerprint set would grow past `MAX_TRACKED_FINGERPRINTS`
and start re-sending the oldest history on every run.

So this keeps a high-water mark per source table instead -- the largest row id
sent -- and advances it only when a batch reports zero failures, so a partial load
never marks itself complete. Belt and braces on top: every row carries
`chronicle_row_id`, and every chronicle panel aggregates over a DISTINCT subquery
on it, so a duplicated row changes no total.

SEPARATE STREAMS, ON PURPOSE
----------------------------
One stream per row shape, because a stream with mixed grain cannot be aggregated
safely:

    copilot_chronicle_usage      one row per model call     -- tokens, credits, latency
    copilot_chronicle_costs      one row per model call     -- the same credits, split by token type
    copilot_chronicle_sessions   one row per session        -- repo, branch, working directory
    copilot_chronicle_files      one row per file touched   -- path and the tool that touched it
    copilot_chronicle_turns      one row per turn           -- when, and how long the text was

`copilot_chronicle_costs` shares its grain with `copilot_chronicle_usage` and is
still a separate stream: OpenObserve has no upsert, so widening an already-loaded
stream would mean `--reset`, and a reset cannot un-send the rows it duplicates.
The cost rows repeat the dimensions a cost panel groups by, so nothing has to join.

WHAT IT DELIBERATELY DOES NOT SEND
----------------------------------
No prompt text, no replies, no session summaries, no checkpoint narratives. Every
column sent is a number, an identifier, a model name or a path.

`turns` holds prompts and replies, and this reads that table without ever selecting
either column: the only thing asked of them is `LENGTH(...)`, which SQLite
evaluates, so two integers cross into this process. Prompt size is worth having --
it is the "pasted a whole log file into the prompt" signal -- and turn count is the
only honest measure of how much a person asked for, model calls being mostly the
agent talking to itself.

`checkpoints` is untouched. Every column in it is prose.

THE DATABASE IS OPENED READ-ONLY, FROM A COPY
---------------------------------------------
Copilot may be running while this does. The live file is copied to a temporary
directory -- with its `-wal` and `-shm` siblings, or recent sessions would be
missing -- and opened `mode=ro`. Nothing here can write to, lock or checkpoint the
store Copilot is using. Same posture as `cli_usage.py`.

HOW FAR BACK TO GO
------------------
`--since` puts a floor under everything: a row whose own timestamp is older is
never sent and never counted. Two reasons to want it. Chronicle keeps months of
history from before anyone was measuring, and the streams do not all start on the
same day -- sessions and turns reach back further than billed calls do, so a
session-level ratio taken over everything divides by sessions that could not have
spent a credit. The floor is applied after the row is read, so it works whether the
source column is ISO text or an epoch, and the watermark only advances over rows
actually sent -- so lowering `--since` later picks up what a higher one skipped
without needing `--reset`.

OLD RECORDS ARE DISCARDED ON INGEST, AND THE RESPONSE STILL SAYS 200
--------------------------------------------------------------------
OpenObserve refuses anything timestamped further back than `ZO_INGEST_ALLOWED_UPTO`
hours -- five by default -- and reports the loss only in the response body. So a
bulk historical load can look like it worked and silently drop most of itself. That
is why this parses the per-batch `status` array instead of trusting the HTTP code,
and why a host that will be backfilled needs that setting raised (4320 = 180 days
is what the reference stack uses). If rows come back rejected as "Too old data",
that is the setting.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from openobserve_export import send_events

DEFAULT_BASE_URL = "http://localhost:5080"
DEFAULT_ORG = "default"
DEFAULT_DB = Path.home() / ".copilot" / "session-store.db"
ENV_STATE = "CHRONICLE_STATE"
ENV_USER = "COPILOT_USER"
BATCH = 500


def default_state_path() -> str:
    """Where the high-water marks live when none is configured.

    Alongside the insights exporter's own state rather than inside the repository,
    so a checkout can be replaced without losing the record of what was ingested.
    """
    configured = os.environ.get(ENV_STATE)
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(os.path.expanduser("~"), ".copilot-dashboard", "chronicle_state.json")


def default_user() -> str:
    """The login written to `service_user`, which the Developer filter matches on.

    Spelled exactly as whatever else writes to these streams spells it, or the
    chronicle panels cannot be selected for that person at all.
    """
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


def credits(row: dict, record: Any) -> None:
    """Credits, in the unit every panel already uses. 1 credit = 1,000,000,000 nano-AIU."""
    if record["total_nano_aiu"] is not None:
        row["ai_credits"] = round(record["total_nano_aiu"] / 1_000_000_000.0, 6)


def cost_split(row: dict, record: Any) -> None:
    """Split one call's credits across the four token types, and price the cache.

    `token_details_json` is GitHub's own price table for the call it belongs to: one
    entry per token type carrying `tokenCount` and a `costPerBatch` per `batchSize`
    tokens, in nano-AIU. Recomputing the bill from it -- rate times count, summed --
    reproduces `total_nano_aiu` to within a thousandth of a credit across a whole
    store. That exactness is why the derived columns below can be read as money
    rather than as an estimate, and it is worth re-checking after a CLI update:
    `SUM(credits_total)` here must equal `SUM(ai_credits)` on
    `copilot_chronicle_usage`. Drift means the price table gained a token type this
    function is silently dropping.

    The rates already include the model's premium. `request_multiplier` reads 15.0
    for opus and 0.33 for a mini, and applying it on top of these rates would
    overstate opus fifteenfold -- the multiplier describes the price, it is not a
    factor still to be applied. Same trap `model_pricing.py` documents.

    `credits_if_no_cache` re-prices the cache read *and* cache write tokens at the
    plain input rate they would have been charged at with caching off, and
    `credits_cache_saved` is the difference -- net, so the premium paid to write the
    cache is already subtracted from the discount earned by reading it. A negative
    value is meaningful, not a bug: a session that built a cache and abandoned it.
    """
    try:
        details = json.loads(record["token_details_json"] or "[]")
    except ValueError:
        details = []
    rate: dict[str, float] = {}
    count: dict[str, int] = {}
    for entry in details:
        kind = entry.get("tokenType")
        batch = entry.get("batchSize") or 0
        if not kind or not batch:
            continue
        rate[kind] = entry.get("costPerBatch", 0) / batch
        count[kind] = entry.get("tokenCount") or 0
    if not rate:
        return

    def nano(kind: str) -> float:
        return rate.get(kind, 0.0) * count.get(kind, 0)

    total = sum(nano(kind) for kind in rate)
    no_cache = (
      nano("input")
      + nano("output")
      + (count.get("cache_read", 0) + count.get("cache_write", 0)) * rate.get("input", 0.0)
    )
    for column, value in (
      ("credits_input", nano("input")),
      ("credits_cache_read", nano("cache_read")),
      ("credits_cache_write", nano("cache_write")),
      ("credits_output", nano("output")),
      ("credits_total", total),
      ("credits_if_no_cache", no_cache),
      ("credits_cache_saved", no_cache - total),
    ):
        row[column] = round(value / 1_000_000_000.0, 6)


# Each entry: stream name, source table, the column the high-water mark advances on,
# the column that dates a row, and the columns to copy. Text-bearing columns are
# absent by design -- see WHAT IT DELIBERATELY DOES NOT SEND. Four optional keys:
#
#     inputs       selected so `derive` can read them, and never put in the row. This
#                  is how token_details_json is used without a 400-character price
#                  blob being sent.
#     expressions  output name -> SQL, evaluated by SQLite. The only way to send a
#                  fact *about* a text column without the text itself entering this
#                  process.
#     derive       called with (row, record) to add columns computed here.
#     derived      the names `derive` adds. Declared separately because
#                  openobserve/seed_schema.py reads this table to register columns and
#                  must learn the names without running anything.
#
# `watermark` has to be monotonic in insertion order, which rules out a UUID primary
# key: ordering `sessions.id` compares text, so a session inserted later with a
# lower-sorting UUID would be skipped forever by the next incremental run. SQLite's
# implicit `rowid` is insertion-ordered, so that table uses it instead of its own id.
JOBS: tuple[dict[str, Any], ...] = (
  {
    "stream": "copilot_chronicle_usage",
    "table": "assistant_usage_events",
    "watermark": "id",
    "time": "created_at",
    "columns": (
      "session_id", "turn_index", "agent_id", "model",
      "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
      "reasoning_tokens", "total_nano_aiu", "request_multiplier",
      "duration_ms", "time_to_first_token_ms", "inter_token_latency_ms",
      "initiator", "api_endpoint", "reasoning_effort", "finish_reason",
      "content_filter_triggered",
    ),
    "derive": credits,
    "derived": ("ai_credits",),
  },
  {
    # Same grain as the stream above and deliberately not part of it -- see
    # SEPARATE STREAMS. The dimensions a cost panel groups by are repeated here so
    # nothing has to be joined.
    "stream": "copilot_chronicle_costs",
    "table": "assistant_usage_events",
    "watermark": "id",
    "time": "created_at",
    "columns": ("session_id", "turn_index", "model", "initiator", "agent_id", "reasoning_effort"),
    "inputs": ("token_details_json",),
    "derive": cost_split,
    "derived": (
      "credits_input", "credits_cache_read", "credits_cache_write", "credits_output",
      "credits_total", "credits_if_no_cache", "credits_cache_saved",
    ),
  },
  {
    "stream": "copilot_chronicle_sessions",
    "table": "sessions",
    "watermark": "rowid",
    "time": "created_at",
    # `summary` is a written description of the session and is left behind. `cwd` is
    # kept because most sessions have no repository set, so the working directory is
    # the only thing that says which project a session belonged to.
    "columns": ("id", "cwd", "repository", "host_type", "branch", "created_at", "updated_at"),
  },
  {
    "stream": "copilot_chronicle_files",
    "table": "session_files",
    "watermark": "id",
    "time": "first_seen_at",
    "columns": ("session_id", "file_path", "tool_name", "turn_index", "first_seen_at"),
  },
  {
    # `user_message` and `assistant_response` are never selected. Only their lengths
    # are, and SQLite computes those, so the text does not enter this process at all.
    "stream": "copilot_chronicle_turns",
    "table": "turns",
    "watermark": "id",
    "time": "timestamp",
    "columns": ("session_id", "turn_index"),
    "expressions": {
      "prompt_chars": "LENGTH(user_message)",
      "reply_chars": "LENGTH(assistant_response)",
    },
  },
)

# Written by chronicle_advice.py rather than by this script, and declared here so the
# schema seeder can register its columns from one place.
ADVICE_STREAM = "copilot_chronicle_advice"
ADVICE_COLUMNS = (
  "service_user", "chronicle_command", "chronicle_request", "advice_text", "advice_summary",
  "exit_code", "duration_ms", "summary_ms", "captured_at",
)


def stream_names() -> list[str]:
    return [job["stream"] for job in JOBS]


def stream_url_overrides(raw: Any = None) -> dict[str, str]:
    """Per-stream full URLs, from an explicit mapping or `$CHRONICLE_STREAM_URLS`.

    Accepts either a dict or the JSON text of one, keyed by stream name:
    `{"copilot_chronicle_turns": "https://oo.example.com/api/team/turns_v2/_json"}`.
    A stream missing from the mapping keeps the base + org form. Unparseable text is
    ignored rather than fatal: a typo in a config file should not stop the export that
    every other stream is still able to make.
    """
    if raw is None:
        raw = os.environ.get("CHRONICLE_STREAM_URLS") or ""
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            raw = json.loads(text)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    return {str(name): str(url) for name, url in raw.items() if url}


def endpoint_for(
  stream: str,
  base_url: str | None = None,
  org: str | None = None,
  stream_urls: dict[str, str] | None = None,
) -> str:
    """The `_json` ingest URL for one chronicle stream.

    Built here rather than through `openobserve_export.resolve_endpoint`, which
    honours `$OPENOBSERVE_URL` -- a single full URL naming the insights stream. Let
    that win and every chronicle stream would be posted into `insights`.

    `stream_urls` overrides the whole URL for named streams, which is what a server
    that does not follow the `{base}/api/{org}/{stream}/_json` shape needs -- a proxy
    in front of OpenObserve, or one stream renamed without moving the other four.
    """
    override = (stream_urls or {}).get(stream)
    if override:
        return override
    base = (base_url or os.environ.get("OPENOBSERVE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    org_name = org or os.environ.get("OPENOBSERVE_ORG") or DEFAULT_ORG
    return f"{base}/api/{org_name}/{stream}/_json"


def micros(value: Any) -> int | None:
    """Chronicle stores ISO-8601 with a trailing Z; OpenObserve wants microseconds."""
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


def open_copy(db: Path, workdir: str) -> sqlite3.Connection:
    """Copy the store and open it read-only. Never touch the file Copilot is using."""
    if not db.exists():
        raise SystemExit(f"no chronicle store at {db} -- has the Copilot CLI ever run here?")
    for suffix in ("", "-wal", "-shm"):
        source = Path(str(db) + suffix)
        if source.exists():
            shutil.copy2(source, Path(workdir) / source.name)
    target = (Path(workdir) / db.name).as_posix()
    connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def load_state(state_path: str, reset: bool = False, only: list[str] | None = None) -> dict:
    """Read the watermarks, forgetting the ones `--reset` applies to.

    `--reset` forgets only the streams this run will actually resend. Clearing the
    whole file would make `--reset --stream one_stream` silently resend a *different*
    stream on the next ordinary run, because its watermark went missing while nothing
    reported a problem.
    """
    try:
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict):
        return {}
    if reset:
        for stream in [s for s in list(state) if not only or s in only]:
            del state[stream]
    return state


def save_state(state_path: str, state: dict) -> None:
    directory = os.path.dirname(state_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_path = f"{state_path}.{os.getpid()}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1)
    os.replace(temp_path, state_path)


def build_chronicle_rows(
  connection: sqlite3.Connection,
  job: dict[str, Any],
  since: Any = None,
  floor: int | None = None,
  user: str | None = None,
) -> tuple[list[dict[str, Any]], Any, int]:
    """Read one job's rows out of the store. Returns (rows, highest watermark, skipped).

    `skipped` counts rows dropped by `floor` only. A row whose timestamp cannot be
    read at all is dropped silently and does not advance the watermark, so a later
    run sees it again if the column becomes readable.
    """
    identity = user or default_user()
    id_column = job["watermark"]
    where = f" WHERE {id_column} > ?" if since is not None else ""
    params: tuple = (since,) if since is not None else ()
    plain = (id_column, job["time"]) + job["columns"] + job.get("inputs", ())
    selected = list(dict.fromkeys(plain))
    selected += [f"{expression} AS {name}" for name, expression in job.get("expressions", {}).items()]
    sql = f"SELECT {', '.join(selected)} FROM {job['table']}{where} ORDER BY {id_column}"

    rows: list[dict[str, Any]] = []
    highest = since
    skipped = 0
    for record in connection.execute(sql, params):
        stamp = micros(record[job["time"]])
        if stamp is None:
            continue
        if floor is not None and stamp < floor:
            skipped += 1
            continue
        row: dict[str, Any] = {
          "_timestamp": stamp,
          "service_user": identity,
          "chronicle_row_id": record[id_column],
        }
        for column in job["columns"] + tuple(job.get("expressions", ())):
            value = record[column]
            if value is not None:
                row[column] = value
        if job.get("derive"):
            job["derive"](row, record)
        rows.append(row)
        highest = record[id_column] if highest is None else max(highest, record[id_column])
    return rows, highest, skipped


def ingest_rows(
  rows: list[dict[str, Any]],
  endpoint: str,
  username: str,
  password: str,
  insecure_tls: bool = False,
  timeout: float = 120.0,
) -> tuple[int, int, str]:
    """POST one batch. Returns (accepted, rejected, first error).

    The per-record `status` array is what is counted, not the HTTP code: OpenObserve
    answers 200 and reports discarded records in the body -- see the module docstring
    on ZO_INGEST_ALLOWED_UPTO.
    """
    result = send_events(
      rows, endpoint, username, password, timeout=timeout, insecure_tls=insecure_tls
    )
    if not result.get("ok"):
        return 0, len(rows), str(result.get("error") or result.get("response") or "")[:300]
    try:
        body = json.loads(result.get("response") or "{}")
    except ValueError:
        # Accepted with a body this cannot read. Treated as sent, because the HTTP
        # call succeeded and the alternative is a watermark that never advances.
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


def count_rows(stream: str, base_url: str | None = None, org: str | None = None) -> int | None:
    """How many rows the stream already holds, or None if that cannot be established.

    Used only to make `--reset` honest about what it is about to do. A stream that
    does not exist yet is the normal first run, so any failure returns None and the
    caller stays quiet rather than printing a number it did not really measure.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent / "openobserve"))
    try:
        import oo_api  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    end = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1_000_000)
    ok, result = oo_api.search(
      f"SELECT COUNT(*) AS rows FROM {stream}",
      end - 400 * 86400 * 1_000_000,
      end,
      size=1,
    )
    if not ok or not isinstance(result, dict):
        return None
    hits = result.get("hits") or []
    return hits[0].get("rows") if hits else None


def export_chronicle(
  db_path: str | None = None,
  base_url: str | None = None,
  org: str | None = None,
  username: str | None = None,
  password: str | None = None,
  user: str | None = None,
  since: str | None = None,
  state_path: str | None = None,
  streams: list[str] | None = None,
  stream_urls: dict[str, str] | str | None = None,
  reset: bool = False,
  dry_run: bool = False,
  insecure_tls: bool | None = None,
  log=None,
) -> dict[str, Any]:
    """Read the store and ship whatever has not been shipped. Never raises on HTTP.

    Returns `{"ok": bool, "sent": int, "failed": int, "streams": {name: {...}}}`.
    """
    def say(message: str) -> None:
        if log is not None:
            log(message)

    identity = user or default_user()
    resolved_state = state_path or default_state_path()
    wanted = list(streams or [])
    overrides = stream_url_overrides(stream_urls)
    floor = micros(since) if since else None
    if since and floor is None:
        raise SystemExit(f"--since {since!r} is not a date I can read; try 2026-07-09")

    account = username or os.environ.get("OPENOBSERVE_USER") or ""
    secret = password or os.environ.get("OPENOBSERVE_PASSWORD") or ""
    allow_insecure = (
      insecure_tls
      if insecure_tls is not None
      else os.environ.get("OPENOBSERVE_INSECURE_TLS", "").lower() in {"1", "true", "yes"}
    )
    if not dry_run and (not account or not secret):
        return {
          "ok": False,
          "sent": 0,
          "failed": 0,
          "streams": {},
          "error": "Missing OpenObserve credentials. Set $OPENOBSERVE_USER and $OPENOBSERVE_PASSWORD.",
        }

    state = load_state(resolved_state, reset=reset, only=wanted)
    if reset:
        say(
          "--reset: forgetting the high-water mark for %s"
          % (", ".join(wanted) if wanted else "every stream")
        )
        if not dry_run:
            for stream in wanted or stream_names():
                existing = count_rows(stream, base_url, org)
                if existing:
                    say(
                      f"      {stream} already holds {existing} row(s). OpenObserve has no upsert, "
                      "so these will be duplicated, not replaced. Every panel dedupes on "
                      "chronicle_row_id so no number changes; a raw COUNT(*) reads high until the "
                      "stream is deleted and reloaded."
                    )

    database = Path(os.path.expanduser(db_path)) if db_path else DEFAULT_DB
    workdir = tempfile.mkdtemp(prefix="chronicle-")
    report: dict[str, Any] = {"ok": True, "sent": 0, "failed": 0, "streams": {}}
    try:
        connection = open_copy(database, workdir)
        for job in JOBS:
            stream = job["stream"]
            if wanted and stream not in wanted:
                continue
            watermark = (state.get(stream) or {}).get("last_id")
            rows, highest, skipped = build_chronicle_rows(
              connection, job, since=watermark, floor=floor, user=identity
            )
            entry = {"rows": len(rows), "sent": 0, "failed": 0, "skippedOlderThanSince": skipped}
            report["streams"][stream] = entry
            label = f"{stream} <- {job['table']}"
            older = f" ({skipped} older than --since)" if skipped else ""
            if not rows:
                say("%-58s nothing new%s" % (label, older))
                continue
            say("%-58s %5d row(s)%s" % (label, len(rows), older))
            endpoint = endpoint_for(stream, base_url, org, overrides)
            entry["endpoint"] = endpoint
            if dry_run:
                entry["sample"] = rows[0]
                say(f"      would post to {endpoint}")
                say("      sample: %s" % json.dumps(rows[0])[:220])
                continue

            sent = failed = 0
            for start in range(0, len(rows), BATCH):
                accepted, rejected, error = ingest_rows(
                  rows[start:start + BATCH], endpoint, account, secret, insecure_tls=allow_insecure
                )
                sent += accepted
                failed += rejected
                if error:
                    entry.setdefault("error", error)
                    say(f"      {error}")
            entry["sent"], entry["failed"] = sent, failed
            report["sent"] += sent
            report["failed"] += failed
            say(f"      sent {sent}, failed {failed} -> {endpoint}")
            if failed == 0 and highest is not None:
                state[stream] = {
                  "last_id": highest,
                  "table": job["table"],
                  "at": dt.datetime.now().isoformat(timespec="seconds"),
                }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if dry_run:
        say("\ndry run: nothing was sent, no state written.")
        report["dryRun"] = True
        return report

    save_state(resolved_state, state)
    report["ok"] = report["failed"] == 0
    report["statePath"] = resolved_state
    say(
      "\nsent %d row(s), %d failed. High-water marks in %s"
      % (report["sent"], report["failed"], resolved_state)
    )
    if report["failed"]:
        say(
          "Rows rejected as 'Too old data' mean ZO_INGEST_ALLOWED_UPTO on the OpenObserve host is "
          "lower than the history being replayed. Raise it (4320 = 180 days), recreate the "
          "container, and re-run."
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
      description=__doc__.splitlines()[0],
      formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
      "--db",
      default=os.environ.get("COPILOT_CLI_DB") or str(DEFAULT_DB),
      help="chronicle store to read (default: $COPILOT_CLI_DB, else %s)" % DEFAULT_DB,
    )
    parser.add_argument(
      "--base-url",
      default=None,
      help="OpenObserve base URL (default: $OPENOBSERVE_BASE_URL, else %s)" % DEFAULT_BASE_URL,
    )
    parser.add_argument("--org", default=None, help="OpenObserve org (default: $OPENOBSERVE_ORG, else 'default').")
    parser.add_argument(
      "--user",
      default=None,
      help="value written to service_user, which the dashboard's Developer filter matches on. "
           "Default: $COPILOT_USER, else the logged-in user.",
    )
    parser.add_argument(
      "--since",
      metavar="DATE",
      help="skip rows older than this, e.g. --since 2026-07-09. Read as UTC, the same way "
           "chronicle's own timestamps are.",
    )
    parser.add_argument(
      "--state",
      default=None,
      help="high-water-mark file (default: $CHRONICLE_STATE, else "
           "~/.copilot-dashboard/chronicle_state.json).",
    )
    parser.add_argument(
      "--stream",
      action="append",
      default=[],
      metavar="NAME",
      help="only this stream, repeatable. Lets a --reset be aimed at the one stream that needs it.",
    )
    parser.add_argument(
      "--stream-url",
      action="append",
      default=[],
      metavar="NAME=URL",
      help="full ingest URL for one stream, repeatable, e.g. --stream-url "
           "copilot_chronicle_turns=https://oo.example.com/api/team/turns/_json. Overrides the "
           "--base-url/--org form for that stream only. Default: $CHRONICLE_STREAM_URLS, a JSON "
           "object keyed by stream name.",
    )
    parser.add_argument("--reset", action="store_true", help="ignore the high-water mark and resend everything")
    parser.add_argument("--dry-run", action="store_true", help="print what would be sent, send nothing")
    parser.add_argument(
      "--insecure-tls",
      action="store_true",
      default=None,
      help="accept a self-signed certificate on an HTTPS endpoint (default: $OPENOBSERVE_INSECURE_TLS).",
    )
    args = parser.parse_args(argv)

    per_stream: dict[str, str] = {}
    for pair in args.stream_url:
        name, _, url = pair.partition("=")
        if not name.strip() or not url.strip():
            parser.error(f"--stream-url expects NAME=URL, got {pair!r}")
        per_stream[name.strip()] = url.strip()

    report = export_chronicle(
      db_path=args.db,
      base_url=args.base_url,
      org=args.org,
      user=args.user,
      since=args.since,
      state_path=args.state,
      streams=args.stream,
      stream_urls=per_stream or None,
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
