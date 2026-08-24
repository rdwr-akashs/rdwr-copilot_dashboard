"""Tests for the remote-sync authentication posture.

Remote sync used to accept an SSH password, persist it verbatim into
`.remote-sync/sources.json`, and trust any host key on first contact
(`AutoAddPolicy`). Both are pinned as gone here rather than left to code
review, because a regression on either is invisible from the outside: syncing
keeps working exactly as before while the password is on disk again, or while
an impersonating host is silently trusted.

Nothing here opens a real SSH connection; `paramiko.SSHClient` is substituted
so the policy and credential decisions can be inspected directly.
"""
from __future__ import annotations

import json

import pytest

import remote_sync
from remote_sync import RemoteSyncManager
from serve_dashboard import parse_remote_spec


# --------------------------------------------------------------------------
# The --remote spec no longer carries a password.
# --------------------------------------------------------------------------

def test_current_spec_without_port():
    assert parse_remote_spec("10.0.0.5,akash,/var/log/copilot") == (
        "10.0.0.5",
        "akash",
        "/var/log/copilot",
        22,
    )


def test_current_spec_with_port():
    assert parse_remote_spec("10.0.0.5,akash,/var/log/copilot,2222") == (
        "10.0.0.5",
        "akash",
        "/var/log/copilot",
        2222,
    )


@pytest.mark.parametrize(
    "spec",
    [
        "10.0.0.5,akash,s3cret,/var/log/copilot",          # legacy, 4 fields
        "10.0.0.5,akash,s3cret,/var/log/copilot,2222",     # legacy, 5 fields
    ],
)
def test_legacy_password_spec_is_rejected_with_an_explanation(spec):
    # A bare "path must be absolute" would send the user hunting the wrong
    # problem, so the legacy shape is detected and named.
    with pytest.raises(ValueError, match="no longer take a PASSWORD field"):
        parse_remote_spec(spec)


def test_path_must_still_be_absolute():
    with pytest.raises(ValueError, match="absolute"):
        parse_remote_spec("10.0.0.5,akash,relative/path")


# --------------------------------------------------------------------------
# Nothing secret reaches sources.json.
# --------------------------------------------------------------------------

def _manager(tmp_path) -> RemoteSyncManager:
    return RemoteSyncManager(
        workspace_dir=str(tmp_path / "workspace"),
        poll_interval_seconds=300,
        base_dir=str(tmp_path / ".remote-sync"),
    )


def test_added_source_is_persisted_without_a_password_field(tmp_path):
    manager = _manager(tmp_path)
    with manager._lock:
        manager._ensure_source_locked(
            host="10.0.0.5", port=22, username="akash", remote_path="/var/log/copilot"
        )
        manager._save_sources_locked()

    raw = (tmp_path / ".remote-sync" / "sources.json").read_text(encoding="utf-8")
    assert "password" not in raw.lower()
    persisted = json.loads(raw)["sources"][0]
    assert "password" not in persisted
    assert persisted["username"] == "akash"


def test_a_legacy_persisted_password_is_dropped_on_re_add(tmp_path):
    # Upgrading does not silently leave the old secret on disk: re-adding the
    # same source strips it, so there is a way out that does not require the
    # user to know the file exists.
    manager = _manager(tmp_path)
    with manager._lock:
        source = manager._ensure_source_locked(
            host="10.0.0.5", port=22, username="akash", remote_path="/var/log/copilot"
        )
        source["password"] = "s3cret-from-an-older-build"
        manager._save_sources_locked()
    assert "s3cret-from-an-older-build" in (tmp_path / ".remote-sync" / "sources.json").read_text(encoding="utf-8")

    with manager._lock:
        manager._ensure_source_locked(
            host="10.0.0.5", port=22, username="akash", remote_path="/var/log/copilot"
        )
        manager._save_sources_locked()

    raw = (tmp_path / ".remote-sync" / "sources.json").read_text(encoding="utf-8")
    assert "s3cret-from-an-older-build" not in raw
    assert "password" not in raw.lower()


# --------------------------------------------------------------------------
# Host keys are verified, and auth is key/agent only.
# --------------------------------------------------------------------------

class _FakeSSHClient:
    """Records the decisions `_open_client` makes, without connecting."""

    instances: list["_FakeSSHClient"] = []

    def __init__(self) -> None:
        self.policy = None
        self.connect_kwargs: dict = {}
        self.loaded_system_host_keys = False
        _FakeSSHClient.instances.append(self)

    def load_system_host_keys(self) -> None:
        self.loaded_system_host_keys = True

    def load_host_keys(self, path) -> None:
        pass

    def set_missing_host_key_policy(self, policy) -> None:
        self.policy = policy

    def connect(self, **kwargs) -> None:
        self.connect_kwargs = kwargs


class _RejectPolicy:
    pass


class _AutoAddPolicy:
    pass


@pytest.fixture
def fake_paramiko(monkeypatch):
    _FakeSSHClient.instances = []

    class _FakeParamiko:
        SSHClient = _FakeSSHClient
        RejectPolicy = _RejectPolicy
        AutoAddPolicy = _AutoAddPolicy

    monkeypatch.setattr(remote_sync, "paramiko", _FakeParamiko)
    monkeypatch.setattr(RemoteSyncManager, "_require_paramiko", lambda self: None)
    return _FakeParamiko


def test_open_client_rejects_unknown_host_keys(tmp_path, fake_paramiko):
    manager = _manager(tmp_path)
    manager._open_client({"host": "10.0.0.5", "username": "akash", "port": 22})

    client = _FakeSSHClient.instances[-1]
    # AutoAddPolicy would accept whatever key the far end presents, which makes
    # a machine-in-the-middle undetectable.
    assert isinstance(client.policy, _RejectPolicy)
    assert not isinstance(client.policy, _AutoAddPolicy)
    assert client.loaded_system_host_keys is True


def test_open_client_uses_key_and_agent_auth_only(tmp_path, fake_paramiko):
    manager = _manager(tmp_path)
    manager._open_client(
        # A stale password on the source dict must not be revived into the
        # connection; the whole point is that this field is never consulted.
        {"host": "10.0.0.5", "username": "akash", "port": 22, "password": "s3cret"}
    )

    kwargs = _FakeSSHClient.instances[-1].connect_kwargs
    assert "password" not in kwargs
    assert kwargs["look_for_keys"] is True
    assert kwargs["allow_agent"] is True
    assert kwargs["username"] == "akash"
    assert kwargs["hostname"] == "10.0.0.5"
