"""CLI tests — API mocked with respx, filesystem isolated per-test."""
from __future__ import annotations

import stat

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from pyvolt_cli.app import app

BASE = "https://pyvolt.test"
runner = CliRunner()

APPS = [
    {
        "id": 11, "domain": "blog.example.com", "server": "hetzy", "status": "live",
        "repo": "acme/blog", "branch": "main",
        "dashboard_url": f"{BASE}/servers/hetzy/sites/blog/",
        "site_url": "https://blog.example.com",
    },
    {
        "id": 12, "domain": "shop.example.com", "server": "hetzy", "status": "live",
        "repo": "acme/shop", "branch": "main",
        "dashboard_url": f"{BASE}/servers/hetzy/sites/shop/",
        "site_url": "https://shop.example.com",
    },
]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("PYVOLT_API_URL", BASE)
    monkeypatch.setenv("PYVOLT_TOKEN", "pyv_test")
    monkeypatch.setattr("time.sleep", lambda s: None)


@pytest.fixture
def api():
    with respx.mock(base_url=BASE) as mock:
        yield mock


def test_not_logged_in(monkeypatch, api):
    monkeypatch.delenv("PYVOLT_TOKEN")
    result = runner.invoke(app, ["whoami"])
    assert result.exit_code == 1
    assert "pyvolt login" in result.output


def test_whoami(api):
    api.get("/api/v1/me").respond(200, json={"username": "will", "email": "w@x.com"})
    result = runner.invoke(app, ["whoami"])
    assert result.exit_code == 0
    assert "will <w@x.com>" in result.output


def test_401_hint(api):
    api.get("/api/v1/me").respond(401, json={"detail": "Unauthorized"})
    result = runner.invoke(app, ["whoami"])
    assert result.exit_code == 1
    assert "pyvolt login" in result.output


def test_apps_table(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    result = runner.invoke(app, ["apps"])
    assert result.exit_code == 0
    assert "blog.example.com" in result.output
    assert "acme/shop" in result.output


def test_app_resolution_substring_and_ambiguity(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    api.get("/api/v1/apps/11/env").respond(200, json=[])
    ok = runner.invoke(app, ["env", "blog", "list"])
    assert ok.exit_code == 0

    api.get("/api/v1/apps").respond(200, json=APPS)
    ambiguous = runner.invoke(app, ["env", "example", "list"])
    assert ambiguous.exit_code == 1
    assert "ambiguous" in ambiguous.output


def test_deploy_conflict(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    api.post("/api/v1/apps/11/deployments").respond(
        409, json={"detail": "A deployment is already queued or running."}
    )
    result = runner.invoke(app, ["deploy", "blog"])
    assert result.exit_code == 1
    assert "already queued" in result.output


def test_deploy_follow_streams_until_terminal(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    api.post("/api/v1/apps/11/deployments").respond(
        201, json={"id": 77, "status": "queued", "commit_sha": "", "commit_message": "",
                   "triggered_by": "will", "created_at": "2026-07-14T10:00:00", "duration_seconds": None},
    )
    log = api.get("/api/v1/deployments/77/log")
    log.side_effect = [
        Response(200, json={"status": "running", "offset": 5, "chunk": "one\n"}),
        Response(200, json={"status": "succeeded", "offset": 9, "chunk": "two\n"}),
    ]
    result = runner.invoke(app, ["deploy", "blog", "--follow"])
    assert result.exit_code == 0
    assert "one" in result.output and "two" in result.output
    assert "Deployed blog.example.com" in result.output


def test_env_get_prints_value(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    api.get("/api/v1/apps/11/env/SECRET_KEY").respond(
        200, json={"key": "SECRET_KEY", "value": "s3kr3t", "is_secret": True}
    )
    result = runner.invoke(app, ["env", "blog", "get", "SECRET_KEY"])
    assert result.exit_code == 0
    assert "s3kr3t" in result.output


def test_env_set_validates_pairs(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    result = runner.invoke(app, ["env", "blog", "set", "NOEQUALS"])
    assert result.exit_code == 1
    assert "KEY=VALUE" in result.output


def test_env_set_posts_each_pair(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    route = api.post("/api/v1/apps/11/env").respond(
        200, json={"key": "A", "value": "1", "is_secret": False}
    )
    result = runner.invoke(app, ["env", "blog", "set", "A=1", "B=2"])
    assert result.exit_code == 0
    assert route.call_count == 2


def test_env_list_masks_secrets(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    api.get("/api/v1/apps/11/env").respond(200, json=[
        {"key": "SECRET_KEY", "value": "shh", "is_secret": True},
        {"key": "DEBUG", "value": "0", "is_secret": False},
    ])
    result = runner.invoke(app, ["env", "blog", "list"])
    assert "shh" not in result.output
    assert "••" in result.output
    assert "DEBUG" in result.output


def test_ps_restart_resolves_name_to_id(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    api.get("/api/v1/apps/11/processes").respond(200, json=[
        {"id": 5, "name": "worker", "kind": "worker", "command": "celery ...", "state": "active", "exit": ""},
    ])
    restart = api.post("/api/v1/apps/11/processes/5/restart").respond(200, json={"restarted": "worker"})
    result = runner.invoke(app, ["ps", "blog", "restart", "worker"])
    assert result.exit_code == 0
    assert restart.called


def test_logs(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    api.get("/api/v1/apps/11/logs").respond(200, json={"unit": "u", "lines": ["alpha", "beta"]})
    result = runner.invoke(app, ["logs", "blog", "-n", "50"])
    assert result.exit_code == 0
    assert "alpha" in result.output


def test_login_device_flow(api, monkeypatch, tmp_path):
    monkeypatch.delenv("PYVOLT_TOKEN")
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    api.post("/api/cli/auth/start").respond(200, json={
        "device_code": "dc", "user_code": "abcd1234",
        "verification_uri": f"{BASE}/cli/authorize/abcd1234/",
        "expires_in": 600, "interval": 2,
    })
    poll = api.post("/api/cli/auth/poll")
    poll.side_effect = [
        Response(200, json={"status": "pending"}),
        Response(200, json={"status": "approved", "token": "pyv_new"}),
    ]
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 0
    assert opened == [f"{BASE}/cli/authorize/abcd1234/"]
    creds = tmp_path / "pyvolt" / "credentials.toml"
    assert 'token = "pyv_new"' in creds.read_text()
    assert stat.S_IMODE(creds.stat().st_mode) == 0o600


def test_login_denied(api, monkeypatch):
    monkeypatch.delenv("PYVOLT_TOKEN")
    monkeypatch.setattr("webbrowser.open", lambda url: None)
    api.post("/api/cli/auth/start").respond(200, json={
        "device_code": "dc", "user_code": "abcd1234",
        "verification_uri": f"{BASE}/cli/authorize/abcd1234/",
        "expires_in": 600, "interval": 2,
    })
    api.post("/api/cli/auth/poll").respond(200, json={"status": "denied"})
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 1
    assert "denied" in result.output


def test_logout_removes_file(api, tmp_path, monkeypatch):
    from pyvolt_cli import config

    config.save("pyv_x", BASE)
    assert config.credentials_path().exists()
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == 0
    assert not config.credentials_path().exists()


# ---- bans / unban ---------------------------------------------------------------

SERVERS = [
    {"id": 7, "name": "hetzy", "ip_address": "1.2.3.4", "provider": "hetzner",
     "status": "ready", "connected": True, "ssh_port": 22, "ssh_user": "pyvolt"},
]


def test_ssh_execs_ssh_with_resolved_host(api, monkeypatch):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    called = {}
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr("os.execvp", lambda file, args: called.setdefault("args", args))
    runner.invoke(app, ["ssh", "hetzy"])
    assert called["args"] == ["ssh", "-p", "22", "pyvolt@1.2.3.4"]


def test_ssh_app_flag_cds_into_app_dir(api, monkeypatch):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.get("/api/v1/apps").respond(200, json=APPS)
    called = {}
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/ssh")
    monkeypatch.setattr("os.execvp", lambda file, args: called.setdefault("args", args))
    runner.invoke(app, ["ssh", "hetzy", "--app", "blog"])
    assert "-t" in called["args"]
    assert any("cd sites/blog.example.com/repo" in a for a in called["args"])


def test_ssh_refuses_non_ready_server(api, monkeypatch):
    api.get("/api/v1/servers").respond(200, json=[{**SERVERS[0], "status": "provisioning"}])
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/ssh")
    result = runner.invoke(app, ["ssh", "hetzy"])
    assert result.exit_code == 1
    assert "not ready" in result.output

BANS = {
    "running": True, "whitelisted": "yes",
    "banned": ["92.118.39.62", "82.1.1.10"], "your_ip": "82.1.1.10",
}


def test_bans_lists_and_flags_own_ip(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.get("/api/v1/servers/7/bans").respond(200, json=BANS)
    result = runner.invoke(app, ["bans", "hetzy"])
    assert result.exit_code == 0
    assert "92.118.39.62" in result.output
    assert "this is you" in result.output
    assert "pyvolt unban hetzy --me" in result.output


def test_bans_when_fail2ban_inactive(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.get("/api/v1/servers/7/bans").respond(
        200, json={**BANS, "running": False, "banned": []}
    )
    result = runner.invoke(app, ["bans", "hetzy"])
    assert result.exit_code == 1
    assert "not active" in result.output


def test_unban_explicit_ip(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.post("/api/v1/servers/7/bans/unban").respond(200, json={"unbanned": "92.118.39.62"})
    result = runner.invoke(app, ["unban", "hetzy", "92.118.39.62"])
    assert result.exit_code == 0
    assert "Unbanned 92.118.39.62" in result.output


def test_unban_me_resolves_own_ip(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.get("/api/v1/servers/7/bans").respond(200, json=BANS)
    route = api.post("/api/v1/servers/7/bans/unban").respond(200, json={"unbanned": "82.1.1.10"})
    result = runner.invoke(app, ["unban", "hetzy", "--me"])
    assert result.exit_code == 0
    assert "Unbanned 82.1.1.10" in result.output
    import json as _json
    assert _json.loads(route.calls[0].request.content) == {"ip": "82.1.1.10"}


def test_unban_requires_ip_or_me(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    result = runner.invoke(app, ["unban", "hetzy"])
    assert result.exit_code == 1
    assert "--me" in result.output
