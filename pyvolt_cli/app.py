"""The Pyvolt CLI — deploy, logs, env and processes from your terminal."""
from __future__ import annotations

import platform
import time
import webbrowser

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, config
from .client import Api, fail

app = typer.Typer(
    name="pyvolt",
    help="The Pyvolt CLI — manage servers, apps and deployments on your own infrastructure.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

STATUS_STYLE = {
    "ready": "green", "live": "green", "succeeded": "green", "running": "cyan",
    "active": "green", "queued": "yellow", "deploying": "cyan",
    "failed": "red", "error": "red", "inactive": "red",
}


def _status(s: str) -> str:
    return f"[{STATUS_STYLE.get(s, 'white')}]{s}[/]"


def _table(*columns: str) -> Table:
    t = Table(box=None, header_style="bold dim", pad_edge=False)
    for c in columns:
        t.add_column(c)
    return t


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="Print version and exit."),
):
    if version:
        console.print(f"pyvolt-cli {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


# ---- auth -------------------------------------------------------------------

@app.command()
def login():
    """Authorize this machine via your browser (no password in the terminal)."""
    import httpx

    base = config.api_url()
    try:
        start = httpx.post(
            f"{base}/api/cli/auth/start",
            json={"device_name": platform.node()},
            timeout=30,
        ).json()
    except httpx.HTTPError as e:
        raise fail(f"Could not reach {base}: {e}") from e

    console.print(f"\nConfirmation code: [bold cyan]{start['user_code']}[/]")
    console.print(f"Opening [link]{start['verification_uri']}[/link] — approve there if the code matches.\n")
    webbrowser.open(start["verification_uri"])

    deadline = time.monotonic() + start.get("expires_in", 600)
    with console.status("Waiting for browser approval…"):
        while time.monotonic() < deadline:
            time.sleep(start.get("interval", 2))
            poll = httpx.post(
                f"{base}/api/cli/auth/poll",
                json={"device_code": start["device_code"]},
                timeout=30,
            ).json()
            if poll["status"] == "approved":
                path = config.save(poll["token"], base)
                console.print(f"[green]✓[/green] Logged in — token stored in {path}")
                return
            if poll["status"] == "denied":
                raise fail("Request denied in the browser.")
            if poll["status"] == "expired":
                raise fail("Login request expired — run [bold]pyvolt login[/bold] again.")
    raise fail("Timed out waiting for approval.")


@app.command()
def logout():
    """Remove this machine's stored token (revoke it fully under Account → API)."""
    config.clear()
    console.print("[green]✓[/green] Logged out. Revoke the token under Account → API on the dashboard.")


@app.command()
def whoami():
    """Show the authenticated account."""
    me = Api().get("/v1/me")
    ctx = f" · server context: {config.selected_server()}" if config.selected_server() else ""
    console.print(f"{me['username']} <{me['email']}> @ {config.api_url()}{ctx}")


# ---- read-only inventory ------------------------------------------------------

def _server_opt():
    return typer.Option(
        "", "--server", "-s",
        help="Scope to one server (overrides `pyvolt servers select`).",
    )


servers_app = typer.Typer(help="List servers; `select` sets the sticky server context.")
app.add_typer(servers_app, name="servers")


@servers_app.callback(invoke_without_command=True)
def _servers_main(ctx: typer.Context):
    """List your servers."""
    if ctx.invoked_subcommand is not None:
        return
    selected = config.selected_server()
    t = _table("", "NAME", "IP", "PROVIDER", "STATUS", "CONNECTED")
    for s in Api().get("/v1/servers"):
        t.add_row(
            "[cyan]›[/]" if s["name"] == selected else "",
            s["name"], s["ip_address"], s["provider"], _status(s["status"]),
            "[green]yes[/]" if s["connected"] else "[red]no[/]",
        )
    console.print(t)


@servers_app.command("select")
def servers_select(
    name: str = typer.Argument("", metavar="[SERVER]"),
    clear: bool = typer.Option(False, "--clear", help="Forget the selected server."),
):
    """Scope later commands to one server (until `--clear`)."""
    if clear:
        config.set_server("")
        console.print("[green]✓[/green] Server context cleared — commands search all servers again.")
        return
    if not name:
        current = config.selected_server()
        console.print(f"Selected server: [bold]{current}[/bold]" if current else "No server selected.")
        return
    names = [s["name"] for s in Api().get("/v1/servers")]
    if name not in names:
        raise fail(f"No server named [bold]{name}[/bold]. Your servers: {', '.join(names) or 'none yet'}")
    config.set_server(name)
    console.print(f"[green]✓[/green] Commands now scoped to [bold]{name}[/bold] (undo: pyvolt servers select --clear)")


@app.command()
def apps(
    server: str = _server_opt(),
    all_: bool = typer.Option(False, "--all", help="Ignore the selected server context."),
):
    """List your apps (within the selected server context, if any)."""
    server = "" if all_ else (server or config.selected_server())
    t = _table("DOMAIN", "SERVER", "STATUS", "REPO", "BRANCH")
    for a in Api().get("/v1/apps", params={"server": server} if server else None):
        t.add_row(a["domain"], a["server"], _status(a["status"]), a["repo"], a["branch"])
    console.print(t)


# ---- deployments --------------------------------------------------------------

TERMINAL = ("succeeded", "failed")


def _follow(api: Api, deployment_id: int) -> str:
    offset, status = 0, "queued"
    while status not in TERMINAL:
        time.sleep(2)
        chunk = api.get(f"/v1/deployments/{deployment_id}/log", params={"offset": offset})
        status, offset = chunk["status"], chunk["offset"]
        if chunk["chunk"]:
            console.out(chunk["chunk"], end="", highlight=False)
    return status


@app.command()
def deploy(
    app_name: str = typer.Argument(..., metavar="DOMAIN"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream the deploy log."),
    server: str = _server_opt(),
):
    """Trigger a deployment."""
    api = Api()
    site = api.resolve_app(app_name, server)
    r = api.post(f"/v1/apps/{site['id']}/deployments", ok=(201, 409))
    if r.status_code == 409:
        raise fail(r.json()["detail"])
    d = r.json()
    console.print(f"[green]✓[/green] Deployment queued for [bold]{site['domain']}[/bold]")
    if not follow:
        console.print(f"  pyvolt deploy {site['domain']} --follow   (or watch {site['dashboard_url']})")
        return
    status = _follow(api, d["id"])
    if status == "failed":
        raise fail("Deployment failed.")
    console.print(f"\n[green]✓[/green] Deployed {site['domain']}")


@app.command()
def deployments(
    app_name: str = typer.Argument(..., metavar="DOMAIN"),
    server: str = _server_opt(),
):
    """Recent deployments for an app."""
    api = Api()
    site = api.resolve_app(app_name, server)
    t = _table("WHEN", "STATUS", "COMMIT", "MESSAGE", "BY", "TOOK")
    for d in api.get(f"/v1/apps/{site['id']}/deployments"):
        took = f"{d['duration_seconds']}s" if d["duration_seconds"] is not None else ""
        t.add_row(
            d["created_at"][:16].replace("T", " "), _status(d["status"]),
            d["commit_sha"][:7], d["commit_message"].splitlines()[0][:60] if d["commit_message"] else "",
            d["triggered_by"], took,
        )
    console.print(t)


# ---- env ----------------------------------------------------------------------

env_app = typer.Typer(no_args_is_help=True, help="Manage an app's environment variables.")
app.add_typer(env_app, name="env")


@env_app.callback()
def _env_main(
    ctx: typer.Context,
    app_name: str = typer.Argument(..., metavar="DOMAIN"),
    server: str = _server_opt(),
):
    ctx.obj = (app_name, server)


@env_app.command("list")
def env_list(ctx: typer.Context):
    """Show the app's variables (secret values masked)."""
    api = Api()
    site = api.resolve_app(*ctx.obj)
    t = _table("KEY", "VALUE")
    for row in api.get(f"/v1/apps/{site['id']}/env"):
        t.add_row(row["key"], "••••••••" if row["is_secret"] else row["value"])
    console.print(t)


@env_app.command("set")
def env_set(ctx: typer.Context, pairs: list[str] = typer.Argument(..., metavar="KEY=VALUE...")):
    """Set one or more variables — pushes the .env and restarts the app."""
    api = Api()
    site = api.resolve_app(*ctx.obj)
    for pair in pairs:
        if "=" not in pair:
            raise fail(f"Expected KEY=VALUE, got [bold]{pair}[/bold]")
        key, _, value = pair.partition("=")
        api.post(f"/v1/apps/{site['id']}/env", json={"key": key, "value": value})
        console.print(f"[green]✓[/green] {key}")


@env_app.command("rm")
def env_rm(ctx: typer.Context, key: str):
    """Remove a variable — pushes the .env and restarts the app."""
    api = Api()
    site = api.resolve_app(*ctx.obj)
    r = api.delete(f"/v1/apps/{site['id']}/env/{key}")
    if not r["deleted"]:
        raise fail(f"[bold]{key}[/bold] is not set.")
    console.print(f"[green]✓[/green] {key} removed")


# ---- processes & logs -----------------------------------------------------------

@app.command()
def ps(
    app_name: str = typer.Argument(..., metavar="DOMAIN"),
    action: str = typer.Argument("", metavar="[restart]"),
    process: str = typer.Argument("", metavar="[NAME]"),
):
    """List background processes; `pyvolt ps APP restart NAME` restarts one."""
    api = Api()
    site = api.resolve_app(app_name)
    procs = api.get(f"/v1/apps/{site['id']}/processes")
    if action:
        if action != "restart" or not process:
            raise fail("Usage: pyvolt ps DOMAIN restart NAME")
        match = [p for p in procs if p["name"] == process]
        if not match:
            known = ", ".join(p["name"] for p in procs) or "none"
            raise fail(f"No process [bold]{process}[/bold]. Processes: {known}")
        api.post(f"/v1/apps/{site['id']}/processes/{match[0]['id']}/restart")
        console.print(f"[green]✓[/green] Restarted {process}")
        return
    t = _table("NAME", "KIND", "STATE", "COMMAND")
    for p in procs:
        state = _status(p["state"]) + (f" ({p['exit']})" if p["exit"] else "")
        t.add_row(p["name"], p["kind"], state, p["command"])
    console.print(t)


@app.command()
def logs(
    app_name: str = typer.Argument(..., metavar="DOMAIN"),
    process: str = typer.Option("", "--process", "-p", help="A named background process instead of the web app."),
    lines: int = typer.Option(100, "--lines", "-n", help="How many lines (max 500)."),
    server: str = _server_opt(),
):
    """Tail the app's journal."""
    api = Api()
    site = api.resolve_app(app_name, server)
    params = {"lines": lines}
    if process:
        params["process"] = process
    r = api.get(f"/v1/apps/{site['id']}/logs", params=params)
    if r.get("error"):
        raise fail(f"journalctl failed on the server: {r['error']}")
    for line in r["lines"]:
        console.out(line, highlight=False)


@app.command("open")
def open_(
    app_name: str = typer.Argument(..., metavar="DOMAIN"),
    server: str = _server_opt(),
):
    """Open the app's dashboard page in your browser."""
    site = Api().resolve_app(app_name, server)
    console.print(f"Opening {site['dashboard_url']}")
    webbrowser.open(site["dashboard_url"])
