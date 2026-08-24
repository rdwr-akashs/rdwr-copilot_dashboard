from __future__ import annotations

import collections
import glob
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

import diagnostics

from model_pricing import (
    AIU_USD,
    TOKEN_TYPES,
    calculate_cost,
    cost_from_token_counts,
    nano_aiu_to_usd,
    split_prompt_tokens,
)

# How a cost figure was arrived at, best first. The CLI is the only source in
# this repo that can be exact, because `assistant_usage_events` records what
# GitHub actually charged rather than what a rate table implies.
#
#   billed   - `total_nano_aiu`, GitHub's own per-call charge. Exact.
#   rates    - priced from the per-token-type rates in `token_details_json`,
#              i.e. the rates GitHub applied to that specific call (promotions,
#              auto-select discount and long-context tier already baked in).
#              Exact to the cent.
#   estimate - priced from the published table in model_pricing.py, for rows
#              written by a CLI build that predates these columns.
COST_SOURCE_BILLED = "billed"
COST_SOURCE_RATES = "rates"
COST_SOURCE_ESTIMATE = "estimate"
EXACT_COST_SOURCES = (COST_SOURCE_BILLED, COST_SOURCE_RATES)


def _month_key_from_epoch_ms(ts_ms: float | int | None) -> str | None:
    if not ts_ms:
        return None
    try:
        return datetime.fromtimestamp(float(ts_ms) / 1000.0).strftime("%Y-%m")
    except Exception:
        return None


def _day_key_from_epoch_ms(ts_ms: float | int | None) -> str | None:
    if not ts_ms:
        return None
    try:
        return datetime.fromtimestamp(float(ts_ms) / 1000.0).strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_token_details(raw: str | None) -> dict[str, Any] | None:
    """Decode one `assistant_usage_events.token_details_json` value.

    The CLI writes one entry per billed token category, carrying both the token
    count and the rate GitHub charged for it:

        [{"batchSize": 1000000, "costPerBatch": 200000000000,
          "tokenCount": 2, "tokenType": "input"}, ...]

    `costPerBatch` is in nano AIU per `batchSize` tokens. Summing
    `tokenCount / batchSize * costPerBatch` over the entries reproduces
    `total_nano_aiu` exactly, so these are the real rates for the call - not
    the published list price, which may differ by a promotion, the auto model
    selection discount, or a long-context tier.

    Returns {"counts", "rates", "cost"} - rates in USD per 1M tokens, cost in
    USD - or None when the column is absent or unusable.
    """
    if not raw:
        return None
    try:
        entries = json.loads(raw)
    except Exception:
        return None
    if not isinstance(entries, list):
        return None

    counts: dict[str, float] = {}
    rates: dict[str, float] = {}
    cost = 0.0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        token_type = str(entry.get("tokenType") or "")
        if token_type not in TOKEN_TYPES:
            continue
        try:
            batch_size = float(entry.get("batchSize") or 0.0)
            cost_per_batch = float(entry.get("costPerBatch") or 0.0)
            tokens = float(entry.get("tokenCount") or 0.0)
        except (TypeError, ValueError):
            continue
        if batch_size <= 0:
            continue
        counts[token_type] = counts.get(token_type, 0.0) + tokens
        rates[token_type] = nano_aiu_to_usd(cost_per_batch) / batch_size * 1_000_000.0
        cost += nano_aiu_to_usd(tokens / batch_size * cost_per_batch)

    if not counts:
        return None
    return {"counts": counts, "rates": rates, "cost": cost}


def _event_cost(
    model_name: str,
    prompt_tokens: float,
    output_tokens: float,
    cache_read_tokens: float,
    cache_write_tokens: float,
    nano_aiu: float | int | None,
    token_details_json: str | None,
) -> dict[str, Any]:
    """Cost one usage event, preferring GitHub's billed figure over any estimate.

    Returns {"cost", "byType", "counts", "source"}. `counts` holds the billed
    token categories (so `counts["input"]` is the uncached prompt remainder),
    and `byType` splits the cost across those same categories so the UI can
    show where the money went without re-deriving it from rates.
    """
    detail = _parse_token_details(token_details_json)

    if detail is not None:
        counts = dict(detail["counts"])
        by_type = cost_from_token_counts(counts, model_name, rates=detail["rates"])["byType"]
        cost = detail["cost"]
        source = COST_SOURCE_RATES
    else:
        counts = split_prompt_tokens(prompt_tokens, cache_read_tokens, cache_write_tokens)
        counts["output"] = float(output_tokens or 0.0)
        priced = calculate_cost(
            prompt_tokens,
            output_tokens,
            cache_read_tokens,
            model_name,
            cache_write_tokens=cache_write_tokens,
        )
        by_type = priced["costByType"]
        cost = priced["cost"]
        source = COST_SOURCE_ESTIMATE

    # `total_nano_aiu` is the charge itself, so it wins outright. The component
    # split stays proportional to whatever we could price, scaled to agree with
    # the billed total, so `sum(byType) == cost` always holds.
    if nano_aiu is not None:
        billed = nano_aiu_to_usd(nano_aiu)
        if cost > 0:
            scale = billed / cost
            by_type = {key: value * scale for key, value in by_type.items()}
        elif billed:
            # Nothing to scale (every rate we know resolved to zero) but GitHub
            # still charged for the call, so split the charge across the token
            # counts we do have rather than reporting a total that its own
            # components contradict.
            weights = {key: max(0.0, float(counts.get(key) or 0.0)) for key in TOKEN_TYPES}
            total_weight = sum(weights.values())
            if total_weight:
                by_type = {key: billed * weight / total_weight for key, weight in weights.items()}
            else:
                by_type = {key: (billed if key == "output" else 0.0) for key in TOKEN_TYPES}
        cost = billed
        source = COST_SOURCE_BILLED

    counts.setdefault("output", float(output_tokens or 0.0))
    return {
        "cost": cost,
        "byType": {key: float(by_type.get(key) or 0.0) for key in TOKEN_TYPES},
        "counts": {key: float(counts.get(key) or 0.0) for key in TOKEN_TYPES},
        "source": source,
    }


def _new_cost_accumulator() -> dict[str, Any]:
    """Zeroed cost/token accumulator shared by the session, model and period rollups."""
    return {
        "cost": 0.0,
        "costByType": {key: 0.0 for key in TOKEN_TYPES},
        "sources": {COST_SOURCE_BILLED: 0, COST_SOURCE_RATES: 0, COST_SOURCE_ESTIMATE: 0},
    }


def _add_cost(target: dict[str, Any], priced: dict[str, Any]) -> None:
    """Fold one priced event (or one already-rolled-up bucket) into `target`."""
    target["cost"] += float(priced.get("cost") or 0.0)
    for key, value in (priced.get("costByType") or priced.get("byType") or {}).items():
        if key in target["costByType"]:
            target["costByType"][key] += float(value or 0.0)
    source = priced.get("source")
    if source:
        target["sources"][source] = target["sources"].get(source, 0) + 1
    # `sources` on a raw accumulator, `costSources` once _cost_fields has
    # rendered it onto a payload row - period rollups fold the latter.
    for key, count in (priced.get("sources") or priced.get("costSources") or {}).items():
        target["sources"][key] = target["sources"].get(key, 0) + int(count or 0)


def _cost_fields(accumulated: dict[str, Any]) -> dict[str, Any]:
    """Render an accumulator into the payload keys the front-end reads.

    `costSource` is the single source when every call in the bucket agrees,
    "mixed" when they do not, so the UI can label a figure exact without
    claiming exactness for a bucket that fell back for some of its calls.
    """
    sources = {key: int(value or 0) for key, value in (accumulated.get("sources") or {}).items() if value}
    used = sorted(sources, key=lambda key: sources[key], reverse=True)
    cost = float(accumulated.get("cost") or 0.0)
    return {
        "cost": cost,
        "costByType": {key: float(value or 0.0) for key, value in (accumulated.get("costByType") or {}).items()},
        "costSource": (used[0] if len(used) == 1 else "mixed") if used else COST_SOURCE_ESTIMATE,
        "costSources": sources,
        "costExact": bool(used) and all(key in EXACT_COST_SOURCES for key in used),
        "credits": cost / AIU_USD,
    }


def _build_cli_period_bundle(sessions_subset: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a {"summary", "byModel"} bundle for a subset of CLI sessions_out rows.

    Mirrors the shape of the chat pipeline's period bundles closely enough
    for the CLI tab to support "this month" / "all time" filtering, without
    touching any existing `cli["..."]` key.

    Costs are SUMMED from the per-call figures already on those rows, never
    re-derived from the aggregated token counts: the exact cost of a bucket is
    the sum of what GitHub charged for each call in it, and re-pricing a
    month's worth of tokens in one go would throw that away (and silently mix
    tiers, promotions and discounts that differ call to call).
    """
    model_totals: dict[str, dict[str, Any]] = collections.defaultdict(
        lambda: {
            "input": 0.0, "inputBillable": 0.0, "output": 0.0, "cached": 0.0,
            "cacheWrite": 0.0, "calls": 0, "sessionIds": set(),
            **_new_cost_accumulator(),
        }
    )
    totals = _new_cost_accumulator()
    total_input = 0.0
    total_input_billable = 0.0
    total_output = 0.0
    total_cached = 0.0
    total_cache_write = 0.0
    total_calls = 0
    total_tool_calls = 0
    file_paths: set[str] = set()

    for session in sessions_subset:
        _add_cost(totals, session)
        total_input += float(session.get("input", 0.0) or 0.0)
        total_input_billable += float(session.get("inputBillable", 0.0) or 0.0)
        total_output += float(session.get("output", 0.0) or 0.0)
        total_cached += float(session.get("cached", 0.0) or 0.0)
        total_cache_write += float(session.get("cacheWrite", 0.0) or 0.0)
        total_calls += int(session.get("callCount", 0) or 0)
        total_tool_calls += sum(int(tool.get("calls", 0) or 0) for tool in session.get("tools", []) or [])
        for file_row in session.get("files", []) or []:
            path = file_row.get("path")
            if path:
                file_paths.add(path)
        for row in session.get("modelBreakdown", []) or []:
            model_name = str(row.get("model") or "unknown")
            bucket = model_totals[model_name]
            bucket["input"] += float(row.get("input", 0.0) or 0.0)
            bucket["inputBillable"] += float(row.get("inputBillable", 0.0) or 0.0)
            bucket["output"] += float(row.get("output", 0.0) or 0.0)
            bucket["cached"] += float(row.get("cached", 0.0) or 0.0)
            bucket["cacheWrite"] += float(row.get("cacheWrite", 0.0) or 0.0)
            bucket["calls"] += int(row.get("calls", 0) or 0)
            bucket["sessionIds"].add(session.get("id"))
            _add_cost(bucket, row)

    by_model = []
    for model_name, bucket in model_totals.items():
        by_model.append({
            "model": model_name,
            "calls": bucket["calls"],
            "sessionCount": len(bucket["sessionIds"]),
            "input": bucket["input"],
            "inputBillable": bucket["inputBillable"],
            "uncached": bucket["inputBillable"],
            "cached": bucket["cached"],
            "cacheWrite": bucket["cacheWrite"],
            "output": bucket["output"],
            **_cost_fields(bucket),
        })
    by_model.sort(key=lambda row: row["cost"], reverse=True)

    cost_fields = _cost_fields(totals)
    return {
        "summary": {
            "sessionCount": len(sessions_subset),
            "callCount": total_calls,
            "totalInput": total_input,
            "totalOutput": total_output,
            "totalCached": total_cached,
            "totalCacheWrite": total_cache_write,
            "totalUncached": total_input_billable,
            "totalInputBillable": total_input_billable,
            "totalCost": cost_fields["cost"],
            "totalCredits": cost_fields["credits"],
            "costByType": cost_fields["costByType"],
            "costSource": cost_fields["costSource"],
            "costSources": cost_fields["costSources"],
            "costExact": cost_fields["costExact"],
            "fileCount": len(file_paths),
            "toolCallCount": total_tool_calls,
        },
        "byModel": by_model,
    }


def default_cli_db_path() -> str | None:
    """Return the local GitHub Copilot CLI session-store.db path, if it exists."""
    override = os.environ.get("COPILOT_CLI_DB")
    if override:
        return override
    candidate = os.path.join(os.path.expanduser("~"), ".copilot", "session-store.db")
    return candidate if os.path.isfile(candidate) else None


def default_cli_otel_paths() -> list[str]:
    """Return the CLI's OpenTelemetry file-exporter JSONL path(s), if any exist.

    The CLI writes these only when OTel export is enabled with the `file`
    exporter (see `copilot help monitoring`), configured via
    `COPILOT_OTEL_FILE_EXPORTER_PATH`. With the default `otlp-http` exporter the
    data goes to a collector instead and none of it lands on disk.

    The export carries OTel GenAI *spans* (`chat`, `execute_tool`) and
    *metrics* (token counters and, where the build emits them, spend counters).
    It is an enrichment and cross-check layer: per-call cost comes from
    session-store.db, which records what GitHub actually billed.

    Accepts a file, a directory, a glob, or several of those separated by the
    platform path separator, because the exporter may be pointed at a rotating
    directory rather than one file.
    """
    override = os.environ.get("COPILOT_OTEL_FILE_EXPORTER_PATH")
    candidates = override.split(os.pathsep) if override else []
    candidates.append(os.path.join(os.path.expanduser("~"), ".copilot", "otel"))

    paths: list[str] = []
    for candidate in candidates:
        candidate = (candidate or "").strip().strip('"')
        if not candidate:
            continue
        if os.path.isfile(candidate):
            paths.append(candidate)
        elif os.path.isdir(candidate):
            paths.extend(
                sorted(
                    os.path.join(candidate, name)
                    for name in os.listdir(candidate)
                    if name.endswith((".jsonl", ".json", ".log"))
                    and os.path.isfile(os.path.join(candidate, name))
                )
            )
        elif any(char in candidate for char in "*?["):
            paths.extend(sorted(path for path in glob.glob(candidate) if os.path.isfile(path)))

    # Preserve discovery order while dropping duplicates.
    return list(dict.fromkeys(paths))


def _otel_timestamp_to_epoch_ms(value: Any) -> float:
    """Convert an OTel [seconds, nanoseconds] timestamp pair to epoch milliseconds."""
    try:
        seconds, nanos = value
        return float(seconds) * 1000 + float(nanos) / 1e6
    except Exception:
        return 0.0


# OTel attribute keys that identify the conversation a record belongs to. The
# GenAI convention is `gen_ai.conversation.id`; the CLI also stamps its own
# session id on some records.
_OTEL_SESSION_KEYS = (
    "gen_ai.conversation.id",
    "gen_ai.session.id",
    "copilot.session.id",
    "session.id",
    "session_id",
)

# Attribute keys naming the billed token category of a token data point, and
# the mapping from the values they carry onto TOKEN_TYPES. `gen_ai.token.type`
# is the convention's key; the values vary by emitter, so both the GenAI
# spellings ("input"/"output") and the provider spellings this repo already
# uses ("cache_read"/"cache_write") are accepted.
_OTEL_TOKEN_TYPE_KEYS = ("gen_ai.token.type", "token.type", "type", "kind")
_OTEL_TOKEN_TYPE_ALIASES = {
    "input": "input",
    "prompt": "input",
    "uncached": "input",
    "uncached_input": "input",
    "output": "output",
    "completion": "output",
    "cache_read": "cache_read",
    "cacheread": "cache_read",
    "cached": "cache_read",
    "cache_read_input": "cache_read",
    "cache_write": "cache_write",
    "cachewrite": "cache_write",
    "cache_creation": "cache_write",
    "cache_write_input": "cache_write",
    "reasoning": "output",
}

# The same aliases, longest-marker-first, for the case where the category is
# baked into the instrument name instead of carried as an attribute. Order is
# load-bearing: "cache_read_input_tokens" contains "input", so a shorter marker
# checked first would file cache reads as uncached input.
_OTEL_TOKEN_TYPE_NAME_MARKERS = sorted(_OTEL_TOKEN_TYPE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)

# Span attributes carrying per-call token counts, per the GenAI conventions.
_OTEL_SPAN_TOKEN_ATTRS = {
    "gen_ai.usage.input_tokens": "input",
    "gen_ai.usage.prompt_tokens": "input",
    "gen_ai.usage.output_tokens": "output",
    "gen_ai.usage.completion_tokens": "output",
    "gen_ai.usage.cache_read_input_tokens": "cache_read",
    "gen_ai.usage.cached_input_tokens": "cache_read",
    "gen_ai.usage.cache_creation_input_tokens": "cache_write",
    "gen_ai.usage.cache_write_input_tokens": "cache_write",
}

# Units, lower-cased, that a spend instrument or attribute may be denominated
# in, mapped to their USD value. Anything else is reported raw and never
# silently treated as money.
_OTEL_SPEND_UNITS = {
    "usd": 1.0,
    "{usd}": 1.0,
    "us_dollar": 1.0,
    "credit": AIU_USD,
    "{credit}": AIU_USD,
    "credits": AIU_USD,
    "aiu": AIU_USD,
    "{aiu}": AIU_USD,
    "nano_aiu": nano_aiu_to_usd(1),
    "{nano_aiu}": nano_aiu_to_usd(1),
    "naiu": nano_aiu_to_usd(1),
}


def _otel_attributes(raw: Any) -> dict[str, Any]:
    """Normalise an OTel attribute collection into a flat dict.

    Exporters emit these either as a plain object or as the protobuf-shaped
    list of `{"key": ..., "value": {"stringValue": ...}}` entries, so both are
    accepted.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, list):
        return {}
    flat: dict[str, Any] = {}
    for item in raw:
        if not isinstance(item, dict) or "key" not in item:
            continue
        value = item.get("value")
        if isinstance(value, dict):
            for wrapper in ("stringValue", "intValue", "doubleValue", "boolValue", "asString", "asInt", "asDouble"):
                if wrapper in value:
                    value = value[wrapper]
                    break
        flat[str(item["key"])] = value
    return flat


def _otel_session_id(attrs: dict[str, Any]) -> str | None:
    for key in _OTEL_SESSION_KEYS:
        value = attrs.get(key)
        if value:
            return str(value)
    return None


def _otel_number(value: Any) -> float | None:
    """Coerce an OTel data-point value to a float, or None if it is not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _otel_data_points(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the data-point list out of a metric record, whatever it is called.

    File exporters disagree on the envelope: the points may sit directly under
    the record, or nested under `sum`/`gauge`/`histogram`, and the key may be
    `dataPoints`, `data_points` or `points`.
    """
    containers = [record]
    for key in ("sum", "gauge", "histogram", "exponentialHistogram", "data"):
        nested = record.get(key)
        if isinstance(nested, dict):
            containers.append(nested)
    for container in containers:
        for key in ("dataPoints", "data_points", "points"):
            points = container.get(key)
            if isinstance(points, list):
                return [point for point in points if isinstance(point, dict)]
    return []


def _otel_point_value(point: dict[str, Any]) -> float | None:
    """Extract the numeric value of one data point.

    Counters expose `value`/`asDouble`/`asInt`; histograms only carry `sum` and
    `count`, and for token or spend totals the sum is the quantity we want.
    """
    for key in ("value", "asDouble", "asInt", "as_double", "as_int", "sum"):
        number = _otel_number(point.get(key))
        if number is not None:
            return number
    return None


def _otel_metric_kind(name: str) -> str | None:
    """Classify an instrument by name: "token", "spend", or None for neither.

    Matching is on the name because instrument names differ across CLI builds
    (and are not in the published docs). Whatever the build emits, every
    instrument seen is reported back in `instruments` so the dashboard can show
    what was actually available rather than guessing silently.
    """
    lowered = name.lower()
    if "token" in lowered:
        return "token"
    if any(marker in lowered for marker in ("aiu", "credit", "cost", "spend", "billing", "charge")):
        return "spend"
    return None


def parse_cli_otel_files(paths: list[str] | None) -> dict[str, Any]:
    """Parse CLI OTel file-exporter JSONL export(s): `execute_tool` and chat spans, plus metrics.

    Returns, in addition to the original
    {"available", "paths", "tools", "toolsBySession"}:

      "tokensBySession"  per-conversation billed token counts read off chat
                         spans and per-session token metrics
      "tokens"           those counts summed
      "spend"            {"usd", "instrument", "unit", "raw"} when the export
                         carries a spend instrument in a unit that converts to
                         money, else {"usd": None, ...}
      "instruments"      every metric instrument seen, with unit and total, so
                         the dashboard can report what the export actually
                         offers instead of failing silently on a build whose
                         instrument names differ
      "recordCounts"     {"span", "metric", "other"} record tallies

    Nothing here overrides cost: `assistant_usage_events.total_nano_aiu` is
    what GitHub charged, so OTel serves as coverage for tool timings and as an
    independent cross-check (see `otelReconciliation` in the payload). Missing
    or unreadable files and malformed lines are skipped - this stays a
    best-effort layer, never a hard dependency.
    """
    global_tools: dict[str, dict[str, Any]] = collections.defaultdict(
        lambda: {"calls": 0, "durationMs": 0.0, "sessionIds": set()}
    )
    tools_by_session: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(
        lambda: collections.defaultdict(lambda: {"calls": 0, "durationMs": 0.0})
    )
    tokens_by_session: dict[str, dict[str, float]] = collections.defaultdict(
        lambda: {key: 0.0 for key in TOKEN_TYPES}
    )
    instruments: dict[str, dict[str, Any]] = {}
    spend_totals: dict[str, dict[str, Any]] = {}
    record_counts = {"span": 0, "metric": 0, "other": 0}
    parsed_any = False
    used_paths: list[str] = []

    token_totals = {key: 0.0 for key in TOKEN_TYPES}

    def note_tokens(session_id: str | None, token_type: str, amount: float) -> None:
        """Record a billed token count, per session when known and always in total.

        A data point without a conversation attribute still tells us how many
        tokens the export saw, and dropping it would make the OTel-vs-DB
        reconciliation look like missing usage rather than missing labelling.
        """
        if token_type not in TOKEN_TYPES or not amount:
            return
        token_totals[token_type] += float(amount)
        if session_id:
            tokens_by_session[session_id][token_type] += float(amount)

    for path in paths or []:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        # OTel is per-tool insight and a cross-check only; it can
                        # never move a cost figure (see the README on the CLI OTel
                        # exporter). Recorded at impact "none" so a half-flushed
                        # JSONL tail stays visible without implying the totals are
                        # wrong - the banner keys on cost impact, not severity.
                        diagnostics.report(
                            diagnostics.CODE_OTEL_LINE_SKIPPED,
                            "Skipped an unparsable line in the CLI OTel log. Cost figures are unaffected.",
                            severity="info",
                            impact="none",
                            source=path,
                        )
                        continue
                    if not isinstance(entry, dict):
                        continue

                    record_type = str(entry.get("type") or "")
                    name = str(entry.get("name") or "")
                    attrs = _otel_attributes(entry.get("attributes"))

                    if record_type == "span":
                        record_counts["span"] += 1
                        parsed_any = True
                        used_paths.append(path)
                        session_id = _otel_session_id(attrs)
                        duration_ms = max(
                            0.0,
                            _otel_timestamp_to_epoch_ms(entry.get("endTime")) - _otel_timestamp_to_epoch_ms(entry.get("startTime")),
                        )

                        if name.startswith("execute_tool"):
                            tool_name = attrs.get("gen_ai.tool.name") or name[len("execute_tool "):].strip() or "unknown"
                            gtotal = global_tools[tool_name]
                            gtotal["calls"] += 1
                            gtotal["durationMs"] += duration_ms
                            if session_id:
                                gtotal["sessionIds"].add(session_id)
                                sbucket = tools_by_session[session_id][tool_name]
                                sbucket["calls"] += 1
                                sbucket["durationMs"] += duration_ms
                            continue

                        # Any other span may still carry GenAI usage attributes
                        # (`chat <model>` spans do).
                        for attr_key, token_type in _OTEL_SPAN_TOKEN_ATTRS.items():
                            amount = _otel_number(attrs.get(attr_key))
                            if amount is not None:
                                note_tokens(session_id, token_type, amount)
                        continue

                    if record_type != "metric":
                        record_counts["other"] += 1
                        continue

                    record_counts["metric"] += 1
                    parsed_any = True
                    used_paths.append(path)
                    unit = str(entry.get("unit") or entry.get("units") or "")
                    kind = _otel_metric_kind(name)
                    points = _otel_data_points(entry)

                    instrument = instruments.setdefault(
                        name, {"instrument": name, "unit": unit, "kind": kind, "points": 0, "total": 0.0}
                    )

                    for point in points:
                        value = _otel_point_value(point)
                        if value is None:
                            continue
                        point_attrs = {**attrs, **_otel_attributes(point.get("attributes"))}
                        instrument["points"] += 1
                        instrument["total"] += value

                        if kind == "token":
                            raw_type = next(
                                (str(point_attrs[key]) for key in _OTEL_TOKEN_TYPE_KEYS if point_attrs.get(key)),
                                "",
                            )
                            token_type = _OTEL_TOKEN_TYPE_ALIASES.get(raw_type.lower().replace("-", "_"))
                            if token_type is None:
                                # Fall back to the instrument name when the
                                # category is baked into it instead of carried
                                # as an attribute.
                                token_type = next(
                                    (alias for marker, alias in _OTEL_TOKEN_TYPE_NAME_MARKERS if marker in name.lower()),
                                    None,
                                )
                            note_tokens(_otel_session_id(point_attrs), token_type or "", value)
                        elif kind == "spend":
                            point_unit = str(point_attrs.get("unit") or unit or "").lower()
                            bucket = spend_totals.setdefault(
                                name, {"instrument": name, "unit": point_unit or unit, "raw": 0.0}
                            )
                            bucket["raw"] += value
        except Exception as exc:
            # Whole-file drop, not a single line: an unreadable export or an
            # unexpected OTel envelope shape loses the entire per-tool
            # cross-check for this file. Still impact "none" because OTel never
            # moves a cost figure, but a warning rather than info - the tool
            # breakdown and the OTel-vs-DB reconciliation will silently look
            # thinner than reality, and only this says why.
            diagnostics.report(
                diagnostics.CODE_OTEL_FILE_SKIPPED,
                f"Could not read the CLI OTel log, so its per-tool breakdown is missing. Cost figures are unaffected: {exc}",
                severity="warning",
                impact="none",
                source=path,
            )
            continue

    tools_out = sorted(
        (
            {
                "tool": tool_name,
                "calls": data["calls"],
                "totalDurationMs": data["durationMs"],
                "avgDurationMs": (data["durationMs"] / data["calls"]) if data["calls"] else 0.0,
                "sessionCount": len(data["sessionIds"]),
            }
            for tool_name, data in global_tools.items()
        ),
        key=lambda row: row["calls"],
        reverse=True,
    )

    tools_by_session_out = {
        session_id: sorted(
            (
                {
                    "tool": tool_name,
                    "calls": data["calls"],
                    "totalDurationMs": data["durationMs"],
                    "avgDurationMs": (data["durationMs"] / data["calls"]) if data["calls"] else 0.0,
                }
                for tool_name, data in tools.items()
            ),
            key=lambda row: row["calls"],
            reverse=True,
        )
        for session_id, tools in tools_by_session.items()
    }

    tokens_by_session_out = {
        session_id: dict(counts)
        for session_id, counts in tokens_by_session.items()
        if any(counts.values())
    }
    # Only convert a spend instrument to money when its unit says what it is.
    # An unrecognised unit is reported raw rather than guessed at, because a
    # wrong factor here would be indistinguishable from a real cost.
    spend: dict[str, Any] = {"usd": None, "instrument": None, "unit": None, "raw": None}
    for bucket in spend_totals.values():
        factor = _OTEL_SPEND_UNITS.get(str(bucket.get("unit") or "").lower())
        if factor is None:
            continue
        spend = {
            "usd": float(bucket["raw"]) * factor,
            "instrument": bucket["instrument"],
            "unit": bucket["unit"],
            "raw": float(bucket["raw"]),
        }
        break
    if spend["instrument"] is None and spend_totals:
        first = sorted(spend_totals)[0]
        spend = {
            "usd": None,
            "instrument": spend_totals[first]["instrument"],
            "unit": spend_totals[first]["unit"],
            "raw": float(spend_totals[first]["raw"]),
        }

    return {
        "available": parsed_any,
        "paths": sorted(set(used_paths)) or [p for p in (paths or []) if p],
        "tools": tools_out,
        "toolsBySession": tools_by_session_out,
        "tokensBySession": tokens_by_session_out,
        "tokens": token_totals,
        "spend": spend,
        "instruments": sorted(instruments.values(), key=lambda row: row["instrument"]),
        "recordCounts": record_counts,
    }


def _iso_to_epoch_ms(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp() * 1000
    except Exception:
        return 0.0


def _reconcile_otel(
    otel_data: dict[str, Any],
    db_tokens: dict[str, float],
    db_cost_usd: float,
) -> dict[str, Any]:
    """Cross-check the OTel export against the billed figures from the DB.

    Two independent records of the same sessions should agree; where they do
    not, the delta is worth surfacing rather than hiding, because it means one
    side is incomplete (an export that started mid-session, a session the
    collector never received, or a DB row written by a build that did not yet
    record billing). The DB stays authoritative either way - this only reports.

    Returns {"available", "tokens": {type: {...}}, "spend": {...}} with an
    absolute and relative delta per compared quantity.
    """
    if not otel_data.get("available"):
        return {"available": False, "tokens": {}, "spend": {}}

    def delta(otel_value: float | None, db_value: float | None) -> dict[str, Any]:
        otel_number = None if otel_value is None else float(otel_value)
        db_number = None if db_value is None else float(db_value)
        row: dict[str, Any] = {"otel": otel_number, "db": db_number, "delta": None, "deltaPct": None}
        if otel_number is None or db_number is None:
            return row
        row["delta"] = otel_number - db_number
        if db_number:
            row["deltaPct"] = (otel_number - db_number) / db_number * 100.0
        return row

    otel_tokens = otel_data.get("tokens") or {}
    tokens = {
        token_type: delta(otel_tokens.get(token_type), db_tokens.get(token_type))
        for token_type in TOKEN_TYPES
        if otel_tokens.get(token_type)
    }
    spend_usd = (otel_data.get("spend") or {}).get("usd")
    return {
        "available": True,
        "tokens": tokens,
        "spend": {
            **delta(spend_usd, db_cost_usd),
            "instrument": (otel_data.get("spend") or {}).get("instrument"),
            "unit": (otel_data.get("spend") or {}).get("unit"),
        },
    }


# Why the `cli` block came back unavailable. Consumed by the UI to explain
# itself; see `empty_cli_payload`. Defined above it because it supplies the
# default argument, which is evaluated at definition time.
REASON_DB_ABSENT = "db_absent"          # never used the CLI - benign, stay quiet
REASON_DB_LOCKED = "db_locked"          # in use by another process - retryable
REASON_DB_UNREADABLE = "db_unreadable"  # exists, cannot be opened at all
REASON_QUERY_FAILED = "query_failed"    # opened, but the schema/query broke


def empty_cli_payload(
    db_path: str | None,
    reason: str = REASON_DB_ABSENT,
    reason_detail: str = "",
) -> dict[str, Any]:
    """The `cli` block for "no usable session-store.db", in the full shape.

    Every key the front-end and the compact-cache writer read has to be present
    even when there is nothing to report, so they can render "unavailable"
    instead of tripping over a missing key.

    `available: False` alone cannot distinguish three very different situations:
    the user has never run the CLI (entirely normal), the database is locked by
    a running `copilot` process (transient, worth retrying), or a query failed
    against an unexpected schema (a bug worth reporting). Since CLI figures are
    the *exact* ones, "we could not read your billing data" must not look like
    "you have no billing data". `reason` carries that distinction to the UI;
    `available` keeps its old meaning for existing callers.
    """
    return {
        "available": False,
        "reason": reason,
        "reasonDetail": reason_detail,
        "dbPath": db_path,
        "sessions": [],
        "byModel": [],
        "files": [],
        "tools": [],
        "otelAvailable": False,
        "otelPaths": [],
        "otel": {},
        "otelReconciliation": {},
        "summary": {},
        "periods": {
            "default": "monthly",
            "labels": {},
            "allTime": {"summary": {}, "byModel": []},
            "monthly": {"monthKey": None, "summary": {}, "byModel": []},
        },
    }


# Columns added to `assistant_usage_events` by later CLI builds. Selected
# separately so an older DB without them still loads (and falls back to
# published-rate estimates) instead of raising OperationalError.
_BILLING_COLUMNS = ("total_nano_aiu", "request_multiplier", "token_details_json")


def _available_columns(cursor: sqlite3.Cursor, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in cursor.execute(f"PRAGMA table_info({table})")}
    except Exception:
        return set()


def build_cli_dashboard_data(
    db_path: str | None = None,
    otel_log_paths: list[str] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Read GitHub Copilot CLI local usage from session-store.db (read-only).

    Returns a JSON-serializable structure independent from the VS Code
    debug-log pipeline: {"available": bool, "dbPath", "sessions": [...],
    "byModel": [...], "tools": [...], "otelAvailable", "summary": {...}}.
    If an OTel JSONL export is available (see `default_cli_otel_paths`), it
    enriches sessions and the summary with real per-tool call telemetry, and
    `otelReconciliation` cross-checks its token/spend counters against the DB.

    COST IS EXACT HERE, not estimated. `assistant_usage_events` records what
    GitHub billed for each call - `total_nano_aiu`, plus the rates it applied in
    `token_details_json` - so every cost figure below is summed from those
    per-call charges rather than re-derived from a rate table. `costSource` /
    `costExact` on each row say which basis was used, and the published table in
    model_pricing.py only backstops rows written before those columns existed.
    See `_event_cost`.

    `now_ms` is an optional epoch-milliseconds time-injection seam for the
    "current calendar month" the `periods.monthly` bucket is built from
    (and its label). It defaults to the live wall clock so every existing
    caller is unaffected; tests can pass a frozen `now_ms` instead of relying
    on real-clock-relative fixtures.
    """
    now = datetime.fromtimestamp(float(now_ms) / 1000.0) if now_ms else datetime.now()
    resolved_db_path = db_path or default_cli_db_path()
    if not resolved_db_path or not os.path.isfile(resolved_db_path):
        # No database at all: the overwhelmingly common cause is simply never
        # having used the CLI. Benign, and deliberately not a diagnostic.
        return empty_cli_payload(resolved_db_path, REASON_DB_ABSENT)

    try:
        # Read-only URI connection avoids taking a write lock on the live CLI DB.
        con = sqlite3.connect(f"file:{resolved_db_path}?mode=ro", uri=True, timeout=5)
    except Exception:
        try:
            con = sqlite3.connect(resolved_db_path, timeout=5)
        except Exception as exc:
            # The file is on disk but will not open. Distinguish "locked by a
            # running copilot process" (retryable) from anything else, because
            # the advice differs and both used to look like "no CLI data".
            locked = "lock" in str(exc).lower() or isinstance(exc, sqlite3.OperationalError)
            reason = REASON_DB_LOCKED if locked else REASON_DB_UNREADABLE
            diagnostics.report(
                diagnostics.CODE_CLI_DB_LOCKED if locked else diagnostics.CODE_CLI_QUERY_FAILED,
                (
                    "Could not open the Copilot CLI database, so exact billed CLI "
                    f"costs are missing from the totals: {exc}"
                ),
                severity="error",
                impact="cost",
                source=resolved_db_path,
            )
            return empty_cli_payload(resolved_db_path, reason, str(exc))

    try:
        cur = con.cursor()

        cur.execute("SELECT id, cwd, repository, branch, summary, created_at, updated_at FROM sessions")
        session_rows = cur.fetchall()
        session_meta: dict[str, dict[str, Any]] = {}
        for session_id, cwd, repository, branch, summary, created_at, updated_at in session_rows:
            session_meta[session_id] = {
                "id": session_id,
                "cwd": cwd,
                "repository": repository,
                "branch": branch,
                "summary": summary,
                "createdAt": _iso_to_epoch_ms(created_at),
                "updatedAt": _iso_to_epoch_ms(updated_at),
            }

        billing_columns = [name for name in _BILLING_COLUMNS if name in _available_columns(cur, "assistant_usage_events")]
        cur.execute(
            "SELECT session_id, turn_index, model, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, reasoning_tokens, duration_ms, created_at"
            + ("".join(f", {name}" for name in billing_columns))
            + " FROM assistant_usage_events"
        )
        event_rows = cur.fetchall()
        # Positional access below would break the moment a column is absent, so
        # the optional billing columns are addressed by name.
        billing_index = {name: 10 + offset for offset, name in enumerate(billing_columns)}

        cur.execute("SELECT session_id, MAX(turn_index) FROM turns GROUP BY session_id")
        turn_counts = {session_id: (max_turn or 0) + 1 for session_id, max_turn in cur.fetchall()}

        cur.execute("SELECT session_id, file_path, tool_name, first_seen_at FROM session_files")
        file_rows = cur.fetchall()

        cur.execute(
            "SELECT session_id, turn_index, user_message, assistant_response, timestamp "
            "FROM turns ORDER BY session_id, turn_index"
        )
        turn_rows = cur.fetchall()
    finally:
        con.close()

    resolved_otel_paths = otel_log_paths if otel_log_paths is not None else default_cli_otel_paths()
    otel_data = parse_cli_otel_files(resolved_otel_paths)

    files_by_session: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(
        lambda: collections.defaultdict(lambda: {"path": "", "created": 0, "edited": 0, "lastTouched": 0.0})
    )
    for session_id, file_path, tool_name, first_seen_at in file_rows:
        session_entry = files_by_session[session_id][file_path]
        session_entry["path"] = file_path
        if tool_name == "create":
            session_entry["created"] += 1
        else:
            session_entry["edited"] += 1
        session_entry["lastTouched"] = max(session_entry["lastTouched"], _iso_to_epoch_ms(first_seen_at))

    files_by_session_out = {
        session_id: sorted(
            (
                {
                    "path": entry["path"],
                    "created": entry["created"],
                    "edited": entry["edited"],
                    "touches": entry["created"] + entry["edited"],
                    "lastTouched": entry["lastTouched"],
                }
                for entry in files.values()
            ),
            key=lambda row: row["touches"],
            reverse=True,
        )
        for session_id, files in files_by_session.items()
    }

    _TURN_PREVIEW_LIMIT = 800
    turns_by_session: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for session_id, turn_index, user_message, assistant_response, timestamp in turn_rows:
        user_text = str(user_message or "")
        assistant_text = str(assistant_response or "")
        turns_by_session[session_id].append({
            "turnIndex": turn_index,
            "timestamp": _iso_to_epoch_ms(timestamp),
            "userMessage": user_text[:_TURN_PREVIEW_LIMIT],
            "userMessageTruncated": len(user_text) > _TURN_PREVIEW_LIMIT,
            "assistantResponse": assistant_text[:_TURN_PREVIEW_LIMIT],
            "assistantResponseTruncated": len(assistant_text) > _TURN_PREVIEW_LIMIT,
        })

    def _new_token_bucket(with_session_ids: bool = False) -> dict[str, Any]:
        bucket = {
            "input": 0.0, "inputBillable": 0.0, "output": 0.0, "cached": 0.0,
            "cacheWrite": 0.0, "reasoning": 0.0, "calls": 0, "durationMs": 0.0,
            **_new_cost_accumulator(),
        }
        if with_session_ids:
            bucket["sessionIds"] = set()
        return bucket

    per_session: dict[str, dict[str, Any]] = {}
    per_session_model: dict[tuple[str, str], dict[str, Any]] = collections.defaultdict(_new_token_bucket)
    model_totals: dict[str, dict[str, Any]] = collections.defaultdict(lambda: _new_token_bucket(with_session_ids=True))

    for row in event_rows:
        session_id, turn_index, model, input_tokens, output_tokens, cache_read, cache_write, reasoning, duration_ms, created_at = row[:10]
        model_name = model or "unknown"
        nano_aiu = row[billing_index["total_nano_aiu"]] if "total_nano_aiu" in billing_index else None
        token_details_json = row[billing_index["token_details_json"]] if "token_details_json" in billing_index else None

        # Price the call on its own: rates, promotions and long-context tiers
        # apply per call, so aggregating tokens first and pricing once would be
        # wrong the moment a session spans two of them.
        priced = _event_cost(
            model_name,
            float(input_tokens or 0),
            float(output_tokens or 0),
            float(cache_read or 0),
            float(cache_write or 0),
            nano_aiu,
            token_details_json,
        )

        for bucket in (per_session_model[(session_id, model_name)], model_totals[model_name]):
            bucket["input"] += float(input_tokens or 0)
            bucket["inputBillable"] += priced["counts"]["input"]
            bucket["output"] += float(output_tokens or 0)
            bucket["cached"] += float(cache_read or 0)
            bucket["cacheWrite"] += float(cache_write or 0)
            bucket["reasoning"] += float(reasoning or 0)
            bucket["calls"] += 1
            bucket["durationMs"] += float(duration_ms or 0)
            _add_cost(bucket, priced)
        model_totals[model_name]["sessionIds"].add(session_id)

        entry = per_session.setdefault(session_id, {
            "id": session_id,
            "models": set(),
            "calls": 0,
            "lastActivity": 0.0,
        })
        entry["models"].add(model_name)
        entry["calls"] += 1
        entry["lastActivity"] = max(entry["lastActivity"], _iso_to_epoch_ms(created_at))

    sessions_out: list[dict[str, Any]] = []
    grand_totals = _new_cost_accumulator()
    total_input = 0.0
    total_input_billable = 0.0
    total_output = 0.0
    total_cached = 0.0
    total_cache_write = 0.0

    for session_id, entry in per_session.items():
        meta = session_meta.get(session_id, {})
        session_totals = _new_cost_accumulator()
        session_input = 0.0
        session_input_billable = 0.0
        session_output = 0.0
        session_cached = 0.0
        session_cache_write = 0.0
        model_breakdown = []
        for model_name in entry["models"]:
            bucket = per_session_model[(session_id, model_name)]
            session_input += bucket["input"]
            session_input_billable += bucket["inputBillable"]
            session_output += bucket["output"]
            session_cached += bucket["cached"]
            session_cache_write += bucket["cacheWrite"]
            _add_cost(session_totals, bucket)
            model_breakdown.append({
                "model": model_name,
                "calls": bucket["calls"],
                "input": bucket["input"],
                "inputBillable": bucket["inputBillable"],
                "output": bucket["output"],
                "cached": bucket["cached"],
                "cacheWrite": bucket["cacheWrite"],
                **_cost_fields(bucket),
            })

        _add_cost(grand_totals, session_totals)
        total_input += session_input
        total_input_billable += session_input_billable
        total_output += session_output
        total_cached += session_cached
        total_cache_write += session_cache_write

        sessions_out.append({
            "id": session_id,
            "cwd": meta.get("cwd"),
            "repository": meta.get("repository"),
            "branch": meta.get("branch"),
            "summary": meta.get("summary"),
            "createdAt": meta.get("createdAt", 0.0),
            "updatedAt": meta.get("updatedAt", 0.0),
            "lastActivity": entry["lastActivity"] or meta.get("updatedAt", 0.0),
            "monthKey": _month_key_from_epoch_ms(entry["lastActivity"] or meta.get("updatedAt", 0.0)),
            "dayKey": _day_key_from_epoch_ms(entry["lastActivity"] or meta.get("updatedAt", 0.0)),
            "turnCount": turn_counts.get(session_id, 0),
            "callCount": entry["calls"],
            "models": sorted(entry["models"]),
            "modelBreakdown": sorted(model_breakdown, key=lambda row: row["cost"], reverse=True),
            "input": session_input,
            "inputBillable": session_input_billable,
            "output": session_output,
            "cached": session_cached,
            "cacheWrite": session_cache_write,
            # `uncached` predates the cache-write split and is read by the front
            # end as "prompt tokens billed at the full input rate", which is
            # exactly the billable remainder - not prompt minus cache reads.
            "uncached": session_input_billable,
            **_cost_fields(session_totals),
            "turns": turns_by_session.get(session_id, []),
            "tools": otel_data["toolsBySession"].get(session_id, []),
            "otelTokens": otel_data.get("tokensBySession", {}).get(session_id),
            "files": files_by_session_out.get(session_id, []),
        })

    sessions_out.sort(key=lambda row: row["lastActivity"], reverse=True)

    by_model = []
    for model_name, mtotal in model_totals.items():
        by_model.append({
            "model": model_name,
            "calls": mtotal["calls"],
            "sessionCount": len(mtotal["sessionIds"]),
            "input": mtotal["input"],
            "inputBillable": mtotal["inputBillable"],
            "uncached": mtotal["inputBillable"],
            "cached": mtotal["cached"],
            "cacheWrite": mtotal["cacheWrite"],
            "output": mtotal["output"],
            **_cost_fields(mtotal),
        })
    by_model.sort(key=lambda row: row["cost"], reverse=True)

    file_stats: dict[str, dict[str, Any]] = collections.defaultdict(
        lambda: {"path": "", "created": 0, "edited": 0, "sessionIds": set(), "lastTouched": 0.0}
    )
    for session_id, file_path, tool_name, first_seen_at in file_rows:
        entry = file_stats[file_path]
        entry["path"] = file_path
        if tool_name == "create":
            entry["created"] += 1
        else:
            entry["edited"] += 1
        entry["sessionIds"].add(session_id)
        entry["lastTouched"] = max(entry["lastTouched"], _iso_to_epoch_ms(first_seen_at))

    files_out = sorted(
        (
            {
                "path": entry["path"],
                "created": entry["created"],
                "edited": entry["edited"],
                "touches": entry["created"] + entry["edited"],
                "sessionCount": len(entry["sessionIds"]),
                "lastTouched": entry["lastTouched"],
            }
            for entry in file_stats.values()
        ),
        key=lambda row: row["touches"],
        reverse=True,
    )

    cost_fields = _cost_fields(grand_totals)
    db_tokens = {
        "input": total_input_billable,
        "cache_read": total_cached,
        "cache_write": total_cache_write,
        "output": total_output,
    }
    return {
        "available": True,
        "dbPath": resolved_db_path,
        "sessions": sessions_out,
        "byModel": by_model,
        "files": files_out,
        "tools": otel_data["tools"],
        "otelAvailable": otel_data["available"],
        "otelPaths": otel_data["paths"],
        "otel": {
            "available": otel_data["available"],
            "paths": otel_data["paths"],
            "instruments": otel_data.get("instruments", []),
            "recordCounts": otel_data.get("recordCounts", {}),
            "tokens": otel_data.get("tokens", {}),
            "spend": otel_data.get("spend", {}),
            "sessionCount": len(otel_data.get("tokensBySession", {}) or {}),
        },
        "otelReconciliation": _reconcile_otel(otel_data, db_tokens, cost_fields["cost"]),
        "summary": {
            "sessionCount": len(sessions_out),
            "callCount": len(event_rows),
            "totalInput": total_input,
            "totalOutput": total_output,
            "totalCached": total_cached,
            "totalCacheWrite": total_cache_write,
            "totalUncached": total_input_billable,
            "totalInputBillable": total_input_billable,
            "totalCost": cost_fields["cost"],
            "totalCredits": cost_fields["credits"],
            "costByType": cost_fields["costByType"],
            "costSource": cost_fields["costSource"],
            "costSources": cost_fields["costSources"],
            "costExact": cost_fields["costExact"],
            "fileCount": len(files_out),
            "toolCallCount": sum(row["calls"] for row in otel_data["tools"]),
        },
        "periods": {
            "default": "monthly",
            "labels": {
                "allTime": "All time",
                "monthly": now.strftime("%B %Y"),
            },
            "allTime": _build_cli_period_bundle(sessions_out),
            "monthly": {
                "monthKey": now.strftime("%Y-%m"),
                **_build_cli_period_bundle(
                    [s for s in sessions_out if s.get("monthKey") == now.strftime("%Y-%m")]
                ),
            },
        },
    }
