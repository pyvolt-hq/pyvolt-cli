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

    def resolve_app(self, name: str, server: str = "") -> dict:
        """Match an app by exact domain, else unambiguous substring.

        Resolution is scoped to `server` when given, else to the sticky
        context from `pyvolt servers select`, else to all your apps."""
        server = server or config.selected_server()
        apps = self.get("/v1/apps", params={"server": server} if server else None)
        scope = f" on [bold]{server}[/bold]" if server else ""
        if server and not apps:
            raise fail(f"No apps{scope} — check [bold]pyvolt servers[/bold].")
        exact = [a for a in apps if a["domain"] == name]
        if exact:
            return exact[0]
        matches = [a for a in apps if name.lower() in a["domain"].lower()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            known = ", ".join(a["domain"] for a in apps) or "none yet"
            raise fail(f"No app matches [bold]{name}[/bold]{scope}. Apps{scope}: {known}")
        ambiguous = ", ".join(a["domain"] for a in matches)
        raise fail(f"[bold]{name}[/bold] is ambiguous{scope}: {ambiguous}")
