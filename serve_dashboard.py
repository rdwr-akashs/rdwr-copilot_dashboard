#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from datetime import timezone
from email.utils import formatdate, parsedate_to_datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import dashboard_core
from cli_usage import default_cli_db_path, default_cli_otel_paths
from dashboard_core import build_dashboard_data, default_output_path, discover_log_dirs, load_full_session_payload
from remote_sync import RemoteSyncManager


def _env_flag(name: str) -> bool:
    """Parse a boolean-ish environment variable (1/true/yes/on, case-insensitive).

    Small local copy of dashboard_core._env_flag() (a private helper we should not
    import/depend on across module boundaries) used only to mirror its
    --anonymize / COPILOT_DASHBOARD_ANONYMIZE default here.
    """
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _compose_dashboard(
    log_dirs: list[str],
    cache_root_dir: str | None,
    force_recalculate: bool,
    cache_verify_seconds: int,
    workers: int,
    cli_db_path: str | None,
    cli_otel_log_paths: list[str] | None,
    premium_plan: str | None = None,
    premium_quota: int | None = None,
    premium_config_path: str | None = None,
    anonymize: bool = False,
) -> tuple[dict, str]:
    """Build app_data + rendered HTML in one pass via dashboard_core's shared seam.

    dashboard_core.compose_app_data() performs the exact same composition
    write_dashboard() does (unified model, premium/budget, insights, anonymization,
    ...) and hands back the finished app_data, so the live server and the batch CLI
    are guaranteed identical by construction -- any future stage added there is
    picked up here for free, with no duplication and no monkeypatching.
    """
    app_data = dashboard_core.compose_app_data(
        log_dirs=log_dirs,
        cache_root_dir=cache_root_dir,
        force_recalculate=force_recalculate,
        cache_verify_seconds=cache_verify_seconds,
        workers=workers,
        cli_db_path=cli_db_path,
        cli_otel_log_paths=cli_otel_log_paths,
        premium_plan=premium_plan,
        premium_quota=premium_quota,
        premium_config_path=premium_config_path,
        anonymize=anonymize,
    )
    html = dashboard_core.generate_html(app_data)
    return app_data, html


class DashboardCache:
    """Thread-safe fingerprint-based cache for the rendered dashboard.

    Fingerprint strategy (deliberately cheap, not a full content hash):
    - For each log dir: stat the directory itself (mtime_ns) plus one shallow
      `scandir` pass over its immediate children (per-session-dir name/mtime/size).
      We do NOT recurse into each session directory's files. Debug-log sessions are
      effectively append-only (new files land in new/changed session dirs, which
      bumps either the parent dir mtime or the session dir's own mtime/size), so this
      catches the overwhelming majority of real changes at O(#sessions) stats instead
      of O(#files). Tradeoff: an in-place edit to an existing file's *content*, with a
      timestamp/size that happens not to change, would be missed until max-age expiry.
    - CLI DB path and OTel log paths: single stat() each (mtime_ns + size).

    Rebuild trigger precedence: forced (no-cache header / ?refresh=1) > no cache yet
    (initial) > fingerprint changed > cache older than max_age_seconds.
    The lock is held for the *entire* rebuild, which intentionally serializes any
    concurrent "first hit" requests instead of doing double-checked locking; rebuilds
    are infrequent (fingerprint-gated) so the extra serialization cost is negligible
    compared to the complexity of a lock-free rebuild-dedup scheme.

    Mtime jitter: all mtimes are quantized down to whole seconds (`_QUANTUM_NS`)
    before hashing. A directory's own mtime can still be "settling" for a few ms
    right after its children finish being written (metadata flush lag), which was
    observed to occasionally produce two different fingerprints for the same real
    state a moment apart. Sub-second precision buys us nothing here anyway (a
    rebuild inherently takes far longer than 1s), so flooring to whole seconds
    absorbs that jitter for free while remaining just as cheap to compute.
    """

    _QUANTUM_NS = 1_000_000_000  # 1 second, to absorb sub-second mtime jitter.

    def __init__(self, max_age_seconds: float):
        self.max_age_seconds = max(1.0, float(max_age_seconds))
        self._lock = threading.Lock()
        self.app_data: dict | None = None
        self.html_bytes: bytes = b""
        self.etag: str | None = None
        self.last_modified_epoch: float = 0.0
        self.last_modified_http: str = ""
        self.fingerprint: str | None = None
        self.last_rebuild_ts: float = 0.0
        self.last_rebuild_duration: float = 0.0
        self.last_rebuild_reason: str = ""
        self.hits = 0
        self.misses = 0

    @classmethod
    def _quantized_mtime(cls, mtime_ns: int) -> int:
        return mtime_ns // cls._QUANTUM_NS

    @classmethod
    def compute_fingerprint(cls, log_dirs: list[str], cli_db_path: str | None, otel_paths: list[str]) -> str:
        hasher = hashlib.sha256()
        for log_dir in sorted(set(log_dirs or [])):
            try:
                top_stat = os.stat(log_dir)
                hasher.update(f"D|{log_dir}|{cls._quantized_mtime(top_stat.st_mtime_ns)}".encode("utf-8", "ignore"))
                with os.scandir(log_dir) as scan_iter:
                    children = sorted(scan_iter, key=lambda entry: entry.name)
                for entry in children:
                    try:
                        child_stat = entry.stat()
                        hasher.update(
                            f"C|{entry.name}|{cls._quantized_mtime(child_stat.st_mtime_ns)}|{child_stat.st_size}".encode(
                                "utf-8", "ignore"
                            )
                        )
                    except OSError:
                        continue
            except OSError:
                hasher.update(f"D|{log_dir}|MISSING".encode("utf-8", "ignore"))
        if cli_db_path:
            try:
                db_stat = os.stat(cli_db_path)
                hasher.update(
                    f"DB|{cli_db_path}|{cls._quantized_mtime(db_stat.st_mtime_ns)}|{db_stat.st_size}".encode(
                        "utf-8", "ignore"
                    )
                )
            except OSError:
                hasher.update(f"DB|{cli_db_path}|MISSING".encode("utf-8", "ignore"))
        for otel_path in sorted(set(otel_paths or [])):
            try:
                otel_stat = os.stat(otel_path)
                hasher.update(
                    f"O|{otel_path}|{cls._quantized_mtime(otel_stat.st_mtime_ns)}|{otel_stat.st_size}".encode(
                        "utf-8", "ignore"
                    )
                )
            except OSError:
                hasher.update(f"O|{otel_path}|MISSING".encode("utf-8", "ignore"))
        return hasher.hexdigest()

    def ensure_fresh(
        self,
        *,
        resolved_log_dirs: list[str],
        cli_db_path: str | None,
        otel_paths: list[str],
        compose_fn,
        output_file: str | None,
        force: bool = False,
    ) -> tuple[dict, bytes, str, str]:
        fingerprint = self.compute_fingerprint(resolved_log_dirs, cli_db_path, otel_paths)
        now = time.time()
        with self._lock:
            reason = None
            if force:
                reason = "forced"
            elif self.app_data is None:
                reason = "initial"
            elif fingerprint != self.fingerprint:
                reason = "fingerprint-changed"
            elif (now - self.last_rebuild_ts) > self.max_age_seconds:
                reason = "max-age-expired"

            if reason is None:
                self.hits += 1
                return self.app_data, self.html_bytes, self.etag, self.last_modified_http

            self.misses += 1
            start = time.perf_counter()
            app_data, html = compose_fn(resolved_log_dirs, cli_db_path, otel_paths)
            duration = time.perf_counter() - start

            html_bytes = html.encode("utf-8")
            html_hash = hashlib.sha256(html_bytes).hexdigest()[:16]
            etag = f'"{fingerprint[:16]}-{html_hash}"'
            last_modified_epoch = time.time()
            last_modified_http = formatdate(last_modified_epoch, usegmt=True)

            if output_file:
                try:
                    output_dir = os.path.dirname(output_file)
                    if output_dir:
                        os.makedirs(output_dir, exist_ok=True)
                    with open(output_file, "w", encoding="utf-8") as handle:
                        handle.write(html)
                except OSError as exc:
                    print(f"[dashboard-cache] Warning: failed to write {output_file}: {exc}", file=sys.stderr)

            self.app_data = app_data
            self.html_bytes = html_bytes
            self.etag = etag
            self.last_modified_epoch = last_modified_epoch
            self.last_modified_http = last_modified_http
            self.fingerprint = fingerprint
            self.last_rebuild_ts = last_modified_epoch
            self.last_rebuild_duration = duration
            self.last_rebuild_reason = reason

            print(
                f"[dashboard-cache] rebuild triggered by '{reason}' in {duration:.3f}s "
                f"(fingerprint={fingerprint[:12]})",
                file=sys.stderr,
            )

            return self.app_data, self.html_bytes, self.etag, self.last_modified_http

    def status(self) -> dict:
        with self._lock:
            app_data = self.app_data or {}
            # Read diagnostics off the cached app_data rather than the live
            # collector: app_data is the snapshot of the last completed
            # rebuild, so /api/status always describes the build that produced
            # the HTML currently being served. The collector is reset at the
            # start of each rebuild and would report an empty set to anyone who
            # asked mid-rebuild.
            diags = app_data.get("diagnostics") or {}
            return {
                "lastRebuildAt": (
                    formatdate(self.last_rebuild_ts, usegmt=True) if self.last_rebuild_ts else None
                ),
                "lastRebuildDurationSeconds": round(self.last_rebuild_duration, 4),
                "lastRebuildReason": self.last_rebuild_reason or None,
                "fingerprint": (self.fingerprint or "")[:12] or None,
                "cacheHits": self.hits,
                "cacheMisses": self.misses,
                "maxAgeSeconds": self.max_age_seconds,
                "etag": self.etag,
                "appDataKeys": sorted(app_data.keys()),
                "anonymized": bool(app_data.get("anonymized", False)),
                "diagnostics": diags.get("entries", []),
                "diagnosticsSummary": diags.get(
                    "summary",
                    {"total": 0, "errors": 0, "warnings": 0, "costImpacting": 0},
                ),
            }


def merge_log_dirs(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw_path in group or []:
            path = os.path.abspath(str(raw_path))
            if path in seen:
                continue
            seen.add(path)
            merged.append(path)
    return merged


_SPEC_FORMAT = "IP,USERNAME,PATH[,PORT]"

# The old spec carried a PASSWORD in the third field. It was dropped because
# argv is visible in shell history and in any process listing on the machine,
# and remote sync now authenticates with SSH keys/agent only. A legacy spec is
# still recognised here purely so it can be rejected with an explanation
# instead of a baffling "path must be absolute" further down.
_LEGACY_SPEC_ERROR = (
    "Remote sources no longer take a PASSWORD field: use "
    f"{_SPEC_FORMAT} and SSH key authentication. Passwords were removed because "
    "argv is visible in shell history and process listings. Verify your key "
    "works first with: ssh USERNAME@IP"
)


def parse_remote_spec(spec: str) -> tuple[str, str, str, int]:
    parts = [item.strip() for item in (spec or "").split(",", 4)]

    # 3 fields is unambiguously the current format; 5 is unambiguously legacy.
    # 4 is ambiguous (IP,USER,PATH,PORT vs IP,USER,PASSWORD,PATH), so decide on
    # which field looks like the absolute remote path.
    if len(parts) == 5:
        raise ValueError(_LEGACY_SPEC_ERROR)
    if len(parts) == 4 and not parts[2].startswith("/") and parts[3].startswith("/"):
        raise ValueError(_LEGACY_SPEC_ERROR)
    if len(parts) not in {3, 4}:
        raise ValueError(f"Remote source must be: {_SPEC_FORMAT}")

    host, username, remote_path = parts[:3]
    if not host or not username or not remote_path:
        raise ValueError(f"Remote source missing required fields. Format: {_SPEC_FORMAT}")
    if not remote_path.startswith("/"):
        raise ValueError("Remote path must be absolute (start with '/').")

    port = 22
    if len(parts) == 4 and parts[3]:
        port = int(parts[3])
    return host, username, remote_path, port


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args,
        directory: str,
        log_dirs: list[str],
        remote_manager: RemoteSyncManager,
        chat_cache_dir: str | None,
        force_recalculate: bool,
        cache_verify_seconds: int,
        workers: int = 8,
        cli_db_path: str | None = None,
        cli_otel_log_paths: list[str] | None = None,
        output_file: str | None = None,
        dashboard_cache: DashboardCache | None = None,
        premium_plan: str | None = None,
        premium_quota: int | None = None,
        premium_config_path: str | None = None,
        anonymize: bool = False,
        **kwargs,
    ):
        self._dashboard_directory = directory
        self._output_file = output_file or os.path.join(directory, "dashboard.html")
        self._log_dirs = log_dirs
        self._remote_manager = remote_manager
        self._chat_cache_dir = chat_cache_dir
        self._force_recalculate = bool(force_recalculate)
        self._cache_verify_seconds = max(30, int(cache_verify_seconds))
        self._workers = max(1, min(64, int(workers or 8)))
        self._cli_db_path = cli_db_path
        self._cli_otel_log_paths = cli_otel_log_paths
        self._premium_plan = premium_plan
        self._premium_quota = premium_quota
        self._premium_config_path = premium_config_path
        self._anonymize = bool(anonymize)
        self._cache = dashboard_cache or DashboardCache(max_age_seconds=60)
        super().__init__(*args, directory=directory, **kwargs)

    def _send_json(self, status: int, payload: dict, *, etag: str | None = None, last_modified: str | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if etag:
            self.send_header("ETag", etag)
        if last_modified:
            self.send_header("Last-Modified", last_modified)
        if etag or last_modified:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _resolved_log_dirs(self) -> list[str]:
        return merge_log_dirs(self._log_dirs, self._remote_manager.get_cache_dirs())

    def _resolved_cli_db_path(self) -> str | None:
        return self._cli_db_path or default_cli_db_path()

    def _resolved_otel_paths(self) -> list[str]:
        return self._cli_otel_log_paths if self._cli_otel_log_paths is not None else default_cli_otel_paths()

    def _compose(self, resolved_log_dirs: list[str], cli_db_path: str | None, otel_paths: list[str]) -> tuple[dict, str]:
        return _compose_dashboard(
            resolved_log_dirs,
            cache_root_dir=self._chat_cache_dir,
            force_recalculate=self._force_recalculate,
            cache_verify_seconds=self._cache_verify_seconds,
            workers=self._workers,
            cli_db_path=cli_db_path,
            cli_otel_log_paths=otel_paths,
            premium_plan=self._premium_plan,
            premium_quota=self._premium_quota,
            premium_config_path=self._premium_config_path,
            anonymize=self._anonymize,
        )

    def _wants_forced_refresh(self, query: dict) -> bool:
        cache_control = (self.headers.get("Cache-Control") or "").lower()
        pragma = (self.headers.get("Pragma") or "").lower()
        if "no-cache" in cache_control or "no-cache" in pragma:
            return True
        return str((query.get("refresh") or [""])[0]) == "1"

    def _ensure_fresh(self, force: bool = False) -> tuple[dict, bytes, str, str]:
        resolved_log_dirs = self._resolved_log_dirs()
        if not resolved_log_dirs:
            raise RuntimeError("Could not find Copilot debug logs. Set COPILOT_DEBUG_LOGS or pass log directories explicitly.")
        return self._cache.ensure_fresh(
            resolved_log_dirs=resolved_log_dirs,
            cli_db_path=self._resolved_cli_db_path(),
            otel_paths=self._resolved_otel_paths(),
            compose_fn=self._compose,
            output_file=self._output_file,
            force=force,
        )

    def _conditional_hit(self, etag: str, last_modified_http: str) -> bool:
        if_none_match = self.headers.get("If-None-Match")
        if if_none_match:
            candidates = [value.strip() for value in if_none_match.split(",")]
            if "*" in candidates or etag in candidates:
                self._send_not_modified(etag, last_modified_http)
                return True

        if_modified_since = self.headers.get("If-Modified-Since")
        if if_modified_since:
            try:
                since_dt = parsedate_to_datetime(if_modified_since)
                last_dt = parsedate_to_datetime(last_modified_http)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=timezone.utc)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if since_dt >= last_dt:
                    self._send_not_modified(etag, last_modified_http)
                    return True
            except (TypeError, ValueError):
                pass
        return False

    def _send_not_modified(self, etag: str, last_modified_http: str) -> None:
        self.send_response(304)
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", last_modified_http)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def do_GET(self):
        parsed_url = urlparse(self.path)
        route = parsed_url.path
        query = parse_qs(parsed_url.query or "")
        force_refresh = self._wants_forced_refresh(query)

        if route == "/api/status":
            status = self._cache.status()
            status["resolvedLogDirs"] = self._resolved_log_dirs()
            status["resolvedCliDbPath"] = self._resolved_cli_db_path()
            status["resolvedOtelPaths"] = self._resolved_otel_paths()
            self._send_json(200, status)
            return

        if route == "/api/data.json":
            try:
                app_data, _html_bytes, etag, last_modified_http = self._ensure_fresh(force=force_refresh)
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": f"Failed to generate dashboard data: {exc}"})
                return
            if not force_refresh and self._conditional_hit(etag, last_modified_http):
                return
            self._send_json(200, app_data, etag=etag, last_modified=last_modified_http)
            return

        if route == "/api/session":
            session_id = str((query.get("id") or [""])[0] or "").strip()
            if not session_id:
                self._send_json(400, {"ok": False, "error": "Missing session id (query: id)."})
                return

            payload = load_full_session_payload(session_id, self._chat_cache_dir)
            if payload is None:
                # Ensure the cache (and its side-effect in-memory full-session index) is
                # current, then retry. ensure_fresh() is fingerprint-gated, so this is a
                # no-op rebuild when nothing has changed since the last request.
                try:
                    self._ensure_fresh(force=False)
                except Exception:
                    pass
                payload = load_full_session_payload(session_id, self._chat_cache_dir)

            if payload is None:
                self._send_json(404, {"ok": False, "error": f"Session '{session_id}' not found."})
                return

            self._send_json(200, payload)
            return

        if route in {"/", "/dashboard.html"}:
            try:
                _app_data, html_bytes, etag, last_modified_http = self._ensure_fresh(force=force_refresh)
            except Exception as exc:
                self.send_error(500, f"Failed to generate dashboard: {exc}")
                return

            if not force_refresh and self._conditional_hit(etag, last_modified_http):
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", last_modified_http)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(html_bytes)
            return

        return super().do_GET()

    def do_POST(self):
        # Remote import/sync endpoints removed; POST not supported.
        self.send_error(404, "Not found")
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Copilot token dashboard and regenerate it on each request.")
    parser.add_argument("--host", default=os.environ.get("COPILOT_DASHBOARD_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("COPILOT_DASHBOARD_PORT", "8765")))
    parser.add_argument(
        "--remote",
        action="append",
        default=[],
        metavar="IP,USERNAME,PATH[,PORT]",
        help=(
            "Add/import a remote source on startup. Authentication is SSH key/agent only "
            "(no password is accepted or stored), and the host must already be in known_hosts."
        ),
    )
    parser.add_argument(
        "--remote-poll-seconds",
        type=int,
        default=int(os.environ.get("COPILOT_DASHBOARD_REMOTE_POLL_SECONDS", "300")),
        help="How often to recompute remote MD5 and download changed logs.",
    )
    parser.add_argument(
        "--remote-cache-dir",
        default=os.environ.get("COPILOT_DASHBOARD_REMOTE_CACHE_DIR"),
        help="Optional directory for remote source metadata and downloaded cache.",
    )
    parser.add_argument(
        "--chat-cache-dir",
        default=os.environ.get("COPILOT_DASHBOARD_CACHE_DIR"),
        help="Directory for parsed chat/session cache (defaults to /mnt/radware/$USER/copilot_dashboard_cache when that mount exists, otherwise ~/.copilot-dashboard/cache).",
    )
    parser.add_argument(
        "--cache-verify-seconds",
        type=int,
        default=int(os.environ.get("COPILOT_DASHBOARD_CACHE_VERIFY_SECONDS", "300")),
        help="How often to content-verify unchanged sessions before trusting cached parse results.",
    )
    parser.add_argument(
        "--recalculate-all",
        action="store_true",
        help="Force full recalculation for all sessions even when cache entries are available.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("COPILOT_DASHBOARD_WORKERS", "8")),
        help="Number of worker threads for parallel session processing (default: 8, max: 64).",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Only write compact/full cache files for the discovered logs and exit without starting the dashboard server.",
    )
    parser.add_argument(
        "--cache-poll-seconds",
        type=int,
        default=int(os.environ.get("COPILOT_DASHBOARD_CACHE_POLL_SECONDS", "0")),
        help="When using --cache-only, keep refreshing the cache every N seconds instead of exiting (0 = one-shot).",
    )
    parser.add_argument(
        "--cache-shard",
        default=os.environ.get("COPILOT_DASHBOARD_CACHE_SHARD"),
        help="Override the cache shard name (defaults to the local server IP).",
    )
    parser.add_argument(
        "--cli-db",
        default=os.environ.get("COPILOT_CLI_DB"),
        help="Path to the GitHub Copilot CLI session-store.db (default: ~/.copilot/session-store.db, if present).",
    )
    parser.add_argument(
        "--cli-otel-log",
        action="append",
        default=None,
        help=(
            "Path to a GitHub Copilot CLI OpenTelemetry JSONL export file (from COPILOT_OTEL_FILE_EXPORTER_PATH), "
            "used to enrich CLI sessions with real per-tool-call data. Repeatable. "
            "Default: $COPILOT_OTEL_FILE_EXPORTER_PATH, if present."
        ),
    )
    parser.add_argument(
        "--cache-max-age-seconds",
        type=float,
        default=float(os.environ.get("COPILOT_DASHBOARD_CACHE_MAX_AGE", "60")),
        help=(
            "Maximum age (seconds) of the cached rendered dashboard before it is rebuilt "
            "even if inputs look unchanged (default: 60)."
        ),
    )
    parser.add_argument(
        "--plan",
        default=os.environ.get("COPILOT_PLAN"),
        help=(
            "GitHub Copilot plan used to resolve the monthly AI-credit allowance "
            "(free|pro|student|pro_plus|max|business|enterprise). Default: $COPILOT_PLAN, else 'pro'."
        ),
    )
    parser.add_argument(
        "--premium-quota",
        type=int,
        default=(int(os.environ.get("COPILOT_CREDIT_QUOTA") or os.environ["COPILOT_PREMIUM_QUOTA"])
                 if (os.environ.get("COPILOT_CREDIT_QUOTA") or os.environ.get("COPILOT_PREMIUM_QUOTA")) else None),
        help=(
            "Explicit monthly AI-credit allowance (1 credit = $0.01 of model usage), overriding "
            "the --plan default. Default: $COPILOT_CREDIT_QUOTA, or legacy $COPILOT_PREMIUM_QUOTA."
        ),
    )
    parser.add_argument(
        "--premium-config",
        default=os.environ.get("COPILOT_PREMIUM_CONFIG"),
        help="Path to a JSON config file overriding plan/credit-allowance/legacy-multipliers/thresholds.",
    )
    parser.add_argument(
        "--anonymize",
        action="store_true",
        default=_env_flag("COPILOT_DASHBOARD_ANONYMIZE"),
        help=(
            "Replace host/IP identifiers and home-directory paths in the served dashboard with "
            "stable per-machine pseudonyms. Default: $COPILOT_DASHBOARD_ANONYMIZE, else off."
        ),
    )
    parser.add_argument("log_dirs", nargs="*", help="Optional debug-log directories to scan.")
    args = parser.parse_args()

    if args.cache_shard:
        os.environ["COPILOT_DASHBOARD_CACHE_SHARD"] = str(args.cache_shard)

    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    dashboard_output_path = default_output_path()
    handler_directory = os.path.dirname(dashboard_output_path) or tempfile.gettempdir()
    os.makedirs(handler_directory, exist_ok=True)
    remote_manager = RemoteSyncManager(
        workspace_dir=workspace_dir,
        poll_interval_seconds=args.remote_poll_seconds,
        base_dir=args.remote_cache_dir,
    )

    for remote_spec in args.remote:
        try:
            host, username, remote_path, port = parse_remote_spec(remote_spec)
            source, sync_result = remote_manager.import_source(
                host=host,
                username=username,
                remote_path=remote_path,
                port=port,
            )
            print(
                f"Imported remote {source['host']}:{source['path']} (changed={sync_result['changed']}, md5={sync_result['remoteMd5']})",
                file=sys.stderr,
            )
        except Exception as exc:
            print(f"Failed to import --remote '{remote_spec}': {exc}", file=sys.stderr)

    existing_sync = remote_manager.sync_all_once()
    for result in existing_sync:
        if not result.get("ok"):
            print(f"Remote sync error ({result.get('sourceId')}): {result.get('error')}", file=sys.stderr)

    base_log_dirs = args.log_dirs or discover_log_dirs()
    workers = max(1, min(64, int(args.workers or 8)))

    if args.cache_only:
        def refresh_cache_once() -> None:
            cache_log_dirs = merge_log_dirs(base_log_dirs, remote_manager.get_cache_dirs())
            build_dashboard_data(
                cache_log_dirs,
                cache_root_dir=args.chat_cache_dir,
                force_recalculate=bool(args.recalculate_all),
                cache_verify_seconds=args.cache_verify_seconds,
                workers=workers,
            )

        poll_seconds = max(0, int(args.cache_poll_seconds or 0))
        if poll_seconds <= 0:
            refresh_cache_once()
            print("Cache-only refresh complete", file=sys.stderr)
            return

        print(f"Cache-only polling every {poll_seconds} seconds", file=sys.stderr)
        try:
            while True:
                try:
                    refresh_cache_once()
                    print("Cache-only refresh complete", file=sys.stderr)
                except Exception as exc:
                    print(f"Cache-only refresh failed: {exc}", file=sys.stderr)
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            pass
        return

    # Background remote sync disabled; use remote_start.sh instead.

    resolved_log_dirs = merge_log_dirs(base_log_dirs, remote_manager.get_cache_dirs())
    dashboard_cache = DashboardCache(max_age_seconds=args.cache_max_age_seconds)

    def _startup_compose(log_dirs: list[str], cli_db_path: str | None, otel_paths: list[str]) -> tuple[dict, str]:
        return _compose_dashboard(
            log_dirs,
            cache_root_dir=args.chat_cache_dir,
            force_recalculate=bool(args.recalculate_all),
            cache_verify_seconds=args.cache_verify_seconds,
            workers=workers,
            cli_db_path=cli_db_path,
            cli_otel_log_paths=otel_paths,
            premium_plan=args.plan,
            premium_quota=args.premium_quota,
            premium_config_path=args.premium_config,
            anonymize=bool(args.anonymize),
        )

    try:
        # Warm the cache (and write dashboard_output_path to disk, preserving prior
        # behavior) before the server starts serving requests.
        dashboard_cache.ensure_fresh(
            resolved_log_dirs=resolved_log_dirs,
            cli_db_path=args.cli_db or default_cli_db_path(),
            otel_paths=args.cli_otel_log if args.cli_otel_log is not None else default_cli_otel_paths(),
            compose_fn=_startup_compose,
            output_file=dashboard_output_path,
            force=bool(args.recalculate_all),
        )
    except Exception as exc:
        print(f"Warning: initial dashboard warm-up failed: {exc}", file=sys.stderr)

    handler = partial(
        DashboardHandler,
        directory=handler_directory,
        output_file=dashboard_output_path,
        log_dirs=base_log_dirs,
        remote_manager=remote_manager,
        chat_cache_dir=args.chat_cache_dir,
        force_recalculate=bool(args.recalculate_all),
        cache_verify_seconds=args.cache_verify_seconds,
        workers=workers,
        cli_db_path=args.cli_db,
        cli_otel_log_paths=args.cli_otel_log,
        dashboard_cache=dashboard_cache,
        premium_plan=args.plan,
        premium_quota=args.premium_quota,
        premium_config_path=args.premium_config,
        anonymize=bool(args.anonymize),
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving dashboard on http://{args.host}:{args.port}/dashboard.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # background sync disabled; nothing to stop
        server.server_close()


if __name__ == "__main__":
    main()
