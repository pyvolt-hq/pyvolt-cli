"""Credentials + endpoint resolution.

Token lives in ~/.config/pyvolt/credentials.toml (mode 600). Environment
overrides — PYVOLT_TOKEN, PYVOLT_API_URL — win over the file, so CI and
local-dev instances need no config file at all.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

DEFAULT_API_URL = "https://pyvolt.com"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "pyvolt"


def credentials_path() -> Path:
    return config_dir() / "credentials.toml"


def _load() -> dict:
    p = credentials_path()
    if not p.exists():
        return {}
    try:
        return tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError:
        return {}


def api_url() -> str:
    return (os.environ.get("PYVOLT_API_URL") or _load().get("api_url") or DEFAULT_API_URL).rstrip("/")


def token() -> str | None:
    return os.environ.get("PYVOLT_TOKEN") or _load().get("token")


def save(tok: str, api: str | None = None) -> Path:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    lines = [f'token = "{tok}"']
    if api and api.rstrip("/") != DEFAULT_API_URL:
        lines.append(f'api_url = "{api.rstrip("/")}"')
    p = credentials_path()
    p.write_text("\n".join(lines) + "\n")
    p.chmod(0o600)
    return p


def clear() -> None:
    credentials_path().unlink(missing_ok=True)
