"""Structured, user-visible diagnostics for parse and cache failures.

Why this module exists
----------------------
This tool's headline claim is that its cost figures are trustworthy - CLI costs
are read from what GitHub actually charged (`total_nano_aiu`), not estimated.
A silently swallowed exception does not produce an error in a tool like this;
it produces a *quieter, wrong number*, rendered with exactly the same authority
as a correct one. A dropped session or an unreadable cache entry lowers a total
and nothing anywhere says so.

The historic pattern throughout the parse/cache layer was:

    try:
        ...
    except Exception:
        return None          # indistinguishable from "file legitimately absent"

Callers cannot tell a cache *miss* from a cache *corruption*, so they cannot
warn the operator. This collector is the missing channel. Failure sites call
`report(...)` and still return their historic value, so control flow and every
existing cost figure are unchanged - the failure simply stops being invisible.

Deliberately not `logging`
--------------------------
These findings have to reach the *browser*, because that is where the numbers
are read. A WARNING on a terminal nobody is watching does not stop someone
acting on an understated total. Entries therefore travel in `app_data`
("diagnostics") and are exposed on `/api/status`. Logging remains fine for
developer-facing tracing; this is for the person reading the dashboard.

The `impact` field is what earns this its keep: it lets the UI say "your totals
may be understated" only when a cost-bearing path actually failed, and stay
quiet for cosmetic ones. Without it every malformed OTel line - which can never
affect a cost, see README "capture the CLI's OpenTelemetry export" - would cry
wolf and the banner would be trained away as noise.
"""
from __future__ import annotations

import threading
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]
Impact = Literal["cost", "presentation", "none"]

# Stable codes. The UI groups on these, so treat them as a contract: add freely,
# rename never.
CODE_CACHE_CORRUPT = "cache.corrupt"
CODE_CACHE_CHECKSUM_MISMATCH = "cache.checksum_mismatch"
CODE_CACHE_UNREADABLE = "cache.unreadable"
CODE_CACHE_BAD_JSON = "cache.bad_json"
CODE_CLI_DB_ABSENT = "cli.db_absent"
CODE_CLI_DB_LOCKED = "cli.db_locked"
CODE_CLI_QUERY_FAILED = "cli.query_failed"
CODE_LOG_PARSE_FAILED = "log.parse_failed"
CODE_OTEL_LINE_SKIPPED = "otel.line_skipped"
# A call whose cache counters exceed its own prompt counter. Cost-impacting
# because `model_pricing.split_prompt_tokens` clamps the split to the reported
# prompt rather than billing tokens the prompt never contained.
CODE_PRICING_PROMPT_OVERFLOW = "pricing.prompt_overflow"
# Distinct from the line-level code on purpose: one bad line loses one data
# point, an unreadable file loses the entire cross-check for that export.
CODE_OTEL_FILE_SKIPPED = "otel.file_skipped"

# A pathological input (a truncated 2GB JSONL, a cache directory of garbage)
# must not turn an observability aid into a memory leak. Distinct
# (code, source) pairs are capped; repeats of an already-seen pair are free
# because they only bump a counter.
_MAX_ENTRIES = 200


class DiagnosticsCollector:
    """Thread-safe, de-duplicating collector.

    Safe under both the cache `ThreadPoolExecutor` and `ThreadingHTTPServer`.
    Entries are keyed on `(code, source)` and roll up a `count`, so 900 bad
    lines in one file yield one entry with `count: 900` rather than 900 entries.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], dict[str, Any]] = {}
        self._dropped = 0

    def report(
        self,
        code: str,
        message: str,
        *,
        severity: Severity = "warning",
        impact: Impact = "presentation",
        source: str = "",
    ) -> None:
        key = (code, source)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                existing["count"] += 1
                return
            if len(self._entries) >= _MAX_ENTRIES:
                self._dropped += 1
                return
            self._entries[key] = {
                "code": code,
                "message": message,
                "severity": severity,
                "impact": impact,
                "source": source,
                "count": 1,
            }

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()
            self._dropped = 0

    def entries(self) -> list[dict[str, Any]]:
        """Snapshot, worst-first, without clearing.

        Read-only on purpose: a rebuild may be serving several requests, and a
        drain-on-read would let whichever caller arrived first swallow the
        findings the others needed to show.
        """
        order = {"error": 0, "warning": 1, "info": 2}
        with self._lock:
            snapshot = [dict(entry) for entry in self._entries.values()]
            dropped = self._dropped
        snapshot.sort(key=lambda item: (order.get(item["severity"], 9), item["code"], item["source"]))
        if dropped:
            snapshot.append(
                {
                    "code": "diagnostics.truncated",
                    "message": (
                        f"{dropped} further distinct diagnostics were suppressed "
                        f"after the {_MAX_ENTRIES}-entry cap."
                    ),
                    "severity": "info",
                    "impact": "none",
                    "source": "",
                    "count": dropped,
                }
            )
        return snapshot

    def summary(self) -> dict[str, Any]:
        """Counts the UI can branch on without walking the list.

        `costImpacting` is the one that drives the banner - see the module
        docstring on why severity alone is the wrong trigger.
        """
        entries = self.entries()
        return {
            "total": len(entries),
            "errors": sum(1 for item in entries if item["severity"] == "error"),
            "warnings": sum(1 for item in entries if item["severity"] == "warning"),
            "costImpacting": sum(1 for item in entries if item["impact"] == "cost"),
        }

    def as_dict(self) -> dict[str, Any]:
        return {"entries": self.entries(), "summary": self.summary()}


# Module-level default collector.
#
# A collector threaded through every call signature would be cleaner in
# isolation, but reaching these failure sites means touching ~6 call chains
# across json_storage/compact_cache/full_cache/cli_usage, several of them
# recursive helpers with historic signatures that tests pin. A module-level
# instance matches how this codebase already carries process-wide state
# (see `COMPRESSED_CACHE_WORKERS`, the pricing table) and keeps the failure
# sites to a one-line edit.
_COLLECTOR = DiagnosticsCollector()


def report(
    code: str,
    message: str,
    *,
    severity: Severity = "warning",
    impact: Impact = "presentation",
    source: str = "",
) -> None:
    _COLLECTOR.report(code, message, severity=severity, impact=impact, source=source)


def reset() -> None:
    """Clear before a rebuild, so stale findings never outlive their cause."""
    _COLLECTOR.reset()


def entries() -> list[dict[str, Any]]:
    return _COLLECTOR.entries()


def summary() -> dict[str, Any]:
    return _COLLECTOR.summary()


def as_dict() -> dict[str, Any]:
    return _COLLECTOR.as_dict()


def collector() -> DiagnosticsCollector:
    """The process-wide collector, for tests that want isolation."""
    return _COLLECTOR
