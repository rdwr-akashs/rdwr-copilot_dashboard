"""Tests for the cache read path in `json_storage.py`.

This module owns zstd decompression plus SHA256 verification for every cached
session, and it previously had no tests at all while carrying the largest
concentration of silent `return None` swallows in the codebase. That is a bad
combination for a tool whose output is a cost figure: a cache entry that fails
to decompress lowers a total, and nothing said so.

The central pair of assertions here is the distinction the old code could not
make:

    absent file             -> no diagnostic (a normal cache miss)
    present but unreadable  -> cost-impacting diagnostic

Both matter. Missing the second silently understates spend; over-reporting the
first trains the operator to ignore the banner.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess

import pytest

import diagnostics
import json_storage

requires_zstd = pytest.mark.skipif(
    shutil.which("zstd") is None, reason="zstd CLI not installed"
)


def setup_function() -> None:
    diagnostics.reset()


def teardown_function() -> None:
    diagnostics.reset()


def _write_zst(path, payload: dict, *, with_checksum: bool = True):
    """Write `payload` as a .zst the way the production writer does."""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    completed = subprocess.run(
        ["zstd", "-q", "-c"], input=raw, capture_output=True, check=True
    )
    path.write_bytes(completed.stdout)
    if with_checksum:
        digest = hashlib.sha256(raw).hexdigest()
        path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}\n")
    return raw


# --------------------------------------------------------------------------
# Absent input is a cache miss, not a failure.
# --------------------------------------------------------------------------

def test_absent_file_returns_none_and_reports_nothing(tmp_path):
    assert json_storage.read_json_file(str(tmp_path / "nope.json")) is None
    assert diagnostics.entries() == []


def test_absent_file_text_reader_reports_nothing(tmp_path):
    assert json_storage.read_json_text(str(tmp_path / "nope.json")) is None
    assert diagnostics.entries() == []


# --------------------------------------------------------------------------
# Happy paths stay silent.
# --------------------------------------------------------------------------

def test_plain_json_roundtrip_is_silent(tmp_path):
    target = tmp_path / "a.json"
    target.write_text(json.dumps({"ok": True}))
    assert json_storage.read_json_file(str(target)) == {"ok": True}
    assert diagnostics.entries() == []


@requires_zstd
def test_compressed_roundtrip_with_valid_checksum_is_silent(tmp_path):
    target = tmp_path / "a.json.zst"
    _write_zst(target, {"ok": True})
    assert json_storage.read_json_file(str(target)) == {"ok": True}
    assert diagnostics.entries() == []


# --------------------------------------------------------------------------
# Present-but-broken input must surface, and must be marked cost-impacting.
# --------------------------------------------------------------------------

@requires_zstd
def test_corrupt_zst_reports_cost_impacting_error(tmp_path):
    target = tmp_path / "a.json.zst"
    _write_zst(target, {"ok": True})
    # Truncate to something zstd cannot inflate.
    target.write_bytes(target.read_bytes()[:5])

    assert json_storage.read_json_file(str(target)) is None

    entries = diagnostics.entries()
    assert len(entries) == 1
    assert entries[0]["code"] == diagnostics.CODE_CACHE_CORRUPT
    assert entries[0]["severity"] == "error"
    assert entries[0]["impact"] == "cost"
    assert str(target) in entries[0]["source"]


@requires_zstd
def test_checksum_mismatch_is_reported_not_silently_discarded(tmp_path):
    target = tmp_path / "a.json.zst"
    _write_zst(target, {"ok": True})
    # Valid zstd, valid JSON, wrong checksum - the torn/tampered-cache case.
    target.with_suffix(target.suffix + ".sha256").write_text(f"{'0' * 64}\n")

    assert json_storage.read_json_file(str(target)) is None

    codes = [item["code"] for item in diagnostics.entries()]
    assert diagnostics.CODE_CACHE_CHECKSUM_MISMATCH in codes
    mismatch = next(
        item
        for item in diagnostics.entries()
        if item["code"] == diagnostics.CODE_CACHE_CHECKSUM_MISMATCH
    )
    assert mismatch["impact"] == "cost"
    assert mismatch["severity"] == "error"


def test_malformed_json_reports_cost_impacting_error(tmp_path):
    target = tmp_path / "a.json"
    target.write_text("{not json at all")

    assert json_storage.read_json_file(str(target)) is None

    entries = diagnostics.entries()
    assert len(entries) == 1
    assert entries[0]["code"] == diagnostics.CODE_CACHE_BAD_JSON
    assert entries[0]["impact"] == "cost"


def test_unreadable_checksum_sidecar_warns_but_is_not_cost_impacting(
    tmp_path, monkeypatch
):
    # The sidecar exists (so the isfile() guard passes) but cannot be opened.
    # Simulated rather than done with permissions, because chmod does not
    # reliably deny the owner on Windows and this suite runs there.
    target = tmp_path / "a.json.zst"
    target.write_bytes(b"whatever")
    sidecar = tmp_path / "a.json.zst.sha256"
    sidecar.write_text("deadbeef\n")

    real_open = open

    def exploding_open(file, *args, **kwargs):
        if str(file) == str(sidecar):
            raise OSError("permission denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", exploding_open)
    json_storage._read_checksum_text(str(target))
    monkeypatch.undo()

    entries = diagnostics.entries()
    assert len(entries) == 1
    assert entries[0]["code"] == diagnostics.CODE_CACHE_UNREADABLE
    assert entries[0]["severity"] == "warning"
    assert entries[0]["impact"] == "presentation"


# --------------------------------------------------------------------------
# Aggregate behaviour across many broken entries.
# --------------------------------------------------------------------------

@requires_zstd
def test_many_broken_entries_stay_individually_attributable(tmp_path):
    # One entry per file, because the operator needs to know WHICH files were
    # dropped, not just that something was.
    for index in range(5):
        target = tmp_path / f"s{index}.json.zst"
        _write_zst(target, {"i": index})
        target.write_bytes(b"\x28\xb5\x2f\xfd\x00")
        json_storage.read_json_file(str(target))

    entries = diagnostics.entries()
    assert len(entries) == 5
    assert diagnostics.summary()["costImpacting"] == 5


def test_repeated_reads_of_the_same_broken_file_collapse(tmp_path):
    target = tmp_path / "a.json"
    target.write_text("{not json")
    for _ in range(10):
        json_storage.read_json_file(str(target))

    entries = diagnostics.entries()
    assert len(entries) == 1
    assert entries[0]["count"] == 10
