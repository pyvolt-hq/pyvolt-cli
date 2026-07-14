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
