"""The Pyvolt CLI — deploy, logs, env and processes from your terminal."""
from __future__ import annotations

import json as _json
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

# Global --json flag (set in the callback). When on, commands emit raw JSON to
# stdout instead of Rich tables, so scripts and AI coding tools get a stable,
# parseable contract instead of scraping formatted output.
_STATE = {"json": False}


def _emit(data) -> bool:
    """If --json is active, print `data` as JSON and return True (the caller
    should then return early). Otherwise return False and let it render normally."""
    if _STATE["json"]:
        print(_json.dumps(data, indent=2, default=str))
        return True
    return False

STATUS_STYLE = {
    "ready": "green", "live": "green", "success": "green", "running": "cyan",
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
    json_output: bool = typer.Option(False, "--json", help="Emit raw JSON instead of tables (for scripts and AI tools)."),
):
    _STATE["json"] = json_output
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
    if _emit(me):
        return
    console.print(f"{me['username']} <{me['email']}> @ {config.api_url()}")


# ---- read-only inventory ------------------------------------------------------

@app.command()
def servers():
    """List your servers."""
    data = Api().get("/v1/servers")
    if _emit(data):
        return
    t = _table("NAME", "IP", "PROVIDER", "STATUS", "CONNECTED")
    for s in data:
        t.add_row(
            s["name"], s["ip_address"], s["provider"], _status(s["status"]),
            "[green]yes[/]" if s["connected"] else "[red]no[/]",
        )
    console.print(t)


@app.command()
def ssh(
    server: str = typer.Argument(..., metavar="SERVER"),
    app_name: str = typer.Option("", "--app", "-a", help="cd into this app's directory on connect."),
):
    """Open an SSH shell on a server (as the pyvolt app-user).

    A thin convenience wrapper: it resolves the host/port from the API and
    execs your local `ssh`, so your own key must be on the box — add it under
    Account → SSH Keys (or `pyvolt` on the web dashboard)."""
    import os
    import shutil

    if not shutil.which("ssh"):
        raise fail("No `ssh` client found on PATH.")
    api = Api()
    srv = api.resolve_server(server)
    if srv["status"] != "ready":
        raise fail(f"{srv['name']} is {srv['status']}, not ready.")
    target = f"{srv.get('ssh_user', 'pyvolt')}@{srv['ip_address']}"
    args = ["ssh", "-p", str(srv.get("ssh_port", 22)), target]
    if app_name:
        site = api.resolve_app(app_name)
        # Drop into the app's checkout, then hand over an interactive shell.
        args += ["-t", f"cd sites/{site['domain']}/repo 2>/dev/null; exec \"$SHELL\" -l"]
    console.print(f"[dim]Connecting to {target}…[/dim]")
    os.execvp("ssh", args)


apps_app = typer.Typer(help="List your apps; `pyvolt apps create` makes a new one.")
app.add_typer(apps_app, name="apps")


@apps_app.callback(invoke_without_command=True)
def apps(
    ctx: typer.Context,
    server: str = typer.Option("", "--server", help="Filter by server name."),
):
    """List your apps."""
    if ctx.invoked_subcommand is not None:
        return
    data = Api().get("/v1/apps", params={"server": server} if server else None)
    if _emit(data):
        return
    t = _table("DOMAIN", "SERVER", "STATUS", "REPO", "BRANCH")
    for a in data:
        t.add_row(a["domain"], a["server"], _status(a["status"]), a["repo"], a["branch"])
    console.print(t)


@apps_app.command("create")
def apps_create(
    server: str = typer.Option(..., "--server", "-s", metavar="SERVER", help="Server to create the app on."),
    domain: str = typer.Option(..., "--domain", "-d", help="Subdomain prefix (no dots — becomes <prefix>.preview.pyvolt.com) or a full custom domain."),
    repo: str = typer.Option("", "--repo", "-r", metavar="OWNER/REPO", help="GitHub repository, resolved through your connection."),
    repo_url: str = typer.Option("", "--repo-url", help="Raw git URL for repos outside a GitHub connection."),
    branch: str = typer.Option("main", "--branch", "-b", help="Branch deploys ship from."),
    path: str = typer.Option("", "--path", help="Project directory inside the repo (monorepos)."),
    env: list[str] = typer.Option([], "--env", "-e", metavar="KEY=VALUE", help="Create-time env var (repeatable)."),
    serve_command: str = typer.Option("", "--serve-command", help="Override the detected start command."),
    release_command: str = typer.Option("", "--release-command", help="Override the detected release steps."),
    build_command: str = typer.Option("", "--build-command", help="Override the detected build command."),
    python_version: str = typer.Option("", "--python", help="Override the detected Python version."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the resolved plan without creating anything."),
):
    """Create an app on one of your servers.

    Repo autodiscovery prefills the framework, serve and release commands
    (same as the dashboard form); every flag above overrides it. Use
    --dry-run to inspect the plan first, then create and follow up with
    `pyvolt deploy DOMAIN --follow`."""
    api = Api()
    srv = api.resolve_server(server)
    env_map: dict[str, str] = {}
    for pair in env:
        if "=" not in pair:
            raise fail(f"Expected KEY=VALUE, got [bold]{pair}[/bold]")
        key, _, value = pair.partition("=")
        env_map[key] = value
    payload = {
        "server": srv["name"],
        "repo": repo,
        "repo_url": repo_url,
        "branch": branch,
        "project_path": path,
        "env": env_map,
        "serve_command": serve_command,
        "release_command": release_command,
        "build_command": build_command,
        "python_version": python_version,
        "dry_run": dry_run,
    }
    # A dot means "that's the whole domain"; a bare word is a pyvolt
    # subdomain prefix. Prefixes can't contain dots, so this never guesses.
    payload["custom_domain" if "." in domain else "domain_prefix"] = domain
    r = api.post("/v1/apps", ok=(200, 201, 400, 402, 409), json=payload)
    if r.status_code in (400, 402, 409):
        raise fail(r.json()["detail"])
    body = r.json()
    if _emit(body):
        return

    plan = body["plan"]
    t = _table("FIELD", "VALUE")
    t.add_row("domain", plan["domain"])
    t.add_row("repo", f"{plan['repo_url']} @ {plan['branch']}")
    if plan["framework"]:
        t.add_row("framework", plan["framework"])
    t.add_row("protocol", plan["app_protocol"].upper())
    t.add_row("package manager", plan["package_manager"])
    if plan["python_version"]:
        t.add_row("python", plan["python_version"])
    if plan["serve_command"]:
        t.add_row("serve", plan["serve_command"])
    if plan["release_command"]:
        t.add_row("release", plan["release_command"])
    if plan["build_command"]:
        t.add_row("build", plan["build_command"])
    if plan["frontend_dir"]:
        t.add_row("frontend", f"{plan['frontend_dir']}/ (passthrough: {plan['frontend_passthrough'] or 'none'})")
    console.print(t)
    if plan["evidence"]:
        console.print(f"[dim]Found: {', '.join(plan['evidence'])}[/dim]")
    for w in plan["warnings"]:
        console.print(f"[yellow]⚠[/yellow] {w}")

    if dry_run:
        console.print("[dim]Dry run — nothing was created.[/dim]")
        return
    created = body["app"]
    if not body["scaffolded"]:
        err_detail = body["scaffold_error"] or "unknown error"
        console.print(f"[red]✗[/red] App row created but scaffolding failed: {err_detail}")
        console.print(f"  Retry from the dashboard: {created['dashboard_url']}")
        raise typer.Exit(1)
    if body["deploy_key_ok"] is False:
        console.print(
            "[yellow]⚠[/yellow] Deploy key push failed — deploys will fail at clone. "
            "Grant the Pyvolt GitHub App access to the repo, then redeploy."
        )
    console.print(f"[green]✓[/green] Created [bold]{created['domain']}[/bold]")
    console.print(f"  Deploy:     [bold]pyvolt deploy {created['domain']} --follow[/bold]")
    console.print(f"  Dashboard:  {created['dashboard_url']}")


@app.command()
def status(app_name: str = typer.Argument(..., metavar="DOMAIN")):
    """Show one app's details: status, URLs, repo and branch."""
    site = Api().resolve_app(app_name)
    if _emit(site):
        return
    t = _table("FIELD", "VALUE")
    t.add_row("domain", site["domain"])
    t.add_row("status", _status(site["status"]))
    t.add_row("server", site.get("server", ""))
    t.add_row("repo", f"{site.get('repo', '')} @ {site.get('branch', '')}")
    if site.get("site_url"):
        t.add_row("url", site["site_url"])
    t.add_row("dashboard", site.get("dashboard_url", ""))
    console.print(t)


# ---- deployments --------------------------------------------------------------

TERMINAL = ("success", "failed")


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
):
    """Trigger a deployment."""
    api = Api()
    site = api.resolve_app(app_name)
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
    watch: bool = typer.Option(
        False, "--watch", "-w",
        help="Wait for the next deployment (e.g. after a git push), stream its log, "
             "exit non-zero on failure. Attaches if one is already running.",
    ),
):
    """Recent deployments for an app."""
    api = Api()
    site = api.resolve_app(app_name)
    data = api.get(f"/v1/apps/{site['id']}/deployments")
    if watch:
        running = next((d for d in data if d["status"] in ("queued", "running")), None)
        if running is None:
            baseline = data[0]["id"] if data else None
            console.print(f"[dim]Waiting for the next deployment of {site['domain']}… (^C to stop)[/dim]")
            while running is None:
                time.sleep(3)
                latest = api.get(f"/v1/apps/{site['id']}/deployments", params={"limit": 1})
                if latest and latest[0]["id"] != baseline:
                    running = latest[0]
        msg = (running.get("commit_message") or "").splitlines()[0][:60]
        console.print(
            f"[green]▶[/green] Deployment [bold]{running['commit_sha'][:7]}[/bold] {msg} "
            f"({running.get('triggered_by', '')})"
        )
        status = _follow(api, running["id"])
        if status == "failed":
            raise fail("Deployment failed.")
        console.print(f"\n[green]✓[/green] Deployed {site['domain']}")
        return
    if _emit(data):
        return
    t = _table("WHEN", "STATUS", "COMMIT", "MESSAGE", "BY", "TOOK")
    for d in data:
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
def _env_main(ctx: typer.Context, app_name: str = typer.Argument(..., metavar="DOMAIN")):
    ctx.obj = app_name


@env_app.command("list")
def env_list(ctx: typer.Context):
    """Show the app's variables (secret values masked)."""
    api = Api()
    site = api.resolve_app(ctx.obj)
    data = api.get(f"/v1/apps/{site['id']}/env")
    if _emit(data):
        return
    t = _table("KEY", "VALUE")
    for row in data:
        t.add_row(row["key"], "••••••••" if row["is_secret"] else row["value"])
    console.print(t)


@env_app.command("get")
def env_get(ctx: typer.Context, key: str):
    """Show one variable's value — unmasked, since it's your own secret."""
    api = Api()
    site = api.resolve_app(ctx.obj)
    row = api.get(f"/v1/apps/{site['id']}/env/{key}")
    if _emit(row):
        return
    console.print(row["value"])


@env_app.command("set")
def env_set(ctx: typer.Context, pairs: list[str] = typer.Argument(..., metavar="KEY=VALUE...")):
    """Set one or more variables — pushes the .env and restarts the app."""
    api = Api()
    site = api.resolve_app(ctx.obj)
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
    site = api.resolve_app(ctx.obj)
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
    if _emit(procs):
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
):
    """Tail the app's journal."""
    api = Api()
    site = api.resolve_app(app_name)
    params = {"lines": lines}
    if process:
        params["process"] = process
    r = api.get(f"/v1/apps/{site['id']}/logs", params=params)
    if r.get("error"):
        raise fail(f"journalctl failed on the server: {r['error']}")
    if _emit(r):
        return
    for line in r["lines"]:
        console.out(line, highlight=False)


@app.command()
def metrics(server: str = typer.Argument(..., metavar="SERVER")):
    """Latest CPU / memory / disk / network snapshot for a server."""
    api = Api()
    srv = api.resolve_server(server)
    m = api.get(f"/v1/servers/{srv['id']}/metrics")
    if _emit(m):
        return
    if m["at"] is None:
        console.print("[yellow]No metrics collected yet[/yellow] — they land a few minutes after provisioning.")
        return
    pct = lambda v: f"{v:.0f}%" if v is not None else "-"  # noqa: E731
    t = _table("METRIC", "VALUE")
    t.add_row("CPU", pct(m["cpu_percent"]))
    t.add_row("Memory", pct(m["memory_percent"]))
    t.add_row("Disk", pct(m["disk_percent"]))
    t.add_row("Net in", f"{m['net_in_bytes'] / 1e6:.1f} MB")
    t.add_row("Net out", f"{m['net_out_bytes'] / 1e6:.1f} MB")
    console.print(t)
    console.print(f"[dim]as of {m['at']}[/dim]")


# ---- fail2ban -------------------------------------------------------------------

@app.command()
def bans(server: str = typer.Argument(..., metavar="SERVER")):
    """List IPs banned by fail2ban on a server (flags your own IP)."""
    api = Api()
    srv = api.resolve_server(server)
    r = api.get(f"/v1/servers/{srv['id']}/bans")
    if _emit(r):
        return
    if not r["running"]:
        raise fail("fail2ban is not active on this server.")
    if not r["banned"]:
        console.print("[green]✓[/green] No IPs are currently banned.")
    else:
        t = _table("BANNED IP", "")
        for ip in r["banned"]:
            t.add_row(ip, "[yellow]← this is you[/]" if ip == r["your_ip"] else "")
        console.print(t)
    console.print(f"[dim]Your public IP: {r['your_ip']}[/dim]")
    if r["your_ip"] in r["banned"]:
        console.print(f"Unban yourself:  [bold]pyvolt unban {srv['name']} --me[/bold]")


@app.command()
def unban(
    server: str = typer.Argument(..., metavar="SERVER"),
    ip: str = typer.Argument("", metavar="[IP]"),
    me: bool = typer.Option(False, "--me", help="Unban your own public IP (as the API sees it)."),
):
    """Lift a fail2ban ban — banned yourself? `pyvolt unban SERVER --me`."""
    api = Api()
    srv = api.resolve_server(server)
    if me:
        ip = api.get(f"/v1/servers/{srv['id']}/bans")["your_ip"]
    if not ip:
        raise fail("Give an IP, or use [bold]--me[/bold] to unban your own.")
    r = api.post(f"/v1/servers/{srv['id']}/bans/unban", ok=(200, 400), json={"ip": ip})
    if r.status_code == 400:
        raise fail(r.json()["detail"])
    console.print(f"[green]✓[/green] Unbanned {ip}")


@app.command("open")
def open_(
    app_name: str = typer.Argument(..., metavar="DOMAIN"),
    print_url: bool = typer.Option(False, "--print", "-p", help="Print the URLs instead of opening a browser."),
):
    """Open the app's dashboard in your browser (or --print the URLs)."""
    site = Api().resolve_app(app_name)
    if _emit({"site_url": site.get("site_url"), "dashboard_url": site.get("dashboard_url")}):
        return
    if print_url:
        if site.get("site_url"):
            console.print(site["site_url"])
        console.print(site["dashboard_url"])
        return
    console.print(f"Opening {site['dashboard_url']}")
    webbrowser.open(site["dashboard_url"])
