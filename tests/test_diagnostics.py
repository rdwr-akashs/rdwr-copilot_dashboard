"""Tests for the structured diagnostics collector.

The behaviour that matters here is not "does it store a string" - it is the two
properties the dashboard banner depends on:

* an ABSENT cache file must produce no diagnostic (otherwise the banner cries
  wolf on every clean first run and gets trained away as noise), and
* a PRESENT-but-unreadable one must produce a cost-impacting diagnostic.

`test_json_storage.py` covers that pair against the real reader.
"""
from __future__ import annotations

import diagnostics


def setup_function() -> None:
    diagnostics.reset()


def teardown_function() -> None:
    diagnostics.reset()


def test_report_records_all_fields():
    diagnostics.report(
        diagnostics.CODE_CACHE_CORRUPT,
        "boom",
        severity="error",
        impact="cost",
        source="/tmp/a.zst",
    )
    entries = diagnostics.entries()
    assert len(entries) == 1
    assert entries[0] == {
        "code": "cache.corrupt",
        "message": "boom",
        "severity": "error",
        "impact": "cost",
        "source": "/tmp/a.zst",
        "count": 1,
    }


def test_repeats_of_same_code_and_source_collapse_into_one_counted_entry():
    for _ in range(500):
        diagnostics.report(
            diagnostics.CODE_OTEL_LINE_SKIPPED,
            "bad line",
            severity="info",
            impact="none",
            source="/tmp/otel.jsonl",
        )
    entries = diagnostics.entries()
    assert len(entries) == 1
    assert entries[0]["count"] == 500


def test_same_code_different_source_stays_separate():
    diagnostics.report(diagnostics.CODE_CACHE_CORRUPT, "x", source="/tmp/a.zst")
    diagnostics.report(diagnostics.CODE_CACHE_CORRUPT, "x", source="/tmp/b.zst")
    assert len(diagnostics.entries()) == 2


def test_summary_counts_cost_impacting_separately_from_severity():
    # An 'error' that cannot move a number, and a 'warning' that can. The banner
    # keys on impact, not severity, so these must be counted independently.
    diagnostics.report(
        diagnostics.CODE_OTEL_LINE_SKIPPED, "x", severity="error", impact="none"
    )
    diagnostics.report(
        diagnostics.CODE_CACHE_CORRUPT, "y", severity="warning", impact="cost"
    )
    summary = diagnostics.summary()
    assert summary["total"] == 2
    assert summary["errors"] == 1
    assert summary["warnings"] == 1
    assert summary["costImpacting"] == 1


def test_entries_are_sorted_worst_first():
    diagnostics.report(diagnostics.CODE_OTEL_LINE_SKIPPED, "c", severity="info")
    diagnostics.report(diagnostics.CODE_CACHE_UNREADABLE, "b", severity="warning")
    diagnostics.report(diagnostics.CODE_CACHE_CORRUPT, "a", severity="error")
    assert [item["severity"] for item in diagnostics.entries()] == [
        "error",
        "warning",
        "info",
    ]


def test_entry_cap_truncates_and_says_so():
    # Distinct sources, so none of them collapse - this is the memory guard.
    for index in range(diagnostics._MAX_ENTRIES + 25):
        diagnostics.report(diagnostics.CODE_CACHE_CORRUPT, "x", source=f"/tmp/{index}")
    entries = diagnostics.entries()
    truncation = [item for item in entries if item["code"] == "diagnostics.truncated"]
    assert len(truncation) == 1
    assert truncation[0]["count"] == 25
    # Cap applies to real entries; the truncation notice itself is the extra one.
    assert len(entries) == diagnostics._MAX_ENTRIES + 1


def test_entries_does_not_drain():
    # Two readers during one rebuild must both see the finding; a drain-on-read
    # would let whoever asked first swallow it.
    diagnostics.report(diagnostics.CODE_CACHE_CORRUPT, "x", source="/tmp/a")
    assert len(diagnostics.entries()) == 1
    assert len(diagnostics.entries()) == 1


def test_reset_clears_between_rebuilds():
    diagnostics.report(diagnostics.CODE_CACHE_CORRUPT, "x", source="/tmp/a")
    diagnostics.reset()
    assert diagnostics.entries() == []
    assert diagnostics.summary()["total"] == 0


def test_as_dict_carries_entries_and_summary():
    diagnostics.report(diagnostics.CODE_CACHE_CORRUPT, "x", impact="cost")
    payload = diagnostics.as_dict()
    assert set(payload) == {"entries", "summary"}
    assert payload["summary"]["costImpacting"] == 1


def test_collector_is_threadsafe_under_concurrent_reports():
    import threading

    def worker(index: int) -> None:
        for _ in range(100):
            diagnostics.report(
                diagnostics.CODE_CACHE_CORRUPT, "x", source=f"/tmp/{index}"
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    entries = diagnostics.entries()
    assert len(entries) == 8
    assert all(item["count"] == 100 for item in entries)
