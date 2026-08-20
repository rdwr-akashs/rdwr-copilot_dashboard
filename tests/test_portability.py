"""Tests for cross-platform path resolution (dashboard_core / compact_cache).

These guard against regressions of the historical `/tmp/dashboard.html`
hardcoding bug, which silently wrote to `C:\\tmp` on Windows.
"""
from __future__ import annotations

import os
import tempfile

import compact_cache
import dashboard_core


def test_default_output_path_honours_env_var(monkeypatch, tmp_path):
    target = tmp_path / "custom" / "out.html"
    monkeypatch.setenv("COPILOT_DASHBOARD_OUTPUT", str(target))
    result = dashboard_core.default_output_path()
    assert result == os.path.abspath(os.path.expanduser(str(target)))


def test_default_output_path_falls_back_to_system_temp_dir(monkeypatch):
    monkeypatch.delenv("COPILOT_DASHBOARD_OUTPUT", raising=False)
    result = dashboard_core.default_output_path()
    assert result == os.path.join(tempfile.gettempdir(), "dashboard.html")


def test_default_output_path_never_literal_tmp_on_windows(monkeypatch):
    monkeypatch.delenv("COPILOT_DASHBOARD_OUTPUT", raising=False)
    result = dashboard_core.default_output_path()
    if os.name == "nt":
        assert not result.startswith("/tmp")
        assert not result.startswith("\\tmp")


def test_default_cache_root_honours_env_var(monkeypatch, tmp_path):
    target = tmp_path / "my-cache"
    monkeypatch.setenv("COPILOT_DASHBOARD_CACHE_DIR", str(target))
    result = compact_cache.default_dashboard_cache_root()
    assert result == os.path.abspath(str(target))


def test_default_cache_root_falls_back_on_non_posix(monkeypatch):
    monkeypatch.delenv("COPILOT_DASHBOARD_CACHE_DIR", raising=False)
    monkeypatch.setattr(os, "name", "nt")
    result = compact_cache.default_dashboard_cache_root()
    assert result == os.path.join(os.path.expanduser("~"), ".copilot-dashboard", "cache")


def test_default_cache_root_never_literal_mnt_radware_on_non_posix(monkeypatch):
    monkeypatch.delenv("COPILOT_DASHBOARD_CACHE_DIR", raising=False)
    monkeypatch.setattr(os, "name", "nt")
    result = compact_cache.default_dashboard_cache_root()
    assert "/mnt/radware" not in result
