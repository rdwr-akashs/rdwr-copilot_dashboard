from __future__ import annotations

"""Ship the deterministic insights from `insights_engine.py` to OpenObserve.

The wire format mirrors the OpenObserve JSON ingestion API:

    POST {base}/api/{org}/{stream}/_json
    Authorization: Basic <user:password>
    Content-Type: application/json
    Body: [ {...event...}, {...event...} ]

Everything here is stdlib-only (urllib) so the dashboard keeps its
zero-dependency install. Credentials are read from the environment
(`OPENOBSERVE_USER` / `OPENOBSERVE_PASSWORD`) or passed explicitly; they are
never written into `app_data`, the generated HTML, or any log line.

Event schema
------------
One flat stream carries three `recordType`s, all sharing `runId` so a
dashboard can scope every panel to a single dashboard generation:

* `recordType="run"`     - one event per export. Carries the panel header
  numbers (finding count, severity counts, total estimated savings in USD /
  AI credits / legacy premium requests) plus portfolio context (total spend,
  tokens, session counts, credit-budget status).
* `recordType="insight"` - one event per recommendation card. Carries every
  field the card renders, plus pre-derived display fields (`sourceLabel`,
  `severityLabel`, `estimatedSavingsCredits`, `hasSavings`, `severityRank`,
  `rank`) so OpenObserve panels need no VRL to match the HTML panel.
* `recordType="evidence"` - one event per evidence row of one insight, with
  the row's own keys flattened alongside `insightId` / `insightTitle` /
  `severity`, so the collapsible "Evidence (n)" tables can be rebuilt as
  drill-down panels. Evidence keys vary per rule; OpenObserve's schema is
  dynamic and simply unions them.
"""

import base64
import getpass
import hashlib
import json
import os
import re
import socket
import ssl
import uuid
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://localhost:5080"
DEFAULT_ORG = "default"
DEFAULT_STREAM = "insights"
DEFAULT_TIMEOUT_SECONDS = 10.0

CREDIT_USD = 0.01

SEVERITY_RANK = {"critical": 0, "warn": 1, "info": 2}
SEVERITY_LABELS = {"critical": "Critical", "warn": "Warn", "info": "Info"}
SOURCE_LABELS = {"chat": "Chat", "cli": "CLI", "both": "Both"}

ENV_URL = "OPENOBSERVE_URL"
ENV_BASE_URL = "OPENOBSERVE_BASE_URL"
ENV_ORG = "OPENOBSERVE_ORG"
ENV_STREAM = "OPENOBSERVE_STREAM"
ENV_USER = "OPENOBSERVE_USER"
ENV_PASSWORD = "OPENOBSERVE_PASSWORD"
ENV_DEDUPE_STATE = "OPENOBSERVE_DEDUPE_STATE"
ENV_INSECURE_TLS = "OPENOBSERVE_INSECURE_TLS"

# Fields that differ on every run even when the underlying finding is identical.
VOLATILE_FIELDS = frozenset({
    "_timestamp",
    "runId",
    "generatedAt",
    "evidenceId",
    "evidenceIds",
    "evidenceGroupId",
})

# Upper bound on remembered fingerprints per endpoint (oldest are dropped first).
MAX_TRACKED_FINGERPRINTS = 20000

# "identity" ships a recurring finding once; "content" re-ships it whenever any
# number in it changes.
DEDUPE_MODES = ("identity", "content")
DEFAULT_DEDUPE_MODE = "identity"


def resolve_endpoint(
  url: str | None = None,
  base_url: str | None = None,
  org: str | None = None,
  stream: str | None = None,
) -> str:
    """Return the full `_json` ingestion URL for the configured stream."""
    explicit = url or os.environ.get(ENV_URL)
    if explicit:
        return explicit.rstrip("/")
    base = (base_url or os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
    org_name = org or os.environ.get(ENV_ORG) or DEFAULT_ORG
    stream_name = stream or os.environ.get(ENV_STREAM) or DEFAULT_STREAM
    return f"{base}/api/{org_name}/{stream_name}/_json"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result


def _scalar(value: Any) -> Any:
    """Coerce a value into something OpenObserve can index as a column."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, default=str)


def _cost_block(bucket: Any) -> dict[str, float]:
    block = bucket if isinstance(bucket, dict) else {}
    return {
        "cost": _number(block.get("cost")),
        "inputTokens": _number(block.get("inputTokens")),
        "outputTokens": _number(block.get("outputTokens")),
        "cacheReadTokens": _number(block.get("cacheReadTokens")),
        "totalTokens": _number(block.get("totalTokens")),
    }


def _run_id(app_data: dict[str, Any], timestamp_ms: int, host: str) -> str:
    seed = f"{app_data.get('generatedAt') or ''}|{host}|{timestamp_ms}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _user_id(app_data: dict[str, Any]) -> str | None:
    """Best-effort user id for indexing; anonymized exports use a generic label."""
    if bool(app_data.get("anonymized")):
        return "user"

    explicit = app_data.get("userId")
    if explicit:
        return str(explicit)

    username = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if username:
        return username

    try:
        username = username or getpass.getuser()
    except Exception:
        pass
    return username or None


def _insight_session_ids(insight: dict[str, Any]) -> list[str]:
    evidence = insight.get("evidence")
    detail = str(insight.get("detail") or "")

    ids: set[str] = set()

    # Best source: structured evidence rows.
    if isinstance(evidence, list):
        for row in evidence:
            if not isinstance(row, dict):
                continue
            for key in ("sessionId", "session_id", "id"):
                value = str(row.get(key) or "").strip()
                if value:
                    ids.add(value)
                    break

    # Fallback: several rules include "Session <id>" in detail text.
    for match in re.findall(r"\bSession\s+([A-Za-z0-9._:-]+)", detail):
        value = str(match or "").strip().rstrip(".,;)")
        if value:
            ids.add(value)

    return sorted(ids)


def _split_session_id(session_id: str | None) -> tuple[str | None, str | None]:
    text = str(session_id or "").strip()
    if not text:
        return None, None
    if ":" in text:
        shard, local = text.split(":", 1)
        return (shard or None), (local or None)
    return None, text


def _random_evidence_group_id() -> str:
    """Short random id so each insight has a unique evidence group key."""
    return f"ev-{uuid.uuid4().hex[:12]}"


def _insight_dedupe_key(insight: dict[str, Any], primary_session_id: str) -> str:
    """Identity of a finding, excluding the estimates that drift between runs."""
    return "|".join([
        "insight",
        str(insight.get("id") or ""),
        primary_session_id,
        str(insight.get("severity") or ""),
        str(insight.get("source") or ""),
        str(insight.get("title") or ""),
    ])


def _evidence_detail_text(row: Any) -> str:
    """Render one evidence row as a compact, normalized name=value sentence."""
    if not isinstance(row, dict):
        return f"value={_scalar(row)}"

    parts: list[str] = []
    for key in sorted(row.keys(), key=lambda k: str(k).lower()):
        name = str(key)
        value = _scalar(row.get(key))
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def _build_run_event(
  app_data: dict[str, Any],
  insights: list[dict[str, Any]],
  base: dict[str, Any],
) -> dict[str, Any]:
    unified = app_data.get("unified") or {}
    totals = unified.get("totals") or {}
    by_source = {
        str(row.get("source") or "").lower(): row
        for row in (unified.get("bySource") or [])
        if isinstance(row, dict)
    }
    budget = (app_data.get("premium") or {}).get("budget") or {}
    usage_range = unified.get("range") or {}

    savings_cost = sum(_number((i.get("estimatedSavings") or {}).get("cost")) for i in insights)
    savings_premium = sum(_number((i.get("estimatedSavings") or {}).get("premiumRequests")) for i in insights)

    attributed = _cost_block(totals.get("attributed"))
    billed = _cost_block(totals.get("billed"))
    chat_billed = _cost_block((by_source.get("chat") or {}).get("billed"))
    cli_billed = _cost_block((by_source.get("cli") or {}).get("billed"))

    event = dict(base)
    event.update({
        "recordType": "run",
        "insightCount": len(insights),
        "criticalCount": sum(1 for i in insights if i.get("severity") == "critical"),
        "warnCount": sum(1 for i in insights if i.get("severity") == "warn"),
        "infoCount": sum(1 for i in insights if i.get("severity") == "info"),
        "chatInsightCount": sum(1 for i in insights if i.get("source") == "chat"),
        "cliInsightCount": sum(1 for i in insights if i.get("source") == "cli"),
        "crossSourceInsightCount": sum(1 for i in insights if i.get("source") == "both"),
        "actionableInsightCount": sum(
            1 for i in insights
            if _number((i.get("estimatedSavings") or {}).get("cost")) > 0
            or _number((i.get("estimatedSavings") or {}).get("premiumRequests")) > 0
        ),
        "totalEstimatedSavingsCost": round(savings_cost, 4),
        "totalEstimatedSavingsCredits": round(savings_cost / CREDIT_USD, 2),
        "totalEstimatedSavingsPremiumRequests": round(savings_premium, 2),
        "totalBilledCost": billed["cost"],
        "totalAttributedCost": attributed["cost"],
        "totalTokens": billed["totalTokens"] or attributed["totalTokens"],
        "totalInputTokens": billed["inputTokens"],
        "totalOutputTokens": billed["outputTokens"],
        "totalCacheReadTokens": billed["cacheReadTokens"],
        "totalCallCount": _number(totals.get("callCount")),
        "totalModelCalls": _number(totals.get("modelCalls")),
        "totalPromptCount": _number(totals.get("promptCount")),
        "totalSessionCount": _number(totals.get("sessionCount")),
        "totalPremiumRequests": _number(totals.get("premiumRequests")),
        "chatCost": chat_billed["cost"],
        "chatSessionCount": _number((by_source.get("chat") or {}).get("sessionCount")),
        "cliCost": cli_billed["cost"],
        "cliSessionCount": _number((by_source.get("cli") or {}).get("sessionCount")),
        "savingsShareOfSpendPercent": round(savings_cost / billed["cost"] * 100.0, 2) if billed["cost"] > 0 else 0.0,
        "budgetPlan": _scalar(budget.get("plan")),
        "budgetStatus": _scalar(budget.get("status")),
        "budgetUsedCredits": _number(budget.get("used")),
        "budgetAllowanceCredits": _number(budget.get("allowance")),
        "budgetRemainingCredits": _number(budget.get("remaining")),
        "budgetPercentUsed": _number(budget.get("percentUsed")),
        "budgetProjectedMonthEnd": _number(budget.get("projectedMonthEnd")),
        "usageFirstTs": _scalar(usage_range.get("firstTs")),
        "usageLastTs": _scalar(usage_range.get("lastTs")),
        "creditUsd": CREDIT_USD,
    })
    return event


def _build_insight_event(
    insight: dict[str, Any],
    rank: int,
    base: dict[str, Any],
    evidence_group_id: str,
) -> dict[str, Any]:
    savings = insight.get("estimatedSavings") or {}
    savings_cost = _number(savings.get("cost"))
    savings_premium = _number(savings.get("premiumRequests"))
    evidence = insight.get("evidence")
    evidence_rows = evidence if isinstance(evidence, list) else []
    run_id = str(base.get("runId") or "")
    insight_id = str(insight.get("id") or "")
    evidence_ids = [
        f"{evidence_group_id}:{idx}" for idx in range(len(evidence_rows))
    ]
    session_ids = _insight_session_ids(insight)
    primary_session_id = session_ids[0] if session_ids else "aggregate"
    session_shard, session_local_id = _split_session_id(primary_session_id)
    severity = str(insight.get("severity") or "info")
    source = str(insight.get("source") or "")
    confidence = str(insight.get("confidence") or "low")

    event = dict(base)
    event.update({
        "recordType": "insight",
        "rank": rank,
        "insightId": insight.get("id"),
        "title": insight.get("title"),
        "detail": insight.get("detail"),
        "action": insight.get("action"),
        "severity": severity,
        "severityLabel": SEVERITY_LABELS.get(severity, severity.title()),
        "severityRank": SEVERITY_RANK.get(severity, 3),
        "source": source,
        "sourceLabel": SOURCE_LABELS.get(source, "Both"),
        "isCrossSource": source == "both",
        "confidence": confidence,
        "confidenceLabel": f"{confidence.upper()} confidence",
        "estimatedSavingsCost": round(savings_cost, 4),
        "estimatedSavingsCredits": round(savings_cost / CREDIT_USD, 2),
        "estimatedSavingsPremiumRequests": round(savings_premium, 2),
        "hasSavings": savings_cost > 0 or savings_premium > 0,
        "evidenceCount": len(evidence_rows),
        # One random evidence-group id per insight row.
        "evidenceId": evidence_group_id,
        "evidenceIds": json.dumps(evidence_ids),
        # Keep both a single-value field and the full set for easy querying.
        "sessionId": primary_session_id,
        "sessionIds": json.dumps(session_ids),
        "sessionCount": len(session_ids),
        "sessionScope": "aggregate" if not session_ids else ("single" if len(session_ids) == 1 else "multiple"),
        "sessionShard": session_shard,
        "sessionLocalId": session_local_id,
        # Kept verbatim so a single card panel can render evidence without a join.
        "evidence": json.dumps(evidence_rows, default=str),
        "dedupeKey": _insight_dedupe_key(insight, primary_session_id),
    })
    return event


def _build_evidence_events(
    insight: dict[str, Any],
    rank: int,
    base: dict[str, Any],
    evidence_group_id: str,
) -> list[dict[str, Any]]:
    evidence = insight.get("evidence")
    if not isinstance(evidence, list):
        return []
    severity = str(insight.get("severity") or "info")
    session_ids = _insight_session_ids(insight)
    insight_key = _insight_dedupe_key(insight, session_ids[0] if session_ids else "aggregate")
    events: list[dict[str, Any]] = []
    for index, row in enumerate(evidence):
        event = dict(base)
        evidence_id = f"{evidence_group_id}:{index}"
        event.update({
            "recordType": "evidence",
            "rank": rank,
            "insightId": insight.get("id"),
            "insightTitle": insight.get("title"),
            "severity": severity,
            "severityLabel": SEVERITY_LABELS.get(severity, severity.title()),
            "source": insight.get("source"),
            "confidence": insight.get("confidence"),
            "evidenceIndex": index,
            "evidenceGroupId": evidence_group_id,
            "evidenceId": evidence_id,
            "evidenceDetail": _evidence_detail_text(row),
            "dedupeKey": f"evidence|{insight_key}|{index}",
        })
        events.append(event)
    return events


def build_insight_events(
  app_data: dict[str, Any],
  extra_fields: dict[str, Any] | None = None,
  now_ms: float | int | None = None,
  include_evidence_rows: bool = True,
) -> list[dict[str, Any]]:
    """Turn `app_data["insights"]` into flat, OpenObserve-friendly JSON events.

    Emits one `run` summary event, one `insight` event per recommendation and
    (unless `include_evidence_rows=False`) one `evidence` event per evidence
    row. See the module docstring for the schema.
    """
    insights = [i for i in (app_data.get("insights") or []) if isinstance(i, dict)]
    timestamp_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    # OpenObserve's default `_timestamp` unit is microseconds.
    timestamp_us = timestamp_ms * 1000
    host = None if app_data.get("anonymized") else socket.gethostname()
    run_id = _run_id(app_data, timestamp_ms, host or "anonymous")
    base: dict[str, Any] = {
        "_timestamp": timestamp_us,
        "runId": run_id,
        "generatedAt": app_data.get("generatedAt"),
        "host": host,
        "userId": _user_id(app_data),
        "anonymized": bool(app_data.get("anonymized")),
    }

    events: list[dict[str, Any]] = [_build_run_event(app_data, insights, base)]
    for rank, insight in enumerate(insights, start=1):
        evidence_group_id = _random_evidence_group_id()
        events.append(_build_insight_event(insight, rank, base, evidence_group_id))
        if include_evidence_rows:
            events.extend(_build_evidence_events(insight, rank, base, evidence_group_id))

    if extra_fields:
        for event in events:
            event.update(extra_fields)
    return [{key: value for key, value in event.items() if value is not None} for event in events]


def default_dedupe_state_path() -> str:
    """Where the "already shipped" fingerprints live when none is configured."""
    configured = os.environ.get(ENV_DEDUPE_STATE)
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(os.path.expanduser("~"), ".copilot-dashboard", "openobserve_sent.json")


def event_fingerprint(event: dict[str, Any], mode: str = DEFAULT_DEDUPE_MODE) -> str:
    """Stable hash identifying an event for de-duplication.

    In `identity` mode an event carrying a `dedupeKey` is hashed on that key
    alone, so a recurring finding is shipped once even as its cost estimate
    moves. In `content` mode (and for events without a key, such as the `run`
    snapshot) the hash covers every field except the per-run volatile ones.
    """
    key = event.get("dedupeKey") if mode == "identity" else None
    if key:
        canonical = f"identity|{key}"
    else:
        stable = {k: v for k, v in event.items() if k not in VOLATILE_FIELDS}
        canonical = json.dumps(stable, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def load_dedupe_state(state_path: str) -> dict[str, Any]:
    try:
        with open(state_path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return {"version": 1, "endpoints": {}}
    if not isinstance(state, dict) or not isinstance(state.get("endpoints"), dict):
        return {"version": 1, "endpoints": {}}
    return state


def save_dedupe_state(state_path: str, state: dict[str, Any]) -> None:
    directory = os.path.dirname(state_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_path = f"{state_path}.{os.getpid()}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(temp_path, state_path)


def filter_unsent_events(
  events: list[dict[str, Any]],
  endpoint: str,
  state: dict[str, Any],
  mode: str = DEFAULT_DEDUPE_MODE,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop events whose content was already accepted by `endpoint` before."""
    seen = (state.get("endpoints", {}).get(endpoint) or {}).get("fingerprints") or {}
    fresh: list[dict[str, Any]] = []
    fingerprints: list[str] = []
    batch: set[str] = set()
    for event in events:
        fingerprint = event_fingerprint(event, mode=mode)
        if fingerprint in seen or fingerprint in batch:
            continue
        batch.add(fingerprint)
        fresh.append(event)
        fingerprints.append(fingerprint)
    return fresh, fingerprints


def record_sent_events(
  state_path: str,
  endpoint: str,
  state: dict[str, Any],
  fingerprints: list[str],
) -> None:
    endpoints = state.setdefault("endpoints", {})
    entry = endpoints.setdefault(endpoint, {})
    seen = entry.setdefault("fingerprints", {})
    stamp = int(time.time())
    for fingerprint in fingerprints:
        seen[fingerprint] = stamp
    if len(seen) > MAX_TRACKED_FINGERPRINTS:
        oldest = sorted(seen.items(), key=lambda item: item[1])[: len(seen) - MAX_TRACKED_FINGERPRINTS]
        for fingerprint, _ in oldest:
            seen.pop(fingerprint, None)
    entry["lastSent"] = stamp
    state["version"] = 1
    save_dedupe_state(state_path, state)


def send_events(
  events: list[dict[str, Any]],
  url: str,
  username: str,
  password: str,
  timeout: float = DEFAULT_TIMEOUT_SECONDS,
    insecure_tls: bool = False,
) -> dict[str, Any]:
    """POST `events` as a JSON array. Returns a status dict; never raises."""
    if not events:
        return {"ok": True, "sent": 0, "url": url, "skipped": "no insights to send"}

    payload = json.dumps(events).encode("utf-8")
    credentials = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {credentials}",
        },
    )
    try:
        context = ssl._create_unverified_context() if insecure_tls else None
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {"ok": 200 <= response.status < 300, "sent": len(events), "url": url, "status": response.status, "response": body[:2000]}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        return {"ok": False, "sent": 0, "url": url, "status": exc.code, "error": f"HTTP {exc.code}", "response": body[:2000]}
    except Exception as exc:
        return {"ok": False, "sent": 0, "url": url, "error": repr(exc)}


def export_insights(
  app_data: dict[str, Any],
  url: str | None = None,
  base_url: str | None = None,
  org: str | None = None,
  stream: str | None = None,
  username: str | None = None,
  password: str | None = None,
  timeout: float = DEFAULT_TIMEOUT_SECONDS,
  extra_fields: dict[str, Any] | None = None,
  include_evidence_rows: bool = True,
  dedupe: bool = True,
  dedupe_state_path: str | None = None,
  dedupe_mode: str = DEFAULT_DEDUPE_MODE,
    insecure_tls: bool | None = None,
) -> dict[str, Any]:
    """Build and ship the insight events for `app_data` in one call.

    With `dedupe=True` (default) any event already accepted by the same
    endpoint in an earlier run is skipped, so repeated scheduled runs only ever
    add genuinely new findings. See `event_fingerprint` for what "already sent"
    means in each `dedupe_mode`.
    """
    endpoint = resolve_endpoint(url=url, base_url=base_url, org=org, stream=stream)
    user = username or os.environ.get(ENV_USER) or ""
    secret = password or os.environ.get(ENV_PASSWORD) or ""
    allow_insecure_tls = insecure_tls if insecure_tls is not None else os.environ.get(ENV_INSECURE_TLS, "").lower() in {"1", "true", "yes"}
    if not user or not secret:
        return {
            "ok": False,
            "sent": 0,
            "url": endpoint,
            "error": f"Missing OpenObserve credentials. Set ${ENV_USER} and ${ENV_PASSWORD}.",
        }
    events = build_insight_events(
        app_data,
        extra_fields=extra_fields,
        include_evidence_rows=include_evidence_rows,
    )
    if not dedupe:
        return send_events(events, endpoint, user, secret, timeout=timeout, insecure_tls=allow_insecure_tls)

    state_path = dedupe_state_path or default_dedupe_state_path()
    mode = dedupe_mode if dedupe_mode in DEDUPE_MODES else DEFAULT_DEDUPE_MODE
    state = load_dedupe_state(state_path)
    total = len(events)
    events, fingerprints = filter_unsent_events(events, endpoint, state, mode=mode)
    duplicates = total - len(events)
    if not events:
        return {
            "ok": True,
            "sent": 0,
            "url": endpoint,
            "duplicatesSkipped": duplicates,
            "dedupeMode": mode,
            "skipped": "all events already sent",
        }
    result = send_events(events, endpoint, user, secret, timeout=timeout, insecure_tls=allow_insecure_tls)
    result["duplicatesSkipped"] = duplicates
    result["dedupeMode"] = mode
    if result.get("ok"):
        try:
            record_sent_events(state_path, endpoint, state, fingerprints)
        except OSError as exc:
            result["dedupeStateError"] = repr(exc)
    return result
