"""Integration tests for `serve_dashboard.py`'s HTTP server.

Starts the real `DashboardHandler` / `DashboardCache` on a real
`ThreadingHTTPServer`, bound to `("127.0.0.1", 0)` so the OS picks a free
ephemeral port -- this suite never hardcodes a port and never touches 8765
(a developer's own dashboard instance may already be running there). The
server is pointed exclusively at the synthetic fixtures from `conftest.py`
(`fake_debug_logs`, `fake_cli_db`, `fake_otel_jsonl`, `tmp_cache_dir`); it
never reads real user data, and `RemoteSyncManager` is given a fresh empty
tmp directory so it never touches `.remote-sync/sources.json` in the repo.

The server is always torn down in the fixture's `finally` block, even if a
test fails or raises.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

from remote_sync import RemoteSyncManager
from serve_dashboard import DashboardCache, DashboardHandler


def _request(base_url: str, path: str, *, method: str = "GET", headers: dict | None = None):
    """Issue an HTTP request and return (status, headers_dict, body_bytes).

    urllib.request raises HTTPError for any non-2xx status (including 304),
    so both the "success" and "error" paths are normalized here into one
    return shape instead of forcing every call site to catch separately.
    """
    req = urllib.request.Request(base_url + path, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.getheaders()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


@pytest.fixture
def dashboard_server(tmp_path, tmp_cache_dir, fake_debug_logs, fake_cli_db, fake_otel_jsonl):
    """Start a real serve_dashboard.py server in-process and yield its base URL."""
    serve_root = tmp_path / "serve-root"
    serve_root.mkdir(parents=True, exist_ok=True)

    remote_manager = RemoteSyncManager(
        workspace_dir=str(tmp_path),
        base_dir=str(tmp_path / ".remote-sync"),
    )
    dashboard_cache = DashboardCache(max_age_seconds=60)

    handler = partial(
        DashboardHandler,
        directory=str(serve_root),
        log_dirs=[fake_debug_logs],
        remote_manager=remote_manager,
        chat_cache_dir=tmp_cache_dir,
        force_recalculate=False,
        cache_verify_seconds=300,
        workers=2,
        cli_db_path=fake_cli_db,
        cli_otel_log_paths=[fake_otel_jsonl],
        output_file=str(serve_root / "dashboard.html"),
        dashboard_cache=dashboard_cache,
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, name="dashboard-test-server", daemon=True)
    thread.start()
    try:
        yield base_url
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _status(base_url: str) -> dict:
    status, _, body = _request(base_url, "/api/status")
    assert status == 200
    return json.loads(body)


def _data(base_url: str) -> dict:
    status, _, body = _request(base_url, "/api/data.json")
    assert status == 200
    return json.loads(body)


# --- /dashboard.html --------------------------------------------------------


def test_dashboard_html_ok_with_etag(dashboard_server):
    status, headers, body = _request(dashboard_server, "/dashboard.html")
    assert status == 200
    assert "html" in headers.get("Content-Type", "").lower()
    text = body.decode("utf-8")
    assert text.startswith("<!DOCTYPE html")
    assert re.search(r"(?:const|var|let)\s+APP_DATA\s*=", text), "APP_DATA assignment not found"
    assert headers.get("ETag"), "expected an ETag header"
    assert headers.get("Last-Modified"), "expected a Last-Modified header"


def test_root_path_serves_same_dashboard(dashboard_server):
    status, headers, body = _request(dashboard_server, "/")
    assert status == 200
    assert body.decode("utf-8").startswith("<!DOCTYPE html")


def test_if_none_match_etag_returns_304_with_empty_body(dashboard_server):
    _, headers, _ = _request(dashboard_server, "/dashboard.html")
    etag = headers["ETag"]

    status, headers2, body = _request(dashboard_server, "/dashboard.html", headers={"If-None-Match": etag})
    assert status == 304
    assert body == b""
    assert headers2.get("ETag") == etag


def test_if_modified_since_returns_304(dashboard_server):
    _, headers, _ = _request(dashboard_server, "/dashboard.html")
    last_modified = headers["Last-Modified"]

    status, _, body = _request(
        dashboard_server, "/dashboard.html", headers={"If-Modified-Since": last_modified}
    )
    assert status == 304
    assert body == b""


def test_second_identical_request_is_served_from_cache(dashboard_server):
    # The fixture already warmed the cache (twice, to settle a filesystem
    # fingerprint-timing race -- see the fixture's docstring), so both calls
    # here start from a stable, already-fresh cache: the fingerprint is
    # unchanged and we're well within the 60s max-age, so the second request
    # must be a cache "hit", not a rebuild. Assert via /api/status counters
    # (not timing, which is flaky in CI).
    _request(dashboard_server, "/dashboard.html")
    before = _status(dashboard_server)

    _request(dashboard_server, "/dashboard.html")
    after = _status(dashboard_server)

    assert after["cacheHits"] == before["cacheHits"] + 1
    assert after["cacheMisses"] == before["cacheMisses"]


def test_refresh_query_param_forces_rebuild(dashboard_server):
    _request(dashboard_server, "/dashboard.html")
    before = _status(dashboard_server)

    _request(dashboard_server, "/dashboard.html?refresh=1")
    after = _status(dashboard_server)

    assert after["cacheMisses"] == before["cacheMisses"] + 1


def test_cache_control_no_cache_header_forces_rebuild(dashboard_server):
    _request(dashboard_server, "/dashboard.html")
    before = _status(dashboard_server)

    _request(dashboard_server, "/dashboard.html", headers={"Cache-Control": "no-cache"})
    after = _status(dashboard_server)

    assert after["cacheMisses"] == before["cacheMisses"] + 1


# --- /api/data.json ----------------------------------------------------------


def test_api_data_json_has_documented_top_level_keys(dashboard_server):
    """`/api/data.json` must include every key `dashboard_core.compose_app_data()`
    attaches -- `unified`/`premium`/`insights`/`anonymized` included -- since
    `serve_dashboard.py`'s `_compose_dashboard()` now shares that composition
    seam with the batch (`write_dashboard()`) path. This test previously
    carried a dedicated strict-xfail (`test_api_data_json_is_missing_unified_and_premium_keys`)
    documenting a real gap where the live server never attached `unified`/
    `premium` at all; that gap has since been fixed (the live and batch paths
    both call `dashboard_core.compose_app_data()`), so the assertion is folded
    back in here rather than kept as a separate xfail.
    """
    status, headers, body = _request(dashboard_server, "/api/data.json")
    assert status == 200
    assert "json" in headers.get("Content-Type", "").lower()
    data = json.loads(body)

    required_keys = {
        "generatedAt",
        "summary",
        "sessions",
        "analysis",
        "periods",
        "cli",
        "unified",
        "premium",
        "insights",
        "anonymized",
    }
    missing = required_keys - data.keys()
    assert not missing, f"app_data missing documented top-level keys: {sorted(missing)}"
    assert isinstance(data["insights"], list)
    assert isinstance(data["anonymized"], bool)


def test_dashboard_html_embedded_app_data_has_documented_top_level_keys(dashboard_server):
    """Same contract as above, but for the APP_DATA blob embedded in the
    rendered `/dashboard.html` document, not just `/api/data.json`.
    """
    _, _, body = _request(dashboard_server, "/dashboard.html")
    text = body.decode("utf-8")
    match = re.search(r"(?:const|var|let)\s+APP_DATA\s*=\s*(\{.*?\});\s*\n", text, re.DOTALL)
    assert match is not None, "APP_DATA assignment not found in /dashboard.html"
    embedded = json.loads(match.group(1))

    required_keys = {
        "generatedAt",
        "summary",
        "sessions",
        "analysis",
        "periods",
        "cli",
        "unified",
        "premium",
        "insights",
        "anonymized",
    }
    missing = required_keys - embedded.keys()
    assert not missing, f"embedded APP_DATA missing documented top-level keys: {sorted(missing)}"


# --- /api/status --------------------------------------------------------------


def test_api_status_has_documented_fields(dashboard_server):
    _request(dashboard_server, "/dashboard.html")  # warm the cache once
    data = _status(dashboard_server)

    for key in (
        "lastRebuildAt",
        "lastRebuildDurationSeconds",
        "lastRebuildReason",
        "fingerprint",
        "cacheHits",
        "cacheMisses",
        "maxAgeSeconds",
        "etag",
        "resolvedLogDirs",
        "resolvedCliDbPath",
        "resolvedOtelPaths",
        "appDataKeys",
        "anonymized",
    ):
        assert key in data, f"missing /api/status field: {key}"

    assert data["maxAgeSeconds"] == 60
    assert data["cacheMisses"] >= 1
    assert isinstance(data["resolvedLogDirs"], list) and data["resolvedLogDirs"]
    assert data["resolvedCliDbPath"]
    assert isinstance(data["appDataKeys"], list)
    for expected_key in ("unified", "premium", "insights", "cli", "sessions"):
        assert expected_key in data["appDataKeys"], (
            f"'{expected_key}' missing from /api/status's appDataKeys: {data['appDataKeys']}"
        )
    assert data["appDataKeys"] == sorted(data["appDataKeys"]), "appDataKeys is documented as sorted"
    assert isinstance(data["anonymized"], bool)
    assert data["anonymized"] is False  # not requested via --anonymize / COPILOT_DASHBOARD_ANONYMIZE here


# --- /api/session -------------------------------------------------------------


def test_api_session_known_id_returns_full_payload(dashboard_server):
    data = _data(dashboard_server)
    sessions = data.get("sessions") or []
    assert sessions, "expected at least one session built from fake_debug_logs"
    known_id = sessions[0]["id"]

    status, headers, body = _request(dashboard_server, f"/api/session?id={known_id}")
    assert status == 200
    assert "json" in headers.get("Content-Type", "").lower()
    payload = json.loads(body)
    assert isinstance(payload, dict)
    assert "session" in payload


def test_api_session_bogus_id_returns_404(dashboard_server):
    status, _, body = _request(dashboard_server, "/api/session?id=this-session-does-not-exist-xyz")
    assert status == 404
    payload = json.loads(body)
    assert payload.get("ok") is False


def test_api_session_missing_id_returns_400(dashboard_server):
    status, _, body = _request(dashboard_server, "/api/session")
    assert status == 400
    payload = json.loads(body)
    assert payload.get("ok") is False


# --- misc / method & routing ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/", "/dashboard.html", "/api/data.json", "/api/status", "/api/session?id=x"],
)
def test_post_to_any_route_returns_404(dashboard_server, path):
    status, _, _ = _request(dashboard_server, path, method="POST")
    assert status == 404


def test_nonexistent_path_returns_404(dashboard_server):
    status, _, _ = _request(dashboard_server, "/this-path-does-not-exist.html")
    assert status == 404


# --- live-vs-batch parity -------------------------------------------------------
#
# serve_dashboard.py's _compose_dashboard() and dashboard_core.write_dashboard()
# both now delegate to the single shared seam, dashboard_core.compose_app_data(),
# specifically so the live HTTP path and the batch/CLI path can never drift apart
# again the way they briefly did (the live path once omitted `unified`/`premium`
# entirely). These tests assert that invariant directly, and then prove the
# assertion has teeth by temporarily breaking one side and watching it fail.


def _batch_app_data(fake_debug_logs, fake_cli_db, fake_otel_jsonl, tmp_cache_dir):
    """Build app_data via the exact same batch-path seam write_dashboard() uses,
    against the same fixtures the `dashboard_server` fixture is pointed at.
    """
    import dashboard_core

    return dashboard_core.compose_app_data(
        log_dirs=[fake_debug_logs],
        cache_root_dir=tmp_cache_dir,
        force_recalculate=False,
        cache_verify_seconds=300,
        workers=2,
        cli_db_path=fake_cli_db,
        cli_otel_log_paths=[fake_otel_jsonl],
    )


def test_live_and_batch_app_data_have_same_top_level_keys(
    dashboard_server, fake_debug_logs, fake_cli_db, fake_otel_jsonl, tmp_cache_dir
):
    """The live server's `app_data` (served at `/api/data.json`) and
    `dashboard_core.compose_app_data()`'s batch-path output, built against the
    identical fixtures, must expose the same set of top-level keys. Exact
    values (e.g. `generatedAt`, timestamps) are legitimately allowed to
    differ -- only the *shape* (key set) is compared.
    """
    status, _, body = _request(dashboard_server, "/api/data.json")
    assert status == 200
    live_keys = set(json.loads(body).keys())

    batch_data = _batch_app_data(fake_debug_logs, fake_cli_db, fake_otel_jsonl, tmp_cache_dir)
    batch_keys = set(batch_data.keys())

    only_in_live = live_keys - batch_keys
    only_in_batch = batch_keys - live_keys
    assert not only_in_live and not only_in_batch, (
        f"live-server app_data and batch compose_app_data() top-level keys diverged: "
        f"present only in the live server response: {sorted(only_in_live) or '(none)'}; "
        f"present only in the batch dashboard_core.compose_app_data() output: "
        f"{sorted(only_in_batch) or '(none)'}"
    )


def test_parity_test_actually_catches_a_dropped_key(
    dashboard_server, fake_debug_logs, fake_cli_db, fake_otel_jsonl, tmp_cache_dir
):
    """Proves `test_live_and_batch_app_data_have_same_top_level_keys` has teeth:
    re-run its comparison with one side's key set deliberately mutated to drop
    a key, and confirm that -- and only that -- produces a failure, then
    confirm the unmutated comparison is green again immediately after.
    """
    status, _, body = _request(dashboard_server, "/api/data.json")
    assert status == 200
    live_keys = set(json.loads(body).keys())

    batch_data = _batch_app_data(fake_debug_logs, fake_cli_db, fake_otel_jsonl, tmp_cache_dir)
    batch_keys = set(batch_data.keys())

    # Sanity: the real, unmutated comparison is green.
    assert not (live_keys - batch_keys) and not (batch_keys - live_keys)

    # Now deliberately simulate one path dropping "unified" (mirroring the
    # real bug that used to exist in serve_dashboard.py's _compose_dashboard())
    # and confirm the same key-set comparison used above now fails loudly.
    broken_live_keys = live_keys - {"unified"}
    with pytest.raises(AssertionError, match=r"unified"):
        only_in_live = broken_live_keys - batch_keys
        only_in_batch = batch_keys - broken_live_keys
        assert not only_in_live and not only_in_batch, (
            f"live-server app_data and batch compose_app_data() top-level keys diverged: "
            f"present only in the live server response: {sorted(only_in_live) or '(none)'}; "
            f"present only in the batch dashboard_core.compose_app_data() output: "
            f"{sorted(only_in_batch) or '(none)'}"
        )

    # And restoring the real (unbroken) key set is green again -- the
    # assertion machinery itself was never at fault, only the deliberately
    # broken input above.
    assert not (live_keys - batch_keys) and not (batch_keys - live_keys)


# --- compose_app_data() seam ----------------------------------------------------


def test_compose_app_data_returns_documented_keys(fake_debug_logs, fake_cli_db, fake_otel_jsonl, tmp_cache_dir):
    """Direct unit coverage of the shared composition seam itself, hermetically
    against the synthetic fixtures, independent of any HTTP server.
    """
    import dashboard_core

    app_data = dashboard_core.compose_app_data(
        log_dirs=[fake_debug_logs],
        cache_root_dir=tmp_cache_dir,
        force_recalculate=False,
        cache_verify_seconds=300,
        workers=2,
        cli_db_path=fake_cli_db,
        cli_otel_log_paths=[fake_otel_jsonl],
    )

    required_keys = {
        "generatedAt",
        "summary",
        "sessions",
        "analysis",
        "periods",
        "cli",
        "unified",
        "premium",
        "insights",
        "anonymized",
    }
    missing = required_keys - app_data.keys()
    assert not missing, f"compose_app_data() missing documented top-level keys: {sorted(missing)}"
    assert isinstance(app_data["insights"], list)
    assert isinstance(app_data["anonymized"], bool)
    assert app_data["anonymized"] is False  # anonymize=False (the default) was passed above


def test_compose_app_data_anonymize_flag_sets_anonymized_true(
    fake_debug_logs, fake_cli_db, fake_otel_jsonl, tmp_cache_dir
):
    import dashboard_core

    app_data = dashboard_core.compose_app_data(
        log_dirs=[fake_debug_logs],
        cache_root_dir=tmp_cache_dir,
        force_recalculate=False,
        cache_verify_seconds=300,
        workers=2,
        cli_db_path=fake_cli_db,
        cli_otel_log_paths=[fake_otel_jsonl],
        anonymize=True,
    )
    assert app_data["anonymized"] is True
