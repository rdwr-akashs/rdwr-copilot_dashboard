from __future__ import annotations

"""Deterministic recommendations engine for the Copilot Token Dashboard.

`build_insights(app_data, config=None, now_ms=None)` turns the already-computed
`app_data["sessions"]` (VS Code chat), `app_data["cli"]` (Copilot CLI),
`app_data["unified"]` (usage_model.py) and `app_data["premium"]`
(premium_requests.py) into a ranked list of concrete, evidence-backed
findings. Every rule here is a **plain deterministic computation over
existing parsed data** - no LLM calls, no network access, no randomness.
Given the same `app_data`, the output is always the same.

Every insight has the shape:

    {
      "id": str,
      "severity": "info" | "warn" | "critical",
      "title": str,
      "detail": str,
      "source": "chat" | "cli" | "both",
      "evidence": [ {...} ],
      "estimatedSavings": {"cost": float, "premiumRequests": float},
      "action": str,
      "confidence": "low" | "medium" | "high",
    }

The returned list is sorted by severity (critical > warn > info), then by
`estimatedSavings.cost` descending.

All thresholds live in `DEFAULT_CONFIG` below and are overridable via the
same JSON config file mechanism `premium_requests.load_config()` uses
(`COPILOT_PREMIUM_CONFIG` env var, default `~/.copilot-dashboard/premium.json`)
under a top-level `"insights"` key, e.g.:

    {
      "insights": {
        "lowCacheHitRate": {"thresholdPercentBelowAverage": 30},
        "abandonedSessions": {"minCost": 0.10}
      }
    }

Rules implemented (see module docstring on each `_rule_*` function for the
exact logic and evidence produced):
  1. lowCacheHitRate            - low-cache-hit-rate
  2. expensiveModelTrivialWork  - expensive-model-trivial-work
  3. duplicateFileReads         - duplicate-file-reads (chat only; see note)
  4. contextResetChurn          - context-reset-churn
  5. oversizedSessions          - oversized-session (chat only; see note)
  6. abandonedSessions          - abandoned-session
  7. modelSubstitutionPolicy    - model-substitution-savings (portfolio)
  8. chatVsCliComparison        - chat-vs-cli-cost (neutral observation)
  9. premiumRequestBurn         - premium-request-burn
  10. dataHealth                - stale-chat-logging / cli-otel-disabled

Rule 3 (duplicate file reads) only covers VS Code chat data: chat tool-call
events carry a resolved file path per read
(`per_chat_calculations.extract_file_paths`), but the CLI's OTel
`execute_tool` spans (`cli_usage.parse_cli_otel_files`) only carry a tool
*name* and call count - no per-argument file path - so a CLI-side duplicate
read cannot be attributed to a specific file with today's telemetry. This is
noted in the rule's `detail`/evidence rather than silently guessed at.

Rule 5 (oversized sessions) is similarly chat-only: it needs a session's
*peak prompt token count* growth trajectory, which only chat's per-call
`llm_request` telemetry exposes; the CLI's `session-store.db` only has
per-session+model aggregate totals, with no per-call prompt-size snapshot.
"""

import collections
import os
from datetime import datetime
from typing import Any

from model_pricing import PRICING, get_pricing, calculate_cost
from premium_requests import (
    MULTIPLIERS,
    get_multiplier,
    _read_config_file,
    _CONFIG_ENV_VAR,
    _DEFAULT_CONFIG_PATH,
)

SEVERITY_RANK = {"critical": 0, "warn": 1, "info": 2}

# Every threshold used by the rules below. Override any leaf via the JSON
# config file's top-level "insights" key (see module docstring). Values here
# are deliberately conservative defaults chosen to avoid false positives on
# small/sparse datasets - see build_insights' verification notes.
DEFAULT_CONFIG: dict[str, Any] = {
    "lowCacheHitRate": {
        # Sessions with less input than this are too small for a cache-hit
        # rate to be a meaningful signal (ignored entirely).
        "minInputTokens": 20000.0,
        # Flag a session whose cache-hit rate is at least this many
        # percentage points below the period's average (across sessions that
        # clear minInputTokens).
        "thresholdPercentBelowAverage": 20.0,
        # Ignore gaps whose estimated extra cost rounds to noise.
        "minGapCost": 0.01,
    },
    "expensiveModelTrivialWork": {
        "maxPromptTokens": 3000.0,
        "maxChatCalls": 3,
        "maxOutputTokens": 600.0,
        # Only flag sessions using a model at/above this premium multiplier -
        # a 0x/mini model doing trivial work isn't wasteful.
        "minMultiplier": 1.0,
        # Model substituted in the savings estimate.
        "cheaperModel": "gpt-5-mini",
    },
    "duplicateFileReads": {
        # A file read this many times or more (not counting the first read)
        # within one session is flagged.
        "minRepeatReads": 3,
    },
    "contextResetChurn": {
        "minChatCalls": 5,
        "minResets": 3,
        # resets == model_switch + context_reset boundary counts.
        "minResetRate": 0.25,
    },
    "oversizedSessions": {
        # Used only when a session's own max_context_window_tokens isn't
        # recorded (older telemetry / model without published limits).
        "defaultContextWindowTokens": 128000.0,
        "minPeakFraction": 0.75,
    },
    "abandonedSessions": {
        "minCost": 0.05,
        "maxOutputTokens": 80.0,
    },
    "modelSubstitutionPolicy": {
        "chatCheapModel": "gpt-5-mini",
        "cliCheapModel": "claude-haiku-4.5",
        "minSavingsToReport": 0.05,
    },
    "chatVsCliComparison": {
        "minSessionsPerSource": 1,
    },
    "premiumRequestBurn": {
        # Reuses premium_requests' own warn/critical thresholds via
        # app_data["premium"]["budget"]["status"]; this only controls the
        # "days remaining" framing.
        "minAllowanceToConsider": 1,
    },
    "dataHealth": {
        "staleChatDays": 14,
    },
}


def _merge_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {key: dict(value) for key, value in DEFAULT_CONFIG.items()}
    for key, value in (overrides or {}).items():
        if key in merged and isinstance(value, dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def load_insights_config(config_path: str | None = None) -> dict[str, Any]:
    """Resolve rule thresholds from the shared JSON config file's "insights" key.

    Uses the exact same file-resolution order as `premium_requests.load_config`
    (`config_path` arg > `$COPILOT_PREMIUM_CONFIG` > `~/.copilot-dashboard/premium.json`),
    reading a top-level `"insights"` object from it. Missing file/key falls
    back to `DEFAULT_CONFIG` untouched.
    """
    import os
    resolved_path = config_path or os.environ.get(_CONFIG_ENV_VAR) or _DEFAULT_CONFIG_PATH
    file_config = _read_config_file(resolved_path)
    overrides = file_config.get("insights") if isinstance(file_config.get("insights"), dict) else {}
    return _merge_config(overrides)


def _now(now_ms: float | int | None) -> datetime:
    return datetime.fromtimestamp(now_ms / 1000.0) if now_ms else datetime.now()


def _round2(value: float) -> float:
    return round(float(value or 0.0), 4)


def _make_insight(
    insight_id: str,
    severity: str,
    title: str,
    detail: str,
    source: str,
    evidence: list[dict[str, Any]],
    savings_cost: float,
    savings_premium: float,
    action: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "id": insight_id,
        "severity": severity,
        "title": title,
        "detail": detail,
        "source": source,
        "evidence": evidence,
        "estimatedSavings": {"cost": _round2(savings_cost), "premiumRequests": _round2(savings_premium)},
        "action": action,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Rule 1: low cache-hit rate
# ---------------------------------------------------------------------------

def _rule_low_cache_hit_rate(sessions: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag sessions whose cache-hit rate lags well behind comparable sessions.

    "Comparable" = chat sessions with at least `minInputTokens` billed input
    in this period. The period average cache-hit rate over that cohort is
    the baseline; any session at least `thresholdPercentBelowAverage`
    percentage points below it is flagged, with the extra cost estimated as
    the delta between actual billed cost and a hypothetical cost at the
    average cache-hit rate (same model pricing, same input/output volume).
    """
    rule_cfg = cfg["lowCacheHitRate"]
    min_input = float(rule_cfg["minInputTokens"])
    threshold_pp = float(rule_cfg["thresholdPercentBelowAverage"])
    min_gap_cost = float(rule_cfg["minGapCost"])

    eligible = []
    for session in sessions:
        billed = session.get("billed_totals") or {}
        input_tokens = float(billed.get("input", 0.0) or 0.0)
        if input_tokens < min_input:
            continue
        cached_tokens = float(billed.get("cached", 0.0) or 0.0)
        rate = (cached_tokens / input_tokens * 100.0) if input_tokens else 0.0
        eligible.append((session, input_tokens, cached_tokens, rate))

    if len(eligible) < 2:
        return []

    avg_rate = sum(rate for _, _, _, rate in eligible) / len(eligible)

    findings = []
    for session, input_tokens, cached_tokens, rate in eligible:
        gap_pp = avg_rate - rate
        if gap_pp < threshold_pp:
            continue
        billed = session.get("billed_totals") or {}
        output_tokens = float(billed.get("output", 0.0) or 0.0)
        actual_cost = float(billed.get("cost", 0.0) or 0.0)
        model_name = str(session.get("model") or "unknown")
        pricing = get_pricing(model_name)
        hyp_cached = min(input_tokens, (avg_rate / 100.0) * input_tokens)
        hyp_uncached = max(0.0, input_tokens - hyp_cached)
        hyp_cost = (
            (hyp_uncached / 1_000_000.0) * pricing["input"]
            + (hyp_cached / 1_000_000.0) * pricing["cached"]
            + (output_tokens / 1_000_000.0) * pricing["output"]
        )
        gap_cost = max(0.0, actual_cost - hyp_cost)
        if gap_cost < min_gap_cost:
            continue
        findings.append((session, rate, gap_pp, gap_cost))

    findings.sort(key=lambda item: item[3], reverse=True)
    insights = []
    for session, rate, gap_pp, gap_cost in findings[:10]:
        insights.append(_make_insight(
            insight_id="low-cache-hit-rate",
            severity="warn" if gap_cost >= 1.0 else "info",
            title="Low cache-hit rate on a high-input session",
            detail=(
                f"Session {session.get('id')} has a {rate:.1f}% cache-hit rate on its billed input, "
                f"{gap_pp:.1f} percentage points below this period's {avg_rate:.1f}% average across comparable "
                f"sessions. That gap is estimated to cost about ${gap_cost:.2f} more than a session hitting the "
                f"average rate would."
            ),
            source="chat",
            evidence=[{
                "sessionId": session.get("id"),
                "model": session.get("model"),
                "cacheHitRatePercent": round(rate, 2),
                "periodAverageCacheHitRatePercent": round(avg_rate, 2),
                "billedInputTokens": (session.get("billed_totals") or {}).get("input"),
            }],
            savings_cost=gap_cost,
            savings_premium=0.0,
            action=(
                "Keep the system prompt, tool set, and early conversation stable across calls in this session so "
                "the provider's prompt cache can be reused; avoid mid-session tool-set switches or unrelated topic "
                "jumps that force a fresh prefix."
            ),
            confidence="medium",
        ))
    return insights


# ---------------------------------------------------------------------------
# Rule 2: expensive model on trivial work
# ---------------------------------------------------------------------------

def _rule_expensive_model_trivial_work(sessions: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag small/short sessions run on a high-multiplier, high-price model."""
    rule_cfg = cfg["expensiveModelTrivialWork"]
    max_prompt = float(rule_cfg["maxPromptTokens"])
    max_calls = int(rule_cfg["maxChatCalls"])
    max_output = float(rule_cfg["maxOutputTokens"])
    min_multiplier = float(rule_cfg["minMultiplier"])
    cheaper_model = str(rule_cfg["cheaperModel"])
    cheaper_pricing = get_pricing(cheaper_model)

    insights = []
    for session in sessions:
        chat_calls = int(session.get("chat_count", 0) or 0)
        if chat_calls == 0 or chat_calls > max_calls:
            continue
        peak_prompt = float(session.get("peak_prompt_tokens", 0.0) or 0.0)
        billed = session.get("billed_totals") or {}
        output_tokens = float(billed.get("output", 0.0) or 0.0)
        if peak_prompt > max_prompt or output_tokens > max_output:
            continue
        model_name = str(session.get("model") or "unknown")
        multiplier = get_multiplier(model_name)
        if multiplier < min_multiplier:
            continue
        actual_cost = float(billed.get("cost", 0.0) or 0.0)
        input_tokens = float(billed.get("input", 0.0) or 0.0)
        cached_tokens = float(billed.get("cached", 0.0) or 0.0)
        hyp = calculate_cost(input_tokens, output_tokens, cached_tokens, cheaper_model)
        cost_savings = max(0.0, actual_cost - hyp["cost"])
        premium_savings = max(0.0, multiplier - get_multiplier(cheaper_model)) * chat_calls
        if cost_savings <= 0 and premium_savings <= 0:
            continue
        insights.append((session, model_name, multiplier, cost_savings, premium_savings))

    insights.sort(key=lambda item: item[3], reverse=True)
    out = []
    for session, model_name, multiplier, cost_savings, premium_savings in insights[:10]:
        out.append(_make_insight(
            insight_id="expensive-model-trivial-work",
            severity="info",
            title="Expensive model used for a small, short session",
            detail=(
                f"Session {session.get('id')} used {model_name} (premium multiplier {multiplier:g}x) for only "
                f"{session.get('chat_count')} call(s) with a peak prompt of {session.get('peak_prompt_tokens', 0):.0f} "
                f"tokens and {(session.get('billed_totals') or {}).get('output', 0):.0f} output tokens. A model "
                f"like {cheaper_model} would likely have handled this equally well."
            ),
            source="chat",
            evidence=[{
                "sessionId": session.get("id"),
                "model": model_name,
                "multiplier": multiplier,
                "chatCalls": session.get("chat_count"),
                "peakPromptTokens": session.get("peak_prompt_tokens"),
            }],
            savings_cost=cost_savings,
            savings_premium=premium_savings,
            action=f"Switch to a lighter model (e.g. {cheaper_model}) for short, simple requests like this one.",
            confidence="low",
        ))
    return out


# ---------------------------------------------------------------------------
# Rule 3: duplicate / repeated file reads (chat only)
# ---------------------------------------------------------------------------

def _rule_duplicate_file_reads(sessions: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag files read many times within one chat session (wasted context tokens).

    Chat-only: see module docstring for why CLI OTel tool spans can't support
    this rule with today's telemetry (no per-argument file path captured).
    """
    min_repeat = int(cfg["duplicateFileReads"]["minRepeatReads"])
    insights = []
    for session in sessions:
        events = session.get("events")
        if not isinstance(events, list) or not events:
            continue
        reads_by_file: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        model_name = str(session.get("model") or "unknown")
        for event in events:
            if not isinstance(event, dict) or event.get("kind") != "tool" or event.get("mode") != "read":
                continue
            files = event.get("files") or []
            if not files:
                continue
            reads_by_file[files[0]].append(event)

        for file_path, reads in reads_by_file.items():
            repeats = len(reads) - 1
            if repeats < min_repeat:
                continue
            wasted_tokens = sum(float(e.get("payload_tokens_estimate", 0.0) or 0.0) for e in reads[1:])
            pricing = get_pricing(model_name)
            wasted_cost = (wasted_tokens / 1_000_000.0) * pricing["input"]
            insights.append((session, file_path, len(reads), wasted_tokens, wasted_cost))

    insights.sort(key=lambda item: item[4], reverse=True)
    out = []
    for session, file_path, count, wasted_tokens, wasted_cost in insights[:10]:
        out.append(_make_insight(
            insight_id="duplicate-file-reads",
            severity="info" if wasted_cost < 0.05 else "warn",
            title="Same file re-read many times in one session",
            detail=(
                f"Session {session.get('id')} read {file_path} {count} times. Re-reads beyond the first are "
                f"estimated to have added ~{wasted_tokens:.0f} redundant tokens (~${wasted_cost:.3f})."
            ),
            source="chat",
            evidence=[{
                "sessionId": session.get("id"),
                "file": file_path,
                "readCount": count,
                "wastedTokensEstimate": round(wasted_tokens, 0),
            }],
            savings_cost=wasted_cost,
            savings_premium=0.0,
            action="Cache the file's contents in conversation instead of re-reading it, or use a targeted grep/range read instead of re-reading the whole file each time.",
            confidence="low",
        ))
    return out


# ---------------------------------------------------------------------------
# Rule 4: context-reset churn
# ---------------------------------------------------------------------------

def _rule_context_reset_churn(sessions: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag sessions with a high rate of context resets / model switches.

    Each reset re-sends the full prompt and is directly billable. The gap
    between the session's real billed cost (`billed_totals`, which sums each
    call's full billed amount) and its attribution-smoothed cost (`totals`,
    which only counts prompt *growth* per call after the first segment) is
    exactly the overhead these resets introduce, so it's used directly as
    the estimated saving from avoiding them.
    """
    rule_cfg = cfg["contextResetChurn"]
    min_calls = int(rule_cfg["minChatCalls"])
    min_resets = int(rule_cfg["minResets"])
    min_rate = float(rule_cfg["minResetRate"])

    insights = []
    for session in sessions:
        chat_calls = int(session.get("chat_count", 0) or 0)
        if chat_calls < min_calls:
            continue
        boundary = session.get("boundary_counts") or {}
        resets = int(boundary.get("model_switch", 0) or 0) + int(boundary.get("context_reset", 0) or 0)
        rate = resets / chat_calls if chat_calls else 0.0
        if resets < min_resets or rate < min_rate:
            continue
        billed_cost = float((session.get("billed_totals") or {}).get("cost", 0.0) or 0.0)
        attributed_cost = float((session.get("totals") or {}).get("cost", 0.0) or 0.0)
        overhead_cost = max(0.0, billed_cost - attributed_cost)
        insights.append((session, resets, rate, overhead_cost))

    insights.sort(key=lambda item: item[3], reverse=True)
    out = []
    for session, resets, rate, overhead_cost in insights[:10]:
        out.append(_make_insight(
            insight_id="context-reset-churn",
            severity="warn" if overhead_cost >= 0.5 else "info",
            title="Frequent context resets/model switches re-billing the full prompt",
            detail=(
                f"Session {session.get('id')} had {resets} context reset(s)/model switch(es) across "
                f"{session.get('chat_count')} calls ({rate * 100.0:.0f}% of calls). Each reset re-sends the full "
                f"prompt at full price; the resulting overhead is estimated at ${overhead_cost:.2f}."
            ),
            source="chat",
            evidence=[{
                "sessionId": session.get("id"),
                "resets": resets,
                "chatCalls": session.get("chat_count"),
                "resetRate": round(rate, 3),
                "billedCost": round(float((session.get("billed_totals") or {}).get("cost", 0.0) or 0.0), 4),
            }],
            savings_cost=overhead_cost,
            savings_premium=0.0,
            action="Avoid switching models mid-session and avoid actions that force a full context reset (e.g. clearing history); start a fresh chat instead when the topic genuinely changes.",
            confidence="medium",
        ))
    return out


# ---------------------------------------------------------------------------
# Rule 5: oversized long-running sessions (chat only)
# ---------------------------------------------------------------------------

def _rule_oversized_sessions(sessions: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag sessions whose prompt has grown past most of the model's context window.

    Chat-only: needs a per-call prompt-size snapshot (`peak_prompt_tokens`),
    which the CLI's session-store.db does not expose (only per-session
    aggregate totals - see module docstring).
    """
    rule_cfg = cfg["oversizedSessions"]
    default_window = float(rule_cfg["defaultContextWindowTokens"])
    min_fraction = float(rule_cfg["minPeakFraction"])

    insights = []
    for session in sessions:
        peak_prompt = float(session.get("peak_prompt_tokens", 0.0) or 0.0)
        if peak_prompt <= 0:
            continue
        window = default_window
        events = session.get("events")
        if isinstance(events, list):
            for event in events:
                if isinstance(event, dict) and event.get("id") == session.get("peak_prompt_event_id"):
                    window = float(event.get("max_context_window_tokens") or default_window) or default_window
                    break
        fraction = peak_prompt / window if window else 0.0
        if fraction < min_fraction:
            continue
        insights.append((session, peak_prompt, window, fraction))

    insights.sort(key=lambda item: item[3], reverse=True)
    out = []
    for session, peak_prompt, window, fraction in insights[:10]:
        out.append(_make_insight(
            insight_id="oversized-session",
            severity="warn" if fraction >= 0.9 else "info",
            title="Session prompt has grown very large",
            detail=(
                f"Session {session.get('id')} peaked at {peak_prompt:.0f} prompt tokens, "
                f"{fraction * 100.0:.0f}% of its ~{window:.0f}-token context window. Continuing to grow this "
                f"session risks context truncation and pays a larger prompt cost on every subsequent call."
            ),
            source="chat",
            evidence=[{
                "sessionId": session.get("id"),
                "peakPromptTokens": peak_prompt,
                "contextWindowTokens": window,
                "peakFraction": round(fraction, 3),
            }],
            # Advisory only: the actual saving depends on how many more calls
            # the user would have made in the bloated session, which isn't
            # knowable in advance. Left at 0 rather than fabricating a number.
            savings_cost=0.0,
            savings_premium=0.0,
            action="Split further work into a fresh chat session once a topic is resolved, instead of continuing to grow this one.",
            confidence="low",
        ))
    return out


# ---------------------------------------------------------------------------
# Rule 6: abandoned / low-yield sessions
# ---------------------------------------------------------------------------

def _rule_abandoned_sessions(sessions: list[dict[str, Any]], cli_sessions: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag sessions with meaningful spend but negligible output / no file edits."""
    rule_cfg = cfg["abandonedSessions"]
    min_cost = float(rule_cfg["minCost"])
    max_output = float(rule_cfg["maxOutputTokens"])

    candidates = []
    for session in sessions:
        billed = session.get("billed_totals") or {}
        cost = float(billed.get("cost", 0.0) or 0.0)
        output_tokens = float(billed.get("output", 0.0) or 0.0)
        if cost < min_cost or output_tokens > max_output:
            continue
        # A session with tool-based file edits produced value even with low
        # chat output; only flag if there's no edit-mode tool activity either.
        events = session.get("events")
        has_edits = False
        if isinstance(events, list):
            has_edits = any(
                isinstance(e, dict) and e.get("kind") == "tool" and e.get("mode") == "edit"
                for e in events
            )
        if has_edits:
            continue
        candidates.append(("chat", session.get("id"), cost, output_tokens, session.get("model")))

    for session in cli_sessions:
        cost = float(session.get("cost", 0.0) or 0.0)
        output_tokens = float(session.get("output", 0.0) or 0.0)
        if cost < min_cost or output_tokens > max_output:
            continue
        files = session.get("files") or []
        has_edits = any(int(f.get("created", 0) or 0) + int(f.get("edited", 0) or 0) > 0 for f in files)
        if has_edits:
            continue
        candidates.append(("cli", session.get("id"), cost, output_tokens, ",".join(session.get("models") or [])))

    candidates.sort(key=lambda item: item[2], reverse=True)
    out = []
    for source, session_id, cost, output_tokens, model_name in candidates[:10]:
        out.append(_make_insight(
            insight_id="abandoned-session",
            severity="info",
            title="Spend with negligible output and no file edits",
            detail=(
                f"{'Chat' if source == 'chat' else 'CLI'} session {session_id} cost ${cost:.2f} but produced only "
                f"{output_tokens:.0f} output tokens and made no file edits. This may be an abandoned or exploratory "
                f"session that didn't result in a change."
            ),
            source=source,
            evidence=[{"sessionId": session_id, "cost": round(cost, 4), "outputTokens": output_tokens, "model": model_name}],
            savings_cost=cost,
            savings_premium=0.0,
            action="If this was exploratory, consider ending sessions earlier once it's clear they won't produce a usable change.",
            confidence="low",
        ))
    return out


# ---------------------------------------------------------------------------
# Rule 7: portfolio-level model-substitution savings
# ---------------------------------------------------------------------------

def _rule_model_substitution_policy(unified: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Estimate what a stated cheaper-model policy would have cost this period, per source."""
    rule_cfg = cfg["modelSubstitutionPolicy"]
    chat_cheap = str(rule_cfg["chatCheapModel"])
    cli_cheap = str(rule_cfg["cliCheapModel"])
    min_savings = float(rule_cfg["minSavingsToReport"])

    by_source = {row.get("source"): row for row in unified.get("bySource", [])}
    out = []
    for source, cheap_model in (("chat", chat_cheap), ("cli", cli_cheap)):
        row = by_source.get(source)
        if not row:
            continue
        billed = row.get("billed") or {}
        actual_cost = float(billed.get("cost", 0.0) or 0.0)
        input_tokens = float(billed.get("input", 0.0) or 0.0)
        output_tokens = float(billed.get("output", 0.0) or 0.0)
        cached_tokens = float(billed.get("cached", 0.0) or 0.0)
        if actual_cost <= 0:
            continue
        hyp = calculate_cost(input_tokens, output_tokens, cached_tokens, cheap_model)
        savings = actual_cost - hyp["cost"]
        if savings < min_savings:
            continue
        actual_premium = float(row.get("premiumRequests", 0.0) or 0.0)
        call_count = int(row.get("callCount", 0) or 0)
        hyp_premium = get_multiplier(cheap_model) * call_count
        premium_savings = max(0.0, actual_premium - hyp_premium)
        out.append(_make_insight(
            insight_id="model-substitution-savings",
            severity="info",
            title=f"Standardizing on {cheap_model} for {source} would cost less this period",
            detail=(
                f"Actual {source} spend this period was ${actual_cost:.2f} across {call_count} call(s). Running "
                f"the same token volume through {cheap_model} instead is estimated at ${hyp['cost']:.2f} - "
                f"a saving of ~${savings:.2f}. This assumes {cheap_model} would produce acceptably similar results, "
                f"which is a policy decision, not something this dashboard can verify."
            ),
            source=source,
            evidence=[{
                "source": source,
                "actualCost": round(actual_cost, 4),
                "hypotheticalCost": round(hyp["cost"], 4),
                "hypotheticalModel": cheap_model,
                "callCount": call_count,
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
            }],
            savings_cost=savings,
            savings_premium=premium_savings,
            action=f"Consider defaulting to {cheap_model} for routine {source} work, reserving pricier models for tasks that need them.",
            confidence="low",
        ))
    return out


# ---------------------------------------------------------------------------
# Rule 8: chat vs CLI cost comparison (neutral observation)
# ---------------------------------------------------------------------------

def _rule_chat_vs_cli_comparison(unified: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """State, neutrally, which surface (chat vs CLI) costs more per session / per output token."""
    min_sessions = int(cfg["chatVsCliComparison"]["minSessionsPerSource"])
    by_source = {row.get("source"): row for row in unified.get("bySource", [])}
    chat = by_source.get("chat")
    cli = by_source.get("cli")
    if not chat or not cli:
        return []
    if chat.get("sessionCount", 0) < min_sessions or cli.get("sessionCount", 0) < min_sessions:
        return []

    def _per_session(row: dict[str, Any]) -> float:
        sessions = float(row.get("sessionCount", 0) or 0)
        return float((row.get("billed") or {}).get("cost", 0.0) or 0.0) / sessions if sessions else 0.0

    def _per_output_1k(row: dict[str, Any]) -> float:
        output = float((row.get("billed") or {}).get("output", 0.0) or 0.0)
        cost = float((row.get("billed") or {}).get("cost", 0.0) or 0.0)
        return (cost / output * 1000.0) if output else 0.0

    chat_per_session = _per_session(chat)
    cli_per_session = _per_session(cli)
    chat_per_1k = _per_output_1k(chat)
    cli_per_1k = _per_output_1k(cli)

    higher_session = "chat" if chat_per_session > cli_per_session else "cli"
    higher_output = "chat" if chat_per_1k > cli_per_1k else "cli"

    return [_make_insight(
        insight_id="chat-vs-cli-cost",
        severity="info",
        title="Chat vs CLI cost profile this period",
        detail=(
            f"Chat averages ${chat_per_session:.3f}/session and ${chat_per_1k:.3f} per 1K output tokens; "
            f"CLI averages ${cli_per_session:.3f}/session and ${cli_per_1k:.3f} per 1K output tokens. "
            f"{higher_session.upper()} costs more per session and {higher_output.upper()} costs more per unit of "
            f"output this period. This is a neutral observation, not a recommendation to shift work between "
            f"surfaces - the two are used for different kinds of tasks."
        ),
        source="both",
        evidence=[
            {"source": "chat", "costPerSession": round(chat_per_session, 4), "costPer1kOutput": round(chat_per_1k, 4), "sessionCount": chat.get("sessionCount")},
            {"source": "cli", "costPerSession": round(cli_per_session, 4), "costPer1kOutput": round(cli_per_1k, 4), "sessionCount": cli.get("sessionCount")},
        ],
        savings_cost=0.0,
        savings_premium=0.0,
        action="No action required - informational comparison only.",
        confidence="high",
    )]


# ---------------------------------------------------------------------------
# Rule 9: premium-request burn
# ---------------------------------------------------------------------------

def _rule_premium_request_burn(premium: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Surface premium_requests.build_budget's projection as an insight when it's not "ok"."""
    budget = (premium or {}).get("budget") or {}
    status = budget.get("status")
    if status not in ("warn", "critical"):
        return []
    allowance = budget.get("allowance")
    if not allowance or allowance < int(cfg["premiumRequestBurn"]["minAllowanceToConsider"]):
        return []

    used = float(budget.get("used", 0.0) or 0.0)
    projected = float(budget.get("projectedMonthEnd", 0.0) or 0.0)
    remaining = budget.get("remaining")
    days_elapsed = int(budget.get("daysElapsed", 0) or 0)
    days_in_month = int(budget.get("daysInMonth", 0) or 0)
    days_remaining = max(0, days_in_month - days_elapsed)
    overshoot = max(0.0, projected - allowance)

    return [_make_insight(
        insight_id="premium-request-burn",
        severity=status,
        title="Premium-request usage is projected to exceed the monthly allowance" if overshoot > 0 else "Premium-request usage is high this month",
        detail=(
            f"{used:.0f} of {allowance} premium requests used with {days_remaining} day(s) left in the month "
            f"({budget.get('percentUsed', 0.0):.0f}% used). At the current burn rate "
            f"(~{budget.get('burnRatePerDay', 0.0):.1f}/day), month-end usage is projected at {projected:.0f} "
            f"({'an overshoot of ~%.0f requests' % overshoot if overshoot > 0 else 'within the allowance'})."
        ),
        source="both",
        evidence=[{
            "plan": budget.get("plan"),
            "allowance": allowance,
            "used": used,
            "remaining": remaining,
            "projectedMonthEnd": projected,
            "daysRemaining": days_remaining,
        }],
        # This is a rationing problem, not a dollar-cost problem: GitHub caps
        # premium requests rather than charging overage on every plan, so the
        # "saving" is expressed only in premium requests, not dollars.
        savings_cost=0.0,
        savings_premium=overshoot,
        action="Shift routine work to 0x-multiplier models (see app_data.premium.multipliers), reduce call volume, or upgrade plan/allowance before the month resets.",
        confidence="high",
    )]


# ---------------------------------------------------------------------------
# Rule 10: data-health warnings
# ---------------------------------------------------------------------------

def _rule_data_health(app_data: dict[str, Any], cfg: dict[str, Any], now_ms: float | int | None) -> list[dict[str, Any]]:
    """Warn when chat logging looks stale/disabled or CLI OTel is off."""
    out = []
    now = _now(now_ms)
    stale_days = float(cfg["dataHealth"]["staleChatDays"])

    sessions = app_data.get("sessions") or []
    cli_data = app_data.get("cli") or {}
    cli_sessions = cli_data.get("sessions") or []

    latest_chat_ts = max((float(s.get("timestamp") or 0.0) for s in sessions), default=0.0)
    latest_cli_ts = max((float(s.get("lastActivity") or 0.0) for s in cli_sessions), default=0.0)

    if cli_data.get("available") and latest_cli_ts:
        cli_age_days = (now - datetime.fromtimestamp(latest_cli_ts / 1000.0)).total_seconds() / 86400.0
        if not sessions or (latest_chat_ts and (now - datetime.fromtimestamp(latest_chat_ts / 1000.0)).total_seconds() / 86400.0 > stale_days):
            if cli_age_days <= stale_days:
                out.append(_make_insight(
                    insight_id="stale-chat-logging",
                    severity="warn",
                    title="VS Code Copilot Chat logging looks stale or disabled",
                    detail=(
                        f"No VS Code chat sessions were logged in the last {stale_days:.0f} days, while CLI activity "
                        f"is recent (within {cli_age_days:.1f} days). If Copilot Chat is actually being used in VS "
                        f"Code, its debug logging is likely disabled or the window hasn't been reloaded since "
                        f"enabling it."
                    ),
                    source="chat",
                    evidence=[{"latestChatTimestamp": latest_chat_ts or None, "latestCliTimestamp": latest_cli_ts}],
                    savings_cost=0.0,
                    savings_premium=0.0,
                    action=(
                        "Add the debug-log settings from the 'Setting up VS Code Copilot Chat logging' README "
                        "section to settings.json (User, and Remote if applicable), then reload the VS Code window "
                        "and start a new chat - history is never retroactively logged."
                    ),
                    confidence="medium",
                ))

    if cli_data.get("available") and not cli_data.get("otelAvailable"):
        out.append(_make_insight(
            insight_id="cli-otel-disabled",
            severity="info",
            title="CLI OpenTelemetry export is off - tool-level insight unavailable",
            detail=(
                "GitHub Copilot CLI data is available, but no OpenTelemetry file-exporter JSONL was found, so "
                "per-tool-call timing/impact data isn't available for the CLI tab."
            ),
            source="cli",
            evidence=[{"dbPath": cli_data.get("dbPath"), "otelPaths": cli_data.get("otelPaths", [])}],
            savings_cost=0.0,
            savings_premium=0.0,
            action=(
                "Set COPILOT_OTEL_FILE_EXPORTER_PATH=/path/to/copilot-otel.jsonl before running `copilot`, then pass "
                "--cli-otel-log /path/to/copilot-otel.jsonl (or set the same env var) when generating the dashboard."
            ),
            confidence="high",
        ))

    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_insights(
    app_data: dict[str, Any],
    config: dict[str, Any] | None = None,
    now_ms: float | int | None = None,
) -> list[dict[str, Any]]:
    """Build the full ranked list of deterministic insights for `app_data`.

    `config` may be a full override dict shaped like `DEFAULT_CONFIG` (missing
    keys fall back to defaults); when omitted, `load_insights_config()` is
    used (JSON config file, if present, else `DEFAULT_CONFIG`). Any single
    rule crashing is caught and recorded in a `_errors` list attached to the
    module-level return via `build_insights_with_diagnostics`; `build_insights`
    itself always returns a plain list (never raises).
    """
    insights, _errors = build_insights_with_diagnostics(app_data, config=config, now_ms=now_ms)
    return insights


def build_insights_with_diagnostics(
    app_data: dict[str, Any],
    config: dict[str, Any] | None = None,
    now_ms: float | int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Same as `build_insights`, but also returns a list of per-rule error strings."""
    cfg = _merge_config(config) if config is not None else load_insights_config()
    errors: list[str] = []
    all_insights: list[dict[str, Any]] = []

    sessions = app_data.get("sessions") or []
    cli_data = app_data.get("cli") or {}
    cli_sessions = cli_data.get("sessions") or []
    unified = app_data.get("unified") or {}
    premium = app_data.get("premium") or {}

    rules = [
        ("lowCacheHitRate", lambda: _rule_low_cache_hit_rate(sessions, cfg)),
        ("expensiveModelTrivialWork", lambda: _rule_expensive_model_trivial_work(sessions, cfg)),
        ("duplicateFileReads", lambda: _rule_duplicate_file_reads(sessions, cfg)),
        ("contextResetChurn", lambda: _rule_context_reset_churn(sessions, cfg)),
        ("oversizedSessions", lambda: _rule_oversized_sessions(sessions, cfg)),
        ("abandonedSessions", lambda: _rule_abandoned_sessions(sessions, cli_sessions, cfg)),
        ("modelSubstitutionPolicy", lambda: _rule_model_substitution_policy(unified, cfg)),
        ("chatVsCliComparison", lambda: _rule_chat_vs_cli_comparison(unified, cfg)),
        ("premiumRequestBurn", lambda: _rule_premium_request_burn(premium, cfg)),
        ("dataHealth", lambda: _rule_data_health(app_data, cfg, now_ms)),
    ]

    for name, rule_fn in rules:
        try:
            all_insights.extend(rule_fn())
        except Exception as exc:  # pragma: no cover - defensive, keeps one bad rule from breaking the rest
            errors.append(f"{name}: {exc!r}")

    all_insights.sort(
        key=lambda insight: (
            SEVERITY_RANK.get(insight.get("severity"), 3),
            -float((insight.get("estimatedSavings") or {}).get("cost", 0.0) or 0.0),
        )
    )
    return all_insights, errors
