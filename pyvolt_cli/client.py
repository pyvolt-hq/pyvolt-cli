"""Thin httpx wrapper over the Pyvolt API (interactive docs at /api/docs)."""
from __future__ import annotations

import httpx
import typer
from rich.console import Console

from . import config

err = Console(stderr=True)


def fail(message: str) -> typer.Exit:
    err.print(f"[red]✗[/red] {message}")
    return typer.Exit(1)


class Api:
    """Authenticated client. Instantiating without a stored token exits."""

    def __init__(self) -> None:
        tok = config.token()
        if not tok:
            raise fail("Not logged in — run [bold]pyvolt login[/bold] first.")
        self.base = config.api_url()
        self.http = httpx.Client(
            base_url=self.base + "/api",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )

    def request(self, method: str, path: str, *, ok=(200, 201), **kw) -> httpx.Response:
        try:
            r = self.http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise fail(f"Could not reach {self.base}: {e}") from e
        if r.status_code == 401:
            raise fail("Token rejected (revoked or expired) — run [bold]pyvolt login[/bold] again.")
        if r.status_code == 404:
            raise fail("Not found.")
        if r.status_code not in ok:
            raise fail(f"API error {r.status_code}: {r.text[:200]}")
        return r

    def get(self, path: str, **kw):
        return self.request("GET", path, **kw).json()

    def post(self, path: str, *, ok=(200, 201), **kw) -> httpx.Response:
        return self.request("POST", path, ok=ok, **kw)

    def delete(self, path: str, **kw):
        return self.request("DELETE", path, **kw).json()

    # -- resolution ---------------------------------------------------------

    def resolve_server(self, name: str) -> dict:
        """Match a server by exact name, else unambiguous substring."""
        servers = self.get("/v1/servers")
        exact = [s for s in servers if s["name"] == name]
        if exact:
            return exact[0]
        matches = [s for s in servers if name.lower() in s["name"].lower()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            known = ", ".join(s["name"] for s in servers) or "none yet"
            raise fail(f"No server matches [bold]{name}[/bold]. Your servers: {known}")
        ambiguous = ", ".join(s["name"] for s in matches)
        raise fail(f"[bold]{name}[/bold] is ambiguous: {ambiguous}")

    def app(self, name: str = "") -> dict:
        """The named app, or with no name, the one this folder deploys."""
        return self.resolve_app(name) if name else self.app_for_cwd()

    def app_for_cwd(self) -> dict:
        """The app deployed from this folder's repo (its git remote), when
        exactly one is. Several (staging and production, say) are never
        guessed between."""
        repo = repo_slug(_git_remote())
        if not repo:
            raise fail("Pass the app's domain, or run this in its repo folder.")
        apps = self.get("/v1/apps")
        matches = [a for a in apps if repo_slug(a.get("repo") or "") == repo]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise fail(f"No app deploys from [bold]{repo}[/bold]. Pass the app's domain.")
        domains = ", ".join(a["domain"] for a in matches)
        raise fail(f"[bold]{repo}[/bold] deploys to more than one app ({domains}). Pass the one you mean.")

    def resolve_app(self, name: str) -> dict:
        """Match an app by exact domain, else unambiguous substring."""
        apps = self.get("/v1/apps")
        exact = [a for a in apps if a["domain"] == name]
        if exact:
            return exact[0]
        matches = [a for a in apps if name.lower() in a["domain"].lower()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            known = ", ".join(a["domain"] for a in apps) or "none yet"
            raise fail(f"No app matches [bold]{name}[/bold]. Your apps: {known}")
        ambiguous = ", ".join(a["domain"] for a in matches)
        raise fail(f"[bold]{name}[/bold] is ambiguous: {ambiguous}")


def _git_remote() -> str:
    """This folder's git remote URL (origin), or empty outside a repo."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def repo_slug(url: str) -> str:
    """owner/repo from any form of a repo's address: git@host:owner/repo.git,
    https://host/owner/repo, or a bare owner/repo. Lowercased, for matching."""
    path = url.strip().removesuffix("/").removesuffix(".git")
    if "://" in path:
        path = path.split("://", 1)[1].split("/", 1)[-1]
    elif "@" in path and ":" in path:
        path = path.split(":", 1)[1]
    parts = [p for p in path.split("/") if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else ""
