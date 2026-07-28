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
        Response(200, json={"status": "success", "offset": 9, "chunk": "two\n"}),
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


def test_metrics_shows_snapshot(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.get("/api/v1/servers/7/metrics").respond(200, json={
        "cpu_percent": 12.5, "memory_percent": 40.0, "disk_percent": 55.0,
        "net_in_bytes": 1500000, "net_out_bytes": 2500000, "at": "2026-07-23T07:00:00",
    })
    result = runner.invoke(app, ["metrics", "hetzy"])
    assert result.exit_code == 0
    assert "55%" in result.output and "1.5 MB" in result.output  # disk + net formatting

def test_metrics_none_yet(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.get("/api/v1/servers/7/metrics").respond(200, json={
        "cpu_percent": None, "memory_percent": None, "disk_percent": None,
        "net_in_bytes": 0, "net_out_bytes": 0, "at": None,
    })
    result = runner.invoke(app, ["metrics", "hetzy"])
    assert result.exit_code == 0
    assert "No metrics collected yet" in result.output


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


# ---- apps create ---------------------------------------------------------------

CREATE_PLAN = {
    "domain": "brest.preview.pyvolt.com",
    "repo_url": "git@github.com:acme/blog.git",
    "branch": "main", "project_path": "",
    "framework": "flask", "app_protocol": "wsgi", "package_manager": "pip",
    "python_version": "", "settings_module": "", "app_module": "app:app",
    "serve_command": "gunicorn app:app --workers 2 --bind $SOCK",
    "release_command": "", "build_command": "", "node_version": "",
    "frontend_dir": "", "frontend_passthrough": "",
    "evidence": ["requirements.txt", "flask", "gunicorn"], "warnings": [],
}

CREATED_APP = {
    "id": 31, "domain": "brest.preview.pyvolt.com", "server": "hetzy",
    "status": "pending", "repo": "acme/blog", "branch": "main",
    "dashboard_url": f"{BASE}/servers/hetzy/apps/31/",
    "site_url": "https://brest.preview.pyvolt.com",
}


def _create_args(*extra):
    return ["apps", "create", "--server", "hetzy", "--repo", "acme/blog",
            "--domain", "brest", *extra]


def test_apps_create_dry_run_plans_without_creating(api):
    import json as _json
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    route = api.post("/api/v1/apps").respond(
        200, json={"plan": CREATE_PLAN, "app": None, "scaffolded": False,
                   "scaffold_error": "", "deploy_key_ok": None},
    )
    result = runner.invoke(app, _create_args("--dry-run"))
    assert result.exit_code == 0
    assert "flask" in result.output
    assert "gunicorn app:app" in result.output
    assert "nothing was created" in result.output
    sent = _json.loads(route.calls[0].request.content)
    assert sent["domain_prefix"] == "brest"
    assert sent["dry_run"] is True


def test_apps_create_success_prints_next_steps(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.post("/api/v1/apps").respond(
        201, json={"plan": CREATE_PLAN, "app": CREATED_APP, "scaffolded": True,
                   "scaffold_error": "", "deploy_key_ok": True},
    )
    result = runner.invoke(app, _create_args())
    assert result.exit_code == 0
    assert "Created" in result.output and "brest.preview.pyvolt.com" in result.output
    assert "pyvolt deploy brest.preview.pyvolt.com --follow" in result.output


def test_apps_create_dotted_domain_sent_as_custom(api):
    import json as _json
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    route = api.post("/api/v1/apps").respond(
        201, json={"plan": CREATE_PLAN, "app": CREATED_APP, "scaffolded": True,
                   "scaffold_error": "", "deploy_key_ok": True},
    )
    result = runner.invoke(
        app, ["apps", "create", "--server", "hetzy", "--repo", "acme/blog",
              "--domain", "brest.pyvolt.com"],
    )
    assert result.exit_code == 0
    sent = _json.loads(route.calls[0].request.content)
    assert sent["custom_domain"] == "brest.pyvolt.com"
    assert "domain_prefix" not in sent


def test_apps_create_env_pairs_and_validation(api):
    import json as _json
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    route = api.post("/api/v1/apps").respond(
        201, json={"plan": CREATE_PLAN, "app": CREATED_APP, "scaffolded": True,
                   "scaffold_error": "", "deploy_key_ok": True},
    )
    ok = runner.invoke(app, _create_args("--env", "SECRET_KEY=shh", "--env", "DEBUG=0"))
    assert ok.exit_code == 0
    sent = _json.loads(route.calls[0].request.content)
    assert sent["env"] == {"SECRET_KEY": "shh", "DEBUG": "0"}

    api.get("/api/v1/servers").respond(200, json=SERVERS)
    bad = runner.invoke(app, _create_args("--env", "NOEQUALS"))
    assert bad.exit_code == 1
    assert "KEY=VALUE" in bad.output


def test_apps_create_api_error_detail_surfaced(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.post("/api/v1/apps").respond(
        409, json={"detail": "'brest.preview.pyvolt.com' is already used by another app on Pyvolt."},
    )
    result = runner.invoke(app, _create_args())
    assert result.exit_code == 1
    assert "already used" in result.output


def test_apps_create_scaffold_failure_exits_nonzero(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.post("/api/v1/apps").respond(
        201, json={"plan": CREATE_PLAN, "app": CREATED_APP, "scaffolded": False,
                   "scaffold_error": "ssh: connect refused", "deploy_key_ok": True},
    )
    result = runner.invoke(app, _create_args())
    assert result.exit_code == 1
    assert "scaffolding failed" in result.output


def test_apps_create_deploy_key_warning(api):
    api.get("/api/v1/servers").respond(200, json=SERVERS)
    api.post("/api/v1/apps").respond(
        201, json={"plan": CREATE_PLAN, "app": CREATED_APP, "scaffolded": True,
                   "scaffold_error": "", "deploy_key_ok": False},
    )
    result = runner.invoke(app, _create_args())
    assert result.exit_code == 0
    assert "Deploy key push failed" in result.output


def test_apps_list_filter_still_works_as_group(api):
    route = api.get("/api/v1/apps", params={"server": "hetzy"}).respond(200, json=APPS)
    result = runner.invoke(app, ["apps", "--server", "hetzy"])
    assert result.exit_code == 0
    assert "blog.example.com" in result.output
    assert route.called


# ---- deployments --watch --------------------------------------------------------

def _dep(id, status, sha="abc1234", msg="Refresh listings data", by="push"):
    return {"id": id, "status": status, "commit_sha": sha, "commit_message": msg,
            "triggered_by": by, "created_at": "2026-07-28T10:00:00", "duration_seconds": None}


def test_watch_attaches_to_running_deployment(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    api.get("/api/v1/apps/11/deployments").respond(200, json=[_dep(90, "running")])
    log = api.get("/api/v1/deployments/90/log")
    log.side_effect = [
        Response(200, json={"status": "running", "offset": 4, "chunk": "one\n"}),
        Response(200, json={"status": "success", "offset": 8, "chunk": "two\n"}),
    ]
    result = runner.invoke(app, ["deployments", "blog", "--watch"])
    assert result.exit_code == 0
    assert "abc1234" in result.output and "two" in result.output and "Deployed" in result.output


def test_watch_waits_for_next_deployment(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    lst = api.get("/api/v1/apps/11/deployments")
    lst.side_effect = [
        Response(200, json=[_dep(90, "success")]),          # baseline
        Response(200, json=[_dep(90, "success")]),          # poll: nothing new yet
        Response(200, json=[_dep(91, "queued", sha="def5678")]),  # push arrived
    ]
    log = api.get("/api/v1/deployments/91/log")
    log.side_effect = [
        Response(200, json={"status": "success", "offset": 3, "chunk": "ok\n"}),
    ]
    result = runner.invoke(app, ["deployments", "blog", "--watch"])
    assert result.exit_code == 0
    assert "def5678" in result.output and "Waiting for the next deployment" in result.output


def test_watch_exits_nonzero_on_failure(api):
    api.get("/api/v1/apps").respond(200, json=APPS)
    api.get("/api/v1/apps/11/deployments").respond(200, json=[_dep(92, "running")])
    api.get("/api/v1/deployments/92/log").respond(
        200, json={"status": "failed", "offset": 5, "chunk": "boom\n"})
    result = runner.invoke(app, ["deployments", "blog", "--watch"])
    assert result.exit_code == 1
    assert "boom" in result.output
