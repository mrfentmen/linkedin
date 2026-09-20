"""Centralized filesystem path resolution.

Every write in this tool goes through here so the layout is consistent.
"""

from __future__ import annotations

from pathlib import Path


# /Users/dtaxk/Desktop/jobs/auto-apply
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def package_root() -> Path:
    return PACKAGE_ROOT


def template_config() -> Path:
    return PACKAGE_ROOT / "config.example.yaml"


def user_config() -> Path:
    return PACKAGE_ROOT / "config.yaml"


def default_state_file() -> Path:
    return PACKAGE_ROOT / "state.jsonl"


def default_failures_dir() -> Path:
    return PACKAGE_ROOT / "failures"


def default_manual_queue() -> Path:
    return PACKAGE_ROOT / "manual_queue.html"


def default_browser_profile() -> Path:
    return PACKAGE_ROOT / "browser_profile"
