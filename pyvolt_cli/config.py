"""Credentials + endpoint + server-context resolution.

Everything lives in ~/.config/pyvolt/credentials.toml (mode 600).
Environment overrides — PYVOLT_TOKEN, PYVOLT_API_URL, PYVOLT_SERVER —
win over the file, so CI and local-dev instances need no config file.
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


def _write(data: dict) -> Path:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = credentials_path()
    p.write_text("".join(f'{k} = "{v}"\n' for k, v in data.items() if v))
    p.chmod(0o600)
    return p


def api_url() -> str:
    return (os.environ.get("PYVOLT_API_URL") or _load().get("api_url") or DEFAULT_API_URL).rstrip("/")


def token() -> str | None:
    return os.environ.get("PYVOLT_TOKEN") or _load().get("token")


def selected_server() -> str:
    """The sticky server context set by `pyvolt servers select`."""
    return os.environ.get("PYVOLT_SERVER") or _load().get("server") or ""


def save(tok: str, api: str | None = None) -> Path:
    data = _load()
    data["token"] = tok
    if api and api.rstrip("/") != DEFAULT_API_URL:
        data["api_url"] = api.rstrip("/")
    else:
        data.pop("api_url", None)
    return _write(data)


def set_server(name: str) -> None:
    data = _load()
    if name:
        data["server"] = name
    else:
        data.pop("server", None)
    _write(data)


def clear() -> None:
    credentials_path().unlink(missing_ok=True)
