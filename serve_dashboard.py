#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from dashboard_core import build_dashboard_data, discover_log_dirs, load_full_session_payload, write_dashboard
from remote_sync import RemoteSyncManager


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


def parse_remote_spec(spec: str) -> tuple[str, str, str, str, int]:
    parts = [item.strip() for item in (spec or "").split(",", 4)]
    if len(parts) not in {4, 5}:
        raise ValueError("Remote source must be: IP,USERNAME,PASSWORD,PATH[,PORT]")

    host, username, password, remote_path = parts[:4]
    if not host or not username or not remote_path:
        raise ValueError("Remote source missing required fields. Format: IP,USERNAME,PASSWORD,PATH[,PORT]")
    if not remote_path.startswith("/"):
        raise ValueError("Remote path must be absolute (start with '/').")

    port = 22
    if len(parts) == 5 and parts[4]:
        port = int(parts[4])
    return host, username, password, remote_path, port


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
        **kwargs,
    ):
        self._dashboard_directory = directory
        self._log_dirs = log_dirs
        self._remote_manager = remote_manager
        self._chat_cache_dir = chat_cache_dir
        self._force_recalculate = bool(force_recalculate)
        self._cache_verify_seconds = max(30, int(cache_verify_seconds))
        self._workers = max(1, min(64, int(workers or 8)))
        super().__init__(*args, directory=directory, **kwargs)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _resolved_log_dirs(self) -> list[str]:
        return merge_log_dirs(self._log_dirs, self._remote_manager.get_cache_dirs())

    def do_GET(self):
        parsed_url = urlparse(self.path)
        route = parsed_url.path


        if route == "/api/session":
            query = parse_qs(parsed_url.query or "")
            session_id = str((query.get("id") or [""])[0] or "").strip()
            if not session_id:
                self._send_json(400, {"ok": False, "error": "Missing session id (query: id)."})
                return

            payload = load_full_session_payload(session_id, self._chat_cache_dir)
            if payload is None:
                # Rebuild once to refresh in-memory session/full-file index, then retry.
                try:
                    write_dashboard(
                        output_file="/tmp/dashboard.html",
                        log_dirs=self._resolved_log_dirs(),
                        cache_root_dir=self._chat_cache_dir,
                        force_recalculate=self._force_recalculate,
                        cache_verify_seconds=self._cache_verify_seconds,
                        workers=self._workers,
                    )
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
                write_dashboard(
                    output_file="/tmp/dashboard.html",
                    log_dirs=self._resolved_log_dirs(),
                    cache_root_dir=self._chat_cache_dir,
                    force_recalculate=self._force_recalculate,
                    cache_verify_seconds=self._cache_verify_seconds,
                    workers=self._workers,
                )
            except Exception as exc:
                self.send_error(500, f"Failed to generate dashboard: {exc}")
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
        metavar="IP,USERNAME,PASSWORD,PATH[,PORT]",
        help="Add/import a remote source on startup. Warning: password will be visible in shell history.",
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
        help="Directory for parsed chat/session cache (defaults to /mnt/radware/$USER/copilot_dashboard_cache).",
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
    parser.add_argument("log_dirs", nargs="*", help="Optional debug-log directories to scan.")
    args = parser.parse_args()

    if args.cache_shard:
        os.environ["COPILOT_DASHBOARD_CACHE_SHARD"] = str(args.cache_shard)

    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    handler_directory = '/tmp'
    remote_manager = RemoteSyncManager(
        workspace_dir=workspace_dir,
        poll_interval_seconds=args.remote_poll_seconds,
        base_dir=args.remote_cache_dir,
    )

    for remote_spec in args.remote:
        try:
            host, username, password, remote_path, port = parse_remote_spec(remote_spec)
            source, sync_result = remote_manager.import_source(
                host=host,
                username=username,
                password=password,
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
    write_dashboard(
        output_file="/tmp/dashboard.html",
        log_dirs=resolved_log_dirs,
        cache_root_dir=args.chat_cache_dir,
        force_recalculate=bool(args.recalculate_all),
        cache_verify_seconds=args.cache_verify_seconds,
        workers=workers,
    )

    handler = partial(
        DashboardHandler,
        directory=handler_directory,
        log_dirs=base_log_dirs,
        remote_manager=remote_manager,
        chat_cache_dir=args.chat_cache_dir,
        force_recalculate=bool(args.recalculate_all),
        cache_verify_seconds=args.cache_verify_seconds,
        workers=workers,
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
