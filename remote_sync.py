#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import shutil
import stat
import threading
import time
from dataclasses import dataclass
from typing import Any

try:
    import paramiko  # type: ignore
except Exception:  # pragma: no cover - optional dependency at runtime
    paramiko = None


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stable_source_id(host: str, port: int, username: str, remote_path: str) -> str:
    raw = f"{host}|{port}|{username}|{remote_path}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


@dataclass
class SyncResult:
    source_id: str
    changed: bool
    downloaded: bool
    remote_md5: str
    file_count: int
    checked_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "changed": self.changed,
            "downloaded": self.downloaded,
            "remoteMd5": self.remote_md5,
            "fileCount": self.file_count,
            "checkedAt": self.checked_at,
        }


class RemoteSyncManager:
    def __init__(
        self,
        workspace_dir: str,
        poll_interval_seconds: int = 300,
        base_dir: str | None = None,
        connect_timeout_seconds: int = 10,
    ):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.base_dir = os.path.abspath(base_dir or os.path.join(self.workspace_dir, ".remote-sync"))
        self.cache_dir = os.path.join(self.base_dir, "cache")
        self.sources_file = os.path.join(self.base_dir, "sources.json")
        self.connect_timeout_seconds = max(2, int(connect_timeout_seconds))
        self.poll_interval_seconds = max(30, int(poll_interval_seconds))

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        os.makedirs(self.cache_dir, exist_ok=True)
        self._sources: list[dict[str, Any]] = self._load_sources_locked()

    def _require_paramiko(self) -> None:
        if paramiko is None:
            raise RuntimeError(
                "Remote import requires paramiko. Install it with: pip install paramiko"
            )

    def _load_sources_locked(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.sources_file):
            return []

        try:
            with open(self.sources_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return []

        sources = payload.get("sources", []) if isinstance(payload, dict) else []
        if not isinstance(sources, list):
            return []
        return [source for source in sources if isinstance(source, dict)]

    def _save_sources_locked(self) -> None:
        os.makedirs(self.base_dir, exist_ok=True)
        payload = {
            "pollIntervalSeconds": self.poll_interval_seconds,
            "updatedAt": utc_timestamp(),
            "sources": self._sources,
        }
        with open(self.sources_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        try:
            os.chmod(self.sources_file, 0o600)
        except OSError:
            pass

    def _sanitize_source(self, source: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": source.get("id"),
            "host": source.get("host"),
            "port": source.get("port", 22),
            "username": source.get("username"),
            "path": source.get("path"),
            "localCacheDir": source.get("local_cache_dir"),
            "remoteMd5": source.get("remote_md5"),
            "status": source.get("status", "unknown"),
            "lastCheckedAt": source.get("last_checked_at"),
            "lastDownloadAt": source.get("last_download_at"),
            "lastFileCount": source.get("last_file_count", 0),
            "downloadCount": source.get("download_count", 0),
            "lastError": source.get("last_error"),
        }

    def list_sources(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._sanitize_source(source) for source in self._sources]

    def get_cache_dirs(self) -> list[str]:
        with self._lock:
            dirs: list[str] = []
            for source in self._sources:
                local_dir = source.get("local_cache_dir")
                if isinstance(local_dir, str) and os.path.isdir(local_dir):
                    dirs.append(local_dir)
            return dirs

    def _find_source_locked(self, source_id: str) -> dict[str, Any] | None:
        for source in self._sources:
            if source.get("id") == source_id:
                return source
        return None

    def _ensure_source_locked(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        remote_path: str,
    ) -> dict[str, Any]:
        source_id = stable_source_id(host, port, username, remote_path)
        source = self._find_source_locked(source_id)
        if source is None:
            source = {
                "id": source_id,
                "download_count": 0,
            }
            self._sources.append(source)

        source["host"] = host
        source["port"] = int(port)
        source["username"] = username
        source["password"] = password
        source["path"] = remote_path
        source["local_cache_dir"] = os.path.join(self.cache_dir, source_id)
        source.setdefault("status", "new")
        return source

    def _open_client(self, source: dict[str, Any]):
        self._require_paramiko()
        assert paramiko is not None

        host = str(source.get("host") or "")
        username = str(source.get("username") or "")
        password = str(source.get("password") or "")
        port = int(source.get("port") or 22)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password or None,
            timeout=self.connect_timeout_seconds,
            look_for_keys=not password,
            allow_agent=not password,
        )
        return client

    def _walk_remote_files(self, sftp, remote_dir: str, rel_prefix: str = "") -> list[tuple[str, str]]:
        files: list[tuple[str, str]] = []
        for entry in sorted(sftp.listdir_attr(remote_dir), key=lambda item: item.filename):
            name = entry.filename
            remote_path = posixpath.join(remote_dir, name)
            relative_path = posixpath.join(rel_prefix, name) if rel_prefix else name
            if stat.S_ISDIR(entry.st_mode):
                files.extend(self._walk_remote_files(sftp, remote_path, relative_path))
            elif stat.S_ISREG(entry.st_mode):
                files.append((relative_path, remote_path))
        return files

    def _compute_remote_md5(self, sftp, remote_dir: str) -> tuple[str, int]:
        digest = hashlib.md5()
        remote_files = self._walk_remote_files(sftp, remote_dir)
        for relative_path, remote_path in remote_files:
            digest.update(relative_path.encode("utf-8", errors="ignore"))
            digest.update(b"\0")
            with sftp.open(remote_path, "rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
        return digest.hexdigest(), len(remote_files)

    def _download_remote_dir(self, sftp, remote_dir: str, local_dir: str) -> int:
        os.makedirs(local_dir, exist_ok=True)
        downloaded_files = 0
        for entry in sftp.listdir_attr(remote_dir):
            name = entry.filename
            remote_path = posixpath.join(remote_dir, name)
            local_path = os.path.join(local_dir, name)
            if stat.S_ISDIR(entry.st_mode):
                downloaded_files += self._download_remote_dir(sftp, remote_path, local_path)
                continue
            if not stat.S_ISREG(entry.st_mode):
                continue
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with sftp.open(remote_path, "rb") as src, open(local_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            downloaded_files += 1
        return downloaded_files

    def _sync_source_locked(self, source: dict[str, Any]) -> SyncResult:
        checked_at = utc_timestamp()
        source_id = str(source.get("id") or "")
        remote_path = str(source.get("path") or "")
        local_cache_dir = str(source.get("local_cache_dir") or "")

        client = None
        sftp = None
        try:
            client = self._open_client(source)
            sftp = client.open_sftp()

            remote_stat = sftp.stat(remote_path)
            if not stat.S_ISDIR(remote_stat.st_mode):
                raise RuntimeError(f"Remote path is not a directory: {remote_path}")

            remote_md5, file_count = self._compute_remote_md5(sftp, remote_path)
            changed = remote_md5 != source.get("remote_md5")
            cache_missing = not os.path.isdir(local_cache_dir)
            downloaded = False

            if changed or cache_missing:
                shutil.rmtree(local_cache_dir, ignore_errors=True)
                downloaded_files = self._download_remote_dir(sftp, remote_path, local_cache_dir)
                downloaded = downloaded_files > 0 or file_count == 0
                source["last_download_at"] = checked_at
                source["download_count"] = int(source.get("download_count", 0) or 0) + 1

            source["remote_md5"] = remote_md5
            source["last_file_count"] = file_count
            source["last_checked_at"] = checked_at
            source["status"] = "ok"
            source["last_error"] = None

            return SyncResult(
                source_id=source_id,
                changed=bool(changed),
                downloaded=bool(downloaded),
                remote_md5=remote_md5,
                file_count=file_count,
                checked_at=checked_at,
            )
        except Exception as exc:
            source["last_checked_at"] = checked_at
            source["status"] = "error"
            source["last_error"] = str(exc)
            raise
        finally:
            try:
                if sftp is not None:
                    sftp.close()
            finally:
                if client is not None:
                    client.close()

    def import_source(
        self,
        host: str,
        username: str,
        password: str,
        remote_path: str,
        port: int = 22,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        host = (host or "").strip()
        username = (username or "").strip()
        remote_path = (remote_path or "").strip()
        if not host:
            raise RuntimeError("Host/IP is required.")
        if not username:
            raise RuntimeError("Username is required.")
        if not remote_path.startswith("/"):
            raise RuntimeError("Remote path must be absolute (start with '/').")

        with self._lock:
            source = self._ensure_source_locked(
                host=host,
                port=int(port or 22),
                username=username,
                password=password,
                remote_path=remote_path,
            )
            sync_result = self._sync_source_locked(source)
            self._save_sources_locked()
            return self._sanitize_source(source), sync_result.as_dict()

    def sync_all_once(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with self._lock:
            for source in self._sources:
                source_id = str(source.get("id") or "")
                try:
                    result = self._sync_source_locked(source)
                    results.append({"sourceId": source_id, "ok": True, "result": result.as_dict()})
                except Exception as exc:
                    results.append({"sourceId": source_id, "ok": False, "error": str(exc)})
            self._save_sources_locked()
        return results

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.poll_interval_seconds):
            try:
                self.sync_all_once()
            except Exception:
                # Individual sync errors are already captured per source.
                continue

    def start_background_sync(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="remote-sync-loop", daemon=True)
            self._thread.start()

    def stop_background_sync(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
